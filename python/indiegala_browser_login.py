"""IndieGala interactive browser login (Playwright) — runs on your PC."""

from __future__ import annotations

import json
import time
from typing import Any, Callable, Optional

HOME_URL = "https://www.indiegala.com/"
LOGIN_URL = "https://www.indiegala.com/login"

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
"""

CHECK_LOGIN_JS = """
async () => {
  const bodyText = (document.body && document.body.innerText || '').toLowerCase();

  const hasLogout =
    !!document.querySelector('a[href*="logout"], a[href*="log-out"], [href="/logout"]') ||
    bodyText.includes('logout') ||
    bodyText.includes('log out');
  const hasSilver =
    bodyText.includes('galasilver') ||
    bodyText.includes('gala silver');
  const hasLibrary =
    bodyText.includes('my library') ||
    !!document.querySelector('a[href*="library"]');
  const uiLoggedIn = hasLogout && (hasSilver || hasLibrary);

  let ajaxLoggedIn = false;
  try {
    const csrf = (document.cookie.match(/(?:^|;\\s*)csrftoken=([^;]+)/) || [])[1] || '';
    const res = await fetch('/ajax/user/get-data', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': decodeURIComponent(csrf),
        'X-Requested-With': 'XMLHttpRequest'
      },
      body: '{}',
      credentials: 'include'
    });
    const data = await res.json();
    ajaxLoggedIn = !!(data && (data.user_is_logged === true || data.user_is_logged === 'true'));
  } catch (e) {}

  return { ok: !!(ajaxLoggedIn || uiLoggedIn) };
}
"""


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
            kwargs: dict[str, Any] = {
                "headless": False,
                "args": [
                    "--disable-blink-features=AutomationControlled",
                    "--no-default-browser-check",
                ],
            }
            if channel:
                kwargs["channel"] = channel
            browser = playwright.chromium.launch(**kwargs)
            return browser, channel or "chromium"
        except Exception as error:
            last_error = error
            continue
    raise RuntimeError(f"Could not launch a browser. Last error: {last_error}")


def _check_logged_in(page) -> bool:
    url = (page.url or "").lower()
    if "indiegala.com" not in url:
        return False
    try:
        result = page.evaluate(CHECK_LOGIN_JS)
        if isinstance(result, dict):
            return bool(result.get("ok"))
        return bool(result)
    except Exception:
        return False


def capture_indiegala_login(
    timeout_seconds: int = 300,
    on_status: Optional[Callable[[str], None]] = None,
) -> str:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise RuntimeError(
            "Playwright is not installed on this PC. Run:\n"
            "  pip install playwright\n"
            "  python -m playwright install chromium"
        ) from error

    def status(message: str) -> None:
        if on_status:
            on_status(message)

    deadline = time.time() + max(60, int(timeout_seconds))

    with sync_playwright() as playwright:
        browser, label = _launch_browser(playwright)
        status(f"Opened {label}. Log into IndieGala and wait for capture.")
        context = browser.new_context(
            viewport={"width": 1360, "height": 900},
            locale="en-US",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
        )
        context.add_init_script(STEALTH_JS)
        page = context.new_page()
        page.goto(HOME_URL, wait_until="domcontentloaded")
        try:
            page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=20000)
        except Exception:
            pass

        logged_in = False
        while time.time() < deadline:
            if _check_logged_in(page):
                logged_in = True
                break
            status("Waiting for IndieGala login… (open profile menu if already in)")
            time.sleep(1.5)

        if not logged_in:
            browser.close()
            raise RuntimeError("Timed out waiting for IndieGala login.")

        time.sleep(1)
        cookies = list(context.cookies())
        ig_cookies = [
            c
            for c in cookies
            if "indiegala" in str(c.get("domain") or "").lower()
            or str(c.get("name") or "").lower()
            in ("sessionid", "csrftoken", "xf_user", "messages", "cart")
            or str(c.get("name") or "").lower().startswith(
                ("incap_", "visid_", "nlbi_")
            )
        ]
        payload = cookies_to_editor_json(ig_cookies or cookies)
        browser.close()
        status("Login captured — saving cookie…")
        return payload
