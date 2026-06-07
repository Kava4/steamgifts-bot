import json
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import unquote

from bs4 import BeautifulSoup

from http_client import HttpClient
from steamgifts_service import GiveawayInfo, WonGiveawayInfo

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
        value = unquote(value.strip())
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
            cookies[name] = unquote(str(value))

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
        cookies[key.strip().lower()] = unquote(value.strip())
    else:
        cookies["sessionid"] = text

    sessionid = cookies.get("sessionid", "")
    csrftoken = cookies.get("csrftoken", "")

    if not sessionid:
        raise ValueError(
            "IndieGala cookie must include sessionid "
            "(paste JSON export or sessionid=...; csrftoken=...)."
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
    cookie_header, _ = parse_indiegala_cookie(raw)
    return cookie_header


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

    price_el = element.select_one(".items-list-item-data-button a")
    cost = 0
    if price_el is not None:
        raw_price = price_el.get("data-price") or price_el.get_text(strip=True)
        cost = int(re.sub(r"[^0-9]", "", raw_price) or "0")

    image_el = element.select_one("img[data-img-src]")
    image_url = image_el.get("data-img-src", "") if image_el else ""

    ends_label_el = element.select_one(".items-list-item-data-left-bottom")
    ends_label = ends_label_el.get_text(strip=True) if ends_label_el else ""

    return GiveawayInfo(
        name=name,
        code=giveaway_id,
        cost=cost,
        image_url=image_url,
        is_entered=False,
        ends_label=ends_label,
        source="indiegala",
        join_token=join_token,
    )


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
    def __init__(self, cookie: str):
        self.cookie_header, self.csrf_token = parse_indiegala_cookie(cookie)
        self.client = HttpClient()
        self.silver = 0

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
        )

        if response.status != 200:
            raise RuntimeError(f"{response.status} - {response.status_text}")

        try:
            payload = json.loads(response.data)
        except json.JSONDecodeError as error:
            raise RuntimeError("IndieGala returned invalid JSON.") from error

        user = payload.get("user") or payload
        if not isinstance(user, dict):
            raise RuntimeError("IndieGala session is not logged in.")

        current_user = user.get("current_user") or {}
        username = current_user.get("username", "")
        if not username and payload.get("status") not in (None, "ok"):
            raise RuntimeError(
                payload.get("status", "IndieGala session is not logged in.")
            )

        self.silver = int(user.get("silver_coins_tot") or 0)
        return IndieGalaAccountInfo(silver=self.silver, username=username)

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
