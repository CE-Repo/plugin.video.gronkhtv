"""
plugin.video.gronkhtv — resume-point persistence
"""

from __future__ import annotations

from typing import Any

import xbmcvfs

from .constants import ADDON_DATA_PATH
from .utils import safe_float


def _resume_path(episode_key: Any, folder: str) -> str:
    return f"{ADDON_DATA_PATH}/{folder}/{episode_key}.txt"


def get_resume(episode_key: Any, folder: str) -> float:
    """Read a stored resume position; returns 0.0 if not found."""
    if episode_key is None:
        return 0.0

    try:
        with xbmcvfs.File(_resume_path(episode_key, folder)) as file_obj:
            raw = file_obj.read()
            return safe_float(raw)
    except Exception:
        return 0.0


def save_resume(episode_key: Any, position: float, folder: str) -> None:
    """Persist a resume position for the given episode key."""
    if episode_key is None:
        return

    directory = xbmcvfs.translatePath(f"{ADDON_DATA_PATH}/{folder}/")
    if not xbmcvfs.exists(directory):
        xbmcvfs.mkdirs(directory)

    with xbmcvfs.File(f"{directory}{episode_key}.txt", "w") as file_obj:
        file_obj.write(str(position))
