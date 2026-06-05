import re
import time
from dataclasses import dataclass
from typing import Optional

from bs4 import BeautifulSoup

from http_client import HttpClient

STEAM_CAPSULE_URL = (
    "https://cdn.cloudflare.steamstatic.com/steam/apps/{app_id}/capsule_184x69.jpg"
)

POINTS_PER_INTERVAL = 6
POINTS_INTERVAL_SECONDS = 15 * 60
MAX_POINTS = 400


@dataclass
class PointsTimerInfo:
    points: int
    username: str
    next_points_at: Optional[int] = None
    points_per_interval: int = POINTS_PER_INTERVAL
    interval_seconds: int = POINTS_INTERVAL_SECONDS
    max_points: int = MAX_POINTS

    def seconds_until_next(self, now: Optional[int] = None) -> Optional[int]:
        if self.points >= self.max_points:
            return None

        current = now or int(time.time())
        if self.next_points_at and self.next_points_at > current:
            return self.next_points_at - current

        return self.interval_seconds

    def estimate_seconds_until_points(self, target_points: int) -> int:
        if self.points >= target_points:
            return 0

        deficit = target_points - self.points
        intervals = (deficit + self.points_per_interval - 1) // self.points_per_interval
        next_tick = self.seconds_until_next() or self.interval_seconds
        return next_tick + max(0, intervals - 1) * self.interval_seconds


@dataclass
class GiveawayInfo:
    name: str
    code: str
    cost: int
    image_url: str
    is_entered: bool


def build_headers(cookie: str) -> dict[str, str]:
    return {
        "Cookie": f"PHPSESSID={cookie.strip()}",
        "Referer": "https://www.steamgifts.com/",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }


def steam_image_url(app_id: str) -> str:
    return STEAM_CAPSULE_URL.format(app_id=app_id)


def extract_steam_app_id(element) -> Optional[str]:
    steam_link = element.select_one("a.giveaway__icon[href*='steampowered.com/app/']")
    if not steam_link:
        return None

    match = re.search(r"/app/(\d+)", steam_link.get("href", ""))
    return match.group(1) if match else None


def parse_giveaway_row(element) -> GiveawayInfo:
    cost_el = element.select(".giveaway__heading__thin")
    game_cost = (
        int(re.sub(r"[^0-9]", "", cost_el[-1].get_text())) if cost_el else 0
    )

    name_el = element.select_one(".giveaway__heading__name")
    game_name = name_el.get_text(strip=True) if name_el else "Unknown"
    game_href = name_el.get("href", "") if name_el else ""
    game_code = game_href.split("/")[2] if game_href else ""

    app_id = extract_steam_app_id(element)
    image_url = steam_image_url(app_id) if app_id else ""

    return GiveawayInfo(
        name=game_name,
        code=game_code,
        cost=game_cost,
        image_url=image_url,
        is_entered="is-faded" in element.get("class", []),
    )


def _find_next_points_timestamp(soup: BeautifulSoup) -> Optional[int]:
    now = int(time.time())
    candidates: list[int] = []

    search_roots = [
        soup.select_one(".nav__right-container"),
        soup.select_one("header"),
        soup.select_one("nav"),
    ]

    for root in search_roots:
        if not root:
            continue
        for element in root.select("[data-timestamp]"):
            raw = element.get("data-timestamp", "")
            if raw.isdigit():
                timestamp = int(raw)
                if timestamp > now:
                    candidates.append(timestamp)

    if candidates:
        return min(candidates)

    return None


def parse_points_timer(html: str) -> PointsTimerInfo:
    soup = BeautifulSoup(html, "html.parser")

    points_el = soup.select_one(".nav__points")
    points = int(re.sub(r"[^0-9]", "", points_el.get_text())) if points_el else 0

    username_el = soup.select_one(".nav__user-name")
    username = username_el.get_text(strip=True) if username_el else ""

    return PointsTimerInfo(
        points=points,
        username=username,
        next_points_at=_find_next_points_timestamp(soup),
    )


def parse_page(html: str) -> tuple[int, str, list[GiveawayInfo]]:
    soup = BeautifulSoup(html, "html.parser")

    points_el = soup.select_one(".nav__points")
    points = int(re.sub(r"[^0-9]", "", points_el.get_text())) if points_el else 0

    xsrf_input = soup.select_one('[name="xsrf_token"]')
    xsrf_token = xsrf_input.get("value", "") if xsrf_input else ""

    giveaways = [
        parse_giveaway_row(game) for game in soup.select(".giveaway__row-inner-wrap")
    ]

    return points, xsrf_token, giveaways


class SteamgiftsService:
    def __init__(self, cookie: str):
        self.cookie = cookie.strip()
        self.client = HttpClient()
        self.headers = build_headers(self.cookie)
        self.html = ""

    def _fetch(self, url: str) -> str:
        response = self.client.request(url, method="GET", headers=self.headers)

        if response.status != 200:
            raise RuntimeError(f"{response.status} - {response.status_text}")

        if "Just a moment" in response.data:
            raise RuntimeError(
                "Cloudflare blocked the request. Refresh your PHPSESSID cookie."
            )

        return response.data

    def fetch_points_timer(self) -> PointsTimerInfo:
        html = self._fetch("https://www.steamgifts.com/")
        return parse_points_timer(html)

    def fetch_search_page(self, page: int = 1) -> tuple[int, str, list[GiveawayInfo]]:
        html = self._fetch(f"https://www.steamgifts.com/giveaways/search?page={page}")
        self.html = html
        return parse_page(html)
