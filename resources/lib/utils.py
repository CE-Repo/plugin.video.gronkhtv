"""
plugin.video.gronkhtv — generic utility helpers
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlencode

import xbmc

from .constants import PLUGIN, URL


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def log(message: str, level: int = xbmc.LOGDEBUG) -> None:
    """Write a namespaced message to Kodi's log."""
    xbmc.log(f"[{PLUGIN}] {message}", level)


# ---------------------------------------------------------------------------
# Safe type conversions
# ---------------------------------------------------------------------------

def safe_int(value: Any, default: int = 0) -> int:
    """Convert unknown API data to int without raising."""
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default


def safe_float(value: Any, default: float = 0.0) -> float:
    """Convert unknown API data to float without raising."""
    try:
        return float(value or default)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

def get_url(**kwargs: Any) -> str:
    """Build an add-on callback URL with URL-encoded query parameters."""
    return f"{URL}?{urlencode(kwargs)}"


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def fmt_time(seconds: float) -> str:
    """Format a second offset as H:MM:SS."""
    total_seconds = safe_int(seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"


def remove_emojis(text: Any) -> str:
    """Remove emojis and common emoji variation/joiner characters from text."""
    if not text:
        return ""

    cleaned = re.sub(
        "["
        "\U0001F1E0-\U0001F1FF"
        "\U0001F300-\U0001F5FF"
        "\U0001F600-\U0001F64F"
        "\U0001F680-\U0001F6FF"
        "\U0001F700-\U0001F77F"
        "\U0001F780-\U0001F7FF"
        "\U0001F800-\U0001F8FF"
        "\U0001F900-\U0001F9FF"
        "\U0001FA00-\U0001FAFF"
        "\U00002700-\U000027BF"
        "\U00002600-\U000026FF"
        "]+",
        "",
        str(text),
        flags=re.UNICODE,
    )
    cleaned = re.sub(r"[\u200d\ufe0e\ufe0f]+", "", cleaned)
    return re.sub(r"\s{2,}", " ", cleaned).strip()
