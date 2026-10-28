"""Strict JSON serialization preserving raw response structure."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def sanitize_json_value(value: Any) -> Any:
    """Convert values to standard JSON values while preserving structure."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Mapping):
        return {key: sanitize_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize_json_value(item) for item in value]

    item_method = getattr(value, "item", None)
    if callable(item_method):
        try:
            return sanitize_json_value(item_method())
        except (TypeError, ValueError):
            pass
    raise TypeError(f"Unsupported JSON value: {type(value).__name__}")


def serialize_json(value: Any) -> bytes:
    """Serialize as UTF-8 standard JSON without sorting keys."""
    sanitized = sanitize_json_value(value)
    text = json.dumps(
        sanitized,
        ensure_ascii=False,
        allow_nan=False,
        indent=2,
    )
    return (text + "\n").encode("utf-8")


def load_strict_json(path: Path) -> Any:
    """Read JSON while rejecting non-standard numeric constants."""
    return json.loads(
        path.read_text(encoding="utf-8"),
        parse_constant=_reject_json_constant,
    )


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Non-standard JSON constant: {value}")
