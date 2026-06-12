import sys
import winreg
from pathlib import Path

APP_NAME = "SteamGiftsBot"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
STARTUP_ARG = "--startup"


def _startup_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable)}" {STARTUP_ARG}'

    python_exe = Path(sys.executable)
    if python_exe.name.lower() == "python.exe":
        pythonw = python_exe.with_name("pythonw.exe")
        if pythonw.exists():
            python_exe = pythonw

    main_script = Path(__file__).resolve().parent / "main.py"
    return f'"{python_exe}" "{main_script}" {STARTUP_ARG}'


def is_launched_from_startup(argv: list[str] | None = None) -> bool:
    return STARTUP_ARG in (argv if argv is not None else sys.argv)


def is_startup_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, APP_NAME)
            return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def set_startup_enabled(enabled: bool) -> None:
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        RUN_KEY,
        0,
        winreg.KEY_SET_VALUE,
    ) as key:
        if enabled:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, _startup_command())
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass


def refresh_startup_command() -> None:
    """Rewrite the Run key so older installs pick up --startup."""
    if is_startup_enabled():
        set_startup_enabled(True)
