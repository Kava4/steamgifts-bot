import platform
import subprocess
from dataclasses import dataclass
from typing import Dict, Optional


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


@dataclass
class HttpResponse:
    status: int
    status_text: str
    data: str


class HttpClient:
    def request(
        self,
        url: str,
        method: str = "GET",
        headers: Optional[Dict[str, str]] = None,
        data: Optional[str] = None,
    ) -> HttpResponse:
        method = method.upper()
        args = [
            "-sS",
            "-L",
            "--compressed",
            "-w",
            "__STATUS__%{http_code}",
            "-A",
            USER_AGENT,
            "-X",
            method,
        ]

        if headers:
            for key, value in headers.items():
                args.extend(["-H", f"{key}: {value}"])

        if data:
            has_content_type = headers and any(
                key.lower() == "content-type" for key in headers
            )
            if not has_content_type:
                args.extend(["-H", "Content-Type: application/x-www-form-urlencoded"])
            args.extend(["--data-raw", data])

        args.append(url)

        curl_bin = "curl.exe" if platform.system() == "Windows" else "curl"

        try:
            result = subprocess.run(
                [curl_bin, *args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                "curl not found. Install curl or use Windows 10+ which includes curl.exe."
            ) from exc

        if result.returncode != 0:
            raise RuntimeError(
                f"curl exited with code {result.returncode}: {result.stderr.strip()}"
            )

        output = result.stdout
        marker_index = output.rfind("__STATUS__")
        if marker_index == -1:
            raise RuntimeError("curl response missing status marker")

        body = output[:marker_index]
        status = int(output[marker_index + len("__STATUS__") :])

        return HttpResponse(
            status=status,
            status_text="OK" if status == 200 else str(status),
            data=body,
        )
