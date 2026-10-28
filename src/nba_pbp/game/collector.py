"""Collect all raw game resources, checkpoint progress, and resume safely."""

from __future__ import annotations

from collections.abc import Callable
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from nba_pbp.common.arguments import GAME_ID_PATTERN
from nba_pbp.common.errors import NbaPbpError, StorageError
from nba_pbp.common.http import classify_error, proxy_is_configured
from nba_pbp.game.resources import (
    BY_NAME,
    LIVE_BOX,
    LIVE_PBP,
    PROFILE,
    RESOURCES,
    Resource,
    game_status,
    inspect_response,
    roster_ids,
)
from nba_pbp.game.storage import (
    atomic_json,
    file_hash,
    file_time,
    load_cache,
    load_manifest,
    utc_now,
)
from nba_pbp.game.transport import Transport


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
    ):
        if not GAME_ID_PATTERN.fullmatch(game_id):
            raise ValueError("比赛 ID 必须恰好由 10 位 ASCII 数字组成")
        self.game_id, self.force = game_id, force
        self.directory = Path(output_root) / game_id
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
            "schema_version": 1,
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
        if person_id is not None:
            return self.directory / "profiles" / f"{person_id}.json"
        return self.directory / "raw" / f"{resource.name}.json"

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
        if entry.get("status") == "failed":
            return False
        if entry.get("sha256") and entry["sha256"] != file_hash(path):
            return False
        # Profiles represent the query time and are not tied to game completion.
        if person_id is not None:
            return True
        if not self.reuse_game:
            return False
        if (
            entry.get("status") in ("success", "empty")
            and entry.get("game_status_at_fetch") == 3
        ):
            return True
        # Reconstruct lost manifests using a final-summary time as a freshness barrier.
        return self.anchor_time is not None and file_time(path) >= self.anchor_time

    def collect(self, resource: Resource, person_id: int | None = None) -> dict | None:
        key = resource.name if person_id is None else f"common_player_info:{person_id}"
        path = self.path(resource, person_id)
        previous = self.old_entries.get(key, {})
        if not isinstance(previous, dict):
            previous = {}
        source = "nba_live_cdn" if resource.module.startswith("live_") else "nba_stats"
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
            if cached is not None:
                raw, count = cached
                entry.update(
                    cache_hit=True,
                    fetched_at=previous.get("fetched_at", file_time(path)),
                )
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
                self.payloads[resource.name] = raw
        except Exception as exc:  # noqa: BLE001 - isolate third-party endpoint failures
            reason = (
                str(exc) if isinstance(exc, NbaPbpError) else classify_error(exc).reason
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

    def run(self) -> dict:
        self.checkpoint()
        try:
            with self.transport:
                summary = self.collect(RESOURCES[0])
                traditional = self.collect(RESOURCES[1])
                live = None
                if summary is None or traditional is None:
                    live = self.collect(LIVE_BOX)
                for resource in RESOURCES[2:]:
                    raw = self.collect(resource)
                    if raw is None and resource.name == "play_by_play_v3":
                        self.collect(LIVE_PBP)
                ids, complete = roster_ids(traditional, summary, live)
                self.report["profiles"].update(person_ids=ids, roster_complete=complete)
                self.checkpoint()
                for person_id in ids:
                    self.collect(PROFILE, person_id)
        except KeyboardInterrupt:
            self.report["status"] = "interrupted"
            self.checkpoint()
            raise
        except Exception as exc:
            # Session setup and dependency failures must still produce an honest report.
            if isinstance(exc, StorageError):
                raise
            self.report["run_error"] = classify_error(exc).reason
        entries = self.report["resources"]
        missing = [r.name for r in RESOURCES if r.name not in entries]
        for name in missing:
            entries[name] = {
                "status": "failed",
                "error": self.report.get("run_error", "未执行"),
                "cache_hit": False,
                "attempts": 0,
            }
        expected = [r.name for r in RESOURCES] + [
            f"common_player_info:{pid}" for pid in self.report["profiles"]["person_ids"]
        ]
        failed = [
            key
            for key in expected
            if entries.get(key, {}).get("status") not in ("success", "empty")
        ]
        self.report["summary"] = {
            "game_resources_expected": len(RESOURCES),
            "game_resources_succeeded": sum(
                entries[r.name]["status"] in ("success", "empty") for r in RESOURCES
            ),
            "profiles_expected": len(self.report["profiles"]["person_ids"]),
            "profiles_succeeded": sum(
                entries.get(f"common_player_info:{pid}", {}).get("status") == "success"
                for pid in self.report["profiles"]["person_ids"]
            ),
            "failed_resources": failed,
            "empty_resources": [
                key for key in expected if entries.get(key, {}).get("status") == "empty"
            ],
        }
        self.report["status"] = (
            "complete"
            if not failed
            and self.report["profiles"]["roster_complete"]
            and "run_error" not in self.report
            else "partial"
        )
        self.report["finished_at"] = utc_now()
        self.checkpoint()
        return self.report


def _versions() -> dict[str, str]:
    versions = {}
    for package in ("nba_api", "curl_cffi", "nba-pbp"):
        try:
            versions[package] = version(package)
        except PackageNotFoundError:
            versions[package] = "not installed"
    return versions
