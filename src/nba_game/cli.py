"""Single-command archival of all supported NBA game data."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from nba_game.arguments import validate_game_id, validate_proxy, validate_timeout
from nba_game.collector import Collector
from nba_game.diagnostics import check_network
from nba_game.errors import NbaGameError

DEFAULT_OUTPUT_ROOT = Path(__file__).resolve().parents[2] / "data" / "games"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="抓取单场 NBA 全部基础、扩展数据及球员当前档案，仅保存原始 JSON。"
    )
    parser.add_argument(
        "game_id", type=validate_game_id, help="10 位 NBA 比赛 ID（保留前导零）"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="输出根目录（默认：项目的 data/games，其下自动追加比赛 ID）",
    )
    parser.add_argument(
        "--proxy",
        type=validate_proxy,
        default=None,
        help="HTTP/HTTPS/SOCKS 代理，默认读取环境变量或系统代理",
    )
    parser.add_argument(
        "--timeout",
        type=validate_timeout,
        default=30.0,
        help="单次请求超时秒数（默认：30）",
    )
    parser.add_argument(
        "--force", action="store_true", help="忽略缓存，重新抓取全部数据和档案"
    )
    parser.add_argument(
        "--check-network",
        action="store_true",
        help="仅检查 NBA Stats 与 CDN 是否返回有效 JSON，不修改存档",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    directory = args.output_dir / args.game_id
    try:
        if args.check_network:
            return check_network(args.game_id, timeout=args.timeout, proxy=args.proxy)
        collector = Collector(
            args.game_id,
            args.output_dir,
            timeout=args.timeout,
            proxy=args.proxy,
            force=args.force,
        )
        report = collector.run()
    except KeyboardInterrupt:
        print(f"已中断，成功进度已保存：{directory}", file=sys.stderr)
        return 1
    except (NbaGameError, OSError) as exc:
        message = str(exc) if isinstance(exc, NbaGameError) else "无法访问输出目录"
        print(f"抓取失败：{message}", file=sys.stderr)
        return 1
    counts = report["summary"]
    print(
        f"比赛接口：{counts['game_resources_succeeded']}/{counts['game_resources_expected']}；"
        f"球员档案：{counts['profiles_succeeded']}/{counts['profiles_expected']}"
    )
    if not report["profiles"]["roster_complete"]:
        print("球员名单覆盖不完整，请查看 manifest.json。", file=sys.stderr)
    if counts["empty_resources"]:
        print("合法空结果：" + ", ".join(counts["empty_resources"]))
    fallbacks = [
        key
        for key, entry in report["resources"].items()
        if entry.get("source") == "nba_live_cdn"
        and entry.get("status") in ("success", "empty")
    ]
    if fallbacks:
        print("官方 Live 数据已保存：" + ", ".join(fallbacks))
    if report.get("stats_unavailable"):
        print(
            "Stats 源暂不可用，未请求的资源已标记 skipped=true、attempts=0；"
            "网络恢复后重新运行原命令即可补抓，无需 --force。",
            file=sys.stderr,
        )
    if report["status"] == "complete":
        print(f"抓取完成：{directory}")
        return 0
    print(
        f"部分数据未完成，已保存成功结果与缺项说明：{directory / 'summary.md'}",
        file=sys.stderr,
    )
    return 1
