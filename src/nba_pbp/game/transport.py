"""Paced NBA raw HTTP requests, without invoking DataFrame parsers."""

from __future__ import annotations

import json
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from nba_pbp.common.errors import FetchError
from nba_pbp.common.http import classify_error, nba_http_session
from nba_pbp.game.resources import Resource


@dataclass
class Response:
    raw: dict[str, Any]
    parameters: dict[str, Any]
    attempts: int


class RequestFailure(FetchError):
    def __init__(self, message: str, attempts: int, parameters: dict[str, Any]):
        super().__init__(message)
        self.attempts = attempts
        self.parameters = parameters


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

    def __enter__(self):
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

        if resource.module.startswith("live_"):
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
                return Response(raw, parameters, attempt)
            except Exception as exc:  # noqa: BLE001 - classify HTTP client exceptions
                disposition = classify_error(exc)
                if disposition.retryable and attempt < 2:
                    self.sleep(2 ** (attempt - 1) + self.jitter(0, 0.5))
                    continue
                raise RequestFailure(disposition.reason, attempt, parameters) from None
        raise AssertionError("unreachable")
