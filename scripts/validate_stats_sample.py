"""Sample completed NBA games from Stats and verify their full raw archives.

Run from the project root with the installed project environment. This is a real
network integration check, separate from pytest's network-free unit tests.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import time
from pathlib import Path

from nba_api.stats.endpoints.leaguegamelog import LeagueGameLog
from nba_api.stats.library.http import NBAStatsHTTP

from nba_pbp.common.arguments import validate_proxy, validate_timeout
from nba_pbp.common.http import nba_http_session
from nba_pbp.game.collector import Collector
from nba_pbp.game.resources import PROFILE, RESOURCES, inspect_response, result_sets
from nba_pbp.game.storage import atomic_json, file_hash, utc_now

ROOT = Path(__file__).resolve().parents[1]


def candidates(raw: dict) -> list[dict]:
    dataset = result_sets(raw)["LeagueGameLog"]
    games = {}
    for values in dataset["rowSet"]:
        row = dict(zip(dataset["headers"], values, strict=True))
        if row.get("WL") not in ("W", "L"):
            continue
        game_id = row["GAME_ID"]
        # Each game appears once per team; draw from unique games, not team rows.
        if game_id not in games or "vs." in row["MATCHUP"]:
            games[game_id] = {
                "game_id": game_id,
                "date": row["GAME_DATE"],
                "matchup": row["MATCHUP"],
            }
    return [games[game_id] for game_id in sorted(games)]


def verify_archive(directory: Path, report: dict) -> dict:
    checks = {}
    raw = {}
    for resource in RESOURCES:
        entry = report["resources"][resource.name]
        path = directory / "raw" / f"{resource.name}.json"
        ok = (
            entry.get("source") == "nba_stats"
            and entry.get("status") == "success"
            and path.is_file()
        )
        if ok:
            data = json.loads(path.read_text())
            ok = file_hash(path) == entry["sha256"] and inspect_response(
                resource, data, report["game_id"]
            ) > 0
            raw[resource.name] = data
        checks[resource.name] = ok

    fields = {
        "box_score_advanced_v3": ("offensiveRating", "defensiveRating", "pace", "PIE"),
        "box_score_four_factors_v3": ("effectiveFieldGoalPercentage", "oppFreeThrowAttemptRate"),
        "box_score_misc_v3": ("pointsPaint", "pointsOffTurnovers"),
        "box_score_scoring_v3": ("percentageAssistedFGM", "percentagePoints3pt"),
        "box_score_usage_v3": ("usagePercentage", "percentagePoints"),
        "box_score_player_track_v3": ("speed", "distance", "touches", "passes"),
        "box_score_hustle_v2": ("contestedShots", "screenAssists", "deflections"),
    }
    for name, required in fields.items():
        if name not in raw:
            checks[f"fields:{name}"] = False
            continue
        root = next(r.root for r in RESOURCES if r.name == name)
        checks[f"fields:{name}"] = all(
            any(
                all(player.get("statistics", {}).get(key) is not None for key in required)
                for player in raw[name][root][side]["players"]
            )
            for side in ("homeTeam", "awayTeam")
        )

    profiles_ok = bool(report["profiles"]["person_ids"])
    for person_id in report["profiles"]["person_ids"]:
        entry = report["resources"][f"common_player_info:{person_id}"]
        path = directory / "profiles" / f"{person_id}.json"
        ok = (
            entry.get("status") == "success"
            and entry.get("source") == "nba_stats"
            and path.is_file()
        )
        if ok:
            data = json.loads(path.read_text())
            ok = file_hash(path) == entry["sha256"] and inspect_response(
                PROFILE, data, report["game_id"], person_id
            ) > 0
        profiles_ok = profiles_ok and ok
    checks["profiles_identity_and_hash"] = profiles_ok
    checks["roster_complete"] = report["profiles"]["roster_complete"]
    checks["final_game"] = report["game_status"] == 3

    summary = raw.get("box_score_summary_v3", {}).get("boxScoreSummary", {})
    traditional = raw.get("box_score_traditional_v3", {}).get("boxScoreTraditional", {})
    actions = raw.get("play_by_play_v3", {}).get("game", {}).get("actions", [])
    shots = raw.get("shot_chart_detail")
    shots_count = len(result_sets(shots)["Shot_Chart_Detail"]["rowSet"]) if shots else None
    scores = {}
    for side, score_key in (("homeTeam", "scoreHome"), ("awayTeam", "scoreAway")):
        points = traditional.get(side, {}).get("statistics", {}).get("points")
        pbp_score = next(
            (int(a[score_key]) for a in reversed(actions) if str(a.get(score_key, "")).isdigit()),
            None,
        )
        checks[f"score:{side}"] = (
            points is not None
            and points == summary.get(side, {}).get("score") == pbp_score
        )
        scores[side] = points
    fga = sum(
        traditional.get(side, {}).get("statistics", {}).get("fieldGoalsAttempted", 0)
        for side in ("homeTeam", "awayTeam")
    )
    checks["shotchart_matches_boxscore_fga"] = (
        shots_count is not None and shots_count == fga and fga > 0
    )
    return {
        "passed": all(checks.values()), "checks": checks,
        "pbp_actions": len(actions), "shotchart_rows": shots_count,
        "boxscore_fga": fga, "scores": scores,
        "stats_resources_with_data": sum(checks[r.name] for r in RESOURCES),
        "profiles_succeeded": report["summary"]["profiles_succeeded"],
        "profiles_expected": report["summary"]["profiles_expected"],
        "cache_hits": sum(e.get("cache_hit", False) for e in report["resources"].values()),
        "request_attempts": sum(e.get("attempts", 0) for e in report["resources"].values()),
        "manifest": str(directory / "manifest.json"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seasons", nargs="+", default=["2023-24", "2024-25", "2025-26"])
    parser.add_argument("--seed", type=int, default=20261028)
    parser.add_argument("--proxy", type=validate_proxy)
    parser.add_argument("--timeout", type=validate_timeout, default=60)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/output")
    parser.add_argument(
        "--report-dir", type=Path,
        default=ROOT / "data/validation/stats-random-sample",
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    rng = random.Random(args.seed)
    run = {
        "started_at": utc_now(),
        "seed": args.seed,
        "method": "one uniform draw per season from sorted unique completed regular-season games",
        "selection": [], "results": [], "status": "running",
    }
    report_path = args.report_dir / "report.json"
    atomic_json(report_path, run)
    try:
        with nba_http_session():
            for season in args.seasons:
                print(f"读取真实比赛池：{season}", flush=True)
                request = LeagueGameLog(
                    season=season, season_type_all_star="Regular Season",
                    player_or_team_abbreviation="T", get_request=False,
                )
                raw = NBAStatsHTTP().send_api_request(
                    endpoint=request.endpoint, parameters=request.parameters,
                    proxy=args.proxy, timeout=args.timeout,
                ).get_dict()
                pool = candidates(raw)
                if not pool:
                    raise ValueError(f"{season} 没有已完成比赛")
                atomic_json(args.report_dir / f"league_game_log_{season}.json", raw)
                selected = rng.choice(pool)
                selected.update(
                    season=season, pool_size=len(pool),
                    pool_sha256=hashlib.sha256(
                        json.dumps(pool, sort_keys=True).encode()
                    ).hexdigest(),
                )
                run["selection"].append(selected)
                atomic_json(report_path, run)
                print(
                    f"抽中：{selected['game_id']} {selected['date']} "
                    f"{selected['matchup']}（{len(pool)} 场候选）",
                    flush=True,
                )
                time.sleep(1)
        # Freeze all selections before testing; never replace a failing sample.
        for selected in run["selection"]:
            game_id = selected["game_id"]
            print(f"开始验证：{game_id}", flush=True)
            report = Collector(
                game_id, args.output_dir, timeout=args.timeout,
                proxy=args.proxy, force=args.force,
            ).run()
            result = verify_archive(args.output_dir / game_id, report)
            run["results"].append({**selected, **result})
            atomic_json(report_path, run)
            print(
                f"验证结果：{game_id} Stats {result['stats_resources_with_data']}/13，"
                f"档案 {result['profiles_succeeded']}/{result['profiles_expected']}，"
                f"通过={result['passed']}", flush=True,
            )
            time.sleep(1)
        run["status"] = "passed" if all(r["passed"] for r in run["results"]) else "failed"
    except Exception as exc:
        run["status"] = "failed"
        # Do not persist arbitrary exception messages containing proxy credentials.
        run["error_type"] = type(exc).__name__
        print(f"验证未完成：{type(exc).__name__}，已有结果已保存。", flush=True)
    finally:
        run["finished_at"] = utc_now()
        atomic_json(report_path, run)
    print(f"报告：{report_path}", flush=True)
    return 0 if run["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
