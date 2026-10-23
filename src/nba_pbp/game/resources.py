"""Endpoint definitions, request parameters and raw response inspection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import import_module
from typing import Any

from nba_pbp.common.errors import ResponseValidationError


@dataclass(frozen=True)
class Resource:
    name: str
    module: str
    class_name: str
    root: str | None = None
    datasets: tuple[str, ...] = ()

    def request(self, game_id: str) -> Any:
        kwargs: dict[str, Any] = {"game_id": game_id}
        if self.module == "playbyplayv3":
            kwargs.update(start_period=0, end_period=0)
        elif self.module == "shotchartdetail":
            season, season_type = game_season(game_id)
            kwargs = {
                "game_id_nullable": game_id,
                "team_id": 0,
                "player_id": 0,
                "context_measure_simple": "FGA",
                "season_nullable": season,
                "season_type_all_star": season_type,
                "league_id": "00",
            }
        elif self.module == "gamerotation":
            kwargs["league_id"] = "00"
        factory = getattr(
            import_module(f"nba_api.stats.endpoints.{self.module}"), self.class_name
        )
        return factory(get_request=False, **kwargs)


RESOURCES = (
    Resource(
        "box_score_summary_v3",
        "boxscoresummaryv3",
        "BoxScoreSummaryV3",
        "boxScoreSummary",
    ),
    Resource(
        "box_score_traditional_v3",
        "boxscoretraditionalv3",
        "BoxScoreTraditionalV3",
        "boxScoreTraditional",
    ),
    Resource("play_by_play_v3", "playbyplayv3", "PlayByPlayV3", "game"),
    Resource(
        "box_score_advanced_v3",
        "boxscoreadvancedv3",
        "BoxScoreAdvancedV3",
        "boxScoreAdvanced",
    ),
    Resource(
        "box_score_four_factors_v3",
        "boxscorefourfactorsv3",
        "BoxScoreFourFactorsV3",
        "boxScoreFourFactors",
    ),
    Resource("box_score_misc_v3", "boxscoremiscv3", "BoxScoreMiscV3", "boxScoreMisc"),
    Resource(
        "box_score_scoring_v3",
        "boxscorescoringv3",
        "BoxScoreScoringV3",
        "boxScoreScoring",
    ),
    Resource(
        "box_score_usage_v3", "boxscoreusagev3", "BoxScoreUsageV3", "boxScoreUsage"
    ),
    Resource(
        "shot_chart_detail",
        "shotchartdetail",
        "ShotChartDetail",
        datasets=("Shot_Chart_Detail",),
    ),
    Resource(
        "game_rotation",
        "gamerotation",
        "GameRotation",
        datasets=("AwayTeam", "HomeTeam"),
    ),
    Resource(
        "box_score_player_track_v3",
        "boxscoreplayertrackv3",
        "BoxScorePlayerTrackV3",
        "boxScorePlayerTrack",
    ),
    Resource(
        "box_score_hustle_v2", "boxscorehustlev2", "BoxScoreHustleV2", "boxScoreHustle"
    ),
    Resource(
        "box_score_matchups_v3",
        "boxscorematchupsv3",
        "BoxScoreMatchupsV3",
        "boxScoreMatchups",
    ),
)
BY_NAME = {resource.name: resource for resource in RESOURCES}
LIVE_BOX = Resource("live_box_score", "live_boxscore", "BoxScore", "game")
LIVE_PBP = Resource("live_play_by_play", "live_playbyplay", "PlayByPlay", "game")
PROFILE = Resource(
    "common_player_info",
    "commonplayerinfo",
    "CommonPlayerInfo",
    datasets=("CommonPlayerInfo",),
)


def game_season(game_id: str) -> tuple[str, str]:
    """NBA game IDs encode the starting season year and competition type."""
    year = 2000 + int(game_id[3:5])
    if year > datetime.now(timezone.utc).year + 1:
        year -= 100
    season_types = {
        "001": "Pre Season",
        "002": "Regular Season",
        "003": "All Star",
        "004": "Playoffs",
        "005": "PlayIn",
        "006": "Regular Season",
    }
    # For unknown competition codes avoid a falsely restrictive season-type filter.
    return f"{year}-{(year + 1) % 100:02d}", season_types.get(game_id[:3], "")


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
    echoed = raw.get("parameters")
    if isinstance(echoed, dict) and "GameID" in echoed and echoed["GameID"] != game_id:
        raise ResponseValidationError("响应参数中的比赛 ID 不匹配")
    if resource.root:
        root = raw.get(resource.root)
        if not isinstance(root, dict) or root.get("gameId") != game_id:
            raise ResponseValidationError(
                f"{resource.class_name} 响应结构或比赛 ID 不匹配"
            )
        if resource.name in ("play_by_play_v3", "live_play_by_play"):
            actions = root.get("actions")
            if not isinstance(actions, list) or not all(
                isinstance(row, dict) for row in actions
            ):
                raise ResponseValidationError("逐回合 actions 不是对象列表")
            return len(actions)
        total = 0
        for side in ("homeTeam", "awayTeam"):
            team = root.get(side)
            if not isinstance(team, dict):
                raise ResponseValidationError(f"响应缺少 {side}")
            players = team.get("players", [])
            if not isinstance(players, list) or not all(
                isinstance(p, dict) for p in players
            ):
                raise ResponseValidationError("球队 players 不是对象列表")
            if resource.name == "box_score_matchups_v3":
                for player in players:
                    matchups = player.get("matchups", [])
                    if not isinstance(matchups, list) or not all(
                        isinstance(row, dict) for row in matchups
                    ):
                        raise ResponseValidationError("球员 matchups 不是对象列表")
                    total += len(matchups)
            else:
                total += len(players)
            stats = team.get("statistics", {})
            if not isinstance(stats, dict):
                raise ResponseValidationError("球队 statistics 不是 JSON 对象")
            if stats and resource.name != "box_score_matchups_v3":
                total += 1
            if resource.name == "box_score_summary_v3":
                inactives = team.get("inactives", [])
                if not isinstance(inactives, list) or not all(
                    isinstance(p, dict) for p in inactives
                ):
                    raise ResponseValidationError("未激活名单不是对象列表")
        return 1 if resource.name == "box_score_summary_v3" else total
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
    return sum(len(sets[name]["rowSet"]) for name in resource.datasets)


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
    traditional_ids: set[int] = set()
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
                        traditional_ids.add(value)
                else:
                    valid_ids = False
    complete = bool(traditional_ids) and summary is not None and valid_ids
    return sorted(ids), complete
