# utils/downloader.py
# Асинхронный загрузчик видео через yt-dlp (внешний процесс).
# Возвращает абсолютный путь к скачанному файлу или выбрасывает исключение.

import asyncio
import shlex
import os
from pathlib import Path
import logging
from typing import Tuple

logger = logging.getLogger(__name__)

class DownloadError(Exception):
    """Ошибка при скачивании видео."""
    pass

async def download_video(url: str, output_dir: Path, timeout: int = 20*60) -> Path:
    """
    Асинхронно запускает yt-dlp для скачивания видео по url в output_dir.
    Возвращает Path к скачанному файлу.
    Бросает DownloadError при ошибках.

    Параметры:
        url: ссылка на видео
        output_dir: папка, куда сохранять (Path)
        timeout: таймаут процесса в секундах
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Шаблон имени выходного файла: title-id.ext (обрезаем title чтобы не было слишком длинным)
    output_template = str(output_dir / "%(title).100s-%(id)s.%(ext)s")

    # Формируем аргументы yt-dlp.
    # - --no-playlist : гарантируем, что не скачиваем плейлист
    # - -f "bestvideo+bestaudio/best" : берем лучший видеопоток и аудио (и объединяем)
    # - --merge-output-format mp4 : итог в mp4 для лучшей совместимости
    # - -o <template> : путь вывода
    # - --no-warnings : уборка лишних предупреждений
    # - --restrict-filenames : чтобы избегать странных символов (опционально)
    cmd = [
        "yt-dlp",
        "--no-playlist",
        "-f", "bestvideo+bestaudio/best",
        "--merge-output-format", "mp4",
        "--no-warnings",
        "--restrict-filenames",
        "-o", output_template,
        url,
    ]

    logger.info("Запускаем yt-dlp: %s", " ".join(shlex.quote(x) for x in cmd))

    # Запускаем subprocess
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            raise DownloadError("Таймаут скачивания (превышено время ожидания).")

        if proc.returncode != 0:
            err_text = stderr.decode(errors="ignore")[:2000]
            logger.error("yt-dlp завершился с кодом %s: %s", proc.returncode, err_text)
            raise DownloadError(f"Ошибка yt-dlp: {err_text or 'неизвестная ошибка'}")

        out_text = stdout.decode(errors="ignore")
        logger.debug("yt-dlp stdout: %s", out_text)

    except FileNotFoundError as e:
        logger.exception("yt-dlp не найден в PATH.")
        raise DownloadError("yt-dlp не найден. Установите yt-dlp в систему и убедитесь, что он доступен в PATH.") from e
    except Exception as e:
        logger.exception("Ошибка при запуске yt-dlp")
        raise DownloadError(f"Ошибка при запуске yt-dlp: {e}") from e

    # После успешного завершения: ищем новый файл в output_dir (по расширению mp4 или другим)
    # Поскольку мы использовали шаблон с title-id, обычно появляется один новый файл.
    candidates = list(output_dir.glob("*"))
    if not candidates:
        raise DownloadError("Файл не найден после завершения yt-dlp.")

    # Берём самый свежий файл (на случай, если папка не пуста)
    candidates_sorted = sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)
    downloaded = candidates_sorted[0]

    # Некоторые форматы могут включать .tmp — если он есть, выдаём ошибку
    if downloaded.suffix == ".tmp" or not downloaded.exists():
        raise DownloadError("Файл скачан некорректно или имеет временное расширение.")

    logger.info("Скачано: %s (%.2f MB)", downloaded, downloaded.stat().st_size / 1024 / 1024)
    return downloaded
