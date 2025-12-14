"""Runtime control helpers for the admin panel."""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import Future
from typing import Any, Dict, Optional

from bot_app import admin_runtime


class RuntimeController:
    """Proxy for interacting with runtime state from the admin panel."""

    def __init__(
        self,
        *,
        bot_loop: Optional[asyncio.AbstractEventLoop],
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._bot_loop = bot_loop
        self._logger = logger or logging.getLogger(__name__)

    # ------------------------------------------------------------------
    def snapshot(self) -> Dict[str, Any]:
        try:
            return self._call_on_bot_loop(admin_runtime.get_runtime_snapshot, 12, 12)
        except Exception:  # pragma: no cover - defensive logging
            self._logger.debug("Не удалось получить снимок очереди", exc_info=True)
            return {}

    def perform_action(self, action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if action == "cancel_user":
            if payload.get("user_id") is None:
                raise ValueError("user_id is required")
            user_id = int(payload.get("user_id"))
            cancelled = self._call_on_bot_loop(admin_runtime.cancel_user_downloads, user_id)
            return {"cancelled": bool(cancelled)}

        if action == "drop_token":
            token = payload.get("token")
            if not token:
                raise ValueError("token is required")
            dropped = self._call_on_bot_loop(admin_runtime.drop_pending_token, str(token))
            return {"dropped": bool(dropped)}

        if action == "flush_tokens":
            dropped = self._call_on_bot_loop(admin_runtime.flush_pending_tokens)
            return {"dropped": int(dropped)}

        raise ValueError("unknown action")

    # ------------------------------------------------------------------
    def _call_on_bot_loop(self, func, *args, **kwargs):
        if not self._bot_loop:
            return func(*args, **kwargs)
        future: Future = Future()

        def runner():
            try:
                future.set_result(func(*args, **kwargs))
            except Exception as exc:  # pragma: no cover - defensive
                future.set_exception(exc)

        self._bot_loop.call_soon_threadsafe(runner)
        return future.result(timeout=5)


__all__ = ["RuntimeController"]
