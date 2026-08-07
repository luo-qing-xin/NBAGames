"""Metadata-free cache validation and atomic output transactions."""

from __future__ import annotations

import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nba_pbp.common.errors import ResponseValidationError, StorageError
from nba_pbp.common.serialization import (
    load_strict_json,
    ordered_columns,
    read_csv_shape,
    serialize_csv,
    serialize_json,
)
from nba_pbp.pbp.fetcher import FetchResult
from nba_pbp.pbp.raw_data import extract_raw_records


API_RESPONSE_FILE = "api_response_raw.json"
PLAY_JSON_FILE = "play_by_play_raw.json"
PLAY_CSV_FILE = "play_by_play_raw.csv"
VIDEO_JSON_FILE = "available_video_raw.json"
VIDEO_CSV_FILE = "available_video_raw.csv"
METADATA_FILE = "fetch_metadata.json"

JSON_TABLE_FILES = {PLAY_JSON_FILE}
CSV_TABLE_FILES = {PLAY_CSV_FILE}
KNOWN_DATA_FILES = {
    API_RESPONSE_FILE,
    PLAY_JSON_FILE,
    PLAY_CSV_FILE,
}
LEGACY_OUTPUT_FILES = {VIDEO_JSON_FILE, VIDEO_CSV_FILE, METADATA_FILE}
RECOVERABLE_FILES = KNOWN_DATA_FILES | LEGACY_OUTPUT_FILES
JOURNAL_FILE = ".nba-pbp-transaction.json"


@dataclass(frozen=True)
class CacheSnapshot:
    """A valid cached API response and its derived play records."""

    raw_response: dict[str, Any]
    play_by_play_records: list[dict[str, Any]]
    valid_outputs: set[str]


class StorageManager:
    """Save and validate one game's output directory."""

    def __init__(self, output_directory: Path) -> None:
        self.output_directory = output_directory

    def recover(self) -> None:
        """Roll back an interrupted transaction, then remove orphan files."""
        self.output_directory.mkdir(parents=True, exist_ok=True)
        journal_path = self.output_directory / JOURNAL_FILE
        if journal_path.exists():
            try:
                journal = load_strict_json(journal_path)
                self._rollback(journal)
            except Exception as exc:  # noqa: BLE001 - recovery must be guarded
                raise StorageError("无法恢复上次未完成的文件事务") from exc
        self._cleanup_orphans()

    def load_cache(self, game_id: str) -> CacheSnapshot | None:
        """Use a structurally valid full API response as the cache base."""
        api_path = self.output_directory / API_RESPONSE_FILE
        if not api_path.is_file():
            return None

        try:
            raw_response = load_strict_json(api_path)
            if not isinstance(raw_response, dict):
                return None
            play_records, _ = extract_raw_records(
                raw_response, game_id
            )
            valid_outputs = {API_RESPONSE_FILE}
            for name in {PLAY_JSON_FILE, PLAY_CSV_FILE}:
                if self._valid_derived_file(
                    name,
                    len(play_records),
                    play_records,
                ):
                    valid_outputs.add(name)

            return CacheSnapshot(
                raw_response=raw_response,
                play_by_play_records=play_records,
                valid_outputs=valid_outputs,
            )
        except (OSError, ValueError, TypeError, ResponseValidationError):
            return None

    def save_fetch(
        self, game_id: str, output_format: str, result: FetchResult
    ) -> list[str]:
        """Save a newly fetched response and requested table views."""
        extract_raw_records(result.raw_response, game_id)
        payloads = self._build_payloads(
            output_format,
            result.raw_response,
            result.play_by_play_records,
            include_api_response=True,
        )
        self._commit(payloads, len(result.play_by_play_records))
        self._remove_legacy_outputs()
        return list(payloads)

    def materialize_cache(
        self, game_id: str, output_format: str, snapshot: CacheSnapshot
    ) -> list[str]:
        """Create missing requested views from the cached full response."""
        requested = _requested_table_files(output_format)
        missing = requested - snapshot.valid_outputs
        all_payloads = self._build_payloads(
            output_format,
            snapshot.raw_response,
            snapshot.play_by_play_records,
            include_api_response=False,
        )
        payloads = {
            name: payload for name, payload in all_payloads.items() if name in missing
        }

        self._commit(payloads, len(snapshot.play_by_play_records))
        self._remove_legacy_outputs()
        return list(payloads)

    def _build_payloads(
        self,
        output_format: str,
        raw_response: dict[str, Any],
        play_records: list[dict[str, Any]],
        *,
        include_api_response: bool,
    ) -> dict[str, bytes]:
        payloads: dict[str, bytes] = {}
        if include_api_response:
            payloads[API_RESPONSE_FILE] = serialize_json(raw_response)
        if output_format in {"json", "both"}:
            payloads[PLAY_JSON_FILE] = serialize_json(play_records)
        if output_format in {"csv", "both"}:
            payloads[PLAY_CSV_FILE] = serialize_csv(play_records)
        return payloads

    def _valid_derived_file(
        self,
        name: str,
        play_count: int,
        play_records: list[dict[str, Any]],
    ) -> bool:
        path = self.output_directory / name
        if not path.is_file():
            return False
        try:
            if name in JSON_TABLE_FILES:
                value = load_strict_json(path)
                return (
                    isinstance(value, list)
                    and len(value) == play_count
                    and path.read_bytes() == serialize_json(play_records)
                )
            if name in CSV_TABLE_FILES:
                header, row_count = read_csv_shape(path)
                return (
                    header == ordered_columns(play_records)
                    and row_count == play_count
                    and path.read_bytes() == serialize_csv(play_records)
                )
        except (OSError, TypeError, ValueError, UnicodeError):
            return False
        return False

    def _commit(
        self,
        data_payloads: dict[str, bytes],
        play_count: int,
    ) -> None:
        if not data_payloads:
            return
        self.output_directory.mkdir(parents=True, exist_ok=True)
        transaction_id = uuid.uuid4().hex
        payloads = dict(data_payloads)
        temporary_paths: dict[str, Path] = {}
        backup_paths: list[Path] = []
        journal_path = self.output_directory / JOURNAL_FILE
        journal_written = False

        try:
            for name, payload in payloads.items():
                temp_path = self.output_directory / (
                    f".nba-pbp-{transaction_id}-{name}.tmp"
                )
                _write_fsynced(temp_path, payload)
                temporary_paths[name] = temp_path
                self._validate_temporary(temp_path, name, play_count)

            entries: list[dict[str, Any]] = []
            for name in payloads:
                target_path = self.output_directory / name
                backup_name: str | None = None
                if target_path.exists():
                    backup_path = self.output_directory / (
                        f".nba-pbp-{transaction_id}-{name}.bak"
                    )
                    shutil.copy2(target_path, backup_path)
                    backup_paths.append(backup_path)
                    backup_name = backup_path.name
                entries.append(
                    {
                        "target": name,
                        "backup": backup_name,
                        "created": not target_path.exists(),
                    }
                )

            journal = {
                "transaction_id": transaction_id,
                "entries": entries,
                "temporary_files": [path.name for path in temporary_paths.values()],
            }
            journal_temp = self.output_directory / (
                f".nba-pbp-{transaction_id}-journal.tmp"
            )
            _write_fsynced(journal_temp, serialize_json(journal))
            os.replace(journal_temp, journal_path)
            journal_written = True

            commit_order = [
                name for name in data_payloads if name != API_RESPONSE_FILE
            ]
            if API_RESPONSE_FILE in data_payloads:
                commit_order.append(API_RESPONSE_FILE)
            for name in commit_order:
                os.replace(
                    temporary_paths[name], self.output_directory / name
                )
            _fsync_directory(self.output_directory)

            journal_path.unlink(missing_ok=True)
            for backup_path in backup_paths:
                backup_path.unlink(missing_ok=True)
        except Exception as exc:  # noqa: BLE001 - every write must roll back
            if journal_written:
                try:
                    journal = load_strict_json(journal_path)
                    self._rollback(journal)
                except Exception:
                    raise StorageError(
                        "保存失败，且自动恢复旧数据未能完成"
                    ) from exc
            for path in temporary_paths.values():
                path.unlink(missing_ok=True)
            for path in backup_paths:
                path.unlink(missing_ok=True)
            journal_path.unlink(missing_ok=True)
            self._cleanup_orphans()
            raise StorageError("无法原子保存抓取结果") from exc

    def _validate_temporary(
        self, path: Path, name: str, play_count: int
    ) -> None:
        if name == API_RESPONSE_FILE:
            if not isinstance(load_strict_json(path), dict):
                raise ValueError("API response JSON is not an object")
            return
        if name in JSON_TABLE_FILES:
            value = load_strict_json(path)
            if not isinstance(value, list) or len(value) != play_count:
                raise ValueError("JSON table row count mismatch")
            return
        if name in CSV_TABLE_FILES:
            header, row_count = read_csv_shape(path)
            if not header or row_count != play_count:
                raise ValueError("CSV table shape mismatch")
            return
        raise ValueError(f"Unknown output file: {name}")

    def _rollback(self, journal: Any) -> None:
        if not isinstance(journal, dict) or not isinstance(
            journal.get("entries"), list
        ):
            raise ValueError("Invalid transaction journal")
        for entry in reversed(journal["entries"]):
            if not isinstance(entry, dict):
                raise ValueError("Invalid transaction entry")
            target_name = str(entry["target"])
            if target_name not in RECOVERABLE_FILES:
                raise ValueError("Invalid transaction target")
            target = self.output_directory / target_name
            backup_name = entry.get("backup")
            if backup_name:
                backup_name = str(backup_name)
                if (
                    Path(backup_name).name != backup_name
                    or not backup_name.startswith(".nba-pbp-")
                    or not backup_name.endswith(".bak")
                ):
                    raise ValueError("Invalid transaction backup")
                backup = self.output_directory / backup_name
                if not backup.is_file():
                    raise ValueError("Missing transaction backup")
                os.replace(backup, target)
            elif entry.get("created"):
                target.unlink(missing_ok=True)
        for name in journal.get("temporary_files", []):
            name = str(name)
            if (
                Path(name).name != name
                or not name.startswith(".nba-pbp-")
                or not name.endswith(".tmp")
            ):
                raise ValueError("Invalid transaction temporary file")
            (self.output_directory / name).unlink(missing_ok=True)
        (self.output_directory / JOURNAL_FILE).unlink(missing_ok=True)
        _fsync_directory(self.output_directory)

    def _cleanup_orphans(self) -> None:
        for pattern in (".nba-pbp-*.tmp", ".nba-pbp-*.bak"):
            for path in self.output_directory.glob(pattern):
                path.unlink(missing_ok=True)

    def _remove_legacy_outputs(self) -> None:
        try:
            for name in LEGACY_OUTPUT_FILES:
                (self.output_directory / name).unlink(missing_ok=True)
        except OSError as exc:
            raise StorageError("无法清理旧版视频或元数据文件") from exc


def _requested_table_files(output_format: str) -> set[str]:
    requested: set[str] = set()
    if output_format in {"json", "both"}:
        requested.update(JSON_TABLE_FILES)
    if output_format in {"csv", "both"}:
        requested.update(CSV_TABLE_FILES)
    return requested


def _write_fsynced(path: Path, payload: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
