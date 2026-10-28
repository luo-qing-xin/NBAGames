"""Collect all raw game resources, checkpoint progress, and resume safely."""

from __future__ import annotations

from collections.abc import Callable
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from nba_game.arguments import GAME_ID_PATTERN
from nba_game.errors import NbaGameError, StorageError
from nba_game.models import GameContext, Resource
from nba_game.reporting import write_summary
from nba_game.sources.live import LIVE_BOX, LIVE_PBP
from nba_game.sources.live import RESOURCES as LIVE_RESOURCES
from nba_game.sources.stats import BY_NAME, LINEUP_SHOTS, LINEUPS, PROFILE, RESOURCES
from nba_game.storage import (
    atomic_json,
    file_hash,
    file_time,
    import_legacy,
    load_cache,
    load_manifest,
    utc_now,
)
from nba_game.transport import Transport, classify_error, proxy_is_configured
from nba_game.validation import (
    consistency_checks,
    game_status,
    inspect_response,
    lineup_ids,
    roster_ids,
    team_ids,
)


class Collector:
    def __init__(
        self,
        game_id: str,
        output_root: Path,
        *,
        timeout: float = 30,
        proxy: str | None = None,
        force: bool = False,
        transport: Any = None,
        progress: Callable[[str], None] = print,
        legacy_root: Path | None = None,
    ):
        if not GAME_ID_PATTERN.fullmatch(game_id):
            raise ValueError("比赛 ID 必须恰好由 10 位 ASCII 数字组成")
        self.game_id, self.force = game_id, force
        self.directory = Path(output_root) / game_id
        self.context = GameContext(game_id)
        if not force:
            import_legacy(
                self.directory,
                (legacy_root or Path(output_root).parent / "output") / game_id,
                game_id,
            )
        self.transport = (
            transport if transport is not None else Transport(timeout, proxy)
        )
        self.progress = progress
        self.old = load_manifest(self.directory, game_id)
        self.old_entries = self.old.get("resources", {})
        self.payloads: dict[str, dict] = {}
        self.current_status: int | None = None
        self.anchor_time: str | None = None
        for resource in (BY_NAME["box_score_summary_v3"], LIVE_BOX):
            path = self.path(resource)
            cached = load_cache(path, resource, game_id)
            if cached is not None:
                self.current_status = game_status(cached[0])
                self.anchor_time = file_time(path)
                if self.current_status is not None:
                    break
        self.reuse_game = not force and self.current_status == 3
        self.report: dict[str, Any] = {
            "schema_version": 2,
            "season": self.context.season[0],
            "season_type": self.context.season[1],
            "game_id": game_id,
            "started_at": utc_now(),
            "status": "running",
            "game_status": self.current_status,
            "versions": _versions(),
            "request_options": {
                "timeout_seconds": timeout,
                "proxy_configured": proxy_is_configured(proxy),
            },
            "resources": {},
            "profiles": {
                "person_ids": [],
                "roster_complete": False,
                "note": "CommonPlayerInfo 是抓取时的当前档案，并非历史比赛时的档案。",
            },
        }

    def path(self, resource: Resource, person_id: int | None = None) -> Path:
        return self.directory / resource.relative_path(person_id)

    def checkpoint(self) -> None:
        self.report["updated_at"] = utc_now()
        self.report["game_status"] = self.current_status
        atomic_json(self.directory / "manifest.json", self.report)

    def _can_reuse(self, key: str, path: Path, person_id: int | None) -> bool:
        if self.force or not path.is_file():
            return False
        entry = self.old_entries.get(key)
        if not isinstance(entry, dict):
            entry = {}
        if entry.get("status") in ("failed", "skipped", "empty"):
            return False
        if entry.get("sha256") and entry["sha256"] != file_hash(path):
            return False
        # Profiles represent the query time and are not tied to game completion.
        if person_id is not None:
            return True
        if not self.reuse_game:
            return False
        if entry.get("status") == "success" and entry.get("game_status_at_fetch") == 3:
            return True
        # Reconstruct lost manifests using a final-summary time as a freshness barrier.
        return self.anchor_time is not None and file_time(path) >= self.anchor_time

    def collect(self, resource: Resource, person_id: int | None = None) -> dict | None:
        key = resource.key(person_id)
        path = self.path(resource, person_id)
        previous = self.old_entries.get(key, {})
        if not isinstance(previous, dict):
            previous = {}
        source = resource.source
        endpoint = (
            f"https://cdn.nba.com/static/json/liveData/"
            f"{'boxscore/boxscore' if resource is LIVE_BOX else 'playbyplay/playbyplay'}_{self.game_id}.json"
            if source == "nba_live_cdn"
            else f"https://stats.nba.com/stats/{resource.module}"
        )
        parameters: dict[str, Any] = {}
        entry: dict[str, Any] = {
            "endpoint": endpoint,
            "source": source,
            "parameters": parameters,
            "resource": resource.name,
            "team_id": resource.team_id,
            "group_id": resource.group_id,
            "checked_at": utc_now(),
            "cache_hit": False,
            "attempts": 0,
        }
        raw = None
        try:
            if person_id is not None:
                from nba_api.stats.endpoints.commonplayerinfo import CommonPlayerInfo

                parameters = CommonPlayerInfo(
                    player_id=person_id, get_request=False
                ).parameters
            elif source == "nba_stats":
                parameters = resource.request(self.game_id).parameters
            entry["parameters"] = parameters
            previous_parameters = previous.get("parameters", {})
            trusted_game_id = (
                bool(previous.get("sha256"))
                and isinstance(previous_parameters, dict)
                and previous_parameters.get("GameID") == self.game_id
            )
            cached = (
                load_cache(
                    path,
                    resource,
                    self.game_id,
                    person_id,
                    trusted_game_id=trusted_game_id,
                )
                if self._can_reuse(key, path, person_id)
                else None
            )
            if cached is not None and cached[1] == 0:
                cached = None
            if cached is not None:
                raw, count = cached
                entry.update(
                    cache_hit=True,
                    fetched_at=previous.get("fetched_at", file_time(path)),
                )
                if "migration" in previous:
                    entry["migration"] = previous["migration"]
            else:
                if not (
                    source == "nba_stats"
                    and getattr(self.transport, "stats_paused", False)
                ):
                    self.progress(f"正在抓取：{key}")
                response = self.transport.fetch(resource, self.game_id, person_id)
                entry.update(attempts=response.attempts, parameters=response.parameters)
                raw = response.raw
                count = inspect_response(resource, raw, self.game_id, person_id)
                atomic_json(path, raw)
                entry["fetched_at"] = utc_now()
            if resource.name == "box_score_summary_v3" or (
                resource is LIVE_BOX and "box_score_summary_v3" not in self.payloads
            ):
                self.current_status = game_status(raw)
                if self.current_status != 3:
                    self.reuse_game = False
            entry.update(
                status="success" if count else "empty",
                row_count=count,
                file=str(path.relative_to(self.directory)),
                sha256=file_hash(path),
                game_status_at_fetch=self.current_status,
            )
            if person_id is None:
                self.payloads[key] = raw
        except Exception as exc:  # noqa: BLE001 - isolate third-party endpoint failures
            reason = (
                str(exc)
                if isinstance(exc, NbaGameError)
                else classify_error(exc).reason
            )
            entry.update(
                status="failed",
                error=reason,
                attempts=getattr(exc, "attempts", entry["attempts"]),
            )
            if hasattr(exc, "parameters"):
                entry["parameters"] = exc.parameters
            if path.is_file():
                entry["retained_previous_file"] = str(path.relative_to(self.directory))
            if getattr(exc, "skipped", False):
                entry["status"] = "skipped"
                entry["skipped"] = True
                if "stats_unavailable" not in self.report:
                    self.report["stats_unavailable"] = reason
                    self.progress(reason)
            else:
                self.progress(f"未完成：{key}（{reason}）")
            raw = None
        self.report["resources"][key] = entry
        self.checkpoint()
        return raw

    def skip(self, resource: Resource, reason: str) -> None:
        self.report["resources"][resource.key()] = {
            "status": "skipped",
            "skipped": True,
            "resource": resource.name,
            "source": resource.source,
            "team_id": resource.team_id,
            "group_id": resource.group_id,
            "attempts": 0,
            "cache_hit": False,
            "error": reason,
            "checked_at": utc_now(),
        }
        self.checkpoint()

    def collect_lineups(self, summary, traditional, live) -> None:
        self.context.team_ids = team_ids(summary, traditional, live)
        self.report["team_ids"] = self.context.team_ids
        if not self.context.team_ids:
            self.skip(LINEUPS, "依赖缺失：无法确定双方球队 ID")
            self.skip(LINEUP_SHOTS, "依赖缺失：无法取得本场阵容列表")
            return
        for team_id in self.context.team_ids:
            raw = self.collect(LINEUPS.bind(team_id))
            groups = lineup_ids(raw) if raw is not None else []
            if not groups:
                self.skip(
                    LINEUP_SHOTS.bind(team_id), "依赖缺失：本队未取得非空的有效阵容列表"
                )
                continue
            for group_id in groups:
                self.collect(LINEUP_SHOTS.bind(team_id, group_id))

    def finish(self, status: str | None = None) -> dict:
        entries = self.report["resources"]
        for resource in (*RESOURCES, *LIVE_RESOURCES):
            if resource.key() not in entries:
                self.skip(resource, self.report.get("run_error", "未执行：运行中断"))
        for resource in (LINEUPS, LINEUP_SHOTS):
            if not any(e.get("resource") == resource.name for e in entries.values()):
                self.skip(resource, "依赖缺失：尚未展开球队／阵容请求")
        for pid in self.report["profiles"]["person_ids"]:
            entries.setdefault(
                PROFILE.key(pid),
                {
                    "resource": PROFILE.name,
                    "source": "nba_stats",
                    "status": "skipped",
                    "attempts": 0,
                    "cache_hit": False,
                    "error": "未执行：运行中断",
                },
            )
        game_entries = {
            k: e for k, e in entries.items() if e.get("resource") != PROFILE.name
        }
        failed = [k for k, e in entries.items() if e["status"] in ("failed", "skipped")]
        self.report["checks"] = consistency_checks(
            self.payloads, self.current_status == 3
        )
        self.report["summary"] = {
            "game_resources_expected": len(game_entries),
            "game_resources_succeeded": sum(
                e["status"] == "success" for e in game_entries.values()
            ),
            "game_resources_empty": sum(
                e["status"] == "empty" for e in game_entries.values()
            ),
            "profiles_expected": len(self.report["profiles"]["person_ids"]),
            "profiles_succeeded": sum(
                entries[PROFILE.key(pid)]["status"] == "success"
                for pid in self.report["profiles"]["person_ids"]
            ),
            "failed_resources": failed,
            "empty_resources": [
                k for k, e in entries.items() if e["status"] == "empty"
            ],
            "failed_checks": [
                c["name"] for c in self.report["checks"] if c["status"] == "failed"
            ],
        }
        self.report["status"] = status or (
            "complete"
            if not failed
            and self.report["profiles"]["roster_complete"]
            and not self.report["summary"]["failed_checks"]
            and "run_error" not in self.report
            else "partial"
        )
        self.report["finished_at"] = utc_now()
        self.checkpoint()
        write_summary(self.directory, self.report)
        return self.report

    def run(self) -> dict:
        self.checkpoint()
        try:
            with self.transport:
                summary = self.collect(RESOURCES[0])
                traditional = self.collect(RESOURCES[1])
                live = self.collect(LIVE_BOX)
                self.collect(LIVE_PBP)
                ids, complete = roster_ids(traditional, summary, live)
                self.report["profiles"].update(person_ids=ids, roster_complete=complete)
                self.checkpoint()
                for resource in RESOURCES[2:]:
                    self.collect(resource)
                self.collect_lineups(summary, traditional, live)
                for person_id in ids:
                    self.collect(PROFILE, person_id)
        except KeyboardInterrupt:
            self.finish("interrupted")
            raise
        except Exception as exc:
            if isinstance(exc, StorageError):
                raise
            self.report["run_error"] = classify_error(exc).reason
        return self.finish()


def _versions() -> dict[str, str]:
    versions = {}
    for package in ("nba_api", "curl_cffi", "nba-game"):
        try:
            versions[package] = version(package)
        except PackageNotFoundError:
            versions[package] = "not installed"
    return versions
