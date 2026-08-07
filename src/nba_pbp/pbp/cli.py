"""Command-line interface for raw NBA play-by-play archival."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from nba_pbp.common.arguments import (
    GAME_ID_PATTERN,
    PROXY_SCHEMES,
    validate_game_id,
    validate_proxy,
    validate_timeout,
)
from nba_pbp.common.errors import NbaPbpError
from nba_pbp.pbp.fetcher import Fetcher
from nba_pbp.pbp.storage import StorageManager


PBP_OUTPUT_DIRECTORY = "pbp"


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="python -m nba_pbp",
        description="抓取并可靠保存 NBA 官方原始逐回合数据。",
    )
    parser.add_argument("game_id", type=validate_game_id, help="10 位 NBA 比赛 ID")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data"),
        help="输出根目录（默认：data）",
    )
    parser.add_argument(
        "--format",
        choices=("json", "csv", "both"),
        default="both",
        help="表格输出格式（默认：both）",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="忽略有效缓存并重新请求",
    )
    parser.add_argument(
        "--timeout",
        type=validate_timeout,
        default=15.0,
        metavar="SECONDS",
        help="单次网络请求超时秒数（默认：15）",
    )
    parser.add_argument(
        "--proxy",
        type=validate_proxy,
        default=None,
        metavar="URL",
        help="HTTP/HTTPS/SOCKS 代理 URL（默认使用代理环境变量）",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    fetcher: Fetcher | None = None,
) -> int:
    """Run the CLI and return a process exit code."""
    args = build_parser().parse_args(argv)
    output_directory = args.output_dir / args.game_id / PBP_OUTPUT_DIRECTORY
    storage = StorageManager(output_directory)

    try:
        storage.recover()
        if not args.force:
            snapshot = storage.load_cache(args.game_id)
            if snapshot is not None:
                storage.materialize_cache(args.game_id, args.format, snapshot)
                print(f"正在使用缓存：{output_directory}")
                return 0

        active_fetcher = fetcher or Fetcher(
            timeout=args.timeout,
            proxy=args.proxy,
        )
        result = active_fetcher.fetch(args.game_id)
        storage.save_fetch(args.game_id, args.format, result)
        print(f"抓取完成：{output_directory}")
        return 0
    except NbaPbpError as exc:
        print(
            f"比赛 {args.game_id} 抓取失败：{exc}",
            file=sys.stderr,
        )
        return 1
