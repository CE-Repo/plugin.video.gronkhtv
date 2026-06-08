"""
plugin.video.gronkhtv — API response normalisation and data accessors
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .constants import BACKENDS, MOST_VIEWED_COUNT, SEARCH_ENDPOINT
from .http import api_get, api_post_json, ensure_session
from .utils import log, remove_emojis, safe_float, safe_int


# ---------------------------------------------------------------------------
# Response normalisation
# ---------------------------------------------------------------------------

def items_from_response(data: Any) -> List[Dict[str, Any]]:
    """Normalise v1/v2/v3-ish API response shapes to a plain list."""
    if data is None:
        return []
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if not isinstance(data, dict):
        return []

    data_items = data.get("data")
    if isinstance(data_items, list):
        return [item for item in data_items if isinstance(item, dict)]

    discovery = data.get("discovery")
    if isinstance(discovery, dict) and isinstance(discovery.get("videos"), list):
        return [item for item in discovery["videos"] if isinstance(item, dict)]

    results = data.get("results")
    if isinstance(results, dict) and isinstance(results.get("videos"), list):
        return [item for item in results["videos"] if isinstance(item, dict)]

    return []


# ---------------------------------------------------------------------------
# Video field accessors
# ---------------------------------------------------------------------------

def video_id(video: Dict[str, Any]) -> str:
    return str(video.get("id") or "")


def episode(video: Dict[str, Any]) -> Any:
    value = video.get("episode")
    return video_id(video) if value is None else value


def duration(video: Dict[str, Any]) -> int:
    meta = video.get("meta") if isinstance(video.get("meta"), dict) else {}
    return safe_int(video.get("video_length") or meta.get("duration"))


def thumbnail(video: Dict[str, Any]) -> str:
    urls = video.get("urls") if isinstance(video.get("urls"), dict) else {}
    return urls.get("thumbnail") or video.get("preview_url") or ""


def playlist_endpoint(video: Dict[str, Any]) -> str:
    urls = video.get("urls") if isinstance(video.get("urls"), dict) else {}
    return urls.get("playlist") or ""


def channel_name(video: Dict[str, Any]) -> str:
    channel = video.get("channel") if isinstance(video.get("channel"), dict) else {}
    return remove_emojis(channel.get("displayname") or channel.get("login") or "Gronkh")


# ---------------------------------------------------------------------------
# Chapter helpers
# ---------------------------------------------------------------------------

def chapter_offset(chapter: Dict[str, Any]) -> float:
    return safe_float(chapter.get("offset") or chapter.get("start_offset"))


def chapter_title(chapter: Dict[str, Any]) -> str:
    title = remove_emojis(chapter.get("title"))
    if title:
        return title
    category = chapter.get("category") if isinstance(chapter.get("category"), dict) else {}
    return remove_emojis(category.get("title") or "Kapitel")


def find_chapters(data: Any) -> List[Dict[str, Any]]:
    """
    Find a chapter list in common API response shapes.

    Accepts wrapped objects like ``{"data": {"chapters": [...]}}`` and raw
    chapter lists from endpoints like ``/videos/<id>/chapters``.
    """
    if isinstance(data, list):
        dict_items = [item for item in data if isinstance(item, dict)]
        if not dict_items:
            return []

        looks_like_chapters = any(
            "offset" in item
            or "start_offset" in item
            or "title" in item
            or "category" in item
            for item in dict_items
        )
        if looks_like_chapters:
            return dict_items

        for item in dict_items:
            chapters = find_chapters(item)
            if chapters:
                return chapters
        return []

    if not isinstance(data, dict):
        return []

    chapters = data.get("chapters")
    if isinstance(chapters, list):
        return [item for item in chapters if isinstance(item, dict)]

    for key in ("data", "video", "stream", "item", "result"):
        nested = data.get(key)
        if nested is not data:
            chapters = find_chapters(nested)
            if chapters:
                return chapters

    return []


def get_video_chapters(video: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return chapters from a video item or lazily fetch from detail endpoints."""
    chapters = find_chapters(video)
    if chapters:
        return chapters

    vid = video_id(video)
    ep = episode(video)
    candidates: List[str] = []

    if vid:
        candidates.extend((f"videos/{vid}/chapters", f"videos/{vid}"))
    if ep:
        candidates.extend((f"streams/{ep}", f"videos/episode/{ep}"))

    seen: set[str] = set()
    for endpoint in candidates:
        if not endpoint or endpoint in seen:
            continue
        seen.add(endpoint)
        data = api_get(endpoint, notify=False)
        chapters = find_chapters(data)
        if chapters:
            log(f"Loaded {len(chapters)} chapters from {endpoint}")
            return chapters

    log(f"No chapters found for video_id={vid!r}, episode={ep!r}")
    return []


# ---------------------------------------------------------------------------
# Category / backend helpers
# ---------------------------------------------------------------------------

def category_label(backend: str) -> str:
    from .constants import CATEGORIES
    for key, label in CATEGORIES:
        if key == backend:
            return label
    return backend


def backend_from_legacy_category(category: str) -> str:
    """Keep old plugin URLs working when they still pass the category label."""
    from .constants import CATEGORIES
    for key, label in CATEGORIES:
        if label == category:
            return key
    return "newest"


# ---------------------------------------------------------------------------
# Backend data fetching
# ---------------------------------------------------------------------------

def get_backend_items(backend: str) -> List[Dict[str, Any]]:
    endpoint = BACKENDS.get(backend, BACKENDS["newest"])
    return items_from_response(api_get(endpoint))


def search_video_items(query: str, page: int = 1) -> List[Dict[str, Any]]:
    """Search videos via the POST endpoint seen in the HAR file."""
    payload = {
        "query": query,
        "page": safe_int(page, 1),
        "order": "created_at",
        "dir": "desc",
    }
    return items_from_response(api_post_json(SEARCH_ENDPOINT, payload))


def get_most_viewed_items() -> List[Dict[str, Any]]:
    """
    Fetch the top ``MOST_VIEWED_COUNT`` videos ordered by view count.

    The search endpoint returns 20 items per page, so we request page 1 and
    page 2 in sequence and return only the first ``MOST_VIEWED_COUNT`` items.
    The payload mirrors what the gronkh.tv web frontend sends when the user
    sorts the search results by views (``order=views&dir=desc``).
    """
    payload_base: Dict[str, Any] = {"order": "views", "dir": "desc"}
    collected: List[Dict[str, Any]] = []

    for page in range(1, 3):  # pages 1 and 2 → up to 40 candidates
        if len(collected) >= MOST_VIEWED_COUNT:
            break
        payload = {**payload_base, "page": page}
        data = api_post_json(SEARCH_ENDPOINT, payload)
        items = items_from_response(data)
        if not items:
            break
        collected.extend(items)

    log(f"get_most_viewed_items: fetched {len(collected)} items, returning {MOST_VIEWED_COUNT}")
    return collected[:MOST_VIEWED_COUNT]
