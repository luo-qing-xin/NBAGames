"""Persistent caches and atomic outputs for game player information."""

from __future__ import annotations

import os
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nba_pbp.errors import ResponseValidationError, StorageError
from nba_pbp.player_data import (
    SourcePayload,
    build_merged_players,
    extract_inactive_players,
    extract_profile,
    extract_traditional_players,
    flatten_merged_players,
)
from nba_pbp.serialization import (
    load_strict_json,
    serialize_csv,
    serialize_json,
)


TRADITIONAL_RAW_FILE = "box_score_traditional_v3_raw.json"
SUMMARY_RAW_FILE = "box_score_summary_v3_raw.json"
PROFILES_RAW_FILE = "common_player_info_raw.json"
MERGED_JSON_FILE = "game_players.json"
MERGED_CSV_FILE = "game_players.csv"


@dataclass
class ProfileCache:
    """Reusable profile responses plus the latest sanitized failures."""

    responses: dict[str, dict[str, Any]]
    failures: dict[str, str]


class PlayerStorageManager:
    """Load, validate, and safely replace game player data files."""

    def __init__(self, output_directory: Path) -> None:
        self.output_directory = output_directory

    def prepare(self) -> None:
        self.output_directory.mkdir(parents=True, exist_ok=True)
        self._cleanup_temporary_files()

    def load_traditional(self, game_id: str) -> SourcePayload | None:
        path = self.output_directory / TRADITIONAL_RAW_FILE
        try:
            raw = load_strict_json(path)
            if not isinstance(raw, dict):
                return None
            records = extract_traditional_players(raw, game_id)
            return SourcePayload(raw, records)
        except (
            OSError,
            TypeError,
            ValueError,
            ResponseValidationError,
        ):
            return None

    def load_summary(self, game_id: str) -> SourcePayload | None:
        path = self.output_directory / SUMMARY_RAW_FILE
        try:
            raw = load_strict_json(path)
            if not isinstance(raw, dict):
                return None
            records = extract_inactive_players(raw, game_id)
            return SourcePayload(raw, records)
        except (
            OSError,
            TypeError,
            ValueError,
            ResponseValidationError,
        ):
            return None

    def load_profiles(self, game_id: str) -> ProfileCache:
        path = self.output_directory / PROFILES_RAW_FILE
        try:
            value = load_strict_json(path)
            if not isinstance(value, Mapping) or value.get("gameId") != game_id:
                return ProfileCache({}, {})
            raw_responses = value.get("responses")
            raw_failures = value.get("failures", {})
            if not isinstance(raw_responses, Mapping) or not isinstance(
                raw_failures, Mapping
            ):
                return ProfileCache({}, {})

            responses: dict[str, dict[str, Any]] = {}
            for key, raw_response in raw_responses.items():
                if not isinstance(key, str) or not isinstance(raw_response, Mapping):
                    continue
                try:
                    person_id = int(key)
                    extract_profile(raw_response, person_id)
                except (ValueError, TypeError, ResponseValidationError):
                    continue
                responses[key] = dict(raw_response)

            failures = {
                key: message
                for key, message in raw_failures.items()
                if isinstance(key, str) and isinstance(message, str)
            }
            return ProfileCache(responses, failures)
        except (OSError, TypeError, ValueError):
            return ProfileCache({}, {})

    def save_traditional(self, raw_response: dict[str, Any]) -> None:
        self._save(TRADITIONAL_RAW_FILE, serialize_json(raw_response))

    def save_summary(self, raw_response: dict[str, Any]) -> None:
        self._save(SUMMARY_RAW_FILE, serialize_json(raw_response))

    def save_profiles(self, game_id: str, cache: ProfileCache) -> None:
        payload = {
            "gameId": game_id,
            "responses": cache.responses,
            "failures": cache.failures,
        }
        self._save(PROFILES_RAW_FILE, serialize_json(payload))

    def save_merged(
        self,
        game_id: str,
        traditional: SourcePayload,
        summary: SourcePayload,
        profiles: ProfileCache,
    ) -> list[dict[str, Any]]:
        merged = build_merged_players(
            game_id,
            traditional.records,
            summary.records,
            profiles.responses,
            profiles.failures,
        )
        self._save(MERGED_JSON_FILE, serialize_json(merged))
        self._save(
            MERGED_CSV_FILE,
            serialize_csv(flatten_merged_players(merged)),
        )
        return merged

    def _save(self, name: str, payload: bytes) -> None:
        self.output_directory.mkdir(parents=True, exist_ok=True)
        target = self.output_directory / name
        temporary = self.output_directory / (
            f".nba-players-{uuid.uuid4().hex}-{name}.tmp"
        )
        try:
            with temporary.open("wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
            _fsync_directory(self.output_directory)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise StorageError(f"无法原子保存 {name}") from exc

    def _cleanup_temporary_files(self) -> None:
        try:
            for path in self.output_directory.glob(".nba-players-*.tmp"):
                path.unlink(missing_ok=True)
        except OSError as exc:
            raise StorageError(
                "无法清理未完成的球员数据临时文件"
            ) from exc


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
