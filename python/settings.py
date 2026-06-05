import json
import shutil
from pathlib import Path

from paths import get_app_dir, get_data_dir

DEFAULTS = {
    "start_with_windows": False,
    "minimize_to_tray_on_close": True,
    "manual_select_giveaways": False,
}


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
    return settings


def save_settings(settings: dict) -> None:
    settings_file = _settings_file()
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {key: settings.get(key, DEFAULTS[key]) for key in DEFAULTS}
    settings_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
