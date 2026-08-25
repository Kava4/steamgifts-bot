"""Free proxies via ProxyScrape Public API (v4).

Docs: https://docs.proxyscrape.com/api-overview
"""

from __future__ import annotations

import random
from typing import Optional
from urllib.parse import urlencode

from http_client import HttpClient

PROXYSCRAPE_V4 = "https://api.proxyscrape.com/v4/free-proxy-list/get"


def _proxyscrape_url(
    protocol: str = "http",
    timeout_ms: int = 3000,
    limit: int = 40,
) -> str:
    query = urlencode(
        {
            "request": "displayproxies",
            "protocol": protocol,
            "timeout": str(timeout_ms),
            "country": "all",
            "ssl": "all",
            "anonymity": "all",
            "limit": str(min(limit, 2000)),
        }
    )
    return f"{PROXYSCRAPE_V4}?{query}"


def _parse_proxy_lines(text: str, default_scheme: str = "http") -> list[str]:
    proxies: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "://" in line:
            proxies.append(line)
            continue
        if ":" in line and " " not in line:
            proxies.append(f"{default_scheme}://{line}")
    return proxies


def fetch_free_proxy_candidates(
    limit: int = 30,
    protocol: str = "http",
) -> list[str]:
    client = HttpClient(connect_timeout=8, max_time=15)
    found: list[str] = []
    try:
        response = client.request(
            _proxyscrape_url(protocol=protocol, limit=max(limit, 30)),
            method="GET",
        )
        if response.status == 200 and response.data.strip():
            default = "socks5" if protocol.startswith("socks") else "http"
            found.extend(_parse_proxy_lines(response.data, default_scheme=default))
    except Exception:
        pass

    seen: set[str] = set()
    unique: list[str] = []
    for proxy in found:
        if proxy in seen:
            continue
        seen.add(proxy)
        unique.append(proxy)
    random.shuffle(unique)
    return unique[:limit]


def pick_working_free_proxy(
    test_url: str = "https://www.steamgifts.com/",
    attempts: int = 6,
    protocol: str = "http",
) -> Optional[str]:
    """Try a few ProxyScrape candidates quickly (short timeouts)."""
    candidates = fetch_free_proxy_candidates(
        limit=max(attempts * 3, 18),
        protocol=protocol,
    )
    for proxy in candidates[:attempts]:
        try:
            client = HttpClient(proxy=proxy, connect_timeout=4, max_time=8)
            response = client.request(test_url, method="GET")
            if response.status == 200 and len(response.data) > 200:
                return proxy
        except Exception:
            continue
    return None
