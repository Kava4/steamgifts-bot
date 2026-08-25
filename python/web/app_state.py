from __future__ import annotations

import asyncio
import secrets
import threading
from collections import deque
from datetime import datetime
from typing import Any, Optional

from accounts import (
    PLATFORM_INDIEGALA,
    PLATFORM_STEAMGIFTS,
    delete_account,
    enabled_accounts,
    get_account,
    get_active_account,
    load_accounts,
    prune_empty_accounts,
    public_accounts_payload,
    set_active_account,
    upsert_account,
)
from bot import SteamgiftsBot
from entered_tracker import IndieGalaEnteredTracker
from indiegala_service import IndieGalaService, format_indiegala_cookie_storage
from notify import notify_win
from paths import get_cookie_file, get_indiegala_cookie_file
from proxy_utils import pick_working_free_proxy
from settings import REFRESH_MINUTE_OPTIONS, load_settings, save_settings
from steamgifts_service import (
    EnteredGiveawayInfo,
    GiveawayInfo,
    SteamgiftsService,
    WonGiveawayInfo,
    format_giveaway_ends,
)
from wins_tracker import WinsTracker
from version import APP_VERSION
from web.browser_login_jobs import browser_login_jobs


WEB_SETTING_KEYS = (
    "manual_select_giveaways",
    "refresh_delay_minutes",
    "max_pages",
    "max_giveaway_end_hours",
    "min_points",
    "enable_indiegala_beta",
    "indiegala_entry_delay",
    "indiegala_min_cost",
    "notify_on_win",
)


def format_ends_text(
    ends_label: str = "",
    ends_at: int | None = None,
    source: str = "steamgifts",
) -> str:
    if source == "indiegala" and ends_label:
        return ends_label
    text = format_giveaway_ends(ends_at, ends_label)
    return f"Ends · {text}" if text else ""


class AppState:
    def __init__(self) -> None:
        self.settings = load_settings()
        self.wins_tracker = WinsTracker()
        self.ig_entered = IndieGalaEnteredTracker()
        self.ig_entered_by_account: dict[str, IndieGalaEnteredTracker] = {}
        self.bot: SteamgiftsBot | None = None
        self.bots: list[SteamgiftsBot] = []
        self._bot_stop_helpers: list[threading.Event] = []
        self.activity: deque[dict[str, Any]] = deque(maxlen=200)
        self.console: deque[str] = deque(maxlen=500)
        self._subscribers: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()

        self.steamgifts_points: int | None = None
        self.indiegala_silver: int | None = None
        self.username = ""
        self.page: int | None = None
        self.countdown_label = ""
        self.countdown_seconds = 0
        self.session_token = secrets.token_hex(32)
        self.running_mode = ""

        # Ensure legacy cookies are migrated into accounts.json.
        load_accounts()
        prune_empty_accounts()
        self._append_console_local(self._welcome_message())

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def _welcome_message(self) -> str:
        sg = get_active_account(PLATFORM_STEAMGIFTS)
        if sg and sg.cookie.strip():
            return "Ready. Click Fetch Points or Start Bot."
        return (
            "Welcome! Open Settings, add a SteamGifts account with PHPSESSID, "
            "then Start Bot."
        )

    def _active_proxy(self, platform: str = PLATFORM_STEAMGIFTS) -> str:
        active = get_active_account(platform)
        return (active.proxy if active else "") or ""

    # --- cookies (active account per platform + legacy files) ---

    def read_cookie(self) -> str:
        active = get_active_account(PLATFORM_STEAMGIFTS)
        if active and active.cookie.strip():
            return active.cookie.strip()
        path = get_cookie_file()
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
        return ""

    def read_indiegala_cookie(self) -> str:
        active = get_active_account(PLATFORM_INDIEGALA)
        if active and active.cookie.strip():
            return active.cookie.strip()
        path = get_indiegala_cookie_file()
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
        return ""

    def save_cookie(self, cookie: str) -> str:
        cookie = cookie.strip()
        if not cookie:
            raise ValueError("Enter PHPSESSID first.")
        active = get_active_account(PLATFORM_STEAMGIFTS)
        if active is None:
            upsert_account(
                {
                    "platform": PLATFORM_STEAMGIFTS,
                    "name": "SteamGifts 1",
                    "cookie": cookie,
                    "enabled": True,
                }
            )
        else:
            upsert_account({"id": active.id, "cookie": cookie})
        self._log("SteamGifts cookie saved")
        return cookie

    def save_indiegala_cookie(self, raw: str) -> str:
        raw = raw.strip()
        if not raw:
            raise ValueError("Paste your IndieGala cookie first.")
        normalized = format_indiegala_cookie_storage(raw)
        active = get_active_account(PLATFORM_INDIEGALA)
        if active is None:
            upsert_account(
                {
                    "platform": PLATFORM_INDIEGALA,
                    "name": "IndieGala 1",
                    "cookie": normalized,
                    "enabled": True,
                }
            )
        else:
            upsert_account({"id": active.id, "cookie": normalized})
        self._log("IndieGala cookie saved")
        return normalized

    # --- accounts ---

    def list_accounts(self) -> dict[str, Any]:
        return public_accounts_payload(include_cookies=False)

    def get_account_detail(self, account_id: str) -> dict[str, Any]:
        account = get_account(account_id)
        if account is None:
            raise ValueError("Account not found.")
        return account.to_public_dict(include_cookie=True)

    def save_account(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload)
        platform = str(data.get("platform") or "").strip().lower()
        raw_cookie = str(data.get("cookie") or "").strip()
        if platform == PLATFORM_INDIEGALA and raw_cookie:
            data["cookie"] = format_indiegala_cookie_storage(raw_cookie)
        elif "cookie" in data and not raw_cookie and not data.get("clear_cookie"):
            # Keep existing cookie for this account id.
            data.pop("cookie", None)
        state = upsert_account(data)
        # Saving also makes it the active account for that platform (Entered/Wins).
        account_id = str(data.get("id") or "").strip()
        if not account_id:
            platform = platform or PLATFORM_STEAMGIFTS
            same = [a for a in state.accounts if a.platform == platform]
            if same:
                account_id = same[-1].id
        if account_id:
            state = set_active_account(account_id)
        saved = get_account(account_id) if account_id else None
        label = saved.name if saved else "account"
        cookie_note = " (cookie updated)" if raw_cookie else ""
        self._log(f"Account saved: {label}{cookie_note}")
        payload_out = public_accounts_payload(state, include_cookies=False)
        self._broadcast({"type": "accounts", "accounts": payload_out})
        return payload_out

    def remove_account(self, account_id: str) -> dict[str, Any]:
        state = delete_account(account_id)
        self._log("Account removed")
        payload_out = public_accounts_payload(state, include_cookies=False)
        self._broadcast({"type": "accounts", "accounts": payload_out})
        return payload_out

    def activate_account(self, account_id: str) -> dict[str, Any]:
        state = set_active_account(account_id)
        active = get_account(account_id)
        label = active.name if active else account_id
        self._log(f"Active for {active.platform if active else '?'}: {label}")
        payload_out = public_accounts_payload(state, include_cookies=False)
        self._broadcast({"type": "accounts", "accounts": payload_out})
        return payload_out

    def prune_accounts(self) -> dict[str, Any]:
        state = prune_empty_accounts()
        self._log("Pruned empty duplicate accounts")
        payload_out = public_accounts_payload(state, include_cookies=False)
        self._broadcast({"type": "accounts", "accounts": payload_out})
        return payload_out

    def assign_free_proxy(self, account_id: str = "") -> dict[str, Any]:
        state = load_accounts()
        target = None
        if account_id.strip():
            target = next((a for a in state.accounts if a.id == account_id), None)
        if target is None:
            target = get_active_account(PLATFORM_STEAMGIFTS, state) or get_active_account(
                PLATFORM_INDIEGALA, state
            )
        if target is None:
            raise ValueError("No account available.")

        test_url = (
            "https://www.indiegala.com/giveaways"
            if target.platform == PLATFORM_INDIEGALA
            else "https://www.steamgifts.com/"
        )
        self._log(f"[{target.name}] ProxyScrape: testing free proxies…")
        proxy = pick_working_free_proxy(
            test_url=test_url, protocol="http", attempts=6
        )
        if not proxy:
            raise RuntimeError(
                "No working free proxy from ProxyScrape right now. Try again, "
                "or paste your own proxy URL (http://host:port). "
                "See https://docs.proxyscrape.com/api-overview"
            )
        state = upsert_account({"id": target.id, "proxy": proxy})
        self._log(f"[{target.name}] Assigned free proxy: {proxy}")
        payload = public_accounts_payload(state, include_cookies=False)
        self._broadcast({"type": "accounts", "accounts": payload})
        return {"proxy": proxy, "accounts": payload}

    # --- settings ---

    def get_web_settings(self) -> dict[str, Any]:
        return {key: self.settings.get(key) for key in WEB_SETTING_KEYS}

    def update_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        for key in WEB_SETTING_KEYS:
            if key not in payload:
                continue
            self.settings[key] = payload[key]

        if self.settings["refresh_delay_minutes"] not in REFRESH_MINUTE_OPTIONS:
            self.settings["refresh_delay_minutes"] = 10

        save_settings(self.settings)
        self.settings = load_settings()

        running_bots = [bot for bot in self.bots if bot.is_running]
        if self.bot and self.bot.is_running and self.bot not in running_bots:
            running_bots.append(self.bot)
        for bot in running_bots:
            bot.set_manual_select(
                bool(self.settings.get("manual_select_giveaways", False))
            )
            bot.apply_bot_settings(
                refresh_delay_minutes=int(
                    self.settings.get("refresh_delay_minutes", 10)
                ),
                max_pages=int(self.settings.get("max_pages", 5)),
                max_giveaway_end_hours=int(
                    self.settings.get("max_giveaway_end_hours", 3)
                ),
                min_points=int(self.settings.get("min_points", 0)),
            )
            bot.apply_indiegala_settings(
                entry_delay=int(self.settings.get("indiegala_entry_delay", 5)),
                min_cost=int(self.settings.get("indiegala_min_cost", 0)),
            )

        self._broadcast({"type": "settings", "settings": self.get_web_settings()})
        return self.get_web_settings()

    # --- snapshot / WS ---

    def snapshot(self) -> dict[str, Any]:
        return {
            "type": "snapshot",
            "version": APP_VERSION,
            "running": self.is_running,
            "points": self.steamgifts_points,
            "silver": self.indiegala_silver,
            "username": self.username,
            "page": self.page,
            "countdown_label": self.countdown_label,
            "countdown_seconds": self.countdown_seconds,
            "settings": self.get_web_settings(),
            "has_cookie": bool(self.read_cookie()),
            "has_indiegala_cookie": bool(self.read_indiegala_cookie()),
            "accounts": self.list_accounts(),
            "running_mode": self.running_mode,
            "activity": list(self.activity),
            "console": list(self.console),
            "wins": self.list_wins(),
            "entered": {"steamgifts": [], "indiegala": []},
        }

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    def _broadcast(self, event: dict[str, Any]) -> None:
        if self._loop is None:
            return
        for queue in list(self._subscribers):
            try:
                self._loop.call_soon_threadsafe(self._enqueue, queue, event)
            except RuntimeError:
                pass

    @staticmethod
    def _enqueue(queue: asyncio.Queue, event: dict[str, Any]) -> None:
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass

    # --- console / activity ---

    def _append_console_local(self, message: str) -> None:
        timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        if " - " in message and message[:2].isdigit():
            line = message
        else:
            line = f"{timestamp} - {message}"
        self.console.append(line)

    def _log(self, message: str) -> None:
        self._append_console_local(message)
        line = self.console[-1]
        self._broadcast({"type": "log", "message": line})

    def clear_logs(self) -> None:
        self.activity.clear()
        self.console.clear()
        self._broadcast({"type": "cleared"})
        self._log("Logs cleared")

    def _push_activity(self, card: dict[str, Any]) -> None:
        self.activity.append(card)
        self._broadcast({"type": "activity", "card": card})

    def _update_waiting(self, card: dict[str, Any]) -> None:
        # Replace previous waiting card or append
        for index in range(len(self.activity) - 1, -1, -1):
            if self.activity[index].get("status") == "waiting":
                self.activity[index] = card
                self._broadcast({"type": "waiting", "card": card})
                return
        self.activity.append(card)
        self._broadcast({"type": "waiting", "card": card})

    def _clear_waiting(self) -> None:
        removed = False
        kept: deque[dict[str, Any]] = deque(maxlen=self.activity.maxlen)
        for card in self.activity:
            if card.get("status") == "waiting":
                removed = True
                continue
            kept.append(card)
        if removed:
            self.activity = kept
            self._broadcast({"type": "waiting_clear"})

    # --- bot callbacks ---

    def _on_log(self, message: str) -> None:
        self._log(message)

    def _on_entry(self, giveaway: GiveawayInfo, status: str) -> None:
        cost_label = (
            f"{giveaway.cost} iS"
            if giveaway.source == "indiegala"
            else f"{giveaway.cost}P"
        )
        ends_text = format_ends_text(
            giveaway.ends_label, giveaway.ends_at, giveaway.source
        )
        prefix = "[IndieGala] " if giveaway.source == "indiegala" else ""
        self._log(f"{prefix}Entering giveaway: {giveaway.name} ({cost_label})")

        # Mirror desktop: activity cards for entries only when not in manual mode
        if self.settings.get("manual_select_giveaways"):
            return

        self._clear_waiting()
        self._push_activity(
            {
                "kind": "card",
                "title": giveaway.name,
                "subtitle": f"Entered · cost {cost_label}",
                "image_url": giveaway.image_url,
                "status": status if status in ("entered", "skipped") else "entered",
                "ends_text": ends_text,
                "source": giveaway.source,
            }
        )

    def _on_waiting_points(
        self, giveaway: GiveawayInfo, points: int, minutes: int
    ) -> None:
        cost_label = (
            f"{giveaway.cost} iS"
            if giveaway.source == "indiegala"
            else f"{giveaway.cost}P"
        )
        ends_text = format_ends_text(
            giveaway.ends_label, giveaway.ends_at, giveaway.source
        )
        self._update_waiting(
            {
                "kind": "card",
                "title": giveaway.name,
                "subtitle": (
                    f"Waiting for points · have {points}P · need {cost_label} "
                    f"· ~{minutes} min"
                ),
                "image_url": giveaway.image_url,
                "status": "waiting",
                "ends_text": ends_text,
                "source": giveaway.source,
            }
        )

    def _on_manual_prompt(self, giveaway: GiveawayInfo) -> None:
        cost_label = (
            f"{giveaway.cost} iS"
            if giveaway.source == "indiegala"
            else f"{giveaway.cost}P"
        )
        ends_text = format_ends_text(
            giveaway.ends_label, giveaway.ends_at, giveaway.source
        )
        card = {
            "kind": "prompt",
            "code": giveaway.code,
            "title": giveaway.name,
            "subtitle": f"Enter this giveaway? · {cost_label}",
            "image_url": giveaway.image_url,
            "status": "prompt",
            "ends_text": ends_text,
            "source": giveaway.source,
        }
        self._clear_waiting()
        self.activity.append(card)
        self._broadcast({"type": "prompt", "card": card})

    def _on_status(self, points: int, page: int, source: str) -> None:
        if source == "indiegala":
            self.indiegala_silver = points
        else:
            self.steamgifts_points = points
        self.page = page
        self._broadcast(
            {
                "type": "status",
                "points": self.steamgifts_points,
                "silver": self.indiegala_silver,
                "page": page,
                "source": source,
            }
        )

    def _on_countdown(self, label: str, seconds: int) -> None:
        self.countdown_label = label or ""
        self.countdown_seconds = max(0, int(seconds))
        self._broadcast(
            {
                "type": "countdown",
                "label": self.countdown_label,
                "seconds": self.countdown_seconds,
            }
        )

    def _on_win(self, win: WonGiveawayInfo) -> None:
        if not self.settings.get("notify_on_win", True):
            return
        self._log(f"Won: {win.name} ({win.source})")
        self._clear_waiting()
        self._push_activity(
            {
                "kind": "card",
                "title": win.name,
                "subtitle": "You won this giveaway!",
                "image_url": win.image_url,
                "status": "won",
                "ends_text": "",
                "source": win.source,
                "url": win.url,
            }
        )
        wins = self.list_wins()
        self._broadcast({"type": "wins", "wins": wins})
        self._broadcast(
            {
                "type": "win_alert",
                "win": {
                    "code": win.code,
                    "name": win.name,
                    "image_url": win.image_url,
                    "source": win.source,
                    "url": win.url,
                },
            }
        )
        error = notify_win(win)
        if error:
            self._log(f"Discord notify failed: {error}")

    # --- bot control ---

    @property
    def is_running(self) -> bool:
        if self.running_mode:
            return True
        if self.bots:
            return any(bot.is_running for bot in self.bots)
        return self.bot is not None and self.bot.is_running

    def _ig_tracker_for(self, account_id: str = "") -> IndieGalaEnteredTracker:
        account_id = (account_id or "").strip()
        if not account_id:
            return self.ig_entered
        tracker = self.ig_entered_by_account.get(account_id)
        if tracker is None:
            tracker = IndieGalaEnteredTracker(account_id)
            self.ig_entered_by_account[account_id] = tracker
        return tracker

    def _make_bot(
        self,
        cookie: str,
        indiegala_cookie: str,
        enable_indiegala: bool,
        proxy: str,
        account_name: str = "",
        account_id: str = "",
        indiegala_entry_delay: int | None = None,
    ) -> SteamgiftsBot:
        prefix = f"[{account_name}] " if account_name else ""
        tracker = (
            self._ig_tracker_for(account_id) if enable_indiegala else None
        )
        delay = (
            int(indiegala_entry_delay)
            if indiegala_entry_delay is not None
            else int(self.settings.get("indiegala_entry_delay", 5))
        )

        def on_log(message: str) -> None:
            self._on_log(f"{prefix}{message}" if prefix else message)

        def on_entry(giveaway: GiveawayInfo, status: str) -> None:
            if (
                tracker is not None
                and giveaway.source == "indiegala"
                and status == "entered"
            ):
                tracker.add_from_giveaway(giveaway)
            self._on_entry(giveaway, status)

        return SteamgiftsBot(
            cookie=cookie,
            proxy=proxy,
            manual_select=bool(
                self.settings.get("manual_select_giveaways", False)
            ),
            refresh_delay_minutes=int(
                self.settings.get("refresh_delay_minutes", 10)
            ),
            max_pages=int(self.settings.get("max_pages", 5)),
            max_giveaway_end_hours=int(
                self.settings.get("max_giveaway_end_hours", 3)
            ),
            min_points=int(self.settings.get("min_points", 0)),
            indiegala_cookie=indiegala_cookie,
            enable_indiegala=enable_indiegala,
            indiegala_entry_delay=max(3, delay),
            indiegala_min_cost=int(self.settings.get("indiegala_min_cost", 0)),
            wins_tracker=self.wins_tracker,
            on_log=on_log,
            on_entry=on_entry,
            on_status=self._on_status,
            on_countdown=self._on_countdown,
            on_waiting_points=self._on_waiting_points,
            on_manual_prompt=self._on_manual_prompt,
            on_win=self._on_win,
        )

    def start_bot(self, mode: str = "all") -> None:
        with self._lock:
            if self.is_running:
                return

            cookie = self.read_cookie()
            if not cookie:
                raise ValueError(
                    "PHPSESSID cookie is required. Save it in Settings -> Accounts."
                )

            enable_indiegala = bool(
                self.settings.get("enable_indiegala_beta", False)
            )
            indiegala_cookie = self.read_indiegala_cookie()
            if enable_indiegala and not indiegala_cookie:
                raise ValueError(
                    "Enable IndieGala is on — set your cookie in Settings -> Accounts."
                )

            for helper in getattr(self, "_bot_stop_helpers", []) or []:
                try:
                    helper.set()
                except Exception:
                    pass
            self._bot_stop_helpers = []

            bot = self._make_bot(
                cookie=cookie,
                indiegala_cookie=indiegala_cookie if enable_indiegala else "",
                enable_indiegala=enable_indiegala,
                proxy="",
                account_name="",
                account_id="",
            )
            bot.start()
            self.bots = [bot]
            self.bot = bot
            self.running_mode = "all"
            self._log("Bot started")
            self._broadcast(
                {"type": "running", "running": True, "running_mode": "all"}
            )

    def stop_bot(self) -> None:
        with self._lock:
            for flag in self._bot_stop_helpers:
                flag.set()
            self._bot_stop_helpers = []
            for bot in self.bots:
                bot.stop()
            if self.bot and self.bot not in self.bots:
                self.bot.stop()
            self.bots = []
            self.bot = None
            self.running_mode = ""
            self.countdown_label = ""
            self.countdown_seconds = 0
            self._log("Bot stopped")
            self._broadcast(
                {
                    "type": "running",
                    "running": False,
                    "running_mode": "",
                    "countdown_label": "",
                    "countdown_seconds": 0,
                }
            )

    def submit_manual(self, enter: bool) -> None:
        for bot in self.bots:
            if bot.is_running:
                bot.submit_manual_decision(enter)
        if self.bot and self.bot.is_running and self.bot not in self.bots:
            self.bot.submit_manual_decision(enter)

    # --- one-shot actions ---

    def fetch_points(self) -> dict[str, Any]:
        cookie = self.read_cookie()
        if not cookie:
            raise ValueError("Save PHPSESSID in Settings first.")

        proxy = self._active_proxy(PLATFORM_STEAMGIFTS)
        service = SteamgiftsService(cookie, proxy=proxy)
        info = service.fetch_points_timer()
        self.steamgifts_points = info.points
        self.username = info.username
        self._log(f"Logged in as {info.username} · {info.points} points")

        ig_cookie = self.read_indiegala_cookie()
        if ig_cookie and (
            self.settings.get("enable_indiegala_beta")
            or get_active_account(PLATFORM_INDIEGALA)
        ):
            try:
                account = IndieGalaService(
                    ig_cookie, proxy=self._active_proxy(PLATFORM_INDIEGALA)
                ).fetch_account()
                self.indiegala_silver = account.silver
                self._log(
                    f"IndieGala · {account.username} · {account.silver} silver"
                )
            except Exception as error:
                self._log(f"IndieGala points failed: {error}")

        result = {
            "points": info.points,
            "username": info.username,
            "silver": self.indiegala_silver,
        }
        self._broadcast(
            {
                "type": "status",
                "points": self.steamgifts_points,
                "silver": self.indiegala_silver,
                "page": self.page,
                "source": "steamgifts",
                "username": self.username,
            }
        )
        return result

    def test_indiegala(
        self, raw: Optional[str] = None, account_id: str = ""
    ) -> dict[str, Any]:
        cookie = (raw or "").strip() or self.read_indiegala_cookie()
        if not cookie:
            raise ValueError("Paste and save your IndieGala cookie first.")
        try:
            cookie = format_indiegala_cookie_storage(cookie)
        except ValueError:
            pass
        account_info = IndieGalaService(
            cookie, proxy=self._active_proxy(PLATFORM_INDIEGALA)
        ).fetch_account()
        self.indiegala_silver = account_info.silver

        saved_to = ""
        target_id = (account_id or "").strip()
        if not target_id:
            active = get_active_account(PLATFORM_INDIEGALA)
            target_id = active.id if active else ""
        if target_id and cookie:
            # Test Session must persist — otherwise Start uses a stale saved cookie.
            upsert_account({"id": target_id, "cookie": cookie})
            set_active_account(target_id)
            target = get_account(target_id)
            saved_to = target.name if target else target_id
            self._log(
                f"IndieGala OK · {account_info.username} · {account_info.silver} silver "
                f"(saved → {saved_to})"
            )
            self._broadcast(
                {"type": "accounts", "accounts": public_accounts_payload(include_cookies=False)}
            )
        else:
            self._log(
                f"IndieGala OK · {account_info.username} · {account_info.silver} silver"
            )
        return {
            "username": account_info.username,
            "silver": account_info.silver,
            "saved_to": saved_to,
        }

    def start_indiegala_browser_login(self, account_id: str) -> dict[str, Any]:
        account = get_account(account_id)
        if account is None:
            raise ValueError("Account not found.")
        if account.platform != PLATFORM_INDIEGALA:
            raise ValueError("Browser login is only for IndieGala accounts.")
        job = browser_login_jobs.start(account.id, account.name)
        self._log(f"IndieGala browser login started · {account.name}")
        return job.to_public()

    def indiegala_browser_login_status(self, token: str) -> dict[str, Any]:
        job = browser_login_jobs.get(token)
        if job is None:
            raise ValueError("Unknown or expired login token.")
        return job.to_public()

    def complete_indiegala_browser_login(
        self,
        token: str,
        *,
        ok: bool,
        cookie: str = "",
        message: str = "",
    ) -> dict[str, Any]:
        # Grace window: helper may finish after the UI timer / after a redeploy.
        job = browser_login_jobs.claim_for_cookie_save(token, grace_seconds=3600)
        if job is None:
            raise ValueError(
                "Unknown or expired login token. "
                "Click Browser login again, Copy command, and re-run "
                "(or: python ig_login_helper.py --server ... --token NEW --cookie-file ig_cookies.json)."
            )
        if job.status == "complete" and ok and cookie.strip():
            # Already saved — idempotent success for helper retries.
            public = job.to_public()
            public["account_name"] = job.account_name
            return public
        if job.status == "complete":
            return job.to_public()

        if not ok:
            done = browser_login_jobs.complete(
                token, ok=False, message=message or "Login cancelled", allow_expired=True
            )
            self._log(f"IndieGala browser login failed · {job.account_name}")
            return done.to_public() if done else {"status": "error", "message": message}

        raw = (cookie or "").strip()
        if not raw:
            done = browser_login_jobs.complete(
                token, ok=False, message="Helper sent an empty cookie.", allow_expired=True
            )
            return done.to_public() if done else {"status": "error"}

        normalized = format_indiegala_cookie_storage(raw)
        # Prefer live validation, but still save if IndieGala/Incapsula blocks the Pi IP.
        info_username = ""
        info_silver = 0
        warn = ""
        try:
            info = IndieGalaService(normalized).fetch_account()
            info_username = info.username
            info_silver = info.silver
            self.indiegala_silver = info.silver
        except Exception as error:
            warn = str(error)
            self._log(f"IndieGala cookie saved but session check failed on Pi: {error}")

        upsert_account({"id": job.account_id, "cookie": normalized})
        set_active_account(job.account_id)
        if warn:
            msg = (
                f"Cookie saved for {job.account_name}, but Pi cannot verify login yet "
                f"({warn}). Try Test Session / Start — or re-export if it stays logged out."
            )
            done = browser_login_jobs.complete(
                token,
                ok=True,
                message=msg,
                username=info_username or job.account_name,
                allow_expired=True,
            )
        else:
            done = browser_login_jobs.complete(
                token,
                ok=True,
                message=f"Saved · {info_username} · {info_silver} silver",
                username=info_username,
                allow_expired=True,
            )
            self._log(
                f"IndieGala browser login OK · {job.account_name} · {info_username}"
            )
        payload_out = public_accounts_payload(include_cookies=False)
        self._broadcast({"type": "accounts", "accounts": payload_out})
        if info_username:
            self._broadcast(
                {
                    "type": "status",
                    "points": self.steamgifts_points,
                    "silver": self.indiegala_silver,
                    "page": self.page,
                    "source": "indiegala",
                    "username": info_username,
                }
            )
        result = done.to_public() if done else {"status": "complete"}
        result["account_name"] = job.account_name
        result["silver"] = info_silver
        if warn:
            result["warning"] = warn
        return result

    def list_entered(self) -> dict[str, list[dict[str, Any]]]:
        steamgifts: list[dict[str, Any]] = []
        cookie = self.read_cookie()
        proxy = self._active_proxy(PLATFORM_STEAMGIFTS)
        if cookie:
            try:
                giveaways = SteamgiftsService(
                    cookie, proxy=proxy
                ).fetch_entered_giveaways()
                steamgifts = [self._entered_to_dict(item) for item in giveaways]
            except Exception as error:
                self._log(f"Entered refresh failed: {error}")
                raise

        ig_cookie = self.read_indiegala_cookie()
        active_ig = get_active_account(PLATFORM_INDIEGALA)
        ig_tracker = self._ig_tracker_for(active_ig.id if active_ig else "")
        if ig_cookie:
            try:
                service = IndieGalaService(
                    ig_cookie, proxy=self._active_proxy(PLATFORM_INDIEGALA)
                )
                remote = service.fetch_entered_giveaways(
                    max_pages=min(3, int(self.settings.get("max_pages", 5)))
                )
                added = ig_tracker.merge_entered(remote)
                if added:
                    self._log(
                        f"[IndieGala] Synced {added} entered giveaway(s) from listing"
                    )
                elif not remote and not ig_tracker.list_active():
                    self._log(
                        "[IndieGala] No joined cards found on listing pages. "
                        "Note: 'SINGLE TICKET' is the ticket type, not entered status."
                    )
            except Exception as error:
                self._log(f"[IndieGala] Entered sync failed: {error}")

        # Merge active account + any other per-account trackers for display.
        merged: dict[str, EnteredGiveawayInfo] = {}
        for item in ig_tracker.list_active():
            merged[item.code] = item
        for tracker in self.ig_entered_by_account.values():
            for item in tracker.list_active():
                merged.setdefault(item.code, item)
        for item in self.ig_entered.list_active():
            merged.setdefault(item.code, item)

        indiegala = [self._entered_to_dict(item) for item in merged.values()]
        return {"steamgifts": steamgifts, "indiegala": indiegala}

    def remove_entered(self, code: str, xsrf_token: str) -> None:
        cookie = self.read_cookie()
        if not cookie:
            raise ValueError("Save PHPSESSID in Settings first.")
        SteamgiftsService(
            cookie, proxy=self._active_proxy(PLATFORM_STEAMGIFTS)
        ).remove_entry(code, xsrf_token)
        self._log(f"Removed entry {code}")

    def list_wins(self) -> dict[str, list[dict[str, Any]]]:
        """Refresh from sites, drop Received SteamGifts wins, return by source."""
        current: list[WonGiveawayInfo] = []
        sources: list[str] = []
        cookie = self.read_cookie()
        if cookie:
            try:
                current.extend(
                    SteamgiftsService(
                        cookie, proxy=self._active_proxy(PLATFORM_STEAMGIFTS)
                    ).fetch_won_giveaways()
                )
                sources.append("steamgifts")
            except Exception as error:
                self._log(f"[SteamGifts] Wins refresh failed: {error}")

        ig_cookie = self.read_indiegala_cookie()
        if ig_cookie:
            try:
                current.extend(
                    IndieGalaService(
                        ig_cookie, proxy=self._active_proxy(PLATFORM_INDIEGALA)
                    ).fetch_won_giveaways()
                )
                sources.append("indiegala")
            except Exception as error:
                self._log(f"[IndieGala] Wins refresh failed: {error}")

        if sources:
            self.wins_tracker.sync_wins(current, sources=sources)

        steamgifts: list[dict[str, Any]] = []
        indiegala: list[dict[str, Any]] = []
        for win in self.wins_tracker.all_wins():
            item = {
                "code": win.code,
                "name": win.name,
                "image_url": win.image_url,
                "source": win.source,
                "url": win.url,
                "detected_at": win.detected_at,
            }
            if win.source == "indiegala":
                indiegala.append(item)
            else:
                steamgifts.append(item)
        return {"steamgifts": steamgifts, "indiegala": indiegala}

    @staticmethod
    def _entered_to_dict(item: EnteredGiveawayInfo) -> dict[str, Any]:
        source = getattr(item, "source", "steamgifts") or "steamgifts"
        return {
            "name": item.name,
            "code": item.code,
            "cost": item.cost,
            "image_url": item.image_url,
            "ends_at": item.ends_at,
            "remaining_label": item.remaining_label,
            "entries_count": item.entries_count,
            "entered_label": item.entered_label,
            "xsrf_token": item.xsrf_token,
            "source": source,
            "url": getattr(item, "url", "") or "",
            "ends_text": format_ends_text(
                item.remaining_label, item.ends_at, source
            ),
        }


state = AppState()
