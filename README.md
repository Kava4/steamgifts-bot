# SteamGifts Bot

Desktop app for automatic giveaway entry on [steamgifts.com](https://www.steamgifts.com/).

Based on [stilManiac/steamgifts-bot](https://github.com/stilManiac/steamgifts-bot), rewritten in **Python + PyQt6** with a modern GUI.

## Features

- Automatic giveaway entry
- Activity feed with Steam game images
- **Entered** tab — active joined giveaways with time remaining and Remove
- **IndieGala (beta)** — optional auto-join on [indiegala.com/giveaways](https://www.indiegala.com/giveaways)
- Manual select (Yes/No per giveaway)
- Smart wait when points are insufficient
- System tray — bot keeps running in the background
- Start with Windows (optional)

## Download

Download `SteamGiftsBot.exe` from [Releases](https://github.com/AimSyncCore/SteamGifts-bot/releases).

## Quick start

### 1. Configure steamgifts.com

1. Log in at [steamgifts.com](https://www.steamgifts.com/)
2. Go to [Giveaway Settings](https://www.steamgifts.com/account/settings/giveaways)
3. Disable giveaways you cannot enter — the bot tries to enter everything it sees

### 2. Cookie (PHPSESSID)

1. Open DevTools (F12) → **Application** → **Cookies** → `steamgifts.com`
2. Copy the `PHPSESSID` value
3. In the app: **Settings → Accounts** → paste → **Save**

The cookie is saved to `%APPDATA%\SteamGiftsBot\cookie.txt`.

### IndieGala (beta)

1. Log in at [indiegala.com](https://www.indiegala.com/)
2. DevTools → **Cookies** → copy `sessionid` (and `csrftoken` if available)
3. Sidebar → **Settings → Accounts** → paste → **Save**
4. Enable **Enable IndieGala giveaways** and set entry delay / **minimum cost** below

After each SteamGifts page, the bot scans the matching IndieGala page. Use a **slow entry delay** (5+ sec) — fast automation can trigger IndieGala rate limits.

Cookie file: `%APPDATA%\SteamGiftsBot\indiegala_cookie.txt`

### 3. Usage

1. **Fetch Points** — verify session and check points
2. **Start Bot** — begin automatic entry
3. **Activity** — entered giveaways, waiting states, manual prompts
4. **Entered** — open giveaways you joined; refresh list and remove entries
5. **Console** — full event log
6. **Settings** — refresh interval (5/10/15 min), max pages to scan

While the bot waits, a **countdown** appears under the status pill (list refresh or points timer).

### System tray

- **Minimize to tray on close** — closing the window (X) hides it; the bot keeps running. To exit: tray → **Quit**
- Double-click the tray icon to open the window

## Development

**Requirements:** Python 3.11+, Windows, `curl` (included with Windows 10/11)

```powershell
pip install -r requirements.txt
python python/main.py
```

### Build single exe

```powershell
.\build.ps1
```

Output: `dist/SteamGiftsBot.exe`

## Data files

| File | Location | Description |
|------|----------|-------------|
| `cookie.txt` | `%APPDATA%\SteamGiftsBot\` | PHPSESSID session token |
| `indiegala_cookie.txt` | `%APPDATA%\SteamGiftsBot\` | IndieGala sessionid (beta) |
| `settings.json` | `%APPDATA%\SteamGiftsBot\` | App settings |

> Do not commit `cookie.txt` to GitHub — it contains your session token.

## Project structure

```
python/
  main.py              # Entry point
  gui.py               # PyQt6 UI
  bot.py               # Bot logic
  widgets.py           # Activity cards
  steamgifts_service.py
  http_client.py       # curl HTTP (bypasses Cloudflare)
  settings.py
  paths.py
  windows_startup.py
  theme.py
assets/
  icon.ico             # App icon (window, tray, exe)
scripts/
  generate_icon.py
build.ps1
requirements.txt
```

## License

See [LICENSE](LICENSE).
