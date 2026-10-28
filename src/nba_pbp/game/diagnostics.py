"""Check the configured route without writing or refreshing archived data."""

from __future__ import annotations

from collections.abc import Callable

from nba_pbp.common.errors import NbaPbpError
from nba_pbp.game.resources import BY_NAME, LIVE_BOX, inspect_response
from nba_pbp.game.transport import Transport


def check_network(
    game_id: str,
    *,
    timeout: float,
    proxy: str | None,
    progress: Callable[[str], None] = print,
) -> int:
    results: dict[str, bool] = {}
    with Transport(timeout, proxy) as transport:
        for label, resource in (
            ("NBA Stats", BY_NAME["box_score_summary_v3"]),
            ("NBA Live CDN", LIVE_BOX),
        ):
            try:
                response = transport.fetch(resource, game_id)
                inspect_response(resource, response.raw, game_id)
                results[label] = True
                progress(f"{label}：可用（JSON 与比赛 ID 校验通过）")
            except NbaPbpError as exc:
                results[label] = False
                progress(f"{label}：不可用（{exc}）")
    if not results["NBA Stats"]:
        progress(
            "Stats 当前不可用，CDN 的状态不能证明 Stats 可用。"
            "请检查 stats.nba.com 的代理路由、切换代理节点或稍后重试。"
        )
    progress("网络检查完成，未修改任何比赛存档。")
    return 0 if all(results.values()) else 1
