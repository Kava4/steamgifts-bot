# SteamGifts Bot

Desktop app for automatic giveaway entry on [steamgifts.com](https://www.steamgifts.com/).

Based on [stilManiac/steamgifts-bot](https://github.com/stilManiac/steamgifts-bot), rewritten in **Python + PyQt6** with a modern GUI.

## Features

- Automatic giveaway entry
- Activity feed with Steam game images
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
3. In the app: paste → **Save**

The cookie is saved to `cookie.txt` next to the exe (or in the project folder in dev mode).

### 3. Usage

1. **Fetch Points** — verify session and check points
2. **Start Bot** — begin automatic entry
3. **Activity** — entered giveaways, waiting states, manual prompts
4. **Console** — full event log

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
| `cookie.txt` | Next to the exe | PHPSESSID session token |
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
