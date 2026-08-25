import json
import os
import urllib.request
from typing import Optional

from steamgifts_service import WonGiveawayInfo


def notify_win(win: WonGiveawayInfo) -> Optional[str]:
    """Send optional Discord webhook notification for a new win.

    Set DISCORD_WEBHOOK_URL in the environment (e.g. docker-compose).
    Returns an error message on failure, otherwise None.
    """
    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook:
        return None

    source = "IndieGala" if win.source == "indiegala" else "SteamGifts"
    title = f"You won on {source}"
    description = win.name
    if win.url:
        description = f"[{win.name}]({win.url})"

    payload = {
        "content": f"🎉 **{title}**",
        "embeds": [
            {
                "title": win.name[:250],
                "description": description[:2000],
                "url": win.url or None,
                "color": 0x86EFAC if win.source == "steamgifts" else 0xF0C674,
                "thumbnail": {"url": win.image_url} if win.image_url else None,
            }
        ],
    }
    # Discord rejects null fields in some embeds
    embed = payload["embeds"][0]
    if not embed.get("url"):
        embed.pop("url", None)
    if not embed.get("thumbnail"):
        embed.pop("thumbnail", None)

    request = urllib.request.Request(
        webhook,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            if response.status >= 400:
                return f"Discord webhook HTTP {response.status}"
    except Exception as error:
        return str(error)
    return None
