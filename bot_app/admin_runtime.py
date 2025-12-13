"""Helpers exposing runtime download state for the admin panel."""

from __future__ import annotations

import time
from typing import Any, Dict, List

import config
from bot_app import state
from bot_app.runtime import global_download_semaphore


def get_runtime_snapshot(
    pending_limit: int = 10,
    active_limit: int = 10,
) -> Dict[str, Any]:
    """Return a snapshot of active downloads and pending tokens."""

    now = time.time()
    active_rows: List[Dict[str, Any]] = []
    for user_id, active_count in state.user_active_downloads.items():
        if active_count <= 0:
            continue
        last_activity = state.user_last_request_ts.get(user_id)
        since_last = (now - last_activity) if last_activity else None
        stuck = bool(
            since_last is not None
            and since_last > getattr(config, "DOWNLOAD_STUCK_TIMEOUT_SECONDS", 900)
        )
        active_rows.append(
            {
                "user_id": user_id,
                "active": active_count,
                "last_activity_ts": last_activity,
                "seconds_since_last": since_last,
                "is_stuck": stuck,
            }
        )
    active_rows.sort(key=lambda row: (-row["active"], -(row["seconds_since_last"] or 0)))
    if active_limit > 0:
        active_rows = active_rows[:active_limit]

    pending_rows: List[Dict[str, Any]] = []
    pending_items = sorted(
        state.pending_downloads.items(),
        key=lambda item: float(item[1].get("ts", 0.0)),
        reverse=True,
    )
    for token, payload in pending_items[:pending_limit]:
        issued_at = float(payload.get("ts", 0.0))
        pending_rows.append(
            {
                "token": token,
                "age_seconds": max(0.0, now - issued_at) if issued_at else None,
                "initiator_id": payload.get("initiator_id"),
                "source_chat_id": payload.get("source_chat_id"),
            }
        )

    max_slots = max(1, getattr(config, "MAX_GLOBAL_CONCURRENT_DOWNLOADS", 1))
    available = getattr(global_download_semaphore, "_value", max_slots)
    in_use = max(0, max_slots - available)

    return {
        "active_total": sum(state.user_active_downloads.values()),
        "active_rows": active_rows,
        "pending_total": len(state.pending_downloads),
        "pending_rows": pending_rows,
        "pending_limit": pending_limit,
        "active_limit": active_limit,
        "semaphore": {
            "max_slots": max_slots,
            "in_use": in_use,
            "available": available,
        },
    }


def cancel_user_downloads(user_id: int) -> bool:
    """Reset active counter for the given user if present."""

    if user_id not in state.user_active_downloads:
        return False
    state.user_active_downloads[user_id] = 0
    state.user_last_request_ts.pop(user_id, None)
    return True


def drop_pending_token(token: str) -> bool:
    """Remove a single pending token."""

    return state.pending_downloads.pop(token, None) is not None


def flush_pending_tokens() -> int:
    """Remove all pending tokens, returning the number of cleared entries."""

    count = len(state.pending_downloads)
    state.pending_downloads.clear()
    return count


__all__ = [
    "get_runtime_snapshot",
    "cancel_user_downloads",
    "drop_pending_token",
    "flush_pending_tokens",
]
