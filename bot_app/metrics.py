"""Shared helpers for updating runtime metrics."""

from __future__ import annotations

import config
from bot_app import state
from bot_app.runtime import global_download_semaphore
from monitoring import set_metric_gauge


def update_active_downloads_gauge() -> None:
    set_metric_gauge("downloads.active", state.total_active_downloads())


def update_pending_tokens_gauge() -> None:
    set_metric_gauge("downloads.pending_tokens", state.pending_tokens_count())


def update_queue_gauges() -> None:
    max_slots = max(1, getattr(config, "MAX_GLOBAL_CONCURRENT_DOWNLOADS", 1))
    available = getattr(global_download_semaphore, "_value", 0)
    in_use = max(0, max_slots - available)
    set_metric_gauge("downloads.queue_available", available)
    set_metric_gauge("downloads.queue_in_use", in_use)