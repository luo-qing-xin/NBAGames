"""Shared command-line argument validation."""

from __future__ import annotations

import argparse
import math
import re
from urllib.parse import urlsplit


GAME_ID_PATTERN = re.compile(r"^\d{10}$")
PROXY_SCHEMES = {
    "http",
    "https",
    "socks4",
    "socks4a",
    "socks5",
    "socks5h",
}


def validate_game_id(value: str) -> str:
    """Validate a ten-digit NBA game identifier for argparse."""
    if not GAME_ID_PATTERN.fullmatch(value):
        raise argparse.ArgumentTypeError(
            "比赛 ID 必须恰好由 10 位数字组成，例如 0022300001"
        )
    return value


def validate_timeout(value: str) -> float:
    """Validate a finite, positive request timeout."""
    try:
        timeout = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("超时时间必须是正数") from None
    if not math.isfinite(timeout) or timeout <= 0:
        raise argparse.ArgumentTypeError("超时时间必须是正数")
    return timeout


def validate_proxy(value: str) -> str:
    """Validate a supported proxy URL without echoing credentials."""
    try:
        parsed = urlsplit(value)
        valid_port = parsed.port is not None
    except ValueError:
        valid_port = False
        parsed = None
    if (
        parsed is None
        or parsed.scheme.lower() not in PROXY_SCHEMES
        or not parsed.hostname
        or not valid_port
    ):
        raise argparse.ArgumentTypeError(
            "代理必须是包含主机和端口的 HTTP/HTTPS/SOCKS URL"
        )
    return value
