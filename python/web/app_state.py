from __future__ import annotations

import asyncio
import secrets
import threading
from collections import deque
from datetime import datetime
from typing import Any, Optional

from bot import SteamgiftsBot
from indiegala_service import IndieGalaService, format_indiegala_cookie_storage
from paths import get_cookie_file, get_indiegala_cookie_file
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


WEB_SETTING_KEYS = (
    "manual_select_giveaways",
    "refresh_delay_minutes",
    "max_pages",
    "max_giveaway_end_hours",
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
        self.bot: SteamgiftsBot | None = None
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

        self._append_console_local(self._welcome_message())

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def _welcome_message(self) -> str:
        cookie = self.read_cookie()
        if cookie:
            return "Ready. Click Fetch Points or Start Bot."
        return (
            "Welcome! Open Settings, paste your PHPSESSID, click Save, "
            "then Start Bot."
        )

    # --- cookies ---

    def read_cookie(self) -> str:
        path = get_cookie_file()
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
        return ""

    def read_indiegala_cookie(self) -> str:
        path = get_indiegala_cookie_file()
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
        return ""

    def save_cookie(self, cookie: str) -> str:
        cookie = cookie.strip()
        if not cookie:
            raise ValueError("Enter PHPSESSID first.")
        path = get_cookie_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(cookie, encoding="utf-8")
        self._log(f"Cookie saved to {path}")
        return cookie

    def save_indiegala_cookie(self, raw: str) -> str:
        raw = raw.strip()
        if not raw:
            raise ValueError("Paste your IndieGala cookie first.")
        normalized = format_indiegala_cookie_storage(raw)
        path = get_indiegala_cookie_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(normalized, encoding="utf-8")
        self._log(f"IndieGala cookie saved to {path}")
        return normalized

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

        if self.bot and self.bot.is_running:
            self.bot.set_manual_select(
                bool(self.settings.get("manual_select_giveaways", False))
            )
            self.bot.apply_bot_settings(
                refresh_delay_minutes=int(
                    self.settings.get("refresh_delay_minutes", 10)
                ),
                max_pages=int(self.settings.get("max_pages", 5)),
                max_giveaway_end_hours=int(
                    self.settings.get("max_giveaway_end_hours", 3)
                ),
            )
            self.bot.apply_indiegala_settings(
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
            "activity": list(self.activity),
            "console": list(self.console),
            "wins": self.list_wins(),
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
        self._broadcast({"type": "wins", "wins": self.list_wins()})

    # --- bot control ---

    @property
    def is_running(self) -> bool:
        return self.bot is not None and self.bot.is_running

    def start_bot(self) -> None:
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

            self.bot = SteamgiftsBot(
                cookie=cookie,
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
                indiegala_cookie=indiegala_cookie,
                enable_indiegala=enable_indiegala,
                indiegala_entry_delay=int(
                    self.settings.get("indiegala_entry_delay", 5)
                ),
                indiegala_min_cost=int(self.settings.get("indiegala_min_cost", 0)),
                wins_tracker=self.wins_tracker,
                on_log=self._on_log,
                on_entry=self._on_entry,
                on_status=self._on_status,
                on_countdown=self._on_countdown,
                on_waiting_points=self._on_waiting_points,
                on_manual_prompt=self._on_manual_prompt,
                on_win=self._on_win,
            )
            self.bot.start()
            self._log("Bot started")
            self._broadcast({"type": "running", "running": True})

    def stop_bot(self) -> None:
        with self._lock:
            if self.bot:
                self.bot.stop()
            self.countdown_label = ""
            self.countdown_seconds = 0
            self._log("Bot stopped")
            self._broadcast(
                {
                    "type": "running",
                    "running": False,
                    "countdown_label": "",
                    "countdown_seconds": 0,
                }
            )

    def submit_manual(self, enter: bool) -> None:
        if self.bot and self.bot.is_running:
            self.bot.submit_manual_decision(enter)

    # --- one-shot actions ---

    def fetch_points(self) -> dict[str, Any]:
        cookie = self.read_cookie()
        if not cookie:
            raise ValueError("Save PHPSESSID in Settings first.")

        service = SteamgiftsService(cookie)
        info = service.fetch_points_timer()
        self.steamgifts_points = info.points
        self.username = info.username
        self._log(f"Logged in as {info.username} · {info.points} points")

        silver = None
        if self.settings.get("enable_indiegala_beta"):
            ig_cookie = self.read_indiegala_cookie()
            if ig_cookie:
                try:
                    account = IndieGalaService(ig_cookie).fetch_account()
                    silver = account.silver
                    self.indiegala_silver = silver
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

    def test_indiegala(self, raw: Optional[str] = None) -> dict[str, Any]:
        cookie = (raw or "").strip() or self.read_indiegala_cookie()
        if not cookie:
            raise ValueError("Paste and save your IndieGala cookie first.")
        try:
            cookie = format_indiegala_cookie_storage(cookie)
        except ValueError:
            pass
        account = IndieGalaService(cookie).fetch_account()
        self.indiegala_silver = account.silver
        self._log(f"IndieGala OK · {account.username} · {account.silver} silver")
        return {
            "username": account.username,
            "silver": account.silver,
        }

    def list_entered(self) -> list[dict[str, Any]]:
        cookie = self.read_cookie()
        if not cookie:
            raise ValueError("Save PHPSESSID in Settings first.")
        giveaways = SteamgiftsService(cookie).fetch_entered_giveaways()
        return [self._entered_to_dict(item) for item in giveaways]

    def remove_entered(self, code: str, xsrf_token: str) -> None:
        cookie = self.read_cookie()
        if not cookie:
            raise ValueError("Save PHPSESSID in Settings first.")
        SteamgiftsService(cookie).remove_entry(code, xsrf_token)
        self._log(f"Removed entry {code}")

    def list_wins(self) -> list[dict[str, Any]]:
        return [
            {
                "code": win.code,
                "name": win.name,
                "image_url": win.image_url,
                "source": win.source,
                "url": win.url,
                "detected_at": win.detected_at,
            }
            for win in self.wins_tracker.all_wins()
        ]

    @staticmethod
    def _entered_to_dict(item: EnteredGiveawayInfo) -> dict[str, Any]:
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
            "ends_text": format_ends_text("", item.ends_at, "steamgifts"),
        }


state = AppState()
