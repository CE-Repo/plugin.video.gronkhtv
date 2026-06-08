"""
plugin.video.gronkhtv — playlist URL resolution and M3U8 handling
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional, Tuple

import xbmc
import xbmcvfs

from .http import api_url, ensure_session, http_get, kodi_url
from .utils import log, safe_float, safe_int


# ---------------------------------------------------------------------------
# JSON playlist extraction
# ---------------------------------------------------------------------------

def extract_playlist_from_json(data: Any) -> Optional[str]:
    """Return a playlist URL from common JSON response shapes."""
    if isinstance(data, dict):
        for key in ("playlist_url", "playlist", "url", "src", "hls"):
            value = data.get(key)
            if isinstance(value, str) and value:
                return value

        nested = data.get("data")
        if nested is not data:
            value = extract_playlist_from_json(nested)
            if value:
                return value

    if isinstance(data, list):
        for item in data:
            value = extract_playlist_from_json(item)
            if value:
                return value

    return None


# ---------------------------------------------------------------------------
# M3U8 rewriting
# ---------------------------------------------------------------------------

def m3u8_kodi_uri(uri: str, base_url: str) -> str:
    """
    Resolve one playlist URI for a standards-compliant local M3U8.

    Do not append Kodi pipe headers inside a playlist — FFmpeg/InputStream can
    treat the pipe suffix as part of nested HLS URLs, causing CDN 404s.
    Headers are passed on the ListItem instead.
    """
    uri = (uri or "").strip()
    if not uri or uri.startswith("data:"):
        return uri
    if "|" in uri:
        uri = uri.split("|", 1)[0]
    return _urljoin(base_url, uri)


def _urljoin(base: str, url: str) -> str:
    from urllib.parse import urljoin
    return urljoin(base, url)


def rewrite_m3u8_for_kodi(text: str, base_url: str) -> str:
    """Make relative M3U8 URLs absolute and playable by Kodi."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    rewritten: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            rewritten.append(line)
            continue

        if stripped.startswith("#"):
            # EXT-X-KEY and EXT-X-MAP can contain URI="..." attributes.
            rewritten.append(
                re.sub(
                    r'(URI=)(["\'])(.*?)(\2)',
                    lambda m: (
                        f"{m.group(1)}{m.group(2)}"
                        f"{m3u8_kodi_uri(m.group(3), base_url)}"
                        f"{m.group(2)}"
                    ),
                    line,
                )
            )
            continue

        rewritten.append(m3u8_kodi_uri(stripped, base_url))

    return "\n".join(rewritten)


# ---------------------------------------------------------------------------
# HLS variant selection
# ---------------------------------------------------------------------------

def parse_stream_inf_attrs(line: str) -> Dict[str, str]:
    """Parse attributes from an #EXT-X-STREAM-INF line."""
    if ":" not in line:
        return {}

    raw_attrs = line.split(":", 1)[1]
    attributes: Dict[str, str] = {}

    for key, value in re.findall(r'([A-Z0-9-]+)=((?:"[^"]*")|[^,]*)', raw_attrs):
        value = value.strip()
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        attributes[key] = value

    return attributes


def variant_score(attrs: Dict[str, str]) -> Tuple[int, int, float, int]:
    """
    Return a sortable quality score for one HLS variant.

    Ordered by: height → width → framerate → bandwidth.
    """
    width = 0
    height = 0
    resolution = attrs.get("RESOLUTION", "") or ""
    match = re.match(r"(\d+)x(\d+)", resolution)
    if match:
        width = safe_int(match.group(1))
        height = safe_int(match.group(2))

    frame_rate = safe_float(attrs.get("FRAME-RATE"))
    bandwidth = safe_int(attrs.get("AVERAGE-BANDWIDTH") or attrs.get("BANDWIDTH"))

    return height, width, frame_rate, bandwidth


def select_best_variant_from_master(text: str, base_url: str) -> Optional[str]:
    """
    Return the best available variant URL from a master M3U8.

    Resolving the variant ourselves avoids an extra master-playlist hop and
    always picks the highest available quality/fps/bitrate.
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    best_url: Optional[str] = None
    best_score: Tuple[int, int, float, int] = (-1, -1, -1.0, -1)
    pending_attrs: Optional[Dict[str, str]] = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        if stripped.startswith("#EXT-X-STREAM-INF"):
            pending_attrs = parse_stream_inf_attrs(stripped)
            continue

        if pending_attrs is None:
            continue
        if stripped.startswith("#"):
            continue

        absolute_url = m3u8_kodi_uri(stripped, base_url)
        score = variant_score(pending_attrs)
        if absolute_url and score >= best_score:
            best_score = score
            best_url = absolute_url
        pending_attrs = None

    if best_url:
        log(f"Selected HLS variant score={best_score}: {best_url}")
    return best_url


# ---------------------------------------------------------------------------
# Temp playlist writing
# ---------------------------------------------------------------------------

def write_temp_m3u8(
    text: str,
    base_url: str,
    video_id_: str = "",
    episode_: str = "",
) -> Optional[str]:
    """Write an API-returned playlist body to a local .m3u8 file for Kodi."""
    try:
        safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(video_id_ or episode_ or "playlist"))
        temp_dir = xbmcvfs.translatePath("special://temp/").rstrip("/\\") + "/"
        if not xbmcvfs.exists(temp_dir):
            xbmcvfs.mkdirs(temp_dir)

        path = f"{temp_dir}plugin.video.gronkhtv_{safe_id}.m3u8"
        with xbmcvfs.File(path, "w") as file_obj:
            file_obj.write(rewrite_m3u8_for_kodi(text, base_url))

        log(f"Wrote resolved HLS playlist to {path}")
        return path
    except Exception as exc:
        log(f"Could not write temp playlist: {exc}", xbmc.LOGERROR)
        return None


# ---------------------------------------------------------------------------
# Main playlist resolver
# ---------------------------------------------------------------------------

def is_backend_playlist_url(url: str) -> bool:
    return bool(url and "/playlist" in url and "backend.gronkh.tv" in url)


def get_playlist_url(
    playlist_endpoint_: str = "",
    video_id_: str = "",
    episode_: str = "",
) -> Optional[str]:
    """
    Resolve a v3 video playlist endpoint to something Kodi can play.

    Discovery items contain ``urls.playlist``, e.g.
    ``https://backend.gronkh.tv/v3/videos/<uuid>/playlist``.  The endpoint may
    return JSON, redirect to a CDN URL, return a plain URL, or return an M3U8
    body directly.
    """
    ensure_session()

    endpoint = playlist_endpoint_ or ""
    if not endpoint and video_id_:
        endpoint = f"videos/{video_id_}/playlist"
    if not endpoint and episode_:
        # Legacy fallback for old saved/context URLs.
        endpoint = f"video/playlist?episode={episode_}"

    if not endpoint:
        log("No playlist endpoint available", xbmc.LOGERROR)
        return None

    requested_url = api_url(endpoint)
    result = http_get(
        requested_url,
        accept=(
            "application/vnd.apple.mpegurl, application/x-mpegURL, "
            "application/json, text/plain, */*"
        ),
    )
    if result is None:
        return None

    final_url, content_type, body = result
    text = body.decode("utf-8", "replace").strip() if body else ""
    content_type_lower = (content_type or "").lower()

    # JSON response containing a playlist URL
    if "json" in content_type_lower or text.startswith(("{", "[")):
        try:
            raw_url = extract_playlist_from_json(json.loads(text))
        except json.JSONDecodeError:
            raw_url = None

        if raw_url:
            same_as_request = raw_url.rstrip("/") == requested_url.rstrip("/")
            if is_backend_playlist_url(raw_url) and not same_as_request:
                return get_playlist_url(raw_url, video_id_, episode_)
            return kodi_url(raw_url)

    # Plain URL in the response body
    if text.startswith(("http://", "https://")):
        same_as_request = text.rstrip("/") == requested_url.rstrip("/")
        if is_backend_playlist_url(text) and not same_as_request:
            return get_playlist_url(text, video_id_, episode_)
        return kodi_url(text)

    # Direct M3U8 body
    if "#EXTM3U" in text or "mpegurl" in content_type_lower or final_url.endswith(".m3u8"):
        variant = select_best_variant_from_master(text, final_url or requested_url)
        if variant:
            log(f"Resolved best HLS variant: {variant}")
            return kodi_url(variant)

        local = write_temp_m3u8(text, final_url or requested_url, video_id_, episode_)
        if local:
            return local
        return kodi_url(final_url or requested_url)

    # Redirect to a CDN URL
    if final_url != requested_url and (".m3u8" in final_url or "cdn" in final_url):
        return kodi_url(final_url)

    log(
        f"Could not resolve playlist response from {requested_url}; "
        f"content-type={content_type}",
        xbmc.LOGERROR,
    )
    return None
