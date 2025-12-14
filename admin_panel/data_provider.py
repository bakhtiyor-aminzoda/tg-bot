"""Data provider utilities for the admin panel."""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

import config
from services import stats as stats_service
from monitoring import get_health_snapshot

from .runtime_controls import RuntimeController

LogReader = Callable[[int], List[Dict[str, str]]]


class DashboardDataProvider:
    """Aggregates stats, logs, runtime, and health data for the dashboard."""

    def __init__(
        self,
        runtime_controller: RuntimeController,
        *,
        log_reader: LogReader,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._runtime = runtime_controller
        self._log_reader = log_reader
        self._logger = logger or logging.getLogger(__name__)

    def collect_dashboard(
        self,
        *,
        chat_id: Optional[int],
        chat_sort: str,
        top_sort: str,
        platform_sort: str,
        search_query: Optional[str],
        log_tail: int,
    ) -> Dict[str, Any]:
        summary = stats_service.get_summary(chat_id)
        top_users = stats_service.get_top_users(chat_id, limit=10, order_by=top_sort)
        platforms = stats_service.get_platform_stats(chat_id, order_by=platform_sort)
        recent = stats_service.get_recent_downloads(chat_id, limit=20)
        failures = stats_service.get_recent_failures(chat_id, limit=10)
        chat_list = stats_service.list_chats(order_by=chat_sort, search=search_query, limit=100)
        scope = "Глобальная статистика" if chat_id is None else f"Чат #{chat_id}"

        health_data: Optional[Dict[str, Any]] = None
        if getattr(config, "HEALTHCHECK_ENABLED", False):
            try:
                health_data = get_health_snapshot()
            except Exception:  # pragma: no cover - defensive logging only
                self._logger.debug("Не удалось получить health snapshot", exc_info=True)

        runtime_state = self._runtime.snapshot()

        return {
            "summary": summary,
            "top_users": top_users,
            "platforms": platforms,
            "recent": recent,
            "failures": failures,
            "scope": scope,
            "chat_id": chat_id,
            "chat_list": chat_list,
            "chat_sort": chat_sort,
            "top_sort": top_sort,
            "platform_sort": platform_sort,
            "search_query": search_query or "",
            "error_logs": self._log_reader(log_tail),
            "health": health_data,
            "runtime": runtime_state,
        }


__all__ = ["DashboardDataProvider"]
