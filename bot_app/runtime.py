"""Runtime objects shared across bot modules."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher

import config
from monitoring import setup_logging

# Configure logging and structured output.
setup_logging(
    level=config.LOG_LEVEL,
    log_file=getattr(config, "LOG_FILE", None),
    max_bytes=getattr(config, "LOG_MAX_BYTES", 10 * 1024 * 1024),
    backup_count=getattr(config, "LOG_BACKUP_COUNT", 5),
    sentry_dsn=getattr(config, "SENTRY_DSN", None),
    structured=getattr(config, "STRUCTURED_LOGS", False),
)

logger = logging.getLogger(__name__)

# Shared aiogram primitives
bot = Bot(token=config.TOKEN)
dp = Dispatcher()

# Global semaphore to limit total concurrent downloads
MAX_CONCURRENT = getattr(config, "MAX_GLOBAL_CONCURRENT_DOWNLOADS", 4)
global_download_semaphore = asyncio.Semaphore(MAX_CONCURRENT)

__all__ = [
    "bot",
    "dp",
    "logger",
    "global_download_semaphore",
]
