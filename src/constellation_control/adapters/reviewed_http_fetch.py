from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/plain,application/xml,text/xml,text/html;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Connection": "close",
}


@dataclass(frozen=True)
class ReviewedHttpResponse:
    raw: bytes
    content_type: str
    transport: str


def fetch_reviewed_url(url: str, *, timeout_s: float = 20.0) -> ReviewedHttpResponse:
    """Fetch a caller-reviewed URL with a browser-compatible primary path and curl fallback.

    Callers remain responsible for strict host/path allowlisting before invoking this helper.
    The curl fallback is useful on Windows/corporate networks where Python urllib and the
    system browser can traverse different TLS/proxy paths.
    """

    request = Request(url, headers=_BROWSER_HEADERS)
    urllib_error: Exception | None = None
    try:
        with urlopen(request, timeout=timeout_s) as response:  # noqa: S310 - caller performs allowlist validation
            return ReviewedHttpResponse(
                raw=response.read(),
                content_type=response.headers.get("Content-Type", ""),
                transport="urllib",
            )
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        urllib_error = exc

    curl = shutil.which("curl") or shutil.which("curl.exe")
    if curl is None:
        raise OSError(f"HTTP fetch failed via urllib and curl is unavailable: {urllib_error}") from urllib_error

    command = [
        curl,
        "--fail-with-body",
        "--location",
        "--silent",
        "--show-error",
        "--connect-timeout",
        str(max(1, int(timeout_s))),
        "--max-time",
        str(max(2, int(timeout_s) + 5)),
        "--user-agent",
        _BROWSER_HEADERS["User-Agent"],
        "--header",
        "Accept: text/plain,application/xml,text/xml,text/html;q=0.9,*/*;q=0.8",
        url,
    ]
    try:
        completed = subprocess.run(  # noqa: S603 - executable and URL are caller-reviewed, shell=False
            command,
            check=False,
            capture_output=True,
            timeout=timeout_s + 10.0,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OSError(f"HTTP fetch failed via urllib ({urllib_error}) and curl ({exc})") from exc

    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        raise OSError(
            "HTTP fetch failed via both transports; "
            f"urllib={urllib_error}; curl_exit={completed.returncode}; curl={stderr or 'no stderr'}"
        ) from urllib_error
    return ReviewedHttpResponse(raw=completed.stdout, content_type="", transport="curl")
