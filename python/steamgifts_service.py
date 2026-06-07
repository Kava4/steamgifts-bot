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
    ends_at: Optional[int] = None
    ends_label: str = ""
    source: str = "steamgifts"
    join_token: str = ""


@dataclass
class EnteredGiveawayInfo:
    name: str
    code: str
    cost: int
    image_url: str
    ends_at: int
    remaining_label: str
    entries_count: str
    entered_label: str
    xsrf_token: str


@dataclass
class WonGiveawayInfo:
    name: str
    code: str
    image_url: str
    source: str = "steamgifts"
    url: str = ""


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


def parse_giveaway_end(element) -> tuple[Optional[int], str]:
    now = int(time.time())
    best_ts: Optional[int] = None
    best_label = ""

    for time_el in element.select("[data-timestamp]"):
        raw = time_el.get("data-timestamp", "")
        if not raw.isdigit():
            continue

        timestamp = int(raw)
        label = time_el.get_text(" ", strip=True)
        if timestamp <= now:
            continue

        if best_ts is None or timestamp < best_ts:
            best_ts = timestamp
            best_label = label

    if best_label:
        return best_ts, best_label

    for time_el in element.select("[data-timestamp]"):
        label = time_el.get_text(" ", strip=True)
        if "remaining" in label.lower() or "left" in label.lower():
            raw = time_el.get("data-timestamp", "")
            ts = int(raw) if raw.isdigit() else None
            return ts, label

    return None, ""


def format_giveaway_ends(ends_at: Optional[int], ends_label: str) -> str:
    if ends_label:
        return ends_label

    if not ends_at:
        return ""

    remaining = ends_at - int(time.time())
    if remaining <= 0:
        return "Ended"

    days, rem = divmod(remaining, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)

    if days:
        return f"{days} day{'s' if days != 1 else ''} remaining"
    if hours:
        return f"{hours} hour{'s' if hours != 1 else ''} remaining"
    minutes = max(1, minutes)
    return f"{minutes} minute{'s' if minutes != 1 else ''} remaining"


def giveaway_remaining_seconds(
    giveaway: GiveawayInfo, now: Optional[int] = None
) -> Optional[int]:
    if not giveaway.ends_at:
        return None

    current = now or int(time.time())
    if giveaway.ends_at <= current:
        return 0

    return giveaway.ends_at - current


def giveaway_within_end_window(
    giveaway: GiveawayInfo, max_hours: int, now: Optional[int] = None
) -> bool:
    if max_hours <= 0:
        return True

    remaining = giveaway_remaining_seconds(giveaway, now)
    if remaining is None:
        return giveaway.source != "steamgifts"

    return remaining <= max_hours * 3600


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
    ends_at, ends_label = parse_giveaway_end(element)

    return GiveawayInfo(
        name=game_name,
        code=game_code,
        cost=game_cost,
        image_url=image_url,
        is_entered="is-faded" in element.get("class", []),
        ends_at=ends_at,
        ends_label=ends_label,
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


def parse_thumbnail_url(element) -> str:
    thumb = element.select_one(".table_image_thumbnail")
    if not thumb:
        return ""

    match = re.search(r"url\(([^)]+)\)", thumb.get("style", ""))
    if not match:
        return ""

    return match.group(1).strip("\"'")


def parse_cost_from_heading(heading_el) -> int:
    for el in reversed(heading_el.select(".is-faded")):
        text = el.get_text(strip=True)
        if text.endswith("P") and "Copies" not in text:
            return int(re.sub(r"[^0-9]", "", text) or "0")
    return 0


def parse_entered_row(element) -> Optional[EnteredGiveawayInfo]:
    delete_form = element.select_one('form input[name="do"][value="entry_delete"]')
    if delete_form is None:
        return None

    form = delete_form.find_parent("form")
    if form is None:
        return None

    code_input = form.select_one('input[name="code"]')
    xsrf_input = form.select_one('input[name="xsrf_token"]')
    code = code_input.get("value", "") if code_input else ""
    xsrf_token = xsrf_input.get("value", "") if xsrf_input else ""
    if not code or not xsrf_token:
        return None

    heading_el = element.select_one(".table__column__heading")
    if heading_el is None:
        return None

    cost = parse_cost_from_heading(heading_el)

    href = heading_el.get("href", "")
    for faded in heading_el.select(".is-faded"):
        faded.decompose()

    name = heading_el.get_text(strip=True)
    if not name:
        name = "Unknown"
    if not code and href:
        parts = href.strip("/").split("/")
        if len(parts) >= 2 and parts[0] == "giveaway":
            code = parts[1]

    fill_col = element.select_one(".table__column--width-fill")
    if fill_col is None:
        return None

    paragraphs = fill_col.find_all("p", recursive=False)
    if len(paragraphs) < 2:
        return None

    time_p = paragraphs[1]
    time_text = time_p.get_text(" ", strip=True)
    if "remaining" not in time_text.lower():
        return None

    time_el = time_p.select_one("[data-timestamp]")
    if time_el is None:
        return None

    raw_ts = time_el.get("data-timestamp", "")
    if not raw_ts.isdigit():
        return None

    ends_at = int(raw_ts)
    if ends_at <= int(time.time()):
        return None

    small_cols = element.select(".table__column--width-small.text-center")
    entries_count = small_cols[0].get_text(strip=True) if len(small_cols) > 0 else ""
    entered_label = small_cols[1].get_text(" ", strip=True) if len(small_cols) > 1 else ""

    return EnteredGiveawayInfo(
        name=name,
        code=code,
        cost=cost,
        image_url=parse_thumbnail_url(element),
        ends_at=ends_at,
        remaining_label=time_text,
        entries_count=entries_count,
        entered_label=entered_label,
        xsrf_token=xsrf_token,
    )


def parse_won_notification_count(html: str) -> Optional[int]:
    soup = BeautifulSoup(html, "html.parser")
    nav = soup.select_one(".nav__right-container")
    if nav is None:
        return None

    for link in nav.select("a[href*='/giveaways/won']"):
        badge = link.select_one(".nav__notification")
        if badge is None:
            continue
        text = badge.get_text(strip=True)
        if text.isdigit():
            return int(text)

    return None


def is_won_row_received(element) -> bool:
    for col in element.select(".table__column--width-small"):
        text = col.get_text(" ", strip=True)
        if "Not Received" in text:
            return False
        if text == "Received":
            return True
    return False


def parse_won_row(element) -> Optional[WonGiveawayInfo]:
    if element.select_one('form input[name="do"][value="entry_delete"]'):
        return None

    if is_won_row_received(element):
        return None

    heading_el = element.select_one(".table__column__heading")
    if heading_el is None:
        return None

    href = heading_el.get("href", "")
    for faded in heading_el.select(".is-faded"):
        faded.decompose()

    name = heading_el.get_text(strip=True) or "Unknown"
    code = ""
    if href:
        parts = href.strip("/").split("/")
        if len(parts) >= 2 and parts[0] == "giveaway":
            code = parts[1]

    if not code:
        return None

    url = href if href.startswith("http") else f"https://www.steamgifts.com{href}"

    return WonGiveawayInfo(
        name=name,
        code=code,
        image_url=parse_thumbnail_url(element),
        source="steamgifts",
        url=url,
    )


def parse_won_page(html: str) -> list[WonGiveawayInfo]:
    soup = BeautifulSoup(html, "html.parser")
    giveaways: list[WonGiveawayInfo] = []

    for row in soup.select(".table__row-inner-wrap"):
        info = parse_won_row(row)
        if info is not None:
            giveaways.append(info)

    return giveaways


def parse_entered_page(html: str) -> list[EnteredGiveawayInfo]:
    soup = BeautifulSoup(html, "html.parser")
    giveaways: list[EnteredGiveawayInfo] = []

    for row in soup.select(".table__row-inner-wrap"):
        info = parse_entered_row(row)
        if info is not None:
            giveaways.append(info)

    giveaways.sort(key=lambda item: item.ends_at)
    return giveaways


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

    def fetch_entered_giveaways(self) -> list[EnteredGiveawayInfo]:
        html = self._fetch("https://www.steamgifts.com/giveaways/entered")
        return parse_entered_page(html)

    def fetch_won_giveaways(self) -> list[WonGiveawayInfo]:
        html = self._fetch("https://www.steamgifts.com/giveaways/won")
        return parse_won_page(html)

    def remove_entry(self, code: str, xsrf_token: str) -> None:
        payload = f"xsrf_token={xsrf_token}&do=entry_delete&code={code}"
        response = self.client.request(
            "https://www.steamgifts.com/ajax.php",
            method="POST",
            headers=self.headers,
            data=payload,
        )

        if response.status != 200:
            raise RuntimeError(f"{response.status} - {response.status_text}")
