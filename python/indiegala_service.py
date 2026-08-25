import json
import re
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import unquote

from bs4 import BeautifulSoup

from http_client import HttpClient
from steamgifts_service import EnteredGiveawayInfo, GiveawayInfo, WonGiveawayInfo

BASE_URL = "https://www.indiegala.com"
JOIN_PATTERN = re.compile(
    r"joinGiveawayOrAuction\s*\(\s*this\s*,\s*event\s*,\s*'(\d+)'\s*,\s*(\d+)\s*,\s*'([^']*)'\s*\)"
)
GIVEAWAY_CARD_PATTERN = re.compile(r"/giveaways/card/[^/]+/(\d+)")


@dataclass
class IndieGalaAccountInfo:
    silver: int
    username: str


IMPORTANT_COOKIE_NAMES = ("sessionid", "csrftoken", "xf_user")


def _parse_cookie_pairs(raw: str) -> dict[str, str]:
    cookies: dict[str, str] = {}

    for part in raw.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip().lower()
        # Keep raw cookie values — unquoting can break Django sessionids.
        value = value.strip()
        if key:
            cookies[key] = value

    return cookies


def _parse_cookie_json(raw: str) -> dict[str, str]:
    cookies: dict[str, str] = {}
    data = json.loads(raw)

    items = data if isinstance(data, list) else [data]
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip().lower()
        value = item.get("value", "")
        if name and value is not None and str(value):
            # Prefer raw export value; only unquote if it clearly looks encoded.
            text = str(value)
            if "%" in text:
                try:
                    text = unquote(text)
                except Exception:
                    pass
            cookies[name] = text

    return cookies


def parse_indiegala_cookie(raw: str) -> tuple[str, str]:
    text = raw.strip()
    if not text:
        raise ValueError("IndieGala cookie is empty.")

    cookies: dict[str, str] = {}
    if text.startswith("[") or text.startswith("{"):
        try:
            cookies = _parse_cookie_json(text)
        except json.JSONDecodeError as error:
            raise ValueError(
                "Invalid IndieGala JSON cookie export."
            ) from error
    elif "=" in text and ";" in text:
        cookies = _parse_cookie_pairs(text)
    elif "=" in text:
        key, value = text.split("=", 1)
        cookies[key.strip().lower()] = value.strip()
    else:
        cookies["sessionid"] = text

    sessionid = cookies.get("sessionid", "")
    csrftoken = cookies.get("csrftoken", "")

    if not sessionid:
        raise ValueError(
            "IndieGala cookie must include sessionid "
            "(paste Cookie-Editor JSON export for indiegala.com)."
        )

    parts: list[str] = []
    for name in IMPORTANT_COOKIE_NAMES:
        if cookies.get(name):
            parts.append(f"{name}={cookies[name]}")

    for name, value in cookies.items():
        if name not in IMPORTANT_COOKIE_NAMES:
            parts.append(f"{name}={value}")

    cookie_header = "; ".join(parts)
    return cookie_header, csrftoken


def format_indiegala_cookie_storage(raw: str) -> str:
    """Validate cookie and store Cookie-Editor JSON as-is when possible."""
    text = raw.strip()
    if not text:
        raise ValueError("IndieGala cookie is empty.")
    # Keep full JSON export — preserves all cookies for this account.
    if text.startswith("["):
        parse_indiegala_cookie(text)
        return text
    cookie_header, _ = parse_indiegala_cookie(text)
    return cookie_header


def parse_ig_ends_at(ends_label: str) -> int:
    """Best-effort absolute end time from labels like '5 minutes left'."""
    text = (ends_label or "").strip().lower()
    if not text:
        return 0
    match = re.search(
        r"(\d+)\s*(second|minute|hour|day|week)s?\s*(left|remaining)?",
        text,
    )
    if not match:
        return 0
    amount = int(match.group(1))
    unit = match.group(2)
    multipliers = {
        "second": 1,
        "minute": 60,
        "hour": 3600,
        "day": 86400,
        "week": 604800,
    }
    return int(time.time()) + amount * multipliers[unit]


def _card_image_url(element) -> str:
    image_el = element.select_one("img[data-img-src]")
    if image_el is not None:
        return image_el.get("data-img-src", "") or ""
    image_el = element.select_one("img[src]")
    return image_el.get("src", "") if image_el else ""


def _card_cost(element) -> int:
    price_el = element.select_one(".items-list-item-data-button a")
    if price_el is None:
        price_el = element.select_one("[data-price]")
    if price_el is None:
        return 0
    raw_price = price_el.get("data-price") or price_el.get_text(strip=True)
    return int(re.sub(r"[^0-9]", "", raw_price) or "0")


def _card_ends_label(element) -> str:
    ends_label_el = element.select_one(".items-list-item-data-left-bottom")
    return ends_label_el.get_text(strip=True) if ends_label_el else ""


def parse_giveaway_item(element) -> Optional[GiveawayInfo]:
    title_el = element.select_one(".items-list-item-title a")
    if title_el is None:
        return None

    name = title_el.get_text(strip=True)
    if not name:
        return None

    join_el = None
    join_match = None
    for candidate in element.find_all(onclick=True):
        match = JOIN_PATTERN.search(candidate.get("onclick", ""))
        if match:
            join_el = candidate
            join_match = match
            break

    if join_el is None or join_match is None:
        return None

    giveaway_id, _extra_odds, join_token = join_match.groups()
    button = element.select_one(".items-list-item-data-button")
    button_classes = button.get("class", []) if button else []
    if "items-list-item-data-not-purchasable" in button_classes:
        return None

    ends_label = _card_ends_label(element)
    return GiveawayInfo(
        name=name,
        code=giveaway_id,
        cost=_card_cost(element),
        image_url=_card_image_url(element),
        is_entered=False,
        ends_at=parse_ig_ends_at(ends_label) or None,
        ends_label=ends_label,
        source="indiegala",
        join_token=join_token,
    )


def parse_entered_item(element) -> Optional[EnteredGiveawayInfo]:
    """
    IndieGala marks joined giveaways by removing the clickable ticket control.
    'SINGLE TICKET' is the giveaway type, not an entered flag.
    """
    if element.select_one(".items-list-item-ticket-click") is not None:
        return None

    title_el = element.select_one(".items-list-item-title a")
    if title_el is None:
        return None

    name = title_el.get_text(strip=True)
    href = title_el.get("href", "")
    match = GIVEAWAY_CARD_PATTERN.search(href)
    if not name or not match:
        return None

    giveaway_id = match.group(1)
    ends_label = _card_ends_label(element)
    url = href if href.startswith("http") else f"{BASE_URL}{href}"
    entries_el = element.select_one(".items-list-item-data-right-bottom")
    entries_count = ""
    if entries_el is not None:
        entries_count = re.sub(r"[^0-9]", "", entries_el.get_text(" ", strip=True))

    return EnteredGiveawayInfo(
        name=name,
        code=giveaway_id,
        cost=_card_cost(element),
        image_url=_card_image_url(element),
        ends_at=parse_ig_ends_at(ends_label),
        remaining_label=ends_label,
        entries_count=entries_count,
        entered_label="IndieGala",
        xsrf_token="",
        source="indiegala",
        url=url,
    )


def parse_entered_html(html: str) -> list[EnteredGiveawayInfo]:
    soup = BeautifulSoup(html, "html.parser")
    entered: list[EnteredGiveawayInfo] = []
    seen: set[str] = set()
    for item in soup.select(".items-list-item"):
        info = parse_entered_item(item)
        if info is None or info.code in seen:
            continue
        seen.add(info.code)
        entered.append(info)
    return entered


def parse_giveaways_html(html: str) -> list[GiveawayInfo]:
    soup = BeautifulSoup(html, "html.parser")
    giveaways: list[GiveawayInfo] = []

    for item in soup.select(".items-list-item"):
        info = parse_giveaway_item(item)
        if info is not None:
            giveaways.append(info)

    return giveaways


def parse_won_items_html(html: str) -> list[WonGiveawayInfo]:
    soup = BeautifulSoup(html, "html.parser")
    wins: list[WonGiveawayInfo] = []
    seen: set[str] = set()

    for item in soup.select(".items-list-item"):
        title_el = item.select_one(".items-list-item-title a")
        if title_el is None:
            continue

        href = title_el.get("href", "")
        match = GIVEAWAY_CARD_PATTERN.search(href)
        if not match:
            continue

        giveaway_id = match.group(1)
        if giveaway_id in seen:
            continue

        name = title_el.get_text(strip=True)
        if not name:
            continue

        image_el = item.select_one("img[data-img-src]")
        image_url = image_el.get("data-img-src", "") if image_el else ""
        url = href if href.startswith("http") else f"{BASE_URL}{href}"

        seen.add(giveaway_id)
        wins.append(
            WonGiveawayInfo(
                name=name,
                code=giveaway_id,
                image_url=image_url,
                source="indiegala",
                url=url,
            )
        )

    if wins:
        return wins

    for link in soup.select("a[href*='/giveaways/card/']"):
        href = link.get("href", "")
        match = GIVEAWAY_CARD_PATTERN.search(href)
        if not match:
            continue

        giveaway_id = match.group(1)
        if giveaway_id in seen:
            continue

        name = link.get_text(strip=True)
        if not name or len(name) < 2:
            continue

        url = href if href.startswith("http") else f"{BASE_URL}{href}"
        seen.add(giveaway_id)
        wins.append(
            WonGiveawayInfo(
                name=name,
                code=giveaway_id,
                image_url="",
                source="indiegala",
                url=url,
            )
        )

    return wins


class IndieGalaService:
    def __init__(self, cookie: str, proxy: str = ""):
        self.cookie_header, self.csrf_token = parse_indiegala_cookie(cookie)
        self.client = HttpClient(proxy=proxy)
        self.silver = 0
        self.proxy = (proxy or "").strip()

    def _ajax_headers(self, content_type: str = "application/json") -> dict[str, str]:
        headers = {
            "Cookie": self.cookie_header,
            "Referer": f"{BASE_URL}/giveaways",
            "Origin": BASE_URL,
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
        }
        if content_type:
            headers["Content-Type"] = content_type
        if self.csrf_token:
            headers["X-CSRFToken"] = self.csrf_token
            headers["X-CSRF-Token"] = self.csrf_token
        return headers

    def _json_headers(self) -> dict[str, str]:
        return self._ajax_headers("application/json")

    def _html_headers(self) -> dict[str, str]:
        headers = self._ajax_headers("")
        headers.pop("Content-Type", None)
        headers["Accept"] = (
            "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        )
        return headers

    def ensure_csrf_token(self) -> None:
        if self.csrf_token:
            return

        response = self.client.request(
            f"{BASE_URL}/giveaways",
            method="GET",
            headers=self._html_headers(),
        )
        if response.status != 200:
            raise RuntimeError(f"{response.status} - {response.status_text}")

        soup = BeautifulSoup(response.data, "html.parser")
        token_el = soup.select_one('[name="csrfmiddlewaretoken"]')
        if token_el is None:
            raise RuntimeError(
                "Could not find IndieGala CSRF token. Paste csrftoken in the cookie field."
            )

        self.csrf_token = token_el.get("value", "")
        if "csrftoken=" not in self.cookie_header and self.csrf_token:
            self.cookie_header += f"; csrftoken={self.csrf_token}"

    def _fetch_json(self, path: str, method: str = "GET", body: Optional[dict] = None) -> dict:
        self.ensure_csrf_token()
        data = json.dumps(body) if body is not None else None
        response = self.client.request(
            f"{BASE_URL}{path}",
            method=method,
            headers=self._json_headers(),
            data=data,
        )

        if response.status != 200:
            raise RuntimeError(f"{response.status} - {response.status_text}")

        try:
            payload = json.loads(response.data)
        except json.JSONDecodeError as error:
            raise RuntimeError("IndieGala returned invalid JSON.") from error

        if payload.get("status") != "ok":
            raise RuntimeError(payload.get("status", "IndieGala request failed"))

        return payload

    def fetch_account(self) -> IndieGalaAccountInfo:
        self.ensure_csrf_token()
        response = self.client.request(
            f"{BASE_URL}/ajax/user/get-data",
            method="POST",
            headers=self._json_headers(),
            data="{}",
        )

        if response.status != 200:
            raise RuntimeError(f"{response.status} - {response.status_text}")

        try:
            payload = json.loads(response.data)
        except json.JSONDecodeError as error:
            raise RuntimeError("IndieGala returned invalid JSON.") from error

        if payload.get("user_is_logged") is False:
            raise RuntimeError(
                "IndieGala session is not logged in. "
                "In the browser, log into THAT account, open indiegala.com, "
                "export cookies with Cookie-Editor (JSON), then Save account. "
                "Use a separate browser profile per IndieGala account."
            )

        user = payload.get("user") or payload
        if not isinstance(user, dict):
            raise RuntimeError("IndieGala session is not logged in.")

        current_user = user.get("current_user") or payload.get("current_user") or {}
        if not isinstance(current_user, dict):
            current_user = {}

        username = str(current_user.get("username") or "").strip()
        self.silver = int(
            user.get("silver_coins_tot")
            or payload.get("silver_coins_tot")
            or 0
        )
        if not username and self.silver <= 0 and payload.get("user_is_logged") is not True:
            raise RuntimeError(
                "IndieGala session is not logged in. "
                "Re-export Cookie-Editor JSON while logged in on indiegala.com."
            )

        return IndieGalaAccountInfo(
            silver=self.silver,
            username=username or "IndieGala",
        )

    def fetch_giveaways_page(
        self,
        page: int = 1,
        sort: str = "expiry",
        order: str = "asc",
        level: int = 0,
    ) -> list[GiveawayInfo]:
        path = f"/giveaways/ajax/{page}/{sort}/{order}/level/{level}"
        payload = self._fetch_json(path)
        return parse_giveaways_html(payload.get("html", ""))

    def fetch_entered_giveaways(
        self,
        max_pages: int = 5,
        sort: str = "expiry",
        order: str = "asc",
        level: int = 0,
    ) -> list[EnteredGiveawayInfo]:
        """
        IndieGala has no public /entered feed. When logged in, joined cards
        lose `.items-list-item-ticket-click` on the listing AJAX pages.
        """
        self.fetch_account()
        found: list[EnteredGiveawayInfo] = []
        seen: set[str] = set()
        pages = max(1, min(int(max_pages or 5), 20))

        for page in range(1, pages + 1):
            path = f"/giveaways/ajax/{page}/{sort}/{order}/level/{level}"
            payload = self._fetch_json(path)
            for item in parse_entered_html(payload.get("html", "")):
                if item.code in seen:
                    continue
                seen.add(item.code)
                found.append(item)

        return found

    def join_giveaway(self, giveaway: GiveawayInfo) -> int:
        self.ensure_csrf_token()
        response = self.client.request(
            f"{BASE_URL}/giveaways/join",
            method="POST",
            headers=self._json_headers(),
            data=json.dumps({"id": giveaway.code, "token": giveaway.join_token}),
        )

        if response.status != 200:
            raise RuntimeError(f"{response.status} - {response.status_text}")

        try:
            payload = json.loads(response.data)
        except json.JSONDecodeError as error:
            raise RuntimeError("IndieGala returned invalid JSON.") from error

        status = payload.get("status", "")
        if status == "ok":
            self.silver = int(payload.get("silver_tot") or self.silver)
            return self.silver

        raise RuntimeError(status or "IndieGala join failed")

    def fetch_won_giveaways(self) -> list[WonGiveawayInfo]:
        self.ensure_csrf_token()
        headers = self._html_headers()
        headers["Referer"] = f"{BASE_URL}/profile"

        response = self.client.request(
            f"{BASE_URL}/giveaways/check_if_won_all",
            method="GET",
            headers=headers,
        )

        if response.status != 200:
            raise RuntimeError(f"{response.status} - {response.status_text}")

        wins = parse_won_items_html(response.data)
        if wins:
            return wins

        profile = self.client.request(
            f"{BASE_URL}/profile",
            method="GET",
            headers=headers,
        )
        if profile.status != 200:
            return wins

        return parse_won_items_html(profile.data)
