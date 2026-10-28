"""Independent atomic JSON files; raw payloads double as validated caches."""

from __future__ import annotations

import hashlib
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nba_game.errors import ResponseValidationError, StorageError
from nba_game.models import Resource
from nba_game.serialization import load_strict_json, serialize_json
from nba_game.validation import inspect_response, result_sets


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, value: Any) -> None:
    try:
        payload = serialize_json(value)
    except (TypeError, ValueError) as exc:
        raise StorageError(f"无法序列化 {path.name}") from exc
    atomic_bytes(path, payload)


def atomic_text(path: Path, text: str) -> None:
    atomic_bytes(path, text.encode("utf-8"))


def atomic_bytes(path: Path, payload: bytes) -> None:
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except (OSError, ValueError, TypeError) as exc:
        raise StorageError(f"无法原子保存 {path.name}") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_manifest(directory: Path, game_id: str) -> dict:
    try:
        value = load_strict_json(directory / "manifest.json")
        if (
            isinstance(value, dict)
            and value.get("game_id") == game_id
            and isinstance(value.get("resources"), dict)
        ):
            value["resources"] = {
                key: entry
                for key, entry in value["resources"].items()
                if isinstance(entry, dict)
            }
            return value
    except (OSError, ValueError, TypeError):
        pass
    return {}


def load_cache(
    path: Path,
    resource: Resource,
    game_id: str,
    person_id: int | None = None,
    *,
    trusted_game_id: bool = False,
) -> tuple[dict, int] | None:
    try:
        raw = load_strict_json(path)
        count = inspect_response(resource, raw, game_id, person_id)
        if resource.root is None and person_id is None and not trusted_game_id:
            echoed = raw.get("parameters", {})
            identified = isinstance(echoed, dict) and echoed.get("GameID") == game_id
            if resource.module == "dunkscoreleaders":
                identified = (
                    bool(raw.get("dunks"))
                    or raw.get("params", {}).get("GameID") == game_id
                )
            for dataset in (
                result_sets(raw).values()
                if resource.module != "dunkscoreleaders"
                else []
            ):
                for key in ("GAME_ID", "gameId"):
                    if key in dataset["headers"] and dataset["rowSet"]:
                        identified = True
            if not identified:
                return None
        return raw, count
    except (OSError, ValueError, TypeError, KeyError, ResponseValidationError):
        return None


def file_time(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()


def import_legacy(directory: Path, legacy: Path, game_id: str) -> None:
    """Copy verified v1 raw files only; never delete source or replace valid v2 files."""
    from nba_game.sources.live import RESOURCES as LIVE_RESOURCES
    from nba_game.sources.stats import PROFILE, RESOURCES

    if not legacy.is_dir() or directory.resolve() == legacy.resolve():
        return
    old = load_manifest(legacy, game_id)
    current = load_manifest(directory, game_id)
    entries = current.setdefault("resources", {})
    candidates = [
        (resource, None, legacy / "raw" / f"{resource.name}.json")
        for resource in (*RESOURCES, *LIVE_RESOURCES)
    ]
    for path in (legacy / "profiles").glob("*.json"):
        if path.stem.isascii() and path.stem.isdigit() and int(path.stem) > 0:
            candidates.append((PROFILE, int(path.stem), path))
    imported = False
    for resource, pid, source in candidates:
        key = resource.key(pid)
        entry = old.get("resources", {}).get(key, {})
        if not isinstance(entry, dict):
            entry = {}
        if not source.is_file() or (
            entry.get("sha256") and entry["sha256"] != file_hash(source)
        ):
            continue
        trusted = (
            bool(entry.get("sha256"))
            and isinstance(entry.get("parameters"), dict)
            and entry.get("parameters", {}).get("GameID") == game_id
        )
        cached = load_cache(source, resource, game_id, pid, trusted_game_id=trusted)
        if cached is None:
            continue
        destination = directory / resource.relative_path(pid)
        existing = entries.get(key, {})
        if (
            destination.is_file()
            and (
                not existing.get("sha256")
                or existing["sha256"] == file_hash(destination)
            )
            and load_cache(
                destination,
                resource,
                game_id,
                pid,
                trusted_game_id=bool(existing.get("sha256"))
                and isinstance(existing.get("parameters"), dict)
                and existing.get("parameters", {}).get("GameID") == game_id,
            )
        ):
            continue
        raw, count = cached
        atomic_json(destination, raw)
        stat = source.stat()
        os.utime(destination, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        entries[key] = {
            **entry,
            "status": entry.get("status", "success" if count else "empty"),
            "row_count": count,
            "source": resource.source,
            "file": str(destination.relative_to(directory)),
            "sha256": file_hash(destination),
            "fetched_at": entry.get("fetched_at", file_time(source)),
            "migration": {
                "source_file": str(source.resolve()),
                "imported_at": utc_now(),
            },
        }
        imported = True
    if imported:
        current.update(schema_version=2, game_id=game_id)
        atomic_json(directory / "manifest.json", current)
