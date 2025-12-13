"""UX helpers for status texts, localization, and inline markups."""

from __future__ import annotations

import time
from typing import Awaitable, Callable, Optional, TYPE_CHECKING

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .i18n import DEFAULT_LOCALE, translate

if TYPE_CHECKING:  # pragma: no cover - type-checking only
    from utils.downloader import DownloadProgress

BOT_LINK = "https://t.me/MediaBanditbot"
SHARE_LINK = (
    "https://t.me/share/url?url=https://t.me/MediaBanditbot&text=%F0%9F%8E%A5%20"
    "%D0%9F%D0%BE%D0%BF%D1%80%D0%BE%D0%B1%D1%83%D0%B9%20Media%20Bandit%20%E2%9E%A1%EF%B8%8F"
)

_AsyncTextUpdate = Callable[[str], Awaitable[None]]


def _format_platform(platform: str) -> str:
    return (platform or "unknown").capitalize()


def _format_size(value: Optional[int]) -> str:
    if not value or value <= 0:
        return "—"
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{value} B"


def _format_speed(value: Optional[float]) -> str:
    if not value or value <= 0:
        return "—"
    return f"{_format_size(int(value))}/s"


def _format_eta(seconds: Optional[int]) -> str:
    if seconds is None or seconds < 0:
        return "—"
    total = int(seconds)
    minutes, sec = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{sec:02d}"
    return f"{minutes:d}:{sec:02d}"


def waiting(platform: str, active: int, max_per_user: int, *, locale: str = DEFAULT_LOCALE) -> str:
    return translate(
        "status.waiting",
        locale,
        platform=_format_platform(platform),
        active=active,
        limit=max_per_user,
    )


def downloading(platform: str, *, locale: str = DEFAULT_LOCALE) -> str:
    return translate("status.downloading", locale, platform=_format_platform(platform))


def downloading_progress(
    platform: str,
    progress: "DownloadProgress",
    *,
    locale: str = DEFAULT_LOCALE,
) -> str:
    percent_value = progress.percent
    percent_text = f"{percent_value:.0f}%" if percent_value is not None else "—"
    return translate(
        "status.downloading_progress",
        locale,
        platform=_format_platform(platform),
        percent=percent_text,
        speed=_format_speed(progress.speed_bytes_per_sec),
        eta=_format_eta(progress.eta_seconds),
        downloaded=_format_size(progress.downloaded_bytes),
        total=_format_size(progress.total_bytes),
    )


def processing(platform: str, *, locale: str = DEFAULT_LOCALE) -> str:
    return translate("status.processing", locale, platform=_format_platform(platform))


def sending(platform: str, *, locale: str = DEFAULT_LOCALE) -> str:
    return translate("status.sending", locale, platform=_format_platform(platform))


def success(platform: str, *, locale: str = DEFAULT_LOCALE) -> str:
    return translate("status.success", locale, platform=_format_platform(platform))


def error(reason: str, *, locale: str = DEFAULT_LOCALE) -> str:
    return translate("status.error", locale, reason=reason)


def success_markup(source_url: Optional[str], *, locale: str = DEFAULT_LOCALE) -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(text=translate("buttons.download_more", locale), url=BOT_LINK)]]
    row = []
    if source_url:
        row.append(InlineKeyboardButton(text=translate("buttons.open_source", locale), url=source_url))
    row.append(InlineKeyboardButton(text=translate("buttons.share_bot", locale), url=SHARE_LINK))
    buttons.append(row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_progress_callback(
    update_func: _AsyncTextUpdate,
    platform: str,
    *,
    locale: str = DEFAULT_LOCALE,
    min_interval: float = 3.0,
    min_delta_percent: float = 1.0,
):
    """Return coroutine callback that throttles status updates for progress events."""

    state = {"last_emit": 0.0, "last_percent": -1.0}

    async def _handler(progress: "DownloadProgress") -> None:
        if progress is None:
            return
        now = time.monotonic()
        percent = progress.percent
        if percent is not None:
            if state["last_percent"] >= 0:
                if percent - state["last_percent"] < min_delta_percent and (now - state["last_emit"]) < min_interval:
                    return
            state["last_percent"] = percent
        elif (now - state["last_emit"]) < (min_interval * 2):
            return
        state["last_emit"] = now
        await update_func(downloading_progress(platform, progress, locale=locale))

    return _handler
