import math
import threading
import time
from datetime import datetime
from typing import Callable, Optional

from indiegala_service import IndieGalaService
from steamgifts_service import GiveawayInfo, SteamgiftsService, WonGiveawayInfo
from wins_tracker import WinsTracker


class SteamgiftsBot:
    def __init__(
        self,
        cookie: str,
        on_log: Callable[[str], None],
        on_status: Optional[Callable[[int, int, str], None]] = None,
        on_entry: Optional[Callable[[GiveawayInfo, str], None]] = None,
        on_waiting_points: Optional[
            Callable[[GiveawayInfo, int, int], None]
        ] = None,
        on_manual_prompt: Optional[Callable[[GiveawayInfo], None]] = None,
        on_countdown: Optional[Callable[[str, int], None]] = None,
        on_win: Optional[Callable[[WonGiveawayInfo], None]] = None,
        manual_select: bool = False,
        entry_delay: int = 2,
        refresh_delay_minutes: int = 10,
        max_pages: int = 5,
        indiegala_cookie: str = "",
        enable_indiegala: bool = False,
        indiegala_entry_delay: int = 5,
        indiegala_min_cost: int = 0,
        wins_tracker: Optional[WinsTracker] = None,
    ):
        self.cookie = cookie.strip()
        self.on_log = on_log
        self.on_status = on_status
        self.on_entry = on_entry
        self.on_waiting_points = on_waiting_points
        self.on_manual_prompt = on_manual_prompt
        self.on_countdown = on_countdown
        self.on_win = on_win
        self.manual_select = manual_select
        self.entry_delay = entry_delay
        self.refresh_delay_minutes = refresh_delay_minutes
        self.max_pages = max(1, max_pages)
        self.refresh_delay = refresh_delay_minutes * 60
        self.indiegala_entry_delay = max(3, indiegala_entry_delay)
        self.indiegala_min_cost = max(0, indiegala_min_cost)

        self.service = SteamgiftsService(self.cookie)
        self.indiegala: Optional[IndieGalaService] = None
        if enable_indiegala and indiegala_cookie.strip():
            self.indiegala = IndieGalaService(indiegala_cookie)

        self.current_page = 1
        self.indiegala_page = 1
        self.xsrf_token = ""
        self.points = 0
        self.silver = 0
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._manual_event = threading.Event()
        self._manual_decision = False
        self._wins_tracker = wins_tracker or WinsTracker()
        self._last_win_check = 0.0

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def set_manual_select(self, enabled: bool) -> None:
        self.manual_select = enabled

    def apply_bot_settings(
        self, refresh_delay_minutes: int, max_pages: int
    ) -> None:
        self.refresh_delay_minutes = refresh_delay_minutes
        self.refresh_delay = refresh_delay_minutes * 60
        self.max_pages = max(1, max_pages)

    def apply_indiegala_settings(
        self, entry_delay: int, min_cost: int
    ) -> None:
        self.indiegala_entry_delay = max(3, entry_delay)
        self.indiegala_min_cost = max(0, min_cost)

    def submit_manual_decision(self, enter: bool) -> None:
        self._manual_decision = enter
        self._manual_event.set()

    def start(self) -> None:
        if self.is_running:
            return

        if not self.cookie:
            raise ValueError("PHPSESSID cookie is required.")

        self.current_page = 1
        self.indiegala_page = 1
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._manual_event.set()
        self._clear_countdown()
        self.write_log("Stopping bot...")

    def _run(self) -> None:
        try:
            self._check_wins(baseline=not self._wins_tracker.baseline_done)
            self._process_games()
        except Exception as error:
            if not self._stop_event.is_set():
                self.write_log(f"Fatal error: {error}")
        finally:
            self._clear_countdown()

    def _process_games(self) -> None:
        while not self._stop_event.is_set():
            if not self._process_steamgifts_page():
                return

            if self._stop_event.is_set():
                return

            if self.indiegala is not None:
                if not self._process_indiegala_page():
                    return

            if self._stop_event.is_set():
                return

            if self.current_page < self.max_pages:
                self.current_page += 1
                self.indiegala_page += 1
                self.write_log(f"Moving to page {self.current_page}")
                continue

            self.current_page = 1
            self.indiegala_page = 1
            self.write_log(
                f"List of games ended. Waiting {self.refresh_delay_minutes} "
                "minutes to update"
            )
            self._check_wins()
            if self._wait(self.refresh_delay, "refresh"):
                return

    def _collect_wins(self) -> list[WonGiveawayInfo]:
        wins: list[WonGiveawayInfo] = []

        try:
            wins.extend(self.service.fetch_won_giveaways())
        except Exception as error:
            self.write_log(f"[SteamGifts] Win check failed: {error}")

        if self.indiegala is not None:
            try:
                wins.extend(self.indiegala.fetch_won_giveaways())
            except Exception as error:
                self.write_log(f"[IndieGala] Win check failed: {error}")

        return wins

    def _check_wins(self, baseline: bool = False) -> None:
        now = time.time()
        if not baseline and now - self._last_win_check < 300:
            return

        self._last_win_check = now
        wins = self._collect_wins()

        if baseline or not self._wins_tracker.baseline_done:
            if wins:
                self.write_log(
                    f"Tracking {len(wins)} existing win(s) — "
                    "new wins will trigger alerts"
                )
            self._wins_tracker.register_baseline(wins)
            return

        new_wins = self._wins_tracker.find_new(wins)
        if not new_wins:
            return

        for win in new_wins:
            self._wins_tracker.mark_seen(win)
            prefix = "[IndieGala] " if win.source == "indiegala" else "[SteamGifts] "
            self.write_log(f"{prefix}You won: {win.name}")
            if self.on_win:
                self.on_win(win)

        self._wins_tracker.save()

    def _process_steamgifts_page(self) -> bool:
        self.points, self.xsrf_token, giveaways = self.service.fetch_search_page(
            self.current_page
        )

        if self.on_status:
            self.on_status(self.points, self.current_page, "steamgifts")

        self.write_log(f"[SteamGifts] Processing page {self.current_page}")

        if not giveaways:
            self.write_log(f"[SteamGifts] Page {self.current_page} is empty.")
            return True

        page_finished = True
        for giveaway in giveaways:
            if self._stop_event.is_set():
                return False

            if self.points - giveaway.cost < 0 and not giveaway.is_entered:
                timer_info = self.service.fetch_points_timer()
                self.points = timer_info.points
                wait_seconds = timer_info.estimate_seconds_until_points(
                    giveaway.cost
                )
                wait_minutes = max(1, math.ceil(wait_seconds / 60))

                if self.on_waiting_points:
                    self.on_waiting_points(giveaway, self.points, wait_minutes)

                self.write_log(
                    "[SteamGifts] Not enough points for the next giveaway. "
                    f"Waiting {wait_minutes} minutes"
                )

                if self._wait_with_indiegala(wait_seconds, "points"):
                    return False
                page_finished = False
                break

            if not giveaway.is_entered:
                if self.manual_select:
                    if not self._wait_manual_decision(giveaway):
                        self.write_log(
                            f"[SteamGifts] Skipped giveaway: {giveaway.name}"
                        )
                        continue

                if self._wait(self.entry_delay):
                    return False

                self._enter_steamgifts_giveaway(giveaway)

        return page_finished

    def _process_indiegala_page(self, skip_silver_wait: bool = False) -> bool:
        assert self.indiegala is not None

        try:
            account = self.indiegala.fetch_account()
            self.silver = account.silver
        except Exception as error:
            self.write_log(f"[IndieGala] Session check failed: {error}")
            self.write_log(
                "[IndieGala] Re-save cookie (JSON export) and click Test Session."
            )
            return True

        giveaways = self.indiegala.fetch_giveaways_page(self.indiegala_page)

        if self.on_status:
            self.on_status(self.silver, self.indiegala_page, "indiegala")

        self.write_log(
            f"[IndieGala] Processing page {self.indiegala_page} "
            f"({self.silver} iS)"
        )

        if not giveaways:
            self.write_log(f"[IndieGala] Page {self.indiegala_page} is empty.")
            return True

        page_finished = True
        for giveaway in giveaways:
            if self._stop_event.is_set():
                return False

            if (
                self.indiegala_min_cost > 0
                and giveaway.cost < self.indiegala_min_cost
            ):
                continue

            if self.silver < giveaway.cost:
                if skip_silver_wait:
                    continue

                wait_minutes = self.refresh_delay_minutes
                if self.on_waiting_points:
                    self.on_waiting_points(giveaway, self.silver, wait_minutes)

                self.write_log(
                    "[IndieGala] Not enough Silver for the next giveaway. "
                    f"Waiting {wait_minutes} minutes"
                )

                if self._wait_with_steamgifts(wait_minutes * 60, "points"):
                    return False

                try:
                    account = self.indiegala.fetch_account()
                    self.silver = account.silver
                except Exception:
                    pass
                page_finished = False
                break

            if self.manual_select:
                if not self._wait_manual_decision(giveaway):
                    self.write_log(
                        f"[IndieGala] Skipped giveaway: {giveaway.name}"
                    )
                    continue

            if self._wait(self.indiegala_entry_delay):
                return False

            if not self._enter_indiegala_giveaway(giveaway):
                continue

        return page_finished

    def _run_indiegala_cycle(self, skip_silver_wait: bool = False) -> None:
        if self.indiegala is None:
            return

        start_page = self.indiegala_page
        for offset in range(self.max_pages):
            if self._stop_event.is_set():
                return

            page = ((start_page - 1 + offset) % self.max_pages) + 1
            self.indiegala_page = page
            self._process_indiegala_page(skip_silver_wait=skip_silver_wait)

    def _run_steamgifts_entries_on_page(self) -> bool:
        """Enter affordable SteamGifts giveaways on the current page only."""
        self.points, self.xsrf_token, giveaways = self.service.fetch_search_page(
            self.current_page
        )

        if self.on_status:
            self.on_status(self.points, self.current_page, "steamgifts")

        entered_any = False
        for giveaway in giveaways:
            if self._stop_event.is_set():
                return entered_any

            if giveaway.is_entered or self.points < giveaway.cost:
                continue

            if self.manual_select:
                if not self._wait_manual_decision(giveaway):
                    continue

            if self._wait(self.entry_delay):
                return entered_any

            self._enter_steamgifts_giveaway(giveaway)
            entered_any = True

        return entered_any

    def _wait_with_indiegala(self, seconds: int, label: str) -> bool:
        if self.indiegala is None:
            return self._wait(seconds, label)

        end_time = time.time() + seconds
        last_remaining = -1
        last_indiegala_run = 0.0
        scan_interval = max(30, self.indiegala_entry_delay * 3)

        self.write_log(
            "[IndieGala] Will keep scanning during SteamGifts points wait"
        )
        self._run_indiegala_cycle(skip_silver_wait=True)
        last_indiegala_run = time.time()

        while time.time() < end_time:
            if self._stop_event.is_set():
                self._clear_countdown()
                return True

            now = time.time()
            if now - last_indiegala_run >= scan_interval:
                self._run_indiegala_cycle(skip_silver_wait=True)
                last_indiegala_run = now

            remaining = max(0, int(end_time - time.time()))
            if remaining != last_remaining and self.on_countdown:
                self.on_countdown(label, remaining)
                last_remaining = remaining

            time.sleep(0.25)

        self._clear_countdown()
        return False

    def _wait_with_steamgifts(self, seconds: int, label: str) -> bool:
        end_time = time.time() + seconds
        last_remaining = -1
        last_steamgifts_run = 0.0
        scan_interval = max(30, self.entry_delay * 3)

        self.write_log(
            "[SteamGifts] Will keep entering during IndieGala Silver wait"
        )
        self._run_steamgifts_entries_on_page()
        last_steamgifts_run = time.time()

        while time.time() < end_time:
            if self._stop_event.is_set():
                self._clear_countdown()
                return True

            now = time.time()
            if now - last_steamgifts_run >= scan_interval:
                self._run_steamgifts_entries_on_page()
                last_steamgifts_run = now

            remaining = max(0, int(end_time - time.time()))
            if remaining != last_remaining and self.on_countdown:
                self.on_countdown(label, remaining)
                last_remaining = remaining

            time.sleep(0.25)

        self._clear_countdown()
        return False

    def _wait_manual_decision(self, giveaway: GiveawayInfo) -> bool:
        self._manual_event.clear()
        self._manual_decision = False

        if self.on_manual_prompt:
            self.on_manual_prompt(giveaway)

        while not self._stop_event.is_set():
            if self._manual_event.wait(0.3):
                return self._manual_decision

        return False

    def _enter_steamgifts_giveaway(self, giveaway: GiveawayInfo) -> None:
        payload = (
            f"xsrf_token={self.xsrf_token}&do=entry_insert&code={giveaway.code}"
        )
        response = self.service.client.request(
            "https://www.steamgifts.com/ajax.php",
            method="POST",
            headers=self.service.headers,
            data=payload,
        )

        if response.status != 200:
            raise RuntimeError(f"{response.status} - {response.status_text}")

        self.points -= giveaway.cost

        if self.on_status:
            self.on_status(self.points, self.current_page, "steamgifts")

        if self.on_entry:
            self.on_entry(giveaway, "entered")
        else:
            self.write_log(f"[SteamGifts] Entering giveaway: {giveaway.name}")

    def _enter_indiegala_giveaway(self, giveaway: GiveawayInfo) -> bool:
        assert self.indiegala is not None

        try:
            self.silver = self.indiegala.join_giveaway(giveaway)
        except RuntimeError as error:
            message = str(error).lower()
            if "duplicate" in message:
                self.write_log(
                    f"[IndieGala] Already joined: {giveaway.name}"
                )
                return False

            self.write_log(
                f"[IndieGala] Join failed ({giveaway.name}): {error}"
            )
            return False

        if self.on_status:
            self.on_status(self.silver, self.indiegala_page, "indiegala")

        if self.on_entry:
            self.on_entry(giveaway, "entered")
        else:
            self.write_log(f"[IndieGala] Entering giveaway: {giveaway.name}")

        return True

    def _clear_countdown(self) -> None:
        if self.on_countdown:
            self.on_countdown("", 0)

    def _wait(self, seconds: int, label: str = "") -> bool:
        end_time = time.time() + seconds
        last_remaining = -1

        while time.time() < end_time:
            if self._stop_event.is_set():
                self._clear_countdown()
                return True

            remaining = max(0, int(end_time - time.time()))
            if remaining != last_remaining and self.on_countdown:
                self.on_countdown(label, remaining)
                last_remaining = remaining

            time.sleep(0.25)

        self._clear_countdown()
        return False

    def write_log(self, text: str) -> None:
        timestamp = datetime.now().strftime("%d/%m/%Y, %H:%M:%S")
        self.on_log(f"{timestamp} - {text}")
