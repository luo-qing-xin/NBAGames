"""Validate raw identity, shape, and cross-resource consistency."""

import re
from typing import Any

from nba_game.errors import ResponseValidationError
from nba_game.models import Resource


def result_sets(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    sets = raw.get("resultSets", raw.get("resultSet"))
    if isinstance(sets, dict):
        sets = [sets]
    if not isinstance(sets, list) or not sets:
        raise ResponseValidationError("响应缺少 resultSets")
    result = {}
    for dataset in sets:
        if not isinstance(dataset, dict) or not isinstance(dataset.get("name"), str):
            raise ResponseValidationError("结果集结构无效")
        headers, rows = dataset.get("headers"), dataset.get("rowSet")
        if not isinstance(headers, list) or not isinstance(rows, list):
            raise ResponseValidationError("结果集缺少 headers/rowSet")
        if not all(isinstance(header, str) for header in headers):
            raise ResponseValidationError("结果集字段名必须是字符串")
        if len(headers) != len(set(headers)):
            raise ResponseValidationError("结果集存在重复字段名")
        if dataset["name"] in result:
            raise ResponseValidationError("响应存在重复结果集名称")
        if not all(isinstance(row, list) and len(row) == len(headers) for row in rows):
            raise ResponseValidationError("结果集字段与记录长度不一致")
        result[dataset["name"]] = dataset
    return result


def inspect_response(
    resource: Resource, raw: Any, game_id: str, person_id: int | None = None
) -> int:
    """Validate identity and shape; return resource row count, including valid zero."""
    if not isinstance(raw, dict):
        raise ResponseValidationError("响应不是 JSON 对象")
    _validate_echoed_parameters(resource, raw, game_id)
    if resource.module == "dunkscoreleaders":
        dunks = raw.get("dunks")
        if not isinstance(dunks, list) or any(
            not isinstance(row, dict) or row.get("gameId") != game_id for row in dunks
        ):
            raise ResponseValidationError("扣篮数据结构或比赛 ID 不匹配")
        return len(dunks)
    if resource.root:
        return _inspect_root_response(resource, raw, game_id)
    return _inspect_tabular_response(resource, raw, game_id, person_id)


def _validate_echoed_parameters(resource: Resource, raw: dict, game_id: str) -> None:
    for echoed in (raw.get("parameters"), raw.get("params")):
        if isinstance(echoed, dict):
            for key in ("GameID", "gameId"):
                if key in echoed and echoed[key] != game_id:
                    raise ResponseValidationError("响应参数中的比赛 ID 不匹配")
            if (
                resource.team_id is not None
                and "TeamID" in echoed
                and str(echoed["TeamID"]) != str(resource.team_id)
            ):
                raise ResponseValidationError("响应参数中的球队 ID 不匹配")


def _object_list(value: Any, message: str) -> list[dict]:
    """Validate shared list shape while retaining field-specific error messages."""
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise ResponseValidationError(message)
    return value


def _inspect_root_response(resource: Resource, raw: dict, game_id: str) -> int:
    root = raw.get(resource.root)
    if not isinstance(root, dict) or root.get("gameId") != game_id:
        raise ResponseValidationError(
            f"{resource.class_name} 响应结构或比赛 ID 不匹配"
        )
    if resource.name in ("box_score_summary_v3", "live_box_score") and root.get(
        "gameStatus"
    ) not in (1, 2, 3):
        raise ResponseValidationError("比赛概要缺少有效 gameStatus")
    if resource.name in ("play_by_play_v3", "live_play_by_play"):
        return len(_object_list(root.get("actions"), "逐回合 actions 不是对象列表"))
    total = 0
    for side in ("homeTeam", "awayTeam"):
        team = root.get(side)
        if not isinstance(team, dict):
            raise ResponseValidationError(f"响应缺少 {side}")
        total += _inspect_team(resource, team)
    return 1 if resource.name == "box_score_summary_v3" else total


def _inspect_team(resource: Resource, team: dict) -> int:
    players = _object_list(
        team.get("players")
        if resource.name in ("box_score_traditional_v3", "live_box_score")
        else team.get("players", []),
        "球队 players 不是对象列表",
    )
    if any(
        "statistics" in player and not isinstance(player["statistics"], dict)
        for player in players
    ):
        raise ResponseValidationError("球员 statistics 不是 JSON 对象")
    if resource.name == "box_score_matchups_v3":
        total = sum(
            len(_object_list(player.get("matchups", []), "球员 matchups 不是对象列表"))
            for player in players
        )
    else:
        total = len(players)
    stats = team.get("statistics", {})
    if not isinstance(stats, dict):
        raise ResponseValidationError("球队 statistics 不是 JSON 对象")
    if stats and resource.name != "box_score_matchups_v3":
        total += 1
    if resource.name == "box_score_summary_v3":
        _object_list(team.get("inactives"), "未激活名单不是对象列表")
    return total


def _inspect_tabular_response(
    resource: Resource, raw: dict, game_id: str, person_id: int | None
) -> int:
    sets = result_sets(raw)
    if any(name not in sets for name in resource.datasets):
        raise ResponseValidationError("响应缺少预期结果集")
    for dataset in sets.values():
        headers = dataset["headers"]
        for key in ("GAME_ID", "gameId"):
            if key in headers and any(
                row[headers.index(key)] != game_id for row in dataset["rowSet"]
            ):
                raise ResponseValidationError("结果集比赛 ID 不匹配")
    if person_id is not None:
        dataset = sets["CommonPlayerInfo"]
        headers, rows = dataset["headers"], dataset["rowSet"]
        if (
            "PERSON_ID" not in headers
            or len(rows) != 1
            or rows[0][headers.index("PERSON_ID")] != person_id
        ):
            raise ResponseValidationError("球员档案 PERSON_ID 不匹配或档案为空")
    if resource.module == "teamdashlineups":
        _validate_lineups(resource, raw, sets, game_id)
        return len(sets["Lineups"]["rowSet"])
    if resource.module == "shotchartlineupdetail":
        _validate_lineup_shots(resource, sets["ShotChartLineupDetail"], game_id)
    return sum(len(sets[name]["rowSet"]) for name in resource.datasets)


def _validate_lineups(resource: Resource, raw: dict, sets: dict, game_id: str) -> None:
    if raw.get("parameters", {}).get("GameID") != game_id:
        raise ResponseValidationError("阵容响应缺少本场 GameID 参数回显")
    for name in ("Overall", "Lineups"):
        for row in records(sets[name]):
            if row.get("GP") != 1 or (
                name == "Overall"
                and str(row.get("TEAM_ID")) != str(resource.team_id)
            ):
                raise ResponseValidationError(
                    "阵容数据未限定为本场／本队（GP 必须为 1）"
                )
    lineup_ids(raw)


def _validate_lineup_shots(resource: Resource, dataset: dict, game_id: str) -> None:
    for row in records(dataset):
        if row.get("GAME_ID") != game_id or row.get("TEAM_ID") != resource.team_id:
            raise ResponseValidationError("阵容投篮的比赛／球队 ID 不匹配")
        if group_members(str(row.get("GROUP_ID", ""))) != group_members(
            resource.group_id or ""
        ):
            raise ResponseValidationError("阵容投篮的 GROUP_ID 不匹配")


def records(dataset: dict) -> list[dict]:
    return [
        dict(zip(dataset["headers"], row, strict=True)) for row in dataset["rowSet"]
    ]


def group_members(value: str) -> frozenset[int]:
    if not re.fullmatch(r"-?[0-9]+(?:-[0-9]+){4}-?", value):
        raise ResponseValidationError("五人阵容 GROUP_ID 格式无效")
    members = frozenset(int(part) for part in value.strip("-").split("-"))
    if len(members) != 5 or min(members) <= 0:
        raise ResponseValidationError("阵容必须包含五个不同的有效球员 ID")
    return members


def lineup_ids(raw: dict) -> list[str]:
    result = set()
    for row in records(result_sets(raw)["Lineups"]):
        value = str(row.get("GROUP_ID", ""))
        group_members(value)
        result.add(value)
    return sorted(result)


def team_ids(*payloads: dict | None) -> list[int]:
    for raw in payloads:
        if not raw:
            continue
        for key in ("boxScoreSummary", "boxScoreTraditional", "game"):
            root = raw.get(key, {})
            ids = [
                root.get(side, {}).get("teamId") for side in ("homeTeam", "awayTeam")
            ]
            if (
                all(
                    isinstance(i, int) and not isinstance(i, bool) and i > 0
                    for i in ids
                )
                and ids[0] != ids[1]
            ):
                return ids
    return []


def consistency_checks(payloads: dict[str, dict], final: bool) -> list[dict]:
    """Cross-check independent official feeds; retain disagreements for inspection."""
    if not final:
        return [
            {
                "name": "final_consistency",
                "status": "skipped",
                "reason": "比赛尚未确认结束",
            }
        ]
    traditional = payloads.get("box_score_traditional_v3", {}).get(
        "boxScoreTraditional"
    )
    if traditional is None:
        return [
            {"name": "final_consistency", "status": "skipped", "reason": "传统统计缺失"}
        ]

    checks = _required_field_checks(payloads)
    checks.extend(_final_score_checks(payloads, traditional))
    shots = payloads.get("shot_chart_detail")
    if shots is not None:
        fga = [
            traditional[side].get("statistics", {}).get("fieldGoalsAttempted")
            for side in ("homeTeam", "awayTeam")
        ]
        count = len(result_sets(shots)["Shot_Chart_Detail"]["rowSet"])
        checks.append(
            _check_result(
                "shotchart_matches_boxscore_fga",
                all(isinstance(v, (int, float)) for v in fga)
                and count == sum(v or 0 for v in fga),
            )
        )
    return checks


def _check_result(name: str, ok: bool) -> dict[str, str]:
    return {"name": name, "status": "passed" if ok else "failed"}


def _has_required_statistics(team: dict, required: tuple[str, ...]) -> bool:
    return any(
        all(player.get("statistics", {}).get(key) is not None for key in required)
        for player in team.get("players", [])
    )


def _required_field_checks(payloads: dict[str, dict]) -> list[dict]:
    from nba_game.sources.stats import BY_NAME

    checks = []
    for name, required in KEY_FIELDS.items():
        if name in payloads:
            root = payloads[name][BY_NAME[name].root]
            checks.append(
                _check_result(
                    f"fields:{name}",
                    all(
                        _has_required_statistics(root[side], required)
                        for side in ("homeTeam", "awayTeam")
                    ),
                )
            )
    return checks


def _final_score_checks(payloads: dict[str, dict], traditional: dict) -> list[dict]:
    checks = []
    for side, score_key in (("homeTeam", "scoreHome"), ("awayTeam", "scoreAway")):
        points = traditional[side].get("statistics", {}).get("points")
        checks.append(
            _check_result(
                f"final_points:{side}", isinstance(points, (int, float)) and points >= 0
            )
        )
        for name, root_key in (
            ("box_score_summary_v3", "boxScoreSummary"),
            ("live_box_score", "game"),
        ):
            if name in payloads:
                root = payloads[name][root_key]
                actual = root[side].get("score")
                checks.append(
                    _check_result(
                        f"score:{name}:{side}", points is not None and points == actual
                    )
                )
                checks.append(
                    _check_result(
                        f"team:{name}:{side}",
                        isinstance(traditional[side].get("teamId"), int)
                        and traditional[side]["teamId"] > 0
                        and traditional[side]["teamId"] == root[side].get("teamId"),
                    )
                )
        for name in ("play_by_play_v3", "live_play_by_play"):
            if name in payloads:
                actions = payloads[name]["game"]["actions"]
                value = next(
                    (
                        int(a[score_key])
                        for a in reversed(actions)
                        if str(a.get(score_key, "")).isdigit()
                    ),
                    None,
                )
                checks.append(
                    _check_result(
                        f"score:{name}:{side}", points is not None and points == value
                    )
                )
    return checks


KEY_FIELDS = {
    "box_score_advanced_v3": ("offensiveRating", "defensiveRating", "pace", "PIE"),
    "box_score_four_factors_v3": (
        "effectiveFieldGoalPercentage",
        "oppFreeThrowAttemptRate",
    ),
    "box_score_misc_v3": ("pointsPaint", "pointsOffTurnovers"),
    "box_score_scoring_v3": ("percentageAssistedFGM", "percentagePoints3pt"),
    "box_score_usage_v3": ("usagePercentage", "percentagePoints"),
    "box_score_player_track_v3": ("speed", "distance", "touches", "passes"),
    "box_score_hustle_v2": ("contestedShots", "screenAssists", "deflections"),
    "box_score_defensive_v2": (
        "matchupMinutes",
        "partialPossessions",
        "matchupFieldGoalsAttempted",
    ),
}


def game_status(raw: dict[str, Any] | None) -> int | None:
    if raw:
        root = raw.get("boxScoreSummary", raw.get("game", {}))
        value = root.get("gameStatus") if isinstance(root, dict) else None
        if value in (1, 2, 3):
            return value
    return None


def roster_ids(
    traditional: dict | None, summary: dict | None, live: dict | None
) -> tuple[list[int], bool]:
    ids: set[int] = set()
    traditional_ids: dict[str, set[int]] = {"homeTeam": set(), "awayTeam": set()}
    valid_ids = True
    for raw, root_key, field in (
        (traditional, "boxScoreTraditional", "players"),
        (summary, "boxScoreSummary", "inactives"),
        (live, "game", "players"),
    ):
        if raw is None:
            continue
        root = raw[root_key]
        for side in ("homeTeam", "awayTeam"):
            for person in root[side].get(field, []):
                value = person.get("personId")
                if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                    ids.add(value)
                    if raw is traditional:
                        traditional_ids[side].add(value)
                else:
                    valid_ids = False
    complete = all(traditional_ids.values()) and summary is not None and valid_ids
    return sorted(ids), complete
