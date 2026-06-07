import json
import platform
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from http_client import HttpClient, USER_AGENT
from paths import get_data_dir, get_executable_path
from version import APP_VERSION, ASSET_NAME, GITHUB_REPO


@dataclass
class UpdateInfo:
    version: str
    tag: str
    download_url: str
    release_notes: str
    html_url: str


def parse_version(value: str) -> tuple[int, ...]:
    cleaned = value.strip().lstrip("vV")
    parts: list[int] = []
    for segment in cleaned.split("."):
        match = re.match(r"(\d+)", segment)
        parts.append(int(match.group(1)) if match else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def is_newer_version(latest: str, current: str = APP_VERSION) -> bool:
    return parse_version(latest) > parse_version(current)


def is_packaged_app() -> bool:
    return getattr(sys, "frozen", False)


def fetch_latest_update() -> UpdateInfo | None:
    client = HttpClient()
    response = client.request(
        f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
        },
    )
    if response.status != 200:
        raise RuntimeError(f"GitHub API returned {response.status}")

    data = json.loads(response.data)
    tag = str(data.get("tag_name", "")).strip()
    if not tag:
        raise RuntimeError("Latest release is missing a version tag")

    version = tag.lstrip("vV")
    if not is_newer_version(version):
        return None

    download_url = ""
    for asset in data.get("assets", []):
        if asset.get("name") == ASSET_NAME:
            download_url = asset.get("browser_download_url", "")
            break

    if not download_url:
        raise RuntimeError(f"Release {tag} has no {ASSET_NAME} asset")

    return UpdateInfo(
        version=version,
        tag=tag,
        download_url=download_url,
        release_notes=str(data.get("body") or "").strip(),
        html_url=str(data.get("html_url") or "").strip(),
    )


def download_update(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(dest.suffix + ".part")
    if partial.exists():
        partial.unlink()
    if dest.exists():
        dest.unlink()

    curl_bin = "curl.exe" if platform.system() == "Windows" else "curl"
    args = [
        curl_bin,
        "-sSL",
        "-L",
        "-A",
        USER_AGENT,
        "-o",
        str(partial),
        url,
    ]

    run_kwargs: dict = {
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }
    if platform.system() == "Windows":
        run_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

    try:
        result = subprocess.run(args, **run_kwargs)
    except FileNotFoundError as exc:
        raise RuntimeError(
            "curl not found. Install curl or use Windows 10+ which includes curl.exe."
        ) from exc

    if result.returncode != 0:
        raise RuntimeError(
            f"Download failed (curl {result.returncode}): {result.stderr.strip()}"
        )

    if not partial.exists() or partial.stat().st_size < 1024 * 1024:
        if partial.exists():
            partial.unlink()
        raise RuntimeError("Downloaded update file looks invalid")

    partial.replace(dest)


def apply_update(downloaded: Path) -> None:
    if not is_packaged_app():
        raise RuntimeError("Updates can only be applied to the packaged app.")

    target = get_executable_path()
    downloaded = downloaded.resolve()
    if not downloaded.exists():
        raise RuntimeError("Downloaded update file is missing")

    batch_path = get_data_dir() / "apply_update.bat"
    batch_path.write_text(
        "\n".join(
            [
                "@echo off",
                "ping 127.0.0.1 -n 3 > nul",
                f'move /Y "{downloaded}" "{target}"',
                f'start "" "{target}"',
                'del "%~f0"',
            ]
        ),
        encoding="utf-8",
    )

    subprocess.Popen(
        ["cmd.exe", "/c", str(batch_path)],
        creationflags=subprocess.CREATE_NO_WINDOW,
        close_fds=True,
    )
    sys.exit(0)
