"""
plugin.video.gronkhtv — shared constants and global addon references
"""

from __future__ import annotations

import sys

import xbmc
import xbmcaddon
import xbmcgui

# ---------------------------------------------------------------------------
# Core addon references
# ---------------------------------------------------------------------------

URL = sys.argv[0]
HANDLE = int(sys.argv[1])
ADDON = xbmcaddon.Addon(id=URL[9:-1])
PLUGIN = ADDON.getAddonInfo("name")

# ---------------------------------------------------------------------------
# Network / API
# ---------------------------------------------------------------------------

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
REFERER = "https://gronkh.tv/"
ORIGIN = "https://gronkh.tv"
API_BASE = "https://backend.gronkh.tv/v3/"
TIMEOUT_SECONDS = 30

# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

ADDON_DATA_PATH = "special://profile/addon_data/plugin.video.gronkhtv"

# ---------------------------------------------------------------------------
# Endpoint maps
# ---------------------------------------------------------------------------

BACKENDS: dict[str, str] = {
    # "newest" is intentionally absent — it uses POST /videos/search, not a GET endpoint.
    "hot": "videos/discovery/hot",
    "random": "videos/discovery/random",
    "streams": "promoted/streams",
}
SEARCH_ENDPOINT = "videos/search"
MOST_VIEWED_COUNT = 40

# How many items the search endpoint returns per page (server-side constant).
SEARCH_PAGE_SIZE = 20

# ---------------------------------------------------------------------------
# Twitch
# ---------------------------------------------------------------------------

TWITCH_GQL_URL = "https://gql.twitch.tv/gql"
TWITCH_HLS_URL = "https://usher.ttvnw.net/api/channel/hls/{login}.m3u8"
TWITCH_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"
TWITCH_REFERER = "https://www.twitch.tv/"

# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

CATEGORIES: list[tuple[str, str]] = [
    ("newest", "Die neusten Streams"),
    ("hot", "Achtung heiß!"),
    ("random", "Wahllos ausgewählt"),
    ("most_viewed", "Top g'schaut"),
    ("streams", "Live-Streams"),
    ("search", "Suche"),
]

HTTP_MESSAGES: dict[int, str] = {
    400: "Ungültige Anfrage (400)",
    401: "Nicht autorisiert (401)",
    403: "Zugriff verweigert (403)",
    404: "Nicht gefunden (404)",
    408: "Zeitüberschreitung der Anfrage (408)",
    429: "Zu viele Anfragen (429)",
    500: "Interner Serverfehler (500)",
    502: "Ungültiges Gateway (502)",
    503: "Dienst nicht verfügbar (503)",
    504: "Gateway-Zeitüberschreitung (504)",
}

xbmc.log(f"[{PLUGIN}] Init — handle {HANDLE}", xbmc.LOGINFO)
