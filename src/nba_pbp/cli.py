"""Command-line interface for raw NBA play-by-play archival."""

from __future__ import annotations

import argparse
import math
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import urlsplit

from nba_pbp.errors import NbaPbpError
from nba_pbp.fetcher import Fetcher
from nba_pbp.storage import StorageManager


GAME_ID_PATTERN = re.compile(r"^\d{10}$")
PBP_OUTPUT_DIRECTORY = "pbp"
PROXY_SCHEMES = {
    "http",
    "https",
    "socks4",
    "socks4a",
    "socks5",
    "socks5h",
}


def validate_game_id(value: str) -> str:
    """Validate a ten-digit NBA game identifier for argparse."""
    if not GAME_ID_PATTERN.fullmatch(value):
        raise argparse.ArgumentTypeError(
            "比赛 ID 必须恰好由 10 位数字组成，例如 0022300001"
        )
    return value


def validate_timeout(value: str) -> float:
    """Validate a finite, positive request timeout."""
    try:
        timeout = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("超时时间必须是正数") from None
    if not math.isfinite(timeout) or timeout <= 0:
        raise argparse.ArgumentTypeError("超时时间必须是正数")
    return timeout


def validate_proxy(value: str) -> str:
    """Validate a supported proxy URL without echoing credentials."""
    try:
        parsed = urlsplit(value)
        valid_port = parsed.port is not None
    except ValueError:
        valid_port = False
        parsed = None
    if (
        parsed is None
        or parsed.scheme.lower() not in PROXY_SCHEMES
        or not parsed.hostname
        or not valid_port
    ):
        raise argparse.ArgumentTypeError(
            "代理必须是包含主机和端口的 HTTP/HTTPS/SOCKS URL"
        )
    return value


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
