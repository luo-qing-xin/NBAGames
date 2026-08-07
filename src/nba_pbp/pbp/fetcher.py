"""Fetch complete raw NBA play-by-play responses with bounded retries."""

from __future__ import annotations

import math
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from nba_pbp.common.errors import FetchError, ResponseValidationError
from nba_pbp.common.http import (
    StatusAwareBrowserSession,
    classify_error,
    nba_http_session,
    proxy_is_configured,
)
from nba_pbp.pbp.raw_data import extract_raw_records


class EndpointFactory(Protocol):
    """Callable shape used to instantiate PlayByPlayV3."""

    def __call__(self, **kwargs: Any) -> Any: ...


@dataclass(frozen=True)
class FetchResult:
    """Values returned by one successful endpoint request."""

    raw_response: dict[str, Any]
    play_by_play_records: list[dict[str, Any]]
    available_video_records: list[dict[str, Any]]
    dataframe_consistency: dict[str, Any]
    request_info: FetchRequestInfo


@dataclass(frozen=True)
class FetchRequestInfo:
    """Non-sensitive details about the request that produced a result."""

    data_source: Literal["stats_playbyplayv3", "nba_live_cdn"]
    endpoint: str
    transport: str
    timeout_seconds: float
    proxy_configured: bool


class Fetcher:
    """Fetch raw NBA play-by-play data."""

    def __init__(
        self,
        endpoint_factory: EndpointFactory | None = None,
        live_endpoint_factory: EndpointFactory | None = None,
        session_context: Callable[[], Any] = nba_http_session,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[float, float], float] = random.uniform,
        timeout: float = 15,
        proxy: str | None = None,
    ) -> None:
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout 必须是正数")
        self._endpoint_factory = endpoint_factory
        self._live_endpoint_factory = live_endpoint_factory
        self._session_context = session_context
        self._sleep = sleep
        self._jitter = jitter
        self._timeout = timeout
        self._proxy = proxy
        self._proxy_configured = proxy_is_configured(proxy)

    def fetch(self, game_id: str) -> FetchResult:
        """Fetch one game from Stats, falling back to the official CDN."""
        try:
            context = self._session_context()
            with context:
                failures: list[tuple[str, str]] = []
                for source in ("stats", "cdn"):
                    result = self._fetch_source(game_id, source, failures)
                    if result is not None:
                        return result
                raise FetchError(
                    _combined_failure_message(
                        failures, self._proxy_configured
                    )
                ) from None
        except (FetchError, ResponseValidationError):
            raise
        except ModuleNotFoundError:
            raise FetchError(
                "缺少 nba_api 或 curl_cffi 运行依赖，请重新安装项目"
            ) from None
        except Exception as exc:  # noqa: BLE001 - keep CLI output concise
            disposition = classify_error(exc)
            raise FetchError(disposition.reason) from None

        raise FetchError("请求未能完成")

    def _fetch_source(
        self,
        game_id: str,
        source: Literal["stats", "cdn"],
        failures: list[tuple[str, str]],
    ) -> FetchResult | None:
        for attempt in range(1, 3):
            try:
                if source == "stats":
                    return self._request_stats_once(game_id)
                return self._request_cdn_once(game_id)
            except ResponseValidationError:
                raise
            except Exception as exc:  # noqa: BLE001 - endpoint errors vary
                disposition = classify_error(exc)
                if disposition.retryable and attempt < 2:
                    delay = (2 ** (attempt - 1)) + self._jitter(0.0, 0.5)
                    self._sleep(delay)
                    continue
                if disposition.fallback_allowed or disposition.retryable:
                    failures.append((source, disposition.reason))
                    return None
                raise FetchError(disposition.reason) from None
        return None

    def _request_stats_once(self, game_id: str) -> FetchResult:
        endpoint_factory = self._endpoint_factory or _load_endpoint_factory()
        kwargs: dict[str, Any] = {
            "game_id": game_id,
            "start_period": 0,
            "end_period": 0,
            "timeout": self._timeout,
        }
        if self._proxy is not None:
            kwargs["proxy"] = self._proxy
        response = endpoint_factory(**kwargs)

        return self._build_result(
            game_id=game_id,
            response=response,
            play_by_play_frame=response.play_by_play.get_data_frame(),
            available_video_frame=response.available_video.get_data_frame(),
            data_source="stats_playbyplayv3",
            endpoint="https://stats.nba.com/stats/playbyplayv3",
        )

    def _request_cdn_once(self, game_id: str) -> FetchResult:
        endpoint_factory = (
            self._live_endpoint_factory or _load_live_endpoint_factory()
        )
        kwargs: dict[str, Any] = {
            "game_id": game_id,
            "timeout": self._timeout,
        }
        if self._proxy is not None:
            kwargs["proxy"] = self._proxy
        response = endpoint_factory(**kwargs)
        return self._build_result(
            game_id=game_id,
            response=response,
            play_by_play_frame=response.actions.get_data_frame(),
            available_video_frame=None,
            data_source="nba_live_cdn",
            endpoint=(
                "https://cdn.nba.com/static/json/liveData/playbyplay/"
                f"playbyplay_{game_id}.json"
            ),
        )

    def _build_result(
        self,
        *,
        game_id: str,
        response: Any,
        play_by_play_frame: Any,
        available_video_frame: Any | None,
        data_source: Literal["stats_playbyplayv3", "nba_live_cdn"],
        endpoint: str,
    ) -> FetchResult:
        raw_response = response.get_dict()
        if not isinstance(raw_response, dict):
            raise ResponseValidationError("API 响应不是 JSON 对象")

        play_records, raw_video_records = extract_raw_records(
            raw_response, game_id
        )
        frame_play_records = _dataframe_records(play_by_play_frame)
        frame_video_records = (
            _dataframe_records(available_video_frame)
            if available_video_frame is not None
            else None
        )
        if frame_video_records == []:
            raise ResponseValidationError("available_video 数据为空")

        consistency = _compare_dataframe_records(
            play_records,
            frame_play_records,
            raw_video_records,
            frame_video_records,
        )
        return FetchResult(
            raw_response=raw_response,
            play_by_play_records=play_records,
            available_video_records=(
                frame_video_records
                if frame_video_records is not None
                else raw_video_records
            ),
            dataframe_consistency=consistency,
            request_info=FetchRequestInfo(
                data_source=data_source,
                endpoint=endpoint,
                transport="curl_cffi/chrome",
                timeout_seconds=self._timeout,
                proxy_configured=self._proxy_configured,
            ),
        )


def _load_endpoint_factory() -> EndpointFactory:
    from nba_api.stats.endpoints.playbyplayv3 import PlayByPlayV3

    return PlayByPlayV3


def _load_live_endpoint_factory() -> EndpointFactory:
    from nba_api.live.nba.endpoints.playbyplay import PlayByPlay

    return PlayByPlay


def _dataframe_records(frame: Any) -> list[dict[str, Any]]:
    records = frame.to_dict(orient="records")
    if not isinstance(records, list) or not all(
        isinstance(record, dict) for record in records
    ):
        raise ResponseValidationError("nba_api DataFrame 无法转换为记录")
    return records


def _compare_dataframe_records(
    raw_play_records: list[dict[str, Any]],
    frame_play_records: list[dict[str, Any]],
    raw_video_records: list[dict[str, Any]],
    frame_video_records: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    frame_columns = _ordered_keys(frame_play_records)
    raw_columns = _ordered_keys(raw_play_records)
    omitted_fields = [key for key in raw_columns if key not in frame_columns]

    play_values_match = len(raw_play_records) == len(frame_play_records)
    if play_values_match:
        for raw_record, frame_record in zip(
            raw_play_records, frame_play_records, strict=True
        ):
            if any(
                not _values_equal(frame_value, raw_record.get(key))
                for key, frame_value in frame_record.items()
            ):
                play_values_match = False
                break

    return {
        "play_by_play_row_count_matches": (
            len(raw_play_records) == len(frame_play_records)
        ),
        "play_by_play_values_match": play_values_match,
        "play_by_play_omitted_fields": omitted_fields,
        "available_video_matches": (
            _records_equal(raw_video_records, frame_video_records)
            if frame_video_records is not None
            else None
        ),
    }


def _ordered_keys(records: list[dict[str, Any]]) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()
    for record in records:
        for key in record:
            if key not in seen:
                seen.add(key)
                keys.append(key)
    return keys


def _records_equal(
    left: list[dict[str, Any]], right: list[dict[str, Any]]
) -> bool:
    if len(left) != len(right):
        return False
    return all(
        left_record.keys() == right_record.keys()
        and all(
            _values_equal(left_record[key], right_record[key])
            for key in left_record
        )
        for left_record, right_record in zip(left, right, strict=True)
    )


def _values_equal(left: Any, right: Any) -> bool:
    if left is right:
        return True
    try:
        if left != left and right != right:
            return True
    except (TypeError, ValueError):
        pass
    try:
        return bool(left == right)
    except (TypeError, ValueError):
        return False


def _combined_failure_message(
    failures: list[tuple[str, str]], proxy_configured: bool
) -> str:
    labels = {"stats": "Stats", "cdn": "CDN"}
    details = "；".join(
        f"{labels[source]}：{reason}" for source, reason in failures
    )
    action = (
        "请切换当前代理节点后重试"
        if proxy_configured
        else "请配置可访问 NBA 的代理（--proxy）后重试"
    )
    return f"两个 NBA 官方数据源均不可用（{details}）。{action}"
