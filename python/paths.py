import os
import shutil
import sys
from pathlib import Path

APP_NAME = "SteamGiftsBot"


def get_app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def get_data_dir() -> Path:
    appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
    path = Path(appdata) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_cookie_file() -> Path:
    new_path = get_data_dir() / "cookie.txt"
    if new_path.exists():
        return new_path

    old_path = get_app_dir() / "cookie.txt"
    if old_path.exists():
        shutil.copy2(old_path, new_path)

    return new_path


def get_indiegala_cookie_file() -> Path:
    return get_data_dir() / "indiegala_cookie.txt"


def get_icon_path() -> Path:
    if getattr(sys, "frozen", False):
        bundled = Path(sys._MEIPASS) / "assets" / "icon.ico"
        if bundled.exists():
            return bundled
    return Path(__file__).resolve().parent.parent / "assets" / "icon.ico"
