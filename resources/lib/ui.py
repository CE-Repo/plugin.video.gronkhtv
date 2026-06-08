"""
plugin.video.gronkhtv — Kodi UI helpers: ListItem builders and directory listing
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List, Tuple
from urllib.parse import quote_plus

import xbmc
import xbmcgui
import xbmcplugin

from .api import (
    channel_name,
    chapter_offset,
    chapter_title,
    duration,
    episode,
    find_chapters,
    playlist_endpoint,
    thumbnail,
    video_id,
)
from .api import (
    backend_from_legacy_category,
    category_label,
    get_backend_items,
    get_most_viewed_items,
    search_video_items,
)
from .constants import CATEGORIES, HANDLE
from .http import cdn_url
from .storage import get_resume
from .utils import fmt_time, get_url, remove_emojis, safe_int


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def set_video_tag_defaults(
    item: xbmcgui.ListItem,
    title: str,
    media_type: str = "video",
) -> Any:
    """Set the most common video info fields and return the Kodi video tag."""
    tag = item.getVideoInfoTag()
    tag.setMediaType(media_type)
    tag.setTitle(title)
    return tag


def add_empty_item(label: str) -> None:
    """Add a simple non-playable placeholder item to the current directory."""
    empty = xbmcgui.ListItem(label=label)
    tag = set_video_tag_defaults(empty, empty.getLabel())
    tag.setTitle(empty.getLabel())
    xbmcplugin.addDirectoryItem(HANDLE, "", empty, False)


def finish_directory(succeeded: bool = True) -> None:
    """Apply shared directory defaults before closing a Kodi directory listing."""
    xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_NONE)
    xbmcplugin.endOfDirectory(HANDLE, succeeded=succeeded)


# ---------------------------------------------------------------------------
# Category menu
# ---------------------------------------------------------------------------

def list_categories() -> None:
    xbmcplugin.setPluginCategory(HANDLE, "Gronkh.tv — Streams & Let's Plays")
    xbmcplugin.setContent(HANDLE, "videos")

    for backend, label in CATEGORIES:
        item = xbmcgui.ListItem(label=label)
        tag = set_video_tag_defaults(item, label)
        tag.setGenres(["Let's Plays"])

        url = (
            get_url(action="search")
            if backend == "search"
            else get_url(action="listing", backend=backend)
        )
        xbmcplugin.addDirectoryItem(HANDLE, url, item, True)

    xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_NONE)
    xbmcplugin.endOfDirectory(HANDLE)


# ---------------------------------------------------------------------------
# Video list item builders
# ---------------------------------------------------------------------------

def created_date(created: str) -> str:
    """Return a German date string for API timestamps, or a safe fallback."""
    if not created:
        return ""
    try:
        timestamp = datetime.fromisoformat(created.replace("Z", "+00:00"))
        return timestamp.strftime("%d.%m.%Y")
    except (TypeError, ValueError):
        return created[:10]


def build_chapter_context_menu(
    video: Dict[str, Any],
    chapters: Iterable[Dict[str, Any]],
) -> List[Tuple[str, str]]:
    """Build Kodi context-menu items for direct chapter jumps."""
    ep = episode(video)
    vid = video_id(video)
    pl = playlist_endpoint(video)
    clean_title = remove_emojis(video.get("title") or "Ohne Titel")
    context_items: List[Tuple[str, str]] = []

    for chapter in chapters:
        offset = chapter_offset(chapter)
        title = chapter_title(chapter)
        context_items.append(
            (
                f"[{fmt_time(offset)}] {title}",
                (
                    "RunPlugin(plugin://plugin.video.gronkhtv/"
                    f"?action=jump_to_chapter&episode={quote_plus(str(ep))}"
                    f"&video_id={quote_plus(str(vid))}"
                    f"&playlist={quote_plus(pl)}"
                    f"&title={quote_plus(clean_title)}"
                    f"&chapter_title={quote_plus(title)}"
                    f"&offset={offset})"
                ),
            )
        )

    return context_items


def build_video_plot(
    video: Dict[str, Any],
    date_string: str,
    ep: Any,
    views: int,
    comment_count: int | None,
    context_items: List[Tuple[str, str]],
) -> str:
    """Build a clean multi-line plot/description for one video item."""
    plot_parts: List[str] = []

    if video.get("description"):
        plot_parts.append(str(video["description"]))
    if date_string:
        plot_parts.append(f"Datum: {date_string}")

    plot_parts.append(f"Aufrufe: {views:,}".replace(",", "."))

    if ep:
        plot_parts.append(f"Episode: #{ep}")
    if comment_count:
        plot_parts.append(f"Kommentare: {comment_count:,}".replace(",", "."))
    if context_items:
        plot_parts.append("\n".join(label for label, _cmd in context_items))

    return "\n".join(plot_parts)


def build_video_list_item(video: Dict[str, Any]) -> Tuple[xbmcgui.ListItem, str]:
    """
    Build a fully annotated ListItem for a video dict from the v3 backend.

    Returns ``(item, playback_url)``.
    """
    ep = episode(video)
    vid = video_id(video)
    pl = playlist_endpoint(video)
    chapters = find_chapters(video)
    context_items = build_chapter_context_menu(video, chapters)
    created = video.get("created_at", "")
    date_string = created_date(created)
    title = remove_emojis(video.get("title") or "Ohne Titel")
    owner = channel_name(video)
    views = safe_int(video.get("views"))
    comment_count = safe_int(video.get("comment_count"))

    item = xbmcgui.ListItem(label=title)
    if context_items:
        item.addContextMenuItems(context_items)

    tag = set_video_tag_defaults(item, title)
    tag.setGenres(["Gaming / Reaction / Talk"])
    tag.setDirectors([owner])
    tag.setWriters([owner])
    tag.setDuration(duration(video))
    tag.setCountries(["Deutschland"])
    tag.setPlot(build_video_plot(video, date_string, ep, views, comment_count, context_items))

    try:
        if isinstance(ep, int) or (isinstance(ep, str) and ep.isdigit()):
            tag.setEpisode(int(ep))
    except Exception:
        pass

    if created:
        tag.setDateAdded(created)
        tag.setPremiered(created[:10])
        tag.setFirstAired(created[:10])

    art = thumbnail(video)
    if art:
        item.setArt({"thumb": cdn_url(art), "fanart": cdn_url(art)})

    item.setProperty("IsPlayable", "true")

    return item, get_url(action="play", episode=ep, video_id=vid, playlist=pl)


# ---------------------------------------------------------------------------
# Stream list item builder
# ---------------------------------------------------------------------------

def stream_login(stream: Dict[str, Any]) -> str:
    """Return the Twitch login/name needed for live HLS playback."""
    for key in ("user_login", "login", "channel_login", "slug", "user_name"):
        value = remove_emojis(stream.get(key))
        if value:
            return value.lower().lstrip("@")
    return "gronkh"


def build_stream_list_item(stream: Dict[str, Any]) -> Tuple[xbmcgui.ListItem, str]:
    """Build a playable list item for promoted/live Twitch streams."""
    title = remove_emojis(stream.get("title") or stream.get("user_name") or "Live-Stream")
    user_name = remove_emojis(stream.get("user_name") or stream.get("user_login") or "Gronkh")
    login = stream_login(stream)
    game_name = remove_emojis(stream.get("game_name") or "")
    viewers = safe_int(stream.get("viewer_count"))

    item = xbmcgui.ListItem(label=f"LIVE: {title}")
    tag = set_video_tag_defaults(item, title)
    tag.setGenres([game_name] if game_name else ["Live"])
    tag.setDirectors([user_name])
    tag.setPlot(
        "\n".join(
            part
            for part in (
                f"Kanal: {user_name}",
                f"Spiel/Kategorie: {game_name}" if game_name else "",
                f"Zuschauer: {viewers:,}".replace(",", ".") if viewers else "",
            )
            if part
        )
    )

    thumbnails = (
        stream.get("thumbnail_urls")
        if isinstance(stream.get("thumbnail_urls"), dict)
        else {}
    )
    art = thumbnails.get("lg") or thumbnails.get("md") or thumbnails.get("base") or ""
    if art:
        item.setArt({"thumb": art, "fanart": art})

    item.setProperty("IsPlayable", "true")
    return item, get_url(action="play_live", login=login, title=title)


# ---------------------------------------------------------------------------
# Directory listing functions
# ---------------------------------------------------------------------------

def list_items(backend: str) -> None:
    xbmcplugin.setPluginCategory(HANDLE, category_label(backend))
    xbmcplugin.setContent(HANDLE, "videos")

    if backend == "most_viewed":
        items = get_most_viewed_items()
    elif backend == "streams":
        items = get_backend_items(backend)
    else:
        items = get_backend_items(backend)

    if backend == "streams":
        for stream in items:
            item, url = build_stream_list_item(stream)
            xbmcplugin.addDirectoryItem(HANDLE, url, item, False)
    else:
        for video in items:
            item, url = build_video_list_item(video)
            xbmcplugin.addDirectoryItem(HANDLE, url, item, False)

    if not items:
        add_empty_item("Keine Einträge gefunden")

    finish_directory()


def list_search(query: str = "", page: int = 1) -> None:
    """Ask for a search term if needed and list POST /videos/search results."""
    if not query:
        keyboard = xbmc.Keyboard("", "Gronkh.tv durchsuchen")
        keyboard.doModal()
        if not keyboard.isConfirmed():
            xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
            return
        query = keyboard.getText().strip()

    xbmcplugin.setPluginCategory(HANDLE, f"Suche: {query}" if query else "Suche")
    xbmcplugin.setContent(HANDLE, "videos")

    if not query:
        add_empty_item("Keine Suche eingegeben")
        xbmcplugin.endOfDirectory(HANDLE)
        return

    items = search_video_items(query, page)
    for video in items:
        item, url = build_video_list_item(video)
        xbmcplugin.addDirectoryItem(HANDLE, url, item, False)

    if not items:
        add_empty_item("Keine Suchergebnisse gefunden")

    finish_directory()
