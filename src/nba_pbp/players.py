"""CLI for fetching complete game player information."""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable, Sequence
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Protocol

from nba_pbp.cli import validate_game_id, validate_proxy, validate_timeout
from nba_pbp.errors import NbaPbpError
from nba_pbp.player_data import PlayerDataFetcher, collect_person_ids
from nba_pbp.player_storage import PlayerStorageManager, ProfileCache


PROFILE_REQUEST_DELAY_SECONDS = 0.6
PLAYERS_OUTPUT_DIRECTORY = "players"


class PlayerFetcher(Protocol):
    """Methods used by the player CLI, kept injectable for tests."""

    def fetch_traditional(self, game_id: str) -> Any: ...

    def fetch_summary(self, game_id: str) -> Any: ...

    def fetch_profile(self, person_id: int) -> Any: ...


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m nba_pbp.players",
        description=(
            "抓取并保存一场 NBA 比赛的球员、"
            "未激活名单和个人档案。"
        ),
    )
    parser.add_argument("game_id", type=validate_game_id, help="10 位 NBA 比赛 ID")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data"),
        help="输出根目录（默认：data）",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="忽略有效缓存并重新请求全部球员数据",
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
    fetcher: PlayerFetcher | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Run the player information command and return a process exit code."""
    args = build_parser().parse_args(argv)
    output_directory = args.output_dir / args.game_id / PLAYERS_OUTPUT_DIRECTORY
    storage = PlayerStorageManager(output_directory)

    try:
        storage.prepare()
        active_fetcher = fetcher or PlayerDataFetcher(
            timeout=args.timeout,
            proxy=args.proxy,
        )
        context = (
            active_fetcher
            if hasattr(active_fetcher, "__enter__")
            else nullcontext(active_fetcher)
        )
        with context:
            traditional = None if args.force else storage.load_traditional(
                args.game_id
            )
            if traditional is None:
                traditional = active_fetcher.fetch_traditional(args.game_id)
                storage.save_traditional(traditional.raw_response)

            summary = None if args.force else storage.load_summary(args.game_id)
            if summary is None:
                summary = active_fetcher.fetch_summary(args.game_id)
                storage.save_summary(summary.raw_response)

            target_ids = collect_person_ids(
                traditional.records,
                summary.records,
            )
            target_keys = {str(person_id) for person_id in target_ids}
            cached_profiles = (
                ProfileCache({}, {})
                if args.force
                else storage.load_profiles(args.game_id)
            )
            profiles = ProfileCache(
                responses={
                    key: value
                    for key, value in cached_profiles.responses.items()
                    if key in target_keys
                },
                failures={
                    key: value
                    for key, value in cached_profiles.failures.items()
                    if key in target_keys
                },
            )

            requested_profiles = 0
            failed_ids: list[int] = []
            for person_id in target_ids:
                key = str(person_id)
                if key in profiles.responses:
                    profiles.failures.pop(key, None)
                    continue
                if requested_profiles:
                    sleep(PROFILE_REQUEST_DELAY_SECONDS)
                requested_profiles += 1
                try:
                    payload = active_fetcher.fetch_profile(person_id)
                    profiles.responses[key] = payload.raw_response
                    profiles.failures.pop(key, None)
                except NbaPbpError as exc:
                    profiles.failures[key] = str(exc)
                    failed_ids.append(person_id)
                storage.save_profiles(args.game_id, profiles)

            storage.save_profiles(args.game_id, profiles)
            merged = storage.save_merged(
                args.game_id,
                traditional,
                summary,
                profiles,
            )

        if failed_ids:
            failed_text = ", ".join(str(person_id) for person_id in failed_ids)
            print(
                f"比赛 {args.game_id} 的部分球员档案抓取失败："
                f"{failed_text}；"
                f"已保留成功进度：{output_directory}",
                file=sys.stderr,
            )
            return 1

        if requested_profiles == 0 and not args.force:
            print(
                f"正在使用球员信息缓存：{output_directory}"
                f"（{len(merged)} 名）"
            )
        else:
            print(
                f"球员信息抓取完成：{output_directory}（{len(merged)} 名）"
            )
        return 0
    except NbaPbpError as exc:
        print(
            f"比赛 {args.game_id} 球员信息抓取失败：{exc}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
