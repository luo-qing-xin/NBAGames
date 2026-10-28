"""NBA Stats resource catalog and explicit request parameter construction."""

from importlib import import_module

from nba_game.models import Resource, game_season

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
    Resource(
        "box_score_defensive_v2",
        "boxscoredefensivev2",
        "BoxScoreDefensiveV2",
        "boxScoreDefensive",
    ),
    Resource("dunk_score_leaders", "dunkscoreleaders", "DunkScoreLeaders"),
)

BY_NAME = {resource.name: resource for resource in RESOURCES}
LINEUPS = Resource(
    "team_dash_lineups",
    "teamdashlineups",
    "TeamDashLineups",
    datasets=("Overall", "Lineups"),
)
LINEUP_SHOTS = Resource(
    "shot_chart_lineup_detail",
    "shotchartlineupdetail",
    "ShotChartLineupDetail",
    datasets=("ShotChartLineupDetail",),
)
PROFILE = Resource(
    "common_player_info",
    "commonplayerinfo",
    "CommonPlayerInfo",
    datasets=("CommonPlayerInfo",),
)


def build_request(resource: Resource, game_id: str):
    season, kind = game_season(game_id)
    kwargs = {"game_id": game_id}
    if resource.module == "playbyplayv3":
        kwargs.update(start_period=0, end_period=0)
    elif resource.module == "shotchartdetail":
        kwargs = {
            "game_id_nullable": game_id,
            "team_id": 0,
            "player_id": 0,
            "context_measure_simple": "FGA",
            "season_nullable": season,
            "season_type_all_star": kind,
            "league_id": "00",
        }
    elif resource.module == "gamerotation":
        kwargs["league_id"] = "00"
    elif resource.module == "dunkscoreleaders":
        kwargs = {
            "game_id_nullable": game_id,
            "season": season,
            "season_type_all_star": kind,
            "league_id_nullable": "00",
            "player_id_nullable": None,
            "team_id_nullable": None,
        }
    elif resource.module in ("teamdashlineups", "shotchartlineupdetail"):
        if resource.team_id is None:
            raise ValueError("阵容请求缺少本场球队 ID")
        kwargs = {
            "game_id_nullable": game_id,
            "season": season,
            "season_type_all_star": kind,
        }
        if resource.module == "teamdashlineups":
            kwargs.update(
                team_id=resource.team_id,
                group_quantity=5,
                measure_type_detailed_defense="Base",
                per_mode_detailed="Totals",
                league_id_nullable="00",
            )
        else:
            if resource.group_id is None:
                raise ValueError("投篮请求缺少本场真实阵容 ID")
            kwargs.update(
                team_id_nullable=resource.team_id,
                group_id=resource.group_id,
                context_measure_detailed="FGA",
                league_id="00",
                last_n_games_nullable=0,
                month_nullable=0,
                opponent_team_id_nullable=0,
            )
    factory = getattr(
        import_module(f"nba_api.stats.endpoints.{resource.module}"), resource.class_name
    )
    request = factory(get_request=False, **kwargs)
    # None means omit: curl and requests do not encode all empty values identically.
    request.parameters = {
        key: value for key, value in request.parameters.items() if value is not None
    }
    return request
