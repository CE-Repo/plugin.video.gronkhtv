"""
plugin.video.gronkhtv — playback: VOD, live Twitch, and chapter jump
"""

from __future__ import annotations

import json
import random
import socket
from typing import Any, Dict, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import xbmc
import xbmcgui
import xbmcplugin

from .constants import (
    HANDLE,
    PLUGIN,
    TIMEOUT_SECONDS,
    TWITCH_CLIENT_ID,
    TWITCH_GQL_URL,
    TWITCH_HLS_URL,
    TWITCH_REFERER,
    USER_AGENT,
)
from .http import handle_http_error, playback_headers, twitch_playback_headers
from .playlist import get_playlist_url
from .storage import get_resume
from .utils import log, remove_emojis, safe_float, safe_int


# ---------------------------------------------------------------------------
# HLS ListItem helper
# ---------------------------------------------------------------------------

def set_hls_listitem_properties(
    list_item: xbmcgui.ListItem,
    url: str,
    header_string: Optional[str] = None,
) -> None:
    """Tell Kodi/InputStream Adaptive this is HLS and which headers to use."""
    if header_string is None:
        header_string = playback_headers(include_cookie=False)

    properties = {
        "IsPlayable": "true",
        "inputstream.adaptive.manifest_type": "hls",
        "inputstream.adaptive.stream_headers": header_string,
        "inputstream.adaptive.manifest_headers": header_string,
    }

    for key, value in properties.items():
        try:
            list_item.setProperty(key, value)
        except Exception:
            pass

    try:
        list_item.setMimeType("application/vnd.apple.mpegurl")
    except Exception:
        pass

    try:
        list_item.setContentLookup(False)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Twitch
# ---------------------------------------------------------------------------

def twitch_gql(payload: Dict[str, Any]) -> Any:
    """POST one GraphQL request to Twitch and return parsed JSON."""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Accept-Encoding": "identity",
        "Accept-Charset": "utf-8",
        "Client-ID": TWITCH_CLIENT_ID,
        "Content-Type": "application/json",
        "Referer": TWITCH_REFERER,
        "Origin": "https://www.twitch.tv",
    }
    request = Request(
        TWITCH_GQL_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            body = response.read()
            return json.loads(body.decode("utf-8")) if body else None
    except (HTTPError, URLError, TimeoutError, socket.timeout, json.JSONDecodeError) as exc:
        handle_http_error(exc)
        return None


def twitch_access_token(login: str) -> Optional[Tuple[str, str]]:
    """Return Twitch playback token/signature for one live channel."""
    query = (
        "query PlaybackAccessToken($login: String!, $isLive: Boolean!, "
        "$vodID: ID!, $isVod: Boolean!, $playerType: String!) { "
        "streamPlaybackAccessToken(channelName: $login, params: {"
        "platform: \"web\", playerBackend: \"mediaplayer\", "
        "playerType: $playerType}) @include(if: $isLive) { value signature } "
        "videoPlaybackAccessToken(id: $vodID, params: {"
        "platform: \"web\", playerBackend: \"mediaplayer\", "
        "playerType: $playerType}) @include(if: $isVod) { value signature } }"
    )
    data = twitch_gql(
        {
            "operationName": "PlaybackAccessToken",
            "variables": {
                "isLive": True,
                "login": login,
                "isVod": False,
                "vodID": "",
                "playerType": "site",
            },
            "query": query,
        }
    )

    token_data = (
        data.get("data", {}).get("streamPlaybackAccessToken")
        if isinstance(data, dict)
        else None
    )
    if not isinstance(token_data, dict):
        log(f"No Twitch playback token for login={login!r}", xbmc.LOGERROR)
        return None

    value = token_data.get("value")
    signature = token_data.get("signature")
    if not value or not signature:
        log(f"Incomplete Twitch playback token for login={login!r}", xbmc.LOGERROR)
        return None

    return str(value), str(signature)


def get_live_stream_url(login: str) -> Optional[str]:
    """Resolve a Twitch login to a playable live HLS URL."""
    login = (login or "").strip().lower().lstrip("@")
    if not login:
        log("No Twitch login supplied for live stream", xbmc.LOGERROR)
        return None

    token = twitch_access_token(login)
    if token is None:
        return None

    token_value, signature = token
    query = urlencode(
        {
            "allow_audio_only": "true",
            "allow_source": "true",
            "cdm": "wv",
            "client_id": TWITCH_CLIENT_ID,
            "fast_bread": "false",
            "p": str(random.randint(1000000, 9999999)),
            "player": "twitchweb",
            "playlist_include_framerate": "true",
            "reassignments_supported": "true",
            "sig": signature,
            "supported_codecs": "avc1",
            "token": token_value,
            "type": "any",
        }
    )
    return f"{TWITCH_HLS_URL.format(login=login)}?{query}|{twitch_playback_headers()}"


# ---------------------------------------------------------------------------
# Play actions
# ---------------------------------------------------------------------------

def play_live_stream(login: str, title: str = "") -> None:
    """Resolve and play one live Twitch stream."""
    url = get_live_stream_url(login)
    if not url:
        xbmcgui.Dialog().notification(
            PLUGIN,
            "Live-Stream konnte nicht aufgelöst werden",
            xbmcgui.NOTIFICATION_ERROR,
            5000,
        )
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        return

    display_title = remove_emojis(title) or f"Live: {login}"
    list_item = xbmcgui.ListItem(label=display_title, path=url)
    try:
        from .ui import set_video_tag_defaults
        tag = set_video_tag_defaults(list_item, display_title)
        tag.setGenres(["Live"])
    except Exception:
        try:
            list_item.setInfo("video", {"title": display_title, "mediatype": "video"})
        except Exception:
            pass

    set_hls_listitem_properties(list_item, url, twitch_playback_headers())
    xbmcplugin.setResolvedUrl(HANDLE, True, list_item)


def play_video(
    playlist_endpoint_: str,
    episode_: Any,
    video_id_: str = "",
) -> None:
    """Resolve and play one VOD."""
    url = get_playlist_url(playlist_endpoint_, video_id_, str(episode_ or ""))
    if not url:
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        return

    list_item = xbmcgui.ListItem(path=url)
    try:
        list_item.setPath(url)
    except Exception:
        pass
    set_hls_listitem_properties(list_item, url)

    resume_key = episode_ or video_id_
    resume = get_resume(resume_key, "resume_points")
    total = get_resume(resume_key, "total_times")
    if resume and total and resume < total * 0.95:
        list_item.setInfo(
            "video",
            {
                "resumetime": safe_int(resume),
                "totaltime": safe_int(total),
            },
        )

    xbmcplugin.setResolvedUrl(HANDLE, True, list_item)


def jump_to_chapter(params: Dict[str, str]) -> None:
    """Start playback at the given chapter offset, seeking if already playing."""
    ep = params.get("episode", "")
    vid = params.get("video_id", "")
    pl = params.get("playlist", "")
    title = remove_emojis(params.get("title") or "Ohne Titel")
    selected_chapter_title = remove_emojis(params.get("chapter_title") or "")
    display_title = title if not selected_chapter_title else f"{title} — {selected_chapter_title}"
    offset = safe_float(params.get("offset"))
    player = xbmc.Player()
    monitor = xbmc.Monitor()

    if not player.isPlayingVideo():
        url = get_playlist_url(pl, vid, ep)
        if url is None:
            return

        list_item = xbmcgui.ListItem(label=display_title, path=url)
        try:
            list_item.setLabel(display_title)
            list_item.setLabel2(selected_chapter_title)
        except Exception:
            pass

        try:
            from .ui import set_video_tag_defaults
            tag = set_video_tag_defaults(list_item, display_title)
            tag.setGenres(["Gaming / Reaction / Talk"])
        except Exception:
            try:
                list_item.setInfo("video", {"title": display_title, "mediatype": "video"})
            except Exception:
                pass

        set_hls_listitem_properties(list_item, url)
        player.play(url, list_item)

        for _ in range(100):
            if player.isPlayingVideo() or monitor.abortRequested():
                break
            xbmc.sleep(100)

    if player.isPlayingVideo():
        player.seekTime(offset)
