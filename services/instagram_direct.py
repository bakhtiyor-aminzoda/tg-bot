"""Fallback helpers for restricted Instagram reels.

If yt-dlp refuses to download "inappropriate" media even with cookies, we
manually call Instagram's internal JSON endpoints using the same cookie jar and
stream the media ourselves.
"""

from __future__ import annotations

import json
import logging
import re
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import aiohttp

DESKTOP_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
IG_APP_ID = "936619743392459"
SHORTCODE_RE = re.compile(r"/(?:p|reel|tv)/([A-Za-z0-9_-]{5,})")

logger = logging.getLogger(__name__)


class InstagramDirectError(RuntimeError):
    """Raised when the direct Instagram fallback fails."""


def _extract_shortcode(url: str) -> Optional[str]:
    match = SHORTCODE_RE.search(url)
    if match:
        return match.group(1)
    parsed = urlparse(url)
    segments = [segment for segment in parsed.path.split("/") if segment]
    for idx, segment in enumerate(segments):
        if segment in {"p", "reel", "tv"} and idx + 1 < len(segments):
            candidate = segments[idx + 1]
            if candidate:
                return candidate
    return None


def _load_cookies(cookies_path: str) -> Dict[str, str]:
    jar = MozillaCookieJar()
    jar.load(cookies_path, ignore_discard=True, ignore_expires=True)
    cookies: Dict[str, str] = {}
    for cookie in jar:
        if cookie.name and cookie.value:
            cookies[cookie.name] = cookie.value
    return cookies


def _build_headers(cookies: Dict[str, str], shortcode: str) -> Dict[str, str]:
    headers = {
        "User-Agent": DESKTOP_UA,
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "X-IG-App-ID": IG_APP_ID,
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"https://www.instagram.com/reel/{shortcode}/",
        "Origin": "https://www.instagram.com",
    }
    csrf = cookies.get("csrftoken")
    if csrf:
        headers["X-CSRFToken"] = csrf
    return headers


async def download_sensitive_media(url: str, output_dir: Path, cookies_file: str) -> Path:
    """Download an Instagram reel by hitting internal APIs directly."""
    shortcode = _extract_shortcode(url)
    if not shortcode:
        raise InstagramDirectError("Не удалось определить shortcode Instagram")
    if not cookies_file:
        raise InstagramDirectError("Instagram cookies path не указан")
    try:
        cookies = _load_cookies(cookies_file)
    except FileNotFoundError as err:
        raise InstagramDirectError(f"Файл cookies Instagram не найден: {cookies_file}") from err
    if "sessionid" not in cookies:
        raise InstagramDirectError("Instagram cookies отсутствуют sessionid — требуется повторный логин")

    headers = _build_headers(cookies, shortcode)
    timeout = aiohttp.ClientTimeout(total=90)
    output_dir.mkdir(parents=True, exist_ok=True)

    async with aiohttp.ClientSession(headers=headers, cookies=cookies, timeout=timeout) as session:
        payload = await _fetch_media_payload(session, shortcode)
        video_url = _find_best_video_url(payload)
        if not video_url:
            raise InstagramDirectError("Instagram API не вернул ссылку на видео")
        destination = output_dir / f"instagram_{shortcode}.mp4"
        await _download_binary(session, video_url, destination)
        logger.info("Instagram API fallback succeeded: %s", destination)
        return destination


async def _fetch_media_payload(session: aiohttp.ClientSession, shortcode: str) -> Dict[str, Any]:
    endpoints = [
        f"https://www.instagram.com/api/v1/media/shortcode/{shortcode}/info/",
        f"https://www.instagram.com/api/v1/clips/shortcode/{shortcode}/info/",
        f"https://www.instagram.com/reel/{shortcode}/?__a=1&__d=dis",
    ]
    last_error = "unknown"
    for endpoint in endpoints:
        try:
            async with session.get(endpoint) as resp:
                body = await resp.text()
                if resp.status == 200:
                    try:
                        return json.loads(body)
                    except json.JSONDecodeError as err:
                        last_error = f"invalid JSON ({err})"
                        logger.debug("Instagram endpoint %s returned invalid JSON: %s", endpoint, err)
                        continue
                else:
                    last_error = f"HTTP {resp.status}"
                    logger.debug(
                        "Instagram endpoint %s failed with %s: %.200s",
                        endpoint,
                        resp.status,
                        body,
                    )
        except Exception as err:  # pragma: no cover - network dependent
            last_error = str(err)
            logger.debug("Instagram endpoint %s request failed: %s", endpoint, err)
    raise InstagramDirectError(f"Не удалось получить данные Instagram: {last_error}")


def _find_best_video_url(payload: Any) -> Optional[str]:
    best_url: Optional[str] = None
    best_width = -1

    def _walk(node: Any) -> None:
        nonlocal best_url, best_width
        if isinstance(node, dict):
            versions = node.get("video_versions")
            if isinstance(versions, list):
                for version in versions:
                    if not isinstance(version, dict):
                        continue
                    url = version.get("url")
                    width = version.get("width") or 0
                    if url and width > best_width:
                        best_url = url
                        best_width = width
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(payload)
    return best_url


async def _download_binary(
    session: aiohttp.ClientSession,
    video_url: str,
    destination: Path,
) -> None:
    tmp_path = destination.with_suffix(destination.suffix + ".part")
    async with session.get(
        video_url,
        headers={"Referer": "https://www.instagram.com/", "User-Agent": DESKTOP_UA},
    ) as resp:
        if resp.status != 200:
            body = await resp.text()
            raise InstagramDirectError(
                f"Instagram CDN вернул {resp.status}: {body[:200]}"
            )
        with tmp_path.open("wb") as fh:
            async for chunk in resp.content.iter_chunked(65536):
                fh.write(chunk)
    tmp_path.replace(destination)

```}