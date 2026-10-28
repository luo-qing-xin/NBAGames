"""Paced NBA raw HTTP requests, without invoking DataFrame parsers."""

from __future__ import annotations

import json
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from nba_pbp.common.errors import FetchError, SourceBlockedError
from nba_pbp.common.http import classify_error, nba_http_session
from nba_pbp.game.resources import Resource


@dataclass
class Response:
    raw: dict[str, Any]
    parameters: dict[str, Any]
    attempts: int


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
                from nba_api.stats.endpoints.commonplayerinfo import CommonPlayerInfo

                request = CommonPlayerInfo(player_id=person_id, get_request=False)
            else:
                request = resource.request(game_id)
            endpoint, parameters = request.endpoint, request.parameters
            http = NBAStatsHTTP()
        if is_stats and self._stats_unavailable_reason:
            raise RequestFailure(
                self._stats_unavailable_reason, 0, parameters, skipped=True
            )
        for attempt in (1, 2):
            if self._last_request is not None:
                self.sleep(max(0, 1.0 - (self.monotonic() - self._last_request)))
            self._last_request = self.monotonic()
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
                if is_stats and isinstance(exc, SourceBlockedError):
                    self._stats_html_endpoints.add(endpoint)
                    if len(self._stats_html_endpoints) >= 2:
                        self._stats_unavailable_reason = (
                            "Stats 的两个不同接口连续返回 HTML，本次暂停后续 Stats 请求"
                            "（含球员档案）；已保留缓存并继续处理官方 CDN 备用源。"
                            "请检查 stats.nba.com 的代理路由、切换代理节点或稍后重试。"
                            f"最近错误：{disposition.reason}"
                        )
                if disposition.retryable and attempt < 2:
                    self.sleep(2 ** (attempt - 1) + self.jitter(0, 0.5))
                    continue
                raise RequestFailure(disposition.reason, attempt, parameters) from None
        raise AssertionError("unreachable")
