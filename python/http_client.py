import platform
import subprocess
import time
from dataclasses import dataclass
from typing import Dict, Optional


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# Transient curl failures (timeouts / TLS / dropped connection).
RETRYABLE_CURL_CODES = {7, 28, 35, 52, 55, 56}


@dataclass
class HttpResponse:
    status: int
    status_text: str
    data: str


class HttpClient:
    def __init__(
        self,
        proxy: str = "",
        connect_timeout: int = 20,
        max_time: int = 60,
        retries: int = 3,
    ):
        self.proxy = (proxy or "").strip()
        self.connect_timeout = max(1, int(connect_timeout))
        self.max_time = max(self.connect_timeout, int(max_time))
        self.retries = max(1, int(retries))

    def request(
        self,
        url: str,
        method: str = "GET",
        headers: Optional[Dict[str, str]] = None,
        data: Optional[str] = None,
    ) -> HttpResponse:
        last_error: Optional[Exception] = None
        for attempt in range(1, self.retries + 1):
            try:
                return self._request_once(url, method, headers, data)
            except RuntimeError as error:
                last_error = error
                message = str(error)
                retryable = any(
                    f"curl exited with code {code}" in message
                    for code in RETRYABLE_CURL_CODES
                ) or "SSL" in message or "timed out" in message.lower()
                if not retryable or attempt >= self.retries:
                    if self.proxy and retryable:
                        raise RuntimeError(
                            f"{message} (via proxy {self.proxy} — "
                            "clear/replace proxy in Settings if this keeps happening)"
                        ) from error
                    raise
                time.sleep(min(1.5 * attempt, 4.0))
        assert last_error is not None
        raise last_error

    def _request_once(
        self,
        url: str,
        method: str,
        headers: Optional[Dict[str, str]],
        data: Optional[str],
    ) -> HttpResponse:
        method = method.upper()
        args = [
            "-sS",
            "-L",
            "--compressed",
            "--http1.1",
            "--connect-timeout",
            str(self.connect_timeout),
            "--max-time",
            str(self.max_time),
            "-w",
            "__STATUS__%{http_code}",
            "-A",
            USER_AGENT,
            "-X",
            method,
        ]

        if self.proxy:
            args.extend(["--proxy", self.proxy])

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

        run_kwargs: dict = {
            "capture_output": True,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
        }
        if platform.system() == "Windows":
            run_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

        try:
            result = subprocess.run([curl_bin, *args], **run_kwargs)
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
