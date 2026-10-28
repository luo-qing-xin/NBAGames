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

from nba_game.arguments import validate_proxy, validate_timeout
from nba_game.collector import Collector
from nba_game.errors import ResponseValidationError
from nba_game.sources.live import RESOURCES as LIVE_RESOURCES
from nba_game.sources.stats import LINEUP_SHOTS, LINEUPS, PROFILE, RESOURCES
from nba_game.storage import atomic_json, atomic_text, file_hash, utc_now
from nba_game.transport import nba_http_session
from nba_game.validation import (
    consistency_checks,
    inspect_response,
    lineup_ids,
    result_sets,
)

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
    checks, raw = {}, {}
    catalog = {
        r.name: r for r in (*RESOURCES, *LIVE_RESOURCES, LINEUPS, LINEUP_SHOTS, PROFILE)
    }
    entries = report["resources"]
    for key, entry in entries.items():
        ok = entry["status"] in ("success", "empty")
        if ok:
            try:
                resource = catalog[entry["resource"]]
                if entry.get("team_id") is not None:
                    resource = resource.bind(entry["team_id"], entry.get("group_id"))
                pid = int(key.split(":")[1]) if resource is PROFILE else None
                path = directory / resource.relative_path(pid)
                data = json.loads(path.read_text())
                count = inspect_response(resource, data, report["game_id"], pid)
                ok = (
                    entry["file"] == str(path.relative_to(directory))
                    and file_hash(path) == entry["sha256"]
                    and count == entry["row_count"]
                    and entry["source"] == resource.source
                    and entry["status"] == ("success" if count else "empty")
                )
                raw[key] = data
            except (OSError, ValueError, KeyError, TypeError, ResponseValidationError):
                ok = False
        checks[f"archive:{key}"] = ok
    required = {r.key() for r in (*RESOURCES, *LIVE_RESOURCES)}
    for tid in report.get("team_ids", []):
        required.add(LINEUPS.bind(tid).key())
        lineups = raw.get(LINEUPS.bind(tid).key())
        if lineups:
            required.update(
                LINEUP_SHOTS.bind(tid, gid).key() for gid in lineup_ids(lineups)
            )
    required.update(PROFILE.key(pid) for pid in report["profiles"]["person_ids"])
    checks["all_planned_resources_present"] = required <= entries.keys()
    checks["both_teams_resolved"] = len(report.get("team_ids", [])) == 2
    checks["roster_complete"] = report["profiles"]["roster_complete"]
    checks["profiles_identity_and_hash"] = bool(
        report["profiles"]["person_ids"]
    ) and all(
        checks.get(f"archive:{PROFILE.key(pid)}")
        for pid in report["profiles"]["person_ids"]
    )
    checks["final_game"] = report["game_status"] == 3
    for check in consistency_checks(raw, report["game_status"] == 3):
        checks[check["name"]] = check["status"] == "passed"
    checks["collection_complete"] = report["status"] == "complete"
    traditional = raw.get("box_score_traditional_v3", {}).get("boxScoreTraditional", {})
    shots = raw.get("shot_chart_detail")
    actions = raw.get("play_by_play_v3", {}).get("game", {}).get("actions", [])
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "pbp_actions": len(actions),
        "shotchart_rows": len(result_sets(shots)["Shot_Chart_Detail"]["rowSet"])
        if shots
        else None,
        "scores": {
            side: traditional.get(side, {}).get("statistics", {}).get("points")
            for side in ("homeTeam", "awayTeam")
        },
        **report["summary"],
        "stats_resources_expected": sum(
            e.get("source") == "nba_stats" and e.get("resource") != PROFILE.name
            for e in entries.values()
        ),
        "stats_resources_with_data": sum(
            e.get("source") == "nba_stats"
            and e.get("resource") != PROFILE.name
            and e["status"] == "success"
            for e in entries.values()
        ),
        "cache_hits": sum(e.get("cache_hit", False) for e in entries.values()),
        "request_attempts": sum(e.get("attempts", 0) for e in entries.values()),
        "availability_errors": {
            k: e.get("error")
            for k, e in entries.items()
            if e["status"] in ("failed", "skipped")
        },
        "manifest": str(directory / "manifest.json"),
    }


def write_report(directory: Path, run: dict) -> None:
    lines = [
        "# 统一单场采集：随机比赛实测",
        "",
        f"种子：{run['seed']}；结果：{run['status']}。每赛季从去重后的已完赛常规赛池均匀抽取一场，测试前固定样本。",
        "",
        "此报告衡量真实接口可用性；离线程序测试单独运行。失败样本不会被替换，合法空结果不会写成非空数据。",
        "",
        "|比赛 ID|日期／对阵|非空比赛资源|合法空结果|球员档案|验收|",
        "|---|---|---:|---:|---:|---|",
    ]
    for result in run["results"]:
        lines.append(
            f"|{result['game_id']}|{result['date']} {result['matchup']}|{result['game_resources_succeeded']}/{result['game_resources_expected']}|{result['game_resources_empty']}|{result['profiles_succeeded']}/{result['profiles_expected']}|{'通过' if result['passed'] else '未全部通过'}|"
        )
    for result in run["results"]:
        lines += [
            "",
            f"### {result['game_id']}",
            "",
            f"[单场明细]({Path(result['manifest']).with_name('summary.md')})",
            "",
        ]
        for key, error in result["availability_errors"].items():
            lines.append(f"- {key}：{error}")
        for key in result["empty_resources"]:
            lines.append(f"- {key}：合法空结果。")
        for key, ok in result["checks"].items():
            if (
                not ok
                and not key.startswith("archive:")
                and key != "collection_complete"
            ):
                lines.append(f"- 校验未通过：{key}")
    if run.get("error_type"):
        lines += ["", "运行错误类型：" + run["error_type"]]
    atomic_text(directory / "report.md", "\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seasons", nargs="+", default=["2023-24", "2024-25", "2025-26"]
    )
    parser.add_argument("--seed", type=int, default=20261028)
    parser.add_argument("--proxy", type=validate_proxy)
    parser.add_argument("--timeout", type=validate_timeout, default=60)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "data/validation/unified-game-sample/games",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=ROOT / "data/validation/unified-game-sample",
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    rng = random.Random(args.seed)
    run = {
        "started_at": utc_now(),
        "seed": args.seed,
        "method": "one uniform draw per season from sorted unique completed regular-season games",
        "selection": [],
        "results": [],
        "status": "running",
    }
    report_path = args.report_dir / "report.json"
    atomic_json(report_path, run)
    try:
        with nba_http_session():
            for season in args.seasons:
                print(f"读取真实比赛池：{season}", flush=True)
                request = LeagueGameLog(
                    season=season,
                    season_type_all_star="Regular Season",
                    player_or_team_abbreviation="T",
                    get_request=False,
                )
                raw = (
                    NBAStatsHTTP()
                    .send_api_request(
                        endpoint=request.endpoint,
                        parameters=request.parameters,
                        proxy=args.proxy,
                        timeout=args.timeout,
                    )
                    .get_dict()
                )
                pool = candidates(raw)
                if not pool:
                    raise ValueError(f"{season} 没有已完成比赛")
                atomic_json(args.report_dir / f"league_game_log_{season}.json", raw)
                selected = rng.choice(pool)
                selected.update(
                    season=season,
                    pool_size=len(pool),
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
                game_id,
                args.output_dir,
                timeout=args.timeout,
                proxy=args.proxy,
                force=args.force,
            ).run()
            result = verify_archive(args.output_dir / game_id, report)
            run["results"].append({**selected, **result})
            atomic_json(report_path, run)
            print(
                f"验证结果：{game_id} Stats {result['stats_resources_with_data']}/{result['stats_resources_expected']}，"
                f"档案 {result['profiles_succeeded']}/{result['profiles_expected']}，"
                f"通过={result['passed']}",
                flush=True,
            )
            time.sleep(1)
        run["status"] = (
            "passed" if all(r["passed"] for r in run["results"]) else "failed"
        )
    except Exception as exc:  # noqa: BLE001 - preserve a redacted integration report on SDK failures
        run["status"] = "failed"
        # Do not persist arbitrary exception messages containing proxy credentials.
        run["error_type"] = type(exc).__name__
        print(f"验证未完成：{type(exc).__name__}，已有结果已保存。", flush=True)
    finally:
        run["finished_at"] = utc_now()
        atomic_json(report_path, run)
        write_report(args.report_dir, run)
    print(f"报告：{report_path}", flush=True)
    return 0 if run["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
