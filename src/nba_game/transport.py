"""Shared NBA HTTP session and transport error handling."""

from __future__ import annotations

import json
import random
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import requests
from curl_cffi import requests as curl_requests
from curl_cffi.requests import exceptions as curl_exceptions

from nba_game.errors import FetchError, SourceBlockedError
from nba_game.models import Resource, Response
from nba_game.sources.stats import build_profile_request


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


class RequestFailure(FetchError):
    def __init__(
        self,
        message: str,
        attempts: int,
        parameters: dict[str, Any],
        *,
        skipped: bool = False,
    ):
        super().__init__(message)
        self.attempts = attempts
        self.parameters = parameters
        self.skipped = skipped


class Transport:
    def __init__(
        self,
        timeout: float = 30,
        proxy: str | None = None,
        sleep: Callable = time.sleep,
        monotonic: Callable = time.monotonic,
        jitter: Callable = random.uniform,
    ):
        self.timeout, self.proxy = timeout, proxy
        self.sleep, self.monotonic, self.jitter = sleep, monotonic, jitter
        self._last_request: float | None = None
        self._stats_html_endpoints: set[str] = set()
        self._stats_unavailable_reason: str | None = None

    @property
    def stats_paused(self) -> bool:
        return self._stats_unavailable_reason is not None

    def __enter__(self):
        self._stats_html_endpoints.clear()
        self._stats_unavailable_reason = None
        self._last_request = None
        self._context = nba_http_session()
        self._context.__enter__()
        return self

    def __exit__(self, *args):
        return self._context.__exit__(*args)

    def _pace_request(self) -> None:
        if self._last_request is not None:
            self.sleep(max(0, 1.0 - (self.monotonic() - self._last_request)))
        self._last_request = self.monotonic()

    def _record_stats_failure(self, endpoint: str, exc: Exception, reason: str) -> None:
        """Pause Stats only after consecutive HTML failures on distinct endpoints."""
        if not isinstance(exc, SourceBlockedError):
            self._stats_html_endpoints.clear()
            return
        self._stats_html_endpoints.add(endpoint)
        if len(self._stats_html_endpoints) >= 2:
            self._stats_unavailable_reason = (
                "Stats 的两个不同接口连续返回 HTML，本次暂停后续 Stats 请求"
                "（含球员档案）；已保留缓存并继续处理官方 CDN 数据。"
                "请检查 stats.nba.com 的代理路由、切换代理节点或稍后重试。"
                f"最近错误：{reason}"
            )

    def fetch(
        self, resource: Resource, game_id: str, person_id: int | None = None
    ) -> Response:
        from nba_api.live.nba.library.http import NBALiveHTTP
        from nba_api.stats.library.http import NBAStatsHTTP

        is_stats = not resource.module.startswith("live_")
        if not is_stats:
            kind = "boxscore" if resource.module == "live_boxscore" else "playbyplay"
            endpoint = f"{kind}/{kind}_{game_id}.json"
            parameters: dict[str, Any] = {}
            http = NBALiveHTTP()
        else:
            if person_id is not None:
                request = build_profile_request(person_id)
            else:
                request = resource.request(game_id)
            endpoint, parameters = request.endpoint, request.parameters
            http = NBAStatsHTTP()
        if is_stats and self._stats_unavailable_reason:
            raise RequestFailure(
                self._stats_unavailable_reason, 0, parameters, skipped=True
            )
        for attempt in (1, 2):
            self._pace_request()
            try:
                response = http.send_api_request(
                    endpoint=endpoint,
                    parameters=parameters,
                    timeout=self.timeout,
                    proxy=self.proxy,
                )
                raw = response.get_dict()
                if not isinstance(raw, dict):
                    raise json.JSONDecodeError("Expected JSON object", "", 0)
                if is_stats:
                    self._stats_html_endpoints.clear()
                return Response(raw, parameters, attempt)
            except Exception as exc:  # noqa: BLE001 - classify HTTP client exceptions
                disposition = classify_error(exc)
                if is_stats:
                    self._record_stats_failure(endpoint, exc, disposition.reason)
                if disposition.retryable and attempt < 2:
                    self.sleep(2 ** (attempt - 1) + self.jitter(0, 0.5))
                    continue
                raise RequestFailure(disposition.reason, attempt, parameters) from None
        raise AssertionError("unreachable")
