from __future__ import annotations

from urllib.parse import urlparse
from urllib.request import OpenerDirector, ProxyHandler, Request, build_opener, urlopen

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def open_orekit_url(request: Request | str, timeout_s: float | None):
    """Open an Orekit HTTP endpoint, never proxying loopback traffic."""
    raw_url = request.full_url if isinstance(request, Request) else request
    host = (urlparse(raw_url).hostname or "").lower()
    if host in _LOOPBACK_HOSTS:
        opener: OpenerDirector = build_opener(ProxyHandler({}))
        return opener.open(request, timeout=timeout_s)
    return urlopen(request, timeout=timeout_s)  # noqa: S310 - explicit scenario-configured endpoint
