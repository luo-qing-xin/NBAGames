"""Extract records without interpreting basketball events."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from nba_pbp.common.errors import ResponseValidationError


def extract_raw_records(
    raw_response: Mapping[str, Any], expected_game_id: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return raw play-by-play and available-video records.

    The V3 response keeps ``gameId`` at the game level. The public
    ``response.play_by_play`` data set repeats it for every action, so the same
    shape is retained here while all action keys remain untouched.
    """
    if not isinstance(raw_response, Mapping):
        raise ResponseValidationError("API 响应不是 JSON 对象")

    game = raw_response.get("game")
    if not isinstance(game, Mapping):
        raise ResponseValidationError("API 响应缺少 game 对象")

    game_id = game.get("gameId")
    if game_id != expected_game_id:
        raise ResponseValidationError("API 响应中的比赛 ID 不匹配")

    actions = game.get("actions")
    if not isinstance(actions, list):
        raise ResponseValidationError("API 响应缺少 actions 列表")
    if not actions:
        raise ResponseValidationError("API 响应中没有逐回合记录")

    play_by_play_records: list[dict[str, Any]] = []
    for action in actions:
        if not isinstance(action, Mapping):
            raise ResponseValidationError("API 响应包含无效的逐回合记录")
        record: dict[str, Any] = {}
        if "gameId" not in action:
            record["gameId"] = game_id
        record.update(action)
        play_by_play_records.append(record)

    available_video_records = [
        {"videoAvailable": game.get("videoAvailable", 0)}
    ]
    return play_by_play_records, available_video_records
