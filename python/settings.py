import json
import shutil
from pathlib import Path

from paths import get_app_dir, get_data_dir

DEFAULTS = {
    "start_with_windows": False,
    "minimize_to_tray_on_close": True,
    "manual_select_giveaways": False,
    "refresh_delay_minutes": 10,
    "max_pages": 5,
    "max_giveaway_end_hours": 3,
    "enable_indiegala_beta": False,
    "indiegala_entry_delay": 5,
    "indiegala_min_cost": 0,
    "notify_on_win": True,
    "check_for_updates_on_startup": True,
}

REFRESH_MINUTE_OPTIONS = (5, 10, 15)


def _settings_file() -> Path:
    new_path = get_data_dir() / "settings.json"
    if new_path.exists():
        return new_path

    old_path = get_app_dir() / "settings.json"
    if old_path.exists():
        shutil.copy2(old_path, new_path)

    return new_path


def load_settings() -> dict:
    settings_file = _settings_file()
    if not settings_file.exists():
        return DEFAULTS.copy()

    try:
        data = json.loads(settings_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return DEFAULTS.copy()

    settings = DEFAULTS.copy()
    settings.update({key: data[key] for key in DEFAULTS if key in data})

    if settings["refresh_delay_minutes"] not in REFRESH_MINUTE_OPTIONS:
        settings["refresh_delay_minutes"] = DEFAULTS["refresh_delay_minutes"]

    settings["max_pages"] = max(1, min(int(settings["max_pages"]), 50))
    settings["max_giveaway_end_hours"] = max(
        0, min(int(settings.get("max_giveaway_end_hours", 3)), 72)
    )
    settings["indiegala_entry_delay"] = max(
        3, min(int(settings.get("indiegala_entry_delay", 5)), 30)
    )
    settings["indiegala_min_cost"] = max(
        0, min(int(settings.get("indiegala_min_cost", 0)), 100)
    )
    return settings


def save_settings(settings: dict) -> None:
    settings_file = _settings_file()
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {key: settings.get(key, DEFAULTS[key]) for key in DEFAULTS}

    if payload["refresh_delay_minutes"] not in REFRESH_MINUTE_OPTIONS:
        payload["refresh_delay_minutes"] = DEFAULTS["refresh_delay_minutes"]

    payload["max_pages"] = max(1, min(int(payload["max_pages"]), 50))
    payload["max_giveaway_end_hours"] = max(
        0, min(int(payload.get("max_giveaway_end_hours", 3)), 72)
    )
    payload["indiegala_entry_delay"] = max(
        3, min(int(payload.get("indiegala_entry_delay", 5)), 30)
    )
    payload["indiegala_min_cost"] = max(
        0, min(int(payload.get("indiegala_min_cost", 0)), 100)
    )
    settings_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
