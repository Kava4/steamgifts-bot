# SteamGifts Bot

Desktop app and Docker WebUI for automatic giveaway entry on [steamgifts.com](https://www.steamgifts.com/).

Based on [stilManiac/steamgifts-bot](https://github.com/stilManiac/steamgifts-bot), rewritten in **Python + PyQt6**, with an optional **browser WebUI** for headless / Raspberry Pi installs.

## Features

- Automatic giveaway entry
- Activity feed with Steam game images
- **Entered** tab — joined giveaways with time remaining and Remove
- **IndieGala (beta)** — optional auto-join on [indiegala.com/giveaways](https://www.indiegala.com/giveaways)
- **Wins** tab — track wins on SteamGifts and IndieGala
- Manual select (Yes/No per giveaway)
- Smart wait when points are insufficient
- System tray (desktop) — keep running in the background
- Start with Windows (desktop)
- Auto-update from GitHub Releases (packaged desktop exe)
- **Docker + WebUI** — same layout in the browser (`:8765`)

## Download (desktop)

Download `SteamGiftsBot.exe` from [Releases](https://github.com/Kava4/steamgifts-bot/releases) (current: **v1.0.1**).

## Quick start (desktop)

### 1. Configure steamgifts.com

1. Log in at [steamgifts.com](https://www.steamgifts.com/)
2. Go to [Giveaway Settings](https://www.steamgifts.com/account/settings/giveaways)
3. Disable giveaways you cannot enter — the bot tries to enter everything it sees

### 2. Cookie (PHPSESSID)

1. Open DevTools (F12) → **Application** → **Cookies** → `steamgifts.com`
2. Copy the `PHPSESSID` value
3. In the app: **Settings → Accounts** → paste → **Save**

Saved to `%APPDATA%\SteamGiftsBot\cookie.txt`.

### IndieGala (beta)

1. Log in at [indiegala.com](https://www.indiegala.com/)
2. DevTools → **Cookies** → copy `sessionid` (and `csrftoken` if available)
3. **Settings → Accounts** → paste → **Save**
4. Enable **Enable IndieGala giveaways** and set entry delay / minimum cost

Use a **slow entry delay** (5+ sec) to reduce rate limits.

Cookie file: `%APPDATA%\SteamGiftsBot\indiegala_cookie.txt`

### 3. Usage

1. **Fetch Points** — verify session
2. **Start Bot** — automatic entry
3. **Activity** / **Entered** / **Wins** / **Console** / **Settings**

While waiting, a **countdown** appears under the status pill.

### System tray

- Closing the window (X) can minimize to tray (setting)
- Tray → **Quit** to exit fully

## Docker + WebUI

Good for Raspberry Pi / Linux servers — no desktop UI required.

```bash
docker compose up -d --build
```

Open [http://localhost:8765](http://localhost:8765) (or `http://<host-ip>:8765`).

Cookies and settings are stored in `./data` (Docker volume).

Optional password in `docker-compose.yml`:

```yaml
environment:
  WEBUI_PASSWORD: change-me
```

WebUI-only dependencies: `requirements-web.txt` (no PyQt6).

## Development (desktop)

**Requirements:** Python 3.11+, Windows, `curl`

```powershell
pip install -r requirements.txt
python python/main.py
```

### Build single exe

```powershell
.\build.ps1
```

Output: `dist/SteamGiftsBot.exe`

### WebUI without Docker

```powershell
pip install -r requirements-web.txt
$env:STEAMGIFTS_DATA_DIR = "$PWD\data"
python python/web_main.py
```

## Data files

| File | Desktop | Docker |
|------|---------|--------|
| `cookie.txt` | `%APPDATA%\SteamGiftsBot\` | `./data` |
| `indiegala_cookie.txt` | same | `./data` |
| `settings.json` | same | `./data` |

> Do not commit cookies or `./data` — they contain session tokens.

## Project structure

```
python/
  main.py                 # Desktop entry
  web_main.py             # WebUI / Docker entry
  gui.py                  # PyQt6 UI
  bot.py
  widgets.py
  steamgifts_service.py
  indiegala_service.py
  wins_tracker.py
  http_client.py
  settings.py
  paths.py
  version.py
  updater.py
  windows_startup.py
  theme.py
  web/                    # FastAPI + static WebUI
assets/
scripts/
build.ps1
Dockerfile
docker-compose.yml
requirements.txt          # Desktop + WebUI
requirements-web.txt      # Docker / WebUI only
```

## License

See [LICENSE](LICENSE).
