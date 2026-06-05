import math
import threading
import time
from datetime import datetime
from typing import Callable, Optional

from steamgifts_service import GiveawayInfo, PointsTimerInfo, SteamgiftsService


class SteamgiftsBot:
    def __init__(
        self,
        cookie: str,
        on_log: Callable[[str], None],
        on_status: Optional[Callable[[int, int], None]] = None,
        on_entry: Optional[Callable[[GiveawayInfo, str], None]] = None,
        on_waiting_points: Optional[
            Callable[[GiveawayInfo, int, int], None]
        ] = None,
        on_manual_prompt: Optional[Callable[[GiveawayInfo], None]] = None,
        manual_select: bool = False,
        entry_delay: int = 2,
        refresh_delay: int = 600,
    ):
        self.cookie = cookie.strip()
        self.on_log = on_log
        self.on_status = on_status
        self.on_entry = on_entry
        self.on_waiting_points = on_waiting_points
        self.on_manual_prompt = on_manual_prompt
        self.manual_select = manual_select
        self.entry_delay = entry_delay
        self.refresh_delay = refresh_delay

        self.service = SteamgiftsService(self.cookie)
        self.current_page = 1
        self.xsrf_token = ""
        self.points = 0
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._manual_event = threading.Event()
        self._manual_decision = False

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def set_manual_select(self, enabled: bool) -> None:
        self.manual_select = enabled

    def submit_manual_decision(self, enter: bool) -> None:
        self._manual_decision = enter
        self._manual_event.set()

    def start(self) -> None:
        if self.is_running:
            return

        if not self.cookie:
            raise ValueError("PHPSESSID cookie is required.")

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._manual_event.set()
        self.write_log("Stopping bot...")

    def _run(self) -> None:
        try:
            self._process_games()
        except Exception as error:
            if not self._stop_event.is_set():
                self.write_log(f"Fatal error: {error}")

    def _process_games(self) -> None:
        while not self._stop_event.is_set():
            self.points, self.xsrf_token, giveaways = self.service.fetch_search_page(
                self.current_page
            )

            if self.on_status:
                self.on_status(self.points, self.current_page)

            self.write_log(f"Processing games from Page {self.current_page}")

            for giveaway in giveaways:
                if self._stop_event.is_set():
                    return

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
                        "Not enough Points to enter the next giveaway. "
                        f"Waiting {wait_minutes} minutes to get more Points"
                    )

                    if self._wait(wait_seconds):
                        return
                    break

                if not giveaway.is_entered:
                    if self.manual_select:
                        if not self._wait_manual_decision(giveaway):
                            self.write_log(f"Skipped giveaway: {giveaway.name}")
                            continue

                    if self._wait(self.entry_delay):
                        return

                    self._enter_giveaway(giveaway)

            if self._stop_event.is_set():
                return

            self.write_log(
                f"List of games ended. Waiting {self.refresh_delay // 60} minutes to update"
            )
            if self._wait(self.refresh_delay):
                return

    def _wait_manual_decision(self, giveaway: GiveawayInfo) -> bool:
        self._manual_event.clear()
        self._manual_decision = False

        if self.on_manual_prompt:
            self.on_manual_prompt(giveaway)

        while not self._stop_event.is_set():
            if self._manual_event.wait(0.3):
                return self._manual_decision

        return False

    def _enter_giveaway(self, giveaway: GiveawayInfo) -> None:
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
            self.on_status(self.points, self.current_page)

        if self.on_entry:
            self.on_entry(giveaway, "entered")
        else:
            self.write_log(f"Entering giveaway: {giveaway.name}")

    def _wait(self, seconds: int) -> bool:
        end_time = time.time() + seconds
        while time.time() < end_time:
            if self._stop_event.is_set():
                return True
            time.sleep(0.5)
        return False

    def write_log(self, text: str) -> None:
        timestamp = datetime.now().strftime("%d/%m/%Y, %H:%M:%S")
        self.on_log(f"{timestamp} - {text}")
