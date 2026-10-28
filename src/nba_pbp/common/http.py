"""Shared NBA HTTP session and transport error handling."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import requests
from curl_cffi import requests as curl_requests
from curl_cffi.requests import exceptions as curl_exceptions

from nba_pbp.common.errors import SourceBlockedError


@dataclass(frozen=True)
class ErrorDisposition:
    """Retry and fallback decisions for one endpoint error."""

    retryable: bool
    fallback_allowed: bool
    reason: str


class StatusAwareBrowserSession:
    """curl_cffi session that detects HTTP and HTML block responses."""

    def __init__(self) -> None:
        self._session = curl_requests.Session(
            impersonate="chrome145",
            trust_env=True,
        )

    def get(self, url: str, **kwargs: Any) -> Any:
        # curl/libcurl does not discover macOS system proxies. requests uses
        # urllib's platform-aware discovery and also applies NO_PROXY/system
        # bypass rules. Keep nba_api's explicit --proxy mapping authoritative.
        if kwargs.get("proxies") is None and kwargs.get("proxy") is None:
            kwargs["proxies"] = {"all": _default_proxy(url) or ""}
        headers = kwargs.get("headers")
        if isinstance(headers, Mapping):
            browser_managed = {
                "user-agent",
                "sec-ch-ua",
                "sec-ch-ua-mobile",
                "sec-ch-ua-platform",
            }
            kwargs["headers"] = {
                key: value
                for key, value in headers.items()
                if key.lower() not in browser_managed
            }
        response = self._session.get(url, **kwargs)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").lower()
        prefix = response.text.lstrip()[:256].lower()
        if "text/html" in content_type or prefix.startswith(
            ("<!doctype html", "<html")
        ):
            raise SourceBlockedError(
                "NBA 返回了 HTML 页面，而不是 API JSON",
                status_code=getattr(response, "status_code", None),
                akamai=(
                    response.headers.get("server", "").lower() == "akamainetstorage"
                ),
            )
        return response

    def close(self) -> None:
        self._session.close()


@contextmanager
def nba_http_session() -> Iterator[None]:
    """Temporarily provide Stats and Live APIs with a browser-like session."""
    from nba_api.live.nba.library.http import NBALiveHTTP
    from nba_api.stats.library.http import NBAStatsHTTP

    previous_stats_session = NBAStatsHTTP.get_session()
    previous_live_session = NBALiveHTTP.get_session()
    current_session = StatusAwareBrowserSession()
    NBAStatsHTTP.set_session(current_session)
    NBALiveHTTP.set_session(current_session)
    try:
        yield
    finally:
        NBAStatsHTTP.set_session(previous_stats_session)
        NBALiveHTTP.set_session(previous_live_session)
        current_session.close()


def classify_error(exc: Exception) -> ErrorDisposition:
    """Classify an endpoint failure without exposing sensitive details."""
    if isinstance(exc, SourceBlockedError):
        details = []
        if exc.status_code is not None:
            details.append(f"HTTP {exc.status_code}")
        if exc.akamai:
            details.append("AkamaiNetStorage")
        detail = "；".join(details)
        if detail:
            detail += "；"
        return ErrorDisposition(
            False,
            True,
            f"NBA 返回了 HTML 错误页（{detail}"
            "可能是接口临时异常或访问限制，尚不能确定原因）",
        )
    if isinstance(exc, (requests.HTTPError, curl_exceptions.HTTPError)):
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
        if status == 429:
            return ErrorDisposition(True, True, "NBA API 返回 HTTP 429（请求过于频繁）")
        if status == 403:
            return ErrorDisposition(False, True, "NBA 拒绝了当前请求（HTTP 403）")
        if status is not None and 500 <= status <= 599:
            return ErrorDisposition(True, True, f"NBA API 返回 HTTP {status}")
        if status is not None and 400 <= status <= 499:
            return ErrorDisposition(False, False, f"NBA API 返回 HTTP {status}")
        return ErrorDisposition(False, False, "NBA API 返回 HTTP 错误")
    if isinstance(exc, (requests.Timeout, curl_exceptions.Timeout)):
        return ErrorDisposition(True, True, "连接 NBA API 超时")
    if isinstance(exc, requests.ConnectionError):
        return ErrorDisposition(True, True, "无法连接 NBA API")
    if isinstance(exc, curl_exceptions.RequestException):
        return ErrorDisposition(True, True, "无法连接 NBA API")
    if isinstance(exc, json.JSONDecodeError):
        return ErrorDisposition(True, True, "NBA API 返回了无效的 JSON")
    if isinstance(exc, KeyError):
        return ErrorDisposition(False, False, "NBA API 响应结构不完整")
    if isinstance(exc, ModuleNotFoundError):
        return ErrorDisposition(
            False, False, "缺少 nba_api 或 curl_cffi 运行依赖，请重新安装项目"
        )
    return ErrorDisposition(False, False, f"请求 NBA API 失败（{type(exc).__name__}）")


def _default_proxy(url: str) -> str | None:
    """Resolve environment or OS proxies for this URL, including bypass rules."""
    return requests.utils.select_proxy(url, requests.utils.get_environ_proxies(url))


def proxy_is_configured(proxy: str | None) -> bool:
    """Report the effective Stats route without exposing proxy credentials."""
    return bool(proxy or _default_proxy("https://stats.nba.com/"))
