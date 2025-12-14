"""Background maintenance utilities for keeping in-memory state tidy."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

import config
from bot_app import state
from services import health_monitor

logger = logging.getLogger(__name__)

_cleanup_task: Optional[asyncio.Task[None]] = None
_cookie_task: Optional[asyncio.Task[None]] = None
_health_task: Optional[asyncio.Task[None]] = None


def _purge_pending(now: float) -> int:
    """Drop expired pending download tokens."""
    ttl = state.PENDING_TOKEN_TTL
    removed = 0
    for token, payload in list(state.pending_downloads.items()):
        issued_at = float(payload.get("ts", 0))
        if now - issued_at > ttl:
            state.pending_downloads.pop(token, None)
            removed += 1
    return removed


def _purge_stuck_actives(now: float, stuck_timeout: float, last_ttl: float) -> int:
    """Reset counters for users whose activity should have completed by now."""
    cleared = 0
    for uid, active in list(state.user_active_downloads.items()):
        last_ts = state.user_last_request_ts.get(uid, 0.0)
        if active <= 0 and (now - last_ts) > last_ttl:
            state.user_active_downloads.pop(uid, None)
            cleared += 1
            continue
        if active > 0 and (now - last_ts) > stuck_timeout:
            logger.warning(
                "Resetting stuck active_downloads=%s for uid=%s (last activity %.0fs ago)",
                active,
                uid,
                now - last_ts,
            )
            state.user_active_downloads[uid] = 0
            cleared += 1
    return cleared


def _purge_stale_last_requests(now: float, last_ttl: float) -> int:
    """Remove idle entries from the last-request map."""
    removed = 0
    for uid, ts in list(state.user_last_request_ts.items()):
        if now - ts > last_ttl and state.user_active_downloads.get(uid, 0) <= 0:
            state.user_last_request_ts.pop(uid, None)
            removed += 1
    return removed


async def _cleanup_loop() -> None:
    interval = max(5, config.PENDING_CLEANUP_INTERVAL_SECONDS)
    stuck_timeout = max(config.USER_COOLDOWN_SECONDS, config.DOWNLOAD_STUCK_TIMEOUT_SECONDS)
    last_ttl = max(config.USER_COOLDOWN_SECONDS, config.USER_STATE_TTL_SECONDS)
    logger.info(
        "Starting cleanup loop (interval=%ss, pending_ttl=%ss, stuck_timeout=%ss)",
        interval,
        state.PENDING_TOKEN_TTL,
        stuck_timeout,
    )
    while True:
        try:
            await asyncio.sleep(interval)
            now = time.time()
            removed_tokens = _purge_pending(now)
            cleared_actives = _purge_stuck_actives(now, stuck_timeout, last_ttl)
            cleared_last = _purge_stale_last_requests(now, last_ttl)
            if removed_tokens or cleared_actives or cleared_last:
                logger.debug(
                    "Cleanup stats: removed_tokens=%s cleared_actives=%s cleared_last_ts=%s",
                    removed_tokens,
                    cleared_actives,
                    cleared_last,
                )
        except asyncio.CancelledError:
            logger.info("Cleanup loop cancelled")
            raise
        except Exception:
            logger.exception("Cleanup loop iteration failed; continuing")


async def _cookie_refresh_loop() -> None:
    try:
        from services import instagram_cookies
    except Exception:
        logger.info("Instagram cookie refresher недоступен (не установлен playwright?)")
        return

    if not instagram_cookies.is_enabled():
        logger.info("Instagram автообновление cookies отключено")
        return

    interval = max(900.0, instagram_cookies.refresh_interval_seconds())
    logger.info("Starting Instagram cookie loop (interval=%.0fs)", interval)
    while True:
        try:
            await instagram_cookies.refresh_instagram_cookies(reason="scheduled")
        except asyncio.CancelledError:
            logger.info("Instagram cookie loop cancelled")
            raise
        except Exception:
            logger.exception("Instagram cookie refresh iteration failed")
        await asyncio.sleep(interval)


def start_background_tasks() -> None:
    """Ensure cleanup loop is running."""
    global _cleanup_task, _cookie_task, _health_task
    loop = asyncio.get_running_loop()
    if not _cleanup_task or _cleanup_task.done():
        _cleanup_task = loop.create_task(_cleanup_loop(), name="state-cleanup")
    if not _cookie_task or _cookie_task.done():
        _cookie_task = loop.create_task(_cookie_refresh_loop(), name="instagram-cookie-refresh")
    if config.ENABLE_HISTORY and (not _health_task or _health_task.done()):
        _health_task = loop.create_task(health_monitor.monitor_loop(), name="health-monitor")


async def stop_background_tasks() -> None:
    """Stop cleanup loop and wait for graceful shutdown."""
    global _cleanup_task, _cookie_task, _health_task
    await _cancel_task(_cleanup_task)
    await _cancel_task(_cookie_task)
    await _cancel_task(_health_task)
    _cleanup_task = None
    _cookie_task = None
    _health_task = None


async def _cancel_task(task: Optional[asyncio.Task[None]]) -> None:
    if not task:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


__all__ = [
    "start_background_tasks",
    "stop_background_tasks",
]
