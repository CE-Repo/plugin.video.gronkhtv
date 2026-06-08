"""
plugin.video.gronkhtv — HTTP session, API helpers, and CDN header utilities
"""

from __future__ import annotations

import json
import socket
from http.cookiejar import CookieJar
from typing import Any, Dict, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus, unquote, urljoin
from urllib.request import (
    HTTPCookieProcessor,
    Request,
    build_opener,
    install_opener,
    urlopen,
)

import xbmc
import xbmcgui

from .constants import (
    API_BASE,
    HTTP_MESSAGES,
    ORIGIN,
    PLUGIN,
    REFERER,
    TIMEOUT_SECONDS,
    TWITCH_REFERER,
    USER_AGENT,
)
from .utils import log

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

COOKIE_JAR = CookieJar()
SESSION_READY = False


def install_cookie_opener() -> None:
    """Install the global urllib opener with the shared add-on cookie jar."""
    opener = build_opener(HTTPCookieProcessor(COOKIE_JAR))
    opener.addheaders = [
        ("User-Agent", USER_AGENT),
        ("Accept", "application/json, text/plain, */*"),
        ("Accept-Encoding", "identity"),
        ("Accept-Charset", "utf-8"),
        ("Referer", REFERER),
        ("Origin", ORIGIN),
    ]
    install_opener(opener)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

def handle_http_error(exc: Exception) -> None:
    """Log and show a Kodi notification for network errors."""
    if isinstance(exc, HTTPError):
        message = HTTP_MESSAGES.get(exc.code, f"HTTP-Fehler {exc.code}")
        log(f"{message}: {exc.url}", xbmc.LOGERROR)
    else:
        reason = getattr(exc, "reason", str(exc))
        message = f"Netzwerkfehler: {reason}"
        log(message, xbmc.LOGERROR)

    xbmcgui.Dialog().notification(
        PLUGIN,
        message,
        xbmcgui.NOTIFICATION_ERROR,
        5000,
    )


# ---------------------------------------------------------------------------
# Low-level request helpers
# ---------------------------------------------------------------------------

def api_url(endpoint: str) -> str:
    """Return an absolute API URL for a relative or absolute endpoint."""
    if endpoint.startswith(("http://", "https://")):
        return endpoint
    return urljoin(API_BASE, endpoint.lstrip("/"))


def request_headers(accept: str = "application/json, text/plain, */*") -> Dict[str, str]:
    """Return the standard request headers expected by gronkh.tv."""
    return {
        "User-Agent": USER_AGENT,
        "Accept": accept,
        "Accept-Encoding": "identity",
        "Accept-Charset": "utf-8",
        "Referer": REFERER,
        "Origin": ORIGIN,
    }


def http_get(
    endpoint: str,
    accept: str = "application/json, text/plain, */*",
    notify: bool = True,
) -> Optional[Tuple[str, str, bytes]]:
    """
    Fetch a relative or absolute endpoint.

    Returns ``(final_url, content_type, body_bytes)`` or ``None`` on error.
    """
    url = api_url(endpoint)
    request = Request(url, headers=request_headers(accept))

    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return (
                response.geturl(),
                response.headers.get("Content-Type", ""),
                response.read(),
            )
    except (HTTPError, URLError, TimeoutError, socket.timeout) as exc:
        if notify:
            handle_http_error(exc)
        else:
            log(f"Ignored bootstrap HTTP error for {url}: {exc}")
        return None


def xsrf_token() -> str:
    """Return the Laravel XSRF token from the cookie jar for POST requests."""
    for cookie in COOKIE_JAR:
        if cookie.name == "XSRF-TOKEN":
            return unquote(cookie.value)
    return ""


def http_post_json(
    endpoint: str,
    payload: Dict[str, Any],
    notify: bool = True,
) -> Optional[Tuple[str, str, bytes]]:
    """POST JSON to the v3 API and return the raw response tuple."""
    ensure_session()

    url = api_url(endpoint)
    headers = request_headers()
    headers["Content-Type"] = "application/json"

    token = xsrf_token()
    if token:
        headers["X-XSRF-TOKEN"] = token

    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return (
                response.geturl(),
                response.headers.get("Content-Type", ""),
                response.read(),
            )
    except (HTTPError, URLError, TimeoutError, socket.timeout) as exc:
        if notify:
            handle_http_error(exc)
        else:
            log(f"Ignored POST HTTP error for {url}: {exc}")
        return None


def parse_json_response(
    result: Optional[Tuple[str, str, bytes]],
    method: str = "GET",
) -> Any:
    """Decode a raw HTTP result tuple as JSON."""
    if result is None:
        return None

    url, _content_type, body = result
    if not body:
        log(f"Empty API {method} response for {url}")
        return None

    try:
        return json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        log(f"JSON parse error for {method} {url}: {exc}", xbmc.LOGERROR)
        return None


# ---------------------------------------------------------------------------
# High-level API calls
# ---------------------------------------------------------------------------

def api_get(endpoint: str, notify: bool = True) -> Any:
    """Fetch *endpoint* from the gronkh.tv v3 API and return parsed JSON."""
    return parse_json_response(http_get(endpoint, notify=notify), "GET")


def api_post_json(endpoint: str, payload: Dict[str, Any]) -> Any:
    """POST JSON to the API and return parsed JSON or ``None``."""
    return parse_json_response(http_post_json(endpoint, payload), "POST")


def ensure_session() -> None:
    """
    Initialise anonymous backend cookies once.

    The web app requests /csrf-cookie and /users/self before discovery calls.
    Bootstrap failures are logged but not fatal.
    """
    global SESSION_READY

    if SESSION_READY:
        return

    try:
        http_get("csrf-cookie", notify=False)
        http_get("users/self", notify=False)
    except (HTTPError, URLError, TimeoutError, socket.timeout, OSError) as exc:
        log(f"Session bootstrap skipped after error: {exc}")

    SESSION_READY = True


# ---------------------------------------------------------------------------
# CDN / playback header helpers
# ---------------------------------------------------------------------------

def cookie_header() -> str:
    """Return cookies from the Python session in Kodi pipe-header format."""
    return "; ".join(f"{cookie.name}={cookie.value}" for cookie in COOKIE_JAR)


def header_pipe(headers: Dict[str, str]) -> str:
    """Build the header string Kodi accepts after the URL pipe."""
    return "&".join(f"{key}={quote_plus(value)}" for key, value in headers.items())


def playback_headers(include_cookie: bool = False) -> str:
    """Build gronkh.tv playback headers in Kodi pipe format."""
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": REFERER,
        "Origin": ORIGIN,
    }

    if include_cookie:
        cookies = cookie_header()
        if cookies:
            headers["Cookie"] = cookies

    return header_pipe(headers)


def twitch_playback_headers() -> str:
    """Build Twitch playback headers in Kodi pipe format."""
    return header_pipe(
        {
            "User-Agent": USER_AGENT,
            "Referer": TWITCH_REFERER,
            "Origin": "https://www.twitch.tv",
        }
    )


def needs_backend_cookies(url: str) -> bool:
    """Return whether a playback URL points to the backend and needs cookies."""
    return "backend.gronkh.tv" in (url or "")


def kodi_url(url: str, include_cookie: bool = False) -> str:
    """Append Kodi pipe headers to a URL."""
    if not url:
        return ""
    if "|" in url:
        return url
    return f"{url}|{playback_headers(include_cookie or needs_backend_cookies(url))}"


def cdn_url(url: str) -> str:
    """Append Kodi header pipe to satisfy CDN/backend Referer/UA checks."""
    return kodi_url(url)
