"""Proxy routing regressions: exercise request construction without networking."""

from __future__ import annotations

from typing import ClassVar

import pytest
import requests
from curl_cffi import requests as curl_requests

from nba_game.transport import StatusAwareBrowserSession, proxy_is_configured


@pytest.fixture
def sent_requests(monkeypatch):
    calls = []

    class Response:
        headers: ClassVar[dict] = {"content-type": "application/json"}
        text = '{"ok":true}'

        def raise_for_status(self):
            pass

    def get(_session, url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setattr(curl_requests.Session, "get", get)
    return calls


def test_os_proxy_without_environment_is_used_and_reported(monkeypatch, sent_requests):
    # requests' platform adapter returns these from macOS system configuration.
    monkeypatch.setattr(
        requests.utils,
        "getproxies",
        lambda: {"http": "http://localhost:11888", "https": "http://localhost:11888"},
    )
    monkeypatch.setattr(requests.utils, "should_bypass_proxies", lambda *a, **kw: False)
    session = StatusAwareBrowserSession()
    try:
        session.get("https://stats.nba.com/stats/boxscoresummaryv3", proxies=None)
    finally:
        session.close()
    assert sent_requests[0][1]["proxies"] == {"all": "http://localhost:11888"}
    assert proxy_is_configured(None)


def test_explicit_proxy_overrides_discovery(monkeypatch, sent_requests):
    def unexpected(*a, **kw):
        raise AssertionError("Explicit proxy must not consult OS/environment routing")

    monkeypatch.setattr(requests.utils, "get_environ_proxies", unexpected)
    explicit = {"https": "http://user:password@explicit:8080"}
    session = StatusAwareBrowserSession()
    try:
        session.get("https://stats.nba.com/stats/playbyplayv3", proxies=explicit)
    finally:
        session.close()
    assert sent_requests[0][1]["proxies"] == explicit
    assert proxy_is_configured("http://user:password@explicit:8080")


def test_no_proxy_bypass_does_not_reenable_proxy(monkeypatch, sent_requests):
    monkeypatch.setenv("NO_PROXY", "stats.nba.com")
    monkeypatch.delenv("no_proxy", raising=False)
    monkeypatch.setattr(
        requests.utils, "getproxies", lambda: {"https": "http://localhost:11888"}
    )
    session = StatusAwareBrowserSession()
    try:
        session.get("https://stats.nba.com/stats/playbyplayv3", proxies=None)
    finally:
        session.close()
    assert sent_requests[0][1]["proxies"] == {"all": ""}
    assert not proxy_is_configured(None)


@pytest.mark.parametrize(
    ("discovered", "expected"),
    [
        ({"all": "socks5h://localhost:11889"}, "socks5h://localhost:11889"),
        ({"http": "http://localhost:11888"}, ""),
        ({}, ""),
    ],
)
def test_selects_proxy_for_requested_scheme(
    monkeypatch, sent_requests, discovered, expected
):
    monkeypatch.setattr(requests.utils, "get_environ_proxies", lambda url: discovered)
    session = StatusAwareBrowserSession()
    try:
        session.get("https://stats.nba.com/stats/playbyplayv3", proxies=None)
    finally:
        session.close()
    assert sent_requests[0][1]["proxies"] == {"all": expected}
    assert proxy_is_configured(None) is bool(expected)
