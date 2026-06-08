"""
plugin.video.gronkhtv — Kodi plugin for gronkh.tv
Author: jamal2362
License: MIT License
Copyright: (c) 2026 U3knOwn
"""

from __future__ import annotations

import sys
from urllib.parse import parse_qsl

from resources.lib.api import backend_from_legacy_category
from resources.lib.http import install_cookie_opener
from resources.lib.player import jump_to_chapter, play_live_stream, play_video
from resources.lib.ui import list_categories, list_items, list_search
from resources.lib.utils import log, safe_int

import xbmc


def router(param_string: str) -> None:
    """Dispatch the plugin call to the correct handler."""
    params = dict(parse_qsl(param_string))
    if not params:
        list_categories()
        return

    action = params.get("action", "")

    if action == "listing":
        backend = params.get("backend") or backend_from_legacy_category(
            params.get("category", "")
        )
        list_items(backend)

    elif action == "search":
        list_search(params.get("query", ""), safe_int(params.get("page"), 1))

    elif action == "play":
        play_video(
            params.get("playlist", ""),
            params.get("episode", ""),
            params.get("video_id", ""),
        )

    elif action == "play_live":
        play_live_stream(params.get("login", ""), params.get("title", ""))

    elif action == "jump_to_chapter":
        jump_to_chapter(params)

    else:
        log(f"Unknown action: {action!r}", xbmc.LOGWARNING)


if __name__ == "__main__":
    install_cookie_opener()
    router(sys.argv[2][1:])
