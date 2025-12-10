"""Logging and monitoring setup helper.

Provides `setup_logging(...)` which configures console + optional rotating file
logging and initializes Sentry if `sentry_dsn` is provided.
"""
import logging
import logging.handlers
from pathlib import Path
from typing import Optional


def setup_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
    sentry_dsn: Optional[str] = None,
):
    """Configure root logger: stream handler + optional rotating file handler.

    If `sentry_dsn` is provided, attempts to initialize `sentry_sdk`.
    """
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove default handlers if any (avoid duplicate logs during tests)
    for h in list(root.handlers):
        root.removeHandler(h)

    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")

    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    root.addHandler(sh)

    if log_file:
        try:
            p = Path(log_file)
            p.parent.mkdir(parents=True, exist_ok=True)
            fh = logging.handlers.RotatingFileHandler(str(p), maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8")
            fh.setFormatter(fmt)
            root.addHandler(fh)
        except Exception:
            root.exception("Не удалось настроить файл логов %s", log_file)

    # Optional Sentry integration (best-effort; don't crash if missing)
    if sentry_dsn:
        try:
            import sentry_sdk

            sentry_sdk.init(dsn=sentry_dsn)
            root.info("Sentry initialized")
        except Exception:
            root.exception("Не удалось инициализировать Sentry (sentry_sdk отсутствует или неверный DSN)")


def capture_exception(exc: Exception) -> None:
    """Capture exception to Sentry if available (best-effort).

    This function will not raise if Sentry is not installed or not initialized.
    """
    try:
        import sentry_sdk

        # sentry_sdk.capture_exception is safe to call even if not initialized.
        sentry_sdk.capture_exception(exc)
    except Exception:
        logging.getLogger(__name__).debug("Sentry capture failed or sentry_sdk not installed.")
