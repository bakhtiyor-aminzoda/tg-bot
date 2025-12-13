from __future__ import annotations

import asyncio
import logging
import shlex
from pathlib import Path

import config
from utils.downloader import DownloadError

logger = logging.getLogger(__name__)


async def ensure_file_is_safe(path: Path) -> None:
    """Run optional external scanner if configured."""
    command = config.MEDIA_SCAN_COMMAND
    if not command:
        return

    cmd_list = shlex.split(command) + [str(path)]
    logger.info("Запускаем проверку файла: %s", " ".join(shlex.quote(part) for part in cmd_list))

    proc = await asyncio.create_subprocess_exec(
        *cmd_list,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=config.MEDIA_SCAN_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        raise DownloadError("Проверка файла заняла слишком много времени и была остановлена.")

    stdout_text = stdout.decode(errors="ignore").strip()
    stderr_text = stderr.decode(errors="ignore").strip()
    if proc.returncode != 0:
        logger.warning("Сканер вернул код %s: %s", proc.returncode, stderr_text or stdout_text)
        raise DownloadError("Сканер заблокировал файл — отправка отменена.")

    if stdout_text:
        logger.info("Результат сканирования: %s", stdout_text)
