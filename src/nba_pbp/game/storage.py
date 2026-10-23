"""Independent atomic JSON files; raw payloads double as validated caches."""

from __future__ import annotations

import hashlib
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nba_pbp.common.errors import ResponseValidationError, StorageError
from nba_pbp.common.serialization import load_strict_json, serialize_json
from nba_pbp.game.resources import Resource, inspect_response, result_sets


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, value: Any) -> None:
    temporary = None
    try:
        payload = serialize_json(value)
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
            for dataset in result_sets(raw).values():
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
