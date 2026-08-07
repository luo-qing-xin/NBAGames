"""Validate, transform, and merge game-level NBA player information."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from nba_pbp.common.errors import ResponseValidationError


TRADITIONAL_TEAM_FIELDS = (
    "teamId",
    "teamCity",
    "teamName",
    "teamTricode",
    "teamSlug",
)
TRADITIONAL_PLAYER_FIELDS = (
    "personId",
    "firstName",
    "familyName",
    "nameI",
    "playerSlug",
    "position",
    "comment",
    "jerseyNum",
)
TRADITIONAL_STAT_FIELDS = (
    "minutes",
    "fieldGoalsMade",
    "fieldGoalsAttempted",
    "fieldGoalsPercentage",
    "threePointersMade",
    "threePointersAttempted",
    "threePointersPercentage",
    "freeThrowsMade",
    "freeThrowsAttempted",
    "freeThrowsPercentage",
    "reboundsOffensive",
    "reboundsDefensive",
    "reboundsTotal",
    "assists",
    "steals",
    "blocks",
    "turnovers",
    "foulsPersonal",
    "points",
    "plusMinusPoints",
)


@dataclass(frozen=True)
class SourcePayload:
    """One game endpoint response and its player-oriented records."""

    raw_response: dict[str, Any]
    records: list[dict[str, Any]]


@dataclass(frozen=True)
class ProfilePayload:
    """One CommonPlayerInfo response and its three useful datasets."""

    raw_response: dict[str, Any]
    profile: dict[str, Any]
    headline_stats: dict[str, Any] | None
    available_seasons: list[dict[str, Any]]


def extract_traditional_players(
    raw_response: Mapping[str, Any], expected_game_id: str
) -> list[dict[str, Any]]:
    """Extract PlayerStats-equivalent rows from a V3 raw response."""
    box_score = _mapping(raw_response.get("boxScoreTraditional"), "boxScoreTraditional")
    game_id = box_score.get("gameId")
    if game_id != expected_game_id:
        raise ResponseValidationError("BoxScoreTraditionalV3 比赛 ID 不匹配")

    records: list[dict[str, Any]] = []
    for team_key in ("homeTeam", "awayTeam"):
        team = _mapping(box_score.get(team_key), team_key)
        players = team.get("players", [])
        if not isinstance(players, list):
            raise ResponseValidationError(
                "BoxScoreTraditionalV3 的 players 不是列表"
            )
        team_values = {field: team.get(field) for field in TRADITIONAL_TEAM_FIELDS}
        for player_value in players:
            player = _mapping(player_value, "player")
            statistics = _mapping(player.get("statistics", {}), "statistics")
            record: dict[str, Any] = {"gameId": game_id, **team_values}
            record.update(
                {field: player.get(field) for field in TRADITIONAL_PLAYER_FIELDS}
            )
            record.update(
                {field: statistics.get(field) for field in TRADITIONAL_STAT_FIELDS}
            )
            _person_id(record.get("personId"))
            records.append(record)
    if not records:
        raise ResponseValidationError("BoxScoreTraditionalV3 没有球员记录")
    return records


def extract_inactive_players(
    raw_response: Mapping[str, Any], expected_game_id: str
) -> list[dict[str, Any]]:
    """Extract InactivePlayers-equivalent rows from a V3 raw response."""
    summary = _mapping(raw_response.get("boxScoreSummary"), "boxScoreSummary")
    game_id = summary.get("gameId")
    if game_id != expected_game_id:
        raise ResponseValidationError("BoxScoreSummaryV3 比赛 ID 不匹配")

    records: list[dict[str, Any]] = []
    for team_key in ("homeTeam", "awayTeam"):
        team = _mapping(summary.get(team_key), team_key)
        inactives = team.get("inactives", [])
        if not isinstance(inactives, list):
            raise ResponseValidationError(
                "BoxScoreSummaryV3 的 inactives 不是列表"
            )
        for inactive_value in inactives:
            inactive = _mapping(inactive_value, "inactive player")
            record = {
                "gameId": game_id,
                "teamId": team.get("teamId"),
                "personId": inactive.get("personId"),
                "firstName": inactive.get("firstName"),
                "familyName": inactive.get("familyName"),
                "jerseyNum": inactive.get("jerseyNum"),
            }
            _person_id(record.get("personId"))
            records.append(record)
    return records


def extract_profile(
    raw_response: Mapping[str, Any], expected_person_id: int
) -> ProfilePayload:
    """Extract CommonPlayerInfo datasets from its legacy tabular response."""
    profile_records = _legacy_records(raw_response, "CommonPlayerInfo")
    if len(profile_records) != 1:
        raise ResponseValidationError(
            f"球员 {expected_person_id} 的 CommonPlayerInfo 记录数不是 1"
        )
    profile = profile_records[0]
    if _person_id(profile.get("PERSON_ID")) != expected_person_id:
        raise ResponseValidationError(
            f"球员 {expected_person_id} 的 CommonPlayerInfo ID 不匹配"
        )

    headline_records = _legacy_records(raw_response, "PlayerHeadlineStats")
    if len(headline_records) > 1:
        raise ResponseValidationError(
            f"球员 {expected_person_id} 的 PlayerHeadlineStats 记录过多"
        )
    if headline_records:
        headline_id = headline_records[0].get("PLAYER_ID")
        if headline_id is not None and _person_id(headline_id) != expected_person_id:
            raise ResponseValidationError(
                f"球员 {expected_person_id} 的 headline stats ID 不匹配"
            )

    return ProfilePayload(
        raw_response=dict(raw_response),
        profile=profile,
        headline_stats=headline_records[0] if headline_records else None,
        available_seasons=_legacy_records(raw_response, "AvailableSeasons"),
    )


def collect_person_ids(
    box_score_records: list[dict[str, Any]],
    inactive_records: list[dict[str, Any]],
) -> list[int]:
    """Return stable, de-duplicated IDs from both game datasets."""
    result: list[int] = []
    seen: set[int] = set()
    for record in [*box_score_records, *inactive_records]:
        person_id = _person_id(record.get("personId"))
        if person_id not in seen:
            seen.add(person_id)
            result.append(person_id)
    return result


def build_merged_players(
    game_id: str,
    box_score_records: list[dict[str, Any]],
    inactive_records: list[dict[str, Any]],
    profile_responses: Mapping[str, Any],
    failures: Mapping[str, str],
) -> list[dict[str, Any]]:
    """Build one nested JSON record per game player."""
    box_by_id = {
        _person_id(record.get("personId")): record for record in box_score_records
    }
    inactive_by_id = {
        _person_id(record.get("personId")): record for record in inactive_records
    }

    merged: list[dict[str, Any]] = []
    for person_id in collect_person_ids(box_score_records, inactive_records):
        key = str(person_id)
        raw_profile = profile_responses.get(key)
        profile_payload = (
            extract_profile(raw_profile, person_id)
            if isinstance(raw_profile, Mapping)
            else None
        )
        inactive = inactive_by_id.get(person_id)
        box_score = box_by_id.get(person_id)
        if inactive is not None:
            game_status = "inactive"
        elif box_score is not None and _minutes_are_positive(
            box_score.get("minutes")
        ):
            game_status = "played"
        else:
            game_status = "available_not_played"

        merged.append(
            {
                "gameId": game_id,
                "personId": person_id,
                "gameStatus": game_status,
                "profileFetchStatus": (
                    "success" if profile_payload is not None else "failed"
                ),
                "profileFetchError": failures.get(key),
                "boxScore": box_score,
                "inactive": inactive,
                "profile": (
                    profile_payload.profile if profile_payload is not None else None
                ),
                "headlineStats": (
                    profile_payload.headline_stats
                    if profile_payload is not None
                    else None
                ),
                "availableSeasons": (
                    profile_payload.available_seasons
                    if profile_payload is not None
                    else []
                ),
            }
        )
    return merged


def flatten_merged_players(
    merged_players: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Flatten nested player records for a readable CSV view."""
    rows: list[dict[str, Any]] = []
    scalar_fields = (
        "gameId",
        "personId",
        "gameStatus",
        "profileFetchStatus",
        "profileFetchError",
    )
    for player in merged_players:
        row = {field: player.get(field) for field in scalar_fields}
        for section, prefix in (
            ("boxScore", "boxScore"),
            ("inactive", "inactive"),
            ("profile", "profile"),
            ("headlineStats", "headlineStats"),
        ):
            value = player.get(section)
            if isinstance(value, Mapping):
                row.update({f"{prefix}_{key}": item for key, item in value.items()})
        row["profile_availableSeasons"] = player.get("availableSeasons", [])
        rows.append(row)
    return rows


def _legacy_records(
    raw_response: Mapping[str, Any], data_set_name: str
) -> list[dict[str, Any]]:
    result_sets = raw_response.get("resultSets", raw_response.get("resultSet"))
    if isinstance(result_sets, Mapping):
        candidates = [result_sets]
    elif isinstance(result_sets, list):
        candidates = result_sets
    else:
        raise ResponseValidationError("CommonPlayerInfo 响应缺少 resultSets")

    for candidate_value in candidates:
        candidate = _mapping(candidate_value, "resultSet")
        if candidate.get("name") != data_set_name:
            continue
        headers = candidate.get("headers")
        rows = candidate.get("rowSet")
        if not isinstance(headers, list) or not all(
            isinstance(header, str) for header in headers
        ):
            raise ResponseValidationError(f"{data_set_name} headers 无效")
        if not isinstance(rows, list):
            raise ResponseValidationError(f"{data_set_name} rowSet 无效")
        records: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, list) or len(row) != len(headers):
                raise ResponseValidationError(f"{data_set_name} 行结构无效")
            records.append(dict(zip(headers, row, strict=True)))
        return records
    raise ResponseValidationError(f"CommonPlayerInfo 响应缺少 {data_set_name}")


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ResponseValidationError(f"NBA API 响应中的 {label} 不是对象")
    return value


def _person_id(value: Any) -> int:
    if isinstance(value, bool):
        raise ResponseValidationError("球员 personId 无效")
    try:
        person_id = int(value)
    except (TypeError, ValueError, OverflowError):
        raise ResponseValidationError("球员 personId 无效") from None
    if person_id <= 0:
        raise ResponseValidationError("球员 personId 无效")
    return person_id


_ISO_MINUTES_PATTERN = re.compile(
    r"^PT(?:(?P<hours>\d+(?:\.\d+)?)H)?"
    r"(?:(?P<minutes>\d+(?:\.\d+)?)M)?"
    r"(?:(?P<seconds>\d+(?:\.\d+)?)S)?$"
)


def _minutes_are_positive(value: Any) -> bool:
    if value is None or isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return math.isfinite(float(value)) and float(value) > 0
    if not isinstance(value, str) or not value.strip():
        return False
    text = value.strip()
    match = _ISO_MINUTES_PATTERN.fullmatch(text)
    if match:
        return any(float(item or 0) > 0 for item in match.groupdict().values())
    if ":" in text:
        try:
            return any(float(item) > 0 for item in text.split(":"))
        except ValueError:
            return False
    try:
        return float(text) > 0
    except ValueError:
        return False

