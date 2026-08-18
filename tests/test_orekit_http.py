from urllib.request import Request

from constellation_control.adapters.orekit import http


def test_loopback_orekit_http_bypasses_system_proxy(monkeypatch) -> None:
    calls: list[object] = []

    class DummyResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class DummyOpener:
        def open(self, request, timeout):
            calls.append((request.full_url if isinstance(request, Request) else request, timeout))
            return DummyResponse()

    monkeypatch.setattr(http, "build_opener", lambda *handlers: DummyOpener())
    monkeypatch.setattr(http, "urlopen", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("system proxy path used")))

    with http.open_orekit_url("http://127.0.0.1:8081/healthz", 1.0):
        pass

    assert calls == [("http://127.0.0.1:8081/healthz", 1.0)]
