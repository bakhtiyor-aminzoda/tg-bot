"""Async health monitoring loop that raises alerts on anomalies."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Iterable, Optional

import config
from bot_app import state
from bot_app.runtime import bot, global_download_semaphore
from monitoring import get_metrics_registry
from services import alerts as alert_service

logger = logging.getLogger(__name__)
UTC = timezone.utc


async def monitor_loop() -> None:
    interval = max(15, getattr(config, "ALERT_MONITOR_INTERVAL_SECONDS", 60))
    error_threshold = max(1, getattr(config, "ALERT_ERROR_SPIKE_THRESHOLD", 8))
    pending_threshold = max(1, getattr(config, "ALERT_PENDING_THRESHOLD", 15))
    stuck_minutes = max(1, getattr(config, "ALERT_STUCK_ACTIVE_MINUTES", 3))
    stuck_seconds_required = stuck_minutes * 60

    prev_failures: Optional[int] = None
    backlog_duration = 0
    stuck_duration = 0

    logger.info(
        "Health monitor loop started (interval=%ss, error_threshold=%s, pending_threshold=%s, stuck_minutes=%s)",
        interval,
        error_threshold,
        pending_threshold,
        stuck_minutes,
    )

    while True:
        try:
            await asyncio.sleep(interval)
            snapshot = get_metrics_registry().snapshot()
            counters: Dict[str, int] = snapshot.get("counters", {})  # type: ignore[assignment]
            failures = int(counters.get("downloads.failure", 0) or 0)
            prev_failures = await _check_error_spike(
                failures,
                prev_failures,
                interval,
                error_threshold,
            )

            pending = state.pending_tokens_count()
            backlog_duration = await _check_pending_backlog(
                pending,
                pending_threshold,
                backlog_duration,
                interval,
            )

            stuck_duration = await _check_queue_stuck(
                pending,
                stuck_duration,
                stuck_seconds_required,
                interval,
            )
        except asyncio.CancelledError:
            logger.info("Health monitor loop cancelled")
            raise
        except Exception:
            logger.exception("Health monitor iteration failed")


async def _check_error_spike(
    failures: int,
    prev_failures: Optional[int],
    interval: int,
    threshold: int,
) -> int:
    if prev_failures is None:
        return failures

    delta = max(0, failures - prev_failures)
    if delta >= threshold:
        message = f"Error spike detected: {delta} failures in the last {interval}s"
        alert, created = alert_service.record_alert(
            "errors.spike",
            message,
            severity="danger",
            details={"delta": delta, "interval_seconds": interval},
        )
        if created:
            await _notify_admins(alert)
    else:
        alert_service.resolve_alert("errors.spike")
    return failures


async def _check_pending_backlog(
    pending: int,
    threshold: int,
    backlog_duration: int,
    interval: int,
) -> int:
    if pending >= threshold:
        backlog_duration += interval
        message = f"Queue backlog: {pending} pending tasks (threshold {threshold})."
        alert, created = alert_service.record_alert(
            "queue.backlog",
            message,
            severity="warning",
            details={"pending": pending, "threshold": threshold},
        )
        if created:
            await _notify_admins(alert)
    else:
        backlog_duration = 0
        alert_service.resolve_alert("queue.backlog")
    return backlog_duration


async def _check_queue_stuck(
    pending: int,
    stuck_duration: int,
    threshold_seconds: int,
    interval: int,
) -> int:
    max_slots = max(1, getattr(config, "MAX_GLOBAL_CONCURRENT_DOWNLOADS", 1))
    available = getattr(global_download_semaphore, "_value", 0)
    in_use = max_slots - max(0, available)
    saturated = in_use >= max_slots and pending > 0

    if saturated:
        stuck_duration += interval
        if stuck_duration >= threshold_seconds:
            minutes = threshold_seconds // 60
            message = (
                f"Queue stuck: all {max_slots} slots busy for over {minutes} min, pending={pending}."
            )
            alert, created = alert_service.record_alert(
                "queue.stuck",
                message,
                severity="danger",
                details={
                    "max_slots": max_slots,
                    "pending": pending,
                    "duration_seconds": stuck_duration,
                },
            )
            if created:
                await _notify_admins(alert)
    else:
        stuck_duration = 0
        alert_service.resolve_alert("queue.stuck")
    return stuck_duration


async def _notify_admins(alert: Dict[str, object]) -> None:
    if not _should_notify(alert):
        return
    recipients = _resolve_recipients()
    if not recipients:
        return
    text = _format_alert_message(alert)
    for chat_id in recipients:
        try:
            await bot.send_message(chat_id, text)
        except Exception:
            logger.exception("Failed to deliver alert %s to chat %s", alert.get("code"), chat_id)
    try:
        alert_service.mark_alert_notified(int(alert.get("id", 0)))
    except Exception:
        logger.debug("Failed to mark alert as notified", exc_info=True)


def _should_notify(alert: Dict[str, object]) -> bool:
    cooldown_minutes = max(1, getattr(config, "ALERT_NOTIFY_COOLDOWN_MINUTES", 60))
    cooldown_seconds = cooldown_minutes * 60
    last_notified = _parse_timestamp(alert.get("last_notified_at"))
    if last_notified is None:
        return True
    elapsed = (datetime.now(tz=UTC) - last_notified).total_seconds()
    return elapsed >= cooldown_seconds


def _resolve_recipients() -> Iterable[int]:
    recipients = set()
    chat_id = getattr(config, "ADMIN_ALERT_CHAT_ID", None)
    if chat_id:
        recipients.add(chat_id)
    extra = getattr(config, "ADMIN_USER_IDS", [])
    if extra:
        recipients.update(int(uid) for uid in extra if uid)
    return recipients


def _format_alert_message(alert: Dict[str, object]) -> str:
    severity = str(alert.get("severity", "warning")).upper()
    code = alert.get("code", "unknown")
    message = alert.get("message", "")
    details = alert.get("details") or {}
    meta = ""
    if isinstance(details, dict) and details:
        formatted_pairs = ", ".join(f"{k}={v}" for k, v in details.items())
        meta = f"\nDetails: {formatted_pairs}"
    return f"ALERT [{severity}] {code}\n{message}{meta}"


def _parse_timestamp(value: object) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    text = str(value).strip()
    if not text:
        return None
    for parser in (_parse_iso8601, _parse_unix_timestamp):
        result = parser(text)
        if result:
            return result
    return None


def _parse_iso8601(value: str) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    else:
        parsed = parsed.astimezone(UTC)
    return parsed


def _parse_unix_timestamp(value: str) -> Optional[datetime]:
    try:
        ts = float(value)
    except ValueError:
        return None
    return datetime.fromtimestamp(ts, tz=UTC)


__all__ = ["monitor_loop"]
