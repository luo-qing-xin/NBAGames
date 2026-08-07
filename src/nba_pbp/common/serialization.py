"""Shared strict JSON and view-only CSV serialization helpers."""

from __future__ import annotations

import csv
import io
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
        return {
            key: sanitize_json_value(item) for key, item in value.items()
        }
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


def serialize_csv(records: list[dict[str, Any]]) -> bytes:
    """Serialize records to an UTF-8 CSV with BOM and stable column order."""
    columns = ordered_columns(records)
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=columns,
        extrasaction="raise",
        lineterminator="\n",
    )
    writer.writeheader()
    for record in records:
        writer.writerow(
            {column: _csv_cell(record.get(column)) for column in columns}
        )
    return output.getvalue().encode("utf-8-sig")


def ordered_columns(records: list[dict[str, Any]]) -> list[str]:
    """Return keys in first-seen order across all records."""
    columns: list[str] = []
    seen: set[str] = set()
    for record in records:
        for key in record:
            if key not in seen:
                seen.add(key)
                columns.append(key)
    return columns


def read_csv_shape(path: Path) -> tuple[list[str], int]:
    """Return a CSV header and data row count."""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            return [], 0
        return header, sum(1 for _ in reader)


def _csv_cell(value: Any) -> str:
    sanitized = sanitize_json_value(value)
    if sanitized is None:
        return ""
    if isinstance(sanitized, str):
        return sanitized
    if isinstance(sanitized, bool):
        return "true" if sanitized else "false"
    if isinstance(sanitized, (dict, list)):
        return json.dumps(
            sanitized,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
    return str(sanitized)


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Non-standard JSON constant: {value}")
