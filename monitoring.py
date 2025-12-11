"""Logging, metrics, and health instrumentation helpers."""

from __future__ import annotations

import asyncio
import json
import logging
import logging.handlers
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Dict, Optional

from aiohttp import web


class JsonFormatter(logging.Formatter):
    """Simple JSON formatter for structured logs."""

    def format(self, record: logging.LogRecord) -> str:  # noqa: D401
        log = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log["exc_info"] = self.formatException(record.exc_info)
        if record.stack_info:
            log["stack"] = record.stack_info
        if record.__dict__.get("extra_data"):
            log["extra"] = record.__dict__["extra_data"]
        return json.dumps(log, ensure_ascii=True)


class MetricsRegistry:
    """Thread-safe in-memory metrics registry."""

    def __init__(self) -> None:
        self._counters: Counter[str] = Counter()
        self._gauges: Dict[str, float] = {}
        self._lock = threading.Lock()
        self._stamp = time.time()

    def increment(self, name: str, value: int = 1) -> None:
        with self._lock:
            self._counters[name] += value
            self._stamp = time.time()

    def set_gauge(self, name: str, value: float) -> None:
        with self._lock:
            self._gauges[name] = value
            self._stamp = time.time()

    def snapshot(self) -> Dict[str, object]:
        with self._lock:
            return {
                "timestamp": self._stamp,
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
            }


_metrics = MetricsRegistry()
_PROCESS_STARTED_AT = time.time()


def get_metrics_registry() -> MetricsRegistry:
    return _metrics


def increment_metric(name: str, value: int = 1) -> None:
    _metrics.increment(name, value)


def set_metric_gauge(name: str, value: float) -> None:
    _metrics.set_gauge(name, value)


def get_health_snapshot() -> Dict[str, object]:
    """Return in-process health data for embedding in admin panel."""

    now = time.time()
    snapshot = get_metrics_registry().snapshot()
    return {
        "status": "ok",
        "timestamp": now,
        "uptime_seconds": int(now - _PROCESS_STARTED_AT),
        "metrics": snapshot,
    }


def setup_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
    sentry_dsn: Optional[str] = None,
    structured: bool = False,
):
    """Configure root logger and optional Sentry."""

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter: logging.Formatter
    if structured:
        formatter = JsonFormatter()
    else:
        formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")

    sh = logging.StreamHandler()
    sh.setFormatter(formatter)
    root.addHandler(sh)

    if log_file:
        try:
            path = Path(log_file)
            path.parent.mkdir(parents=True, exist_ok=True)
            fh = logging.handlers.RotatingFileHandler(
                str(path),
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
            )
            fh.setFormatter(formatter)
            root.addHandler(fh)
        except Exception:
            root.exception("Не удалось настроить файл логов %s", log_file)

    if sentry_dsn:
        try:
            import sentry_sdk

            sentry_sdk.init(dsn=sentry_dsn)
            root.info("Sentry initialized")
        except Exception:
            root.exception("Не удалось инициализировать Sentry (sentry_sdk отсутствует или неверный DSN)")


def capture_exception(exc: Exception) -> None:
    """Send exception data to Sentry when possible."""

    try:
        import sentry_sdk

        sentry_sdk.capture_exception(exc)
    except Exception:
        logging.getLogger(__name__).debug("Sentry capture failed or sentry_sdk not installed.")


class HealthCheckServer:
    """Minimal aiohttp server exposing /health and /metrics endpoints."""

    def __init__(self, host: str = "0.0.0.0", port: int = 8080) -> None:
        self._host = host
        self._port = port
        self._runner: web.AppRunner | None = None
        self._task: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._shutdown_event: asyncio.Event | None = None
        self._logger = logging.getLogger(__name__)

    async def _handle_health(self, request: web.Request) -> web.Response:  # noqa: ARG002
        return web.json_response({"status": "ok", "timestamp": time.time()})

    async def _handle_metrics(self, request: web.Request) -> web.Response:  # noqa: ARG002
        return web.json_response(get_metrics_registry().snapshot())

    async def _run_app(self) -> None:
        app = web.Application()
        app.router.add_get("/health", self._handle_health)
        app.router.add_get("/metrics", self._handle_metrics)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, host=self._host, port=self._port)
        await site.start()
        self._logger.info("Healthcheck server listening on %s:%s", self._host, self._port)
        self._shutdown_event = asyncio.Event()
        try:
            await self._shutdown_event.wait()
        finally:
            await self._runner.cleanup()
            self._runner = None
            self._logger.info("Healthcheck server stopped")

    def ensure_running(self) -> None:
        if self._task and self._task.is_alive():
            return

        def _run(loop: asyncio.AbstractEventLoop) -> None:
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._run_app())

        self._loop = asyncio.new_event_loop()
        self._task = threading.Thread(target=_run, args=(self._loop,), daemon=True)
        self._task.start()
        self._logger.info("Healthcheck server thread started")

    def shutdown(self, timeout: float = 5.0) -> None:
        thread = self._task
        if not thread:
            return

        if self._loop and self._shutdown_event:
            self._loop.call_soon_threadsafe(self._shutdown_event.set)

        thread.join(timeout=timeout)
        if thread.is_alive():
            self._logger.warning("Healthcheck server thread did not stop within timeout")

        self._task = None
        self._loop = None
        self._shutdown_event = None
