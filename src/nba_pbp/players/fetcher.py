"""Fetch and validate game-level NBA player information."""

from __future__ import annotations

import math
import random
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any, Protocol

from nba_pbp.common.errors import FetchError, ResponseValidationError
from nba_pbp.common.http import classify_error, nba_http_session
from nba_pbp.players.transforms import (
    ProfilePayload,
    SourcePayload,
    _person_id,
    extract_inactive_players,
    extract_profile,
    extract_traditional_players,
)


class EndpointFactory(Protocol):
    """Callable shape shared by the three nba_api endpoints."""

    def __call__(self, **kwargs: Any) -> Any: ...


class PlayerDataFetcher:
    """Fetch player-related Stats endpoints with bounded retries."""

    def __init__(
        self,
        *,
        traditional_factory: EndpointFactory | None = None,
        summary_factory: EndpointFactory | None = None,
        profile_factory: EndpointFactory | None = None,
        session_context: Callable[[], AbstractContextManager[Any]] = nba_http_session,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[float, float], float] = random.uniform,
        timeout: float = 15,
        proxy: str | None = None,
    ) -> None:
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout 必须是正数")
        self._traditional_factory = traditional_factory
        self._summary_factory = summary_factory
        self._profile_factory = profile_factory
        self._session_context_factory = session_context
        self._sleep = sleep
        self._jitter = jitter
        self._timeout = timeout
        self._proxy = proxy
        self._session_context: AbstractContextManager[Any] | None = None

    def __enter__(self) -> PlayerDataFetcher:
        try:
            self._session_context = self._session_context_factory()
            self._session_context.__enter__()
            return self
        except FetchError:
            raise
        except Exception as exc:  # noqa: BLE001 - context dependencies vary
            disposition = classify_error(exc)
            raise FetchError(disposition.reason) from None

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> Any:
        if self._session_context is None:
            return None
        return self._session_context.__exit__(exc_type, exc, traceback)

    def fetch_traditional(self, game_id: str) -> SourcePayload:
        factory = self._traditional_factory or _load_traditional_factory()
        response = self._request(factory, game_id=game_id)
        raw_response = _raw_response(response)
        records = _dataframe_records(response.player_stats.get_data_frame())
        _validate_game_records(records, game_id, "PlayerStats", allow_empty=False)
        raw_records = extract_traditional_players(raw_response, game_id)
        _validate_person_ids_match(records, raw_records, "PlayerStats")
        return SourcePayload(raw_response, records)

    def fetch_summary(self, game_id: str) -> SourcePayload:
        factory = self._summary_factory or _load_summary_factory()
        response = self._request(factory, game_id=game_id)
        raw_response = _raw_response(response)
        records = _dataframe_records(response.inactive_players.get_data_frame())
        _validate_game_records(records, game_id, "InactivePlayers", allow_empty=True)
        raw_records = extract_inactive_players(raw_response, game_id)
        _validate_person_ids_match(records, raw_records, "InactivePlayers")
        return SourcePayload(raw_response, records)

    def fetch_profile(self, person_id: int) -> ProfilePayload:
        factory = self._profile_factory or _load_profile_factory()
        response = self._request(factory, player_id=person_id)
        raw_response = _raw_response(response)
        profile_records = _dataframe_records(
            response.common_player_info.get_data_frame()
        )
        headline_records = _dataframe_records(
            response.player_headline_stats.get_data_frame()
        )
        season_records = _dataframe_records(
            response.available_seasons.get_data_frame()
        )
        payload = extract_profile(raw_response, person_id)
        if profile_records != [payload.profile]:
            raise ResponseValidationError(
                f"球员 {person_id} 的 CommonPlayerInfo "
                "原始响应与 DataFrame 不一致"
            )
        if headline_records != (
            [payload.headline_stats] if payload.headline_stats is not None else []
        ):
            raise ResponseValidationError(
                f"球员 {person_id} 的 headline stats "
                "原始响应与 DataFrame 不一致"
            )
        if season_records != payload.available_seasons:
            raise ResponseValidationError(
                f"球员 {person_id} 的赛季列表原始响应与 DataFrame 不一致"
            )
        return payload

    def _request(self, factory: EndpointFactory, **parameters: Any) -> Any:
        parameters["timeout"] = self._timeout
        if self._proxy is not None:
            parameters["proxy"] = self._proxy
        for attempt in range(1, 3):
            try:
                return factory(**parameters)
            except (ResponseValidationError, FetchError):
                raise
            except Exception as exc:  # noqa: BLE001 - nba_api errors vary
                disposition = classify_error(exc)
                if disposition.retryable and attempt < 2:
                    delay = (2 ** (attempt - 1)) + self._jitter(0.0, 0.5)
                    self._sleep(delay)
                    continue
                raise FetchError(disposition.reason) from None
        raise FetchError("请求未能完成")


def _raw_response(response: Any) -> dict[str, Any]:
    value = response.get_dict()
    if not isinstance(value, dict):
        raise ResponseValidationError("NBA API 响应不是 JSON 对象")
    return value


def _dataframe_records(frame: Any) -> list[dict[str, Any]]:
    value = frame.to_dict(orient="records")
    if not isinstance(value, list) or not all(
        isinstance(record, dict) for record in value
    ):
        raise ResponseValidationError("nba_api DataFrame 无法转换为记录")
    return value


def _validate_game_records(
    records: list[dict[str, Any]],
    expected_game_id: str,
    label: str,
    *,
    allow_empty: bool,
) -> None:
    if not records and not allow_empty:
        raise ResponseValidationError(f"{label} 数据为空")
    if any(record.get("gameId") != expected_game_id for record in records):
        raise ResponseValidationError(f"{label} 比赛 ID 不匹配")


def _validate_person_ids_match(
    frame_records: list[dict[str, Any]],
    raw_records: list[dict[str, Any]],
    label: str,
) -> None:
    frame_ids = [_person_id(record.get("personId")) for record in frame_records]
    raw_ids = [_person_id(record.get("personId")) for record in raw_records]
    if frame_ids != raw_ids:
        raise ResponseValidationError(f"{label} 原始响应与 DataFrame 不一致")


def _load_traditional_factory() -> EndpointFactory:
    from nba_api.stats.endpoints.boxscoretraditionalv3 import (
        BoxScoreTraditionalV3,
    )

    return BoxScoreTraditionalV3


def _load_summary_factory() -> EndpointFactory:
    from nba_api.stats.endpoints.boxscoresummaryv3 import BoxScoreSummaryV3

    return BoxScoreSummaryV3


def _load_profile_factory() -> EndpointFactory:
    from nba_api.stats.endpoints.commonplayerinfo import CommonPlayerInfo

    return CommonPlayerInfo
