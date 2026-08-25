#!/usr/bin/env python3
"""
IndieGala browser login helper — run on your PC.

Opens Chrome. You log in. Press ENTER in this terminal. Cookie is sent to the bot.

  python ig_login_helper.py --server http://192.168.1.80:8765 --token YOUR_TOKEN
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

HOME_URL = "https://www.indiegala.com/"


def cookies_to_editor_json(cookies: list[dict[str, Any]]) -> str:
    export: list[dict[str, Any]] = []
    for item in cookies:
        name = str(item.get("name") or "")
        if not name:
            continue
        export.append(
            {
                "name": name,
                "value": str(item.get("value") or ""),
                "domain": str(item.get("domain") or ".indiegala.com"),
                "path": str(item.get("path") or "/"),
                "httpOnly": bool(item.get("httpOnly", False)),
                "secure": bool(item.get("secure", True)),
                "session": bool(item.get("expires", -1) in (-1, None)),
                "expirationDate": item.get("expires"),
            }
        )
    return json.dumps(export, indent=2)


def _launch_browser(playwright):
    last_error: Optional[Exception] = None
    for channel in ("chrome", "msedge", None):
        try:
            kwargs: dict[str, Any] = {"headless": False}
            if channel:
                kwargs["channel"] = channel
            return playwright.chromium.launch(**kwargs), channel or "chromium"
        except Exception as error:
            last_error = error
    raise RuntimeError(f"Could not launch browser: {last_error}")


def capture_indiegala_login() -> str:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise RuntimeError(
            "pip install playwright && python -m playwright install chromium"
        ) from error

    with sync_playwright() as playwright:
        browser, label = _launch_browser(playwright)
        print(f"Opened {label}. Log into IndieGala in that window.", flush=True)
        context = browser.new_context(locale="en-US")
        page = context.new_page()
        page.goto(HOME_URL, wait_until="domcontentloaded")
        print(
            "\n>>> When you see your account (avatar / GalaSilver), "
            "click this terminal and press ENTER <<<\n",
            flush=True,
        )
        try:
            input()
        except EOFError:
            pass

        cookies = list(context.cookies())
        ig = [
            c
            for c in cookies
            if "indiegala" in str(c.get("domain") or "").lower()
            or str(c.get("name") or "").lower()
            in ("sessionid", "csrftoken", "xf_user")
            or str(c.get("name") or "").lower().startswith(
                ("incap_", "visid_", "nlbi_")
            )
        ]
        payload = cookies_to_editor_json(ig or cookies)
        browser.close()
        if "sessionid" not in payload.lower():
            raise RuntimeError(
                "No sessionid cookie. Stay on indiegala.com while logged in, then press ENTER."
            )
        return payload


def _post_json(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--cookie-file", default="")
    args = parser.parse_args()
    server = args.server.rstrip("/")
    cookie_path = Path(args.cookie_file) if args.cookie_file else Path("ig_cookies.json")

    if args.cookie_file:
        cookie = Path(args.cookie_file).read_text(encoding="utf-8").strip()
    else:
        try:
            cookie = capture_indiegala_login()
        except Exception as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 1
        cookie_path.write_text(cookie, encoding="utf-8")
        print(f"Cookie file: {cookie_path.resolve()}", flush=True)

    print("Saving cookie to bot…", flush=True)
    try:
        result = _post_json(
            f"{server}/api/indiegala/browser-login/complete",
            {"token": args.token, "ok": True, "cookie": cookie},
        )
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", "replace")
        print(f"ERROR posting: {error.code} {body}", file=sys.stderr)
        print(
            f"\nRetry (no re-login):\n"
            f"  python ig_login_helper.py --server {server} --token NEW_TOKEN "
            f'--cookie-file "{cookie_path}"\n'
            "Get NEW_TOKEN: WebUI → Browser login → Copy command (only the token).\n",
            file=sys.stderr,
        )
        return 1

    if result.get("status") == "error":
        print(f"ERROR: {result.get('message')}", file=sys.stderr)
        return 1

    print(
        f"OK — {result.get('account_name')} · {result.get('username') or ''} "
        f"{result.get('message') or ''}".strip()
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
