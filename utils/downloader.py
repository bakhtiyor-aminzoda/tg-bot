# utils/downloader.py
"""
Улучшенный асинхронный загрузчик для yt-dlp с постпроверкой через ffprobe + мерджем через ffmpeg.
- Скачивает bestvideo+bestaudio (предпочитая mp4/m4a).
- При отсутствии аудио скачивает отдельно аудио и делает merge.
- Поддерживает COOKIES_FILE (опционно) и настраиваемый USER_AGENT.
- Бросает DownloadError при неудаче.
"""

import asyncio
import shlex
import os
from pathlib import Path
import logging
from typing import Optional

try:
    from services import video_cache
except Exception:  # pragma: no cover - cache unavailable in some envs
    video_cache = None  # type: ignore

try:
    from services import instagram_direct
except Exception:  # pragma: no cover - fallback unavailable in some envs
    instagram_direct = None  # type: ignore

logger = logging.getLogger(__name__)

class DownloadError(Exception):
    pass

async def _run_cmd(cmd: list[str], timeout: int):
    """Run subprocess, return (stdout, stderr, returncode)."""
    logger.debug("Run command: %s", " ".join(shlex.quote(x) for x in cmd))
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
        raise DownloadError("Таймаут выполнения внешней команды.")
    return stdout.decode(errors="ignore"), stderr.decode(errors="ignore"), proc.returncode

async def _ffprobe_has_audio_or_video(path: Path, timeout: int = 30) -> dict:
    """
    Проверяем потоки в файле через ffprobe.
    Возвращаем dict {'has_audio': bool, 'has_video': bool}
    """
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "a",
        "-show_entries", "stream=codec_type",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path)
    ]
    has_audio = False
    try:
        stdout, stderr, rc = await _run_cmd(cmd, timeout=timeout)
        has_audio = bool(stdout.strip())
    except DownloadError:
        logger.debug("ffprobe audio check failed for %s", path)

    cmd_v = [
        "ffprobe", "-v", "error",
        "-select_streams", "v",
        "-show_entries", "stream=codec_type",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path)
    ]
    has_video = False
    try:
        stdout, stderr, rc = await _run_cmd(cmd_v, timeout=timeout)
        has_video = bool(stdout.strip())
    except DownloadError:
        logger.debug("ffprobe video check failed for %s", path)

    return {"has_audio": has_audio, "has_video": has_video}

async def _ffmpeg_merge(video_path: Path, audio_path: Path, output_path: Path, timeout: int = 120):
    """
    Мерджит video + audio в output_path с помощью ffmpeg.
    Мы стараемся копировать видео-стрим, перекодировать аудио в aac (для совместимости).
    """
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", str(audio_path),
        "-c:v", "copy",
        "-c:a", "aac",
        "-map", "0:v:0",
        "-map", "1:a:0",
        str(output_path)
    ]
    stdout, stderr, rc = await _run_cmd(cmd, timeout=timeout)
    if rc != 0:
        logger.error("ffmpeg merge failed: %s", stderr[:1000])
        raise DownloadError(f"ffmpeg merge failed: {stderr.splitlines()[-1] if stderr else 'unknown'}")
    return output_path

async def download_video(url: str, output_dir: Path, timeout: int = 20 * 60, cookies_file: Optional[str] = None) -> Path:
    """Скачивает видео, пытаясь обновить Instagram-cookies при необходимости."""
    output_dir.mkdir(parents=True, exist_ok=True)
    cached_path = await _try_cache_get(url, output_dir)
    if cached_path:
        return cached_path
    attempts = 2
    last_error: Optional[DownloadError] = None
    for attempt in range(attempts):
        try:
            result = await _download_once(url, output_dir, timeout, cookies_file)
            await _maybe_store_cache(url, result)
            return result
        except DownloadError as err:
            last_error = err
            if await _try_refresh_instagram(url, str(err), attempt):
                continue
            raise
    if last_error:
        raise last_error
    raise DownloadError("Не удалось скачать видео по неизвестной причине.")


async def _download_once(url: str, output_dir: Path, timeout: int, cookies_file: Optional[str]) -> Path:
    output_template = str(output_dir / "%(title).100s-%(id)s.%(ext)s")
    user_agent = os.environ.get(
        "YTDLP_USER_AGENT",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
    )
    cmd = [
        "yt-dlp",
        "--no-playlist",
        "-f",
        "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best",
        "--merge-output-format",
        "mp4",
        "--no-warnings",
        "--restrict-filenames",
        "--output",
        output_template,
        "--retries",
        "3",
        "--fragment-retries",
        "3",
        "--user-agent",
        user_agent,
    ]

    if cookies_file:
        cmd += ["--cookies", cookies_file]
    else:
        cf = os.environ.get("YTDLP_COOKIES_FILE")
        if cf:
            cmd += ["--cookies", cf]

    if "instagram.com" in url:
        cmd += ["--add-header", "Referer: https://www.instagram.com/"]

    logger.info("Запускаем yt-dlp: %s ...", url)
    try:
        stdout, stderr, rc = await _run_cmd(cmd + [url], timeout=timeout)
    except FileNotFoundError as e:
        logger.exception("yt-dlp не найден.")
        raise DownloadError("yt-dlp не найден. Убедитесь, что он установлен и доступен в PATH.") from e
    except DownloadError as e:
        logger.exception("Ошибка yt-dlp (timeout?)")
        raise

    if rc != 0:
        logger.error("yt-dlp завершился с кодом %s: %s", rc, stderr[:2000])
        last_line = stderr.splitlines()[-1] if stderr else "unknown error"
        if _should_try_instagram_fallback(url, last_line, cookies_file):
            logger.warning("Instagram reported restricted media, invoking API fallback")
            try:
                assert instagram_direct is not None  # for type checkers
                return await instagram_direct.download_sensitive_media(
                    url=url,
                    output_dir=output_dir,
                    cookies_file=cookies_file or "",
                )
            except Exception as fallback_err:
                logger.warning("Instagram API fallback failed: %s", fallback_err)
                last_line = f"{last_line} (fallback failed: {fallback_err})"
        raise DownloadError(f"Ошибка yt-dlp: {last_line}")

    candidates = [p for p in output_dir.iterdir() if p.is_file()]
    if not candidates:
        raise DownloadError("Файл не найден после завершения yt-dlp.")

    downloaded = sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)[0]
    logger.info("Первичный файл: %s (%.2f MB)", downloaded, downloaded.stat().st_size / 1024 / 1024)

    # Проверяем с помощью ffprobe наличие аудио+видео
    probes = await _ffprobe_has_audio_or_video(downloaded)
    logger.debug("ffprobe result: %s", probes)

    if probes.get("has_video") and probes.get("has_audio"):
        return downloaded

    if probes.get("has_video") and not probes.get("has_audio"):
        logger.info("Файл не содержит аудио. Пробуем скачать аудио отдельно и смержить.")
        audio_template = str(output_dir / "%(title).100s-%(id)s.%(ext)s")
        audio_cmd = [
            "yt-dlp",
            "--no-playlist",
            "-f", "bestaudio[ext=m4a]/bestaudio",
            "--output", audio_template,
            "--user-agent", user_agent,
            "--retries", "3",
            "--fragment-retries", "3",
        ]
        if cookies_file:
            audio_cmd += ["--cookies", cookies_file]
        else:
            cf = os.environ.get("YTDLP_COOKIES_FILE")
            if cf:
                audio_cmd += ["--cookies", cf]
        if "instagram.com" in url:
            audio_cmd += ["--add-header", "Referer: https://www.instagram.com/"]

        stdout_a, stderr_a, rc_a = await _run_cmd(audio_cmd + [url], timeout=timeout)
        if rc_a != 0:
            logger.error("Не удалось скачать аудио отдельно: %s", stderr_a[:1000])
            raise DownloadError("Не удалось скачать аудио для объединения.")

        # Найдём скачанный аудиофайл
        candidates2 = [p for p in output_dir.iterdir() if p.is_file() and p != downloaded]
        if not candidates2:
            raise DownloadError("Аудиофайл не найден после скачивания.")
        audio_file = sorted(candidates2, key=lambda p: p.stat().st_mtime, reverse=True)[0]
        logger.info("Аудио скачано: %s", audio_file)

        # Мержим через ffmpeg
        merged_path = downloaded.with_name(downloaded.stem + "_merged.mp4")
        merged = await _ffmpeg_merge(downloaded, audio_file, merged_path)
        # Clean up originals if merge ok
        try:
            downloaded.unlink(missing_ok=True)
            audio_file.unlink(missing_ok=True)
        except Exception:
            logger.debug("Не удалось удалить временные файлы после merge.")
        logger.info("Merge выполнен, итог: %s", merged)
        return merged

    if probes.get("has_audio") and not probes.get("has_video"):
        logger.info("Файл содержит только аудио. Пробуем скачать video отдельно и смержить.")
        video_template = str(output_dir / "%(title).100s-%(id)s.%(ext)s")
        video_cmd = [
            "yt-dlp",
            "--no-playlist",
            "-f", "bestvideo[ext=mp4]/bestvideo",
            "--output", video_template,
            "--user-agent", user_agent,
            "--retries", "3",
            "--fragment-retries", "3",
        ]
        if cookies_file:
            video_cmd += ["--cookies", cookies_file]
        else:
            cf = os.environ.get("YTDLP_COOKIES_FILE")
            if cf:
                video_cmd += ["--cookies", cf]
        if "instagram.com" in url:
            video_cmd += ["--add-header", "Referer: https://www.instagram.com/"]

        stdout_v, stderr_v, rc_v = await _run_cmd(video_cmd + [url], timeout=timeout)
        if rc_v != 0:
            logger.error("Не удалось скачать video отдельно: %s", stderr_v[:1000])
            raise DownloadError("Не удалось скачать видео для объединения.")

        # Найдём скачанный видеофайл
        candidates3 = [p for p in output_dir.iterdir() if p.is_file() and p != downloaded]
        if not candidates3:
            raise DownloadError("Видеофайл не найден после скачивания.")
        video_file = sorted(candidates3, key=lambda p: p.stat().st_mtime, reverse=True)[0]
        merged_path = video_file.with_name(video_file.stem + "_merged.mp4")
        merged = await _ffmpeg_merge(video_file, downloaded, merged_path)
        try:
            downloaded.unlink(missing_ok=True)
            video_file.unlink(missing_ok=True)
        except Exception:
            logger.debug("Не удалось удалить временные файлы после merge.")
        logger.info("Merge выполнен, итог: %s", merged)
        return merged

    raise DownloadError("Скачанный файл не содержит не аудио, ни видео или неизвестный формат.")


async def _try_refresh_instagram(url: str, error_text: str, attempt: int) -> bool:
    if "instagram.com" not in url.lower():
        return False
    if attempt > 0:
        return False
    try:
        from services import instagram_cookies
    except Exception:
        logger.debug("Instagram refresher module unavailable", exc_info=True)
        return False
    if not instagram_cookies.should_retry_for_error(error_text):
        return False
    logger.info("Instagram download failed (%s). Пытаемся обновить cookies...", error_text)
    result = await instagram_cookies.refresh_instagram_cookies(
        force=True,
        reason="download-error",
        allow_disabled=True,
    )
    if result.refreshed:
        logger.info("Instagram cookies обновлены, повторяем попытку")
        await asyncio.sleep(2)
        return True
    logger.warning("Не удалось автоматически обновить Instagram cookies: %s", result.message)
    return False


async def _try_cache_get(url: str, output_dir: Path) -> Optional[Path]:
    if not video_cache or not video_cache.is_enabled():
        return None
    return await video_cache.get_cached_copy(url, output_dir)


async def _maybe_store_cache(url: str, file_path: Path) -> None:
    if not video_cache or not video_cache.is_enabled():
        return
    await video_cache.store_copy(url, file_path)


def _should_try_instagram_fallback(url: str, error_line: str, cookies_file: Optional[str]) -> bool:
    if not cookies_file or not error_line:
        return False
    if instagram_direct is None:
        return False
    if "instagram.com" not in url.lower():
        return False
    lowered = error_line.lower()
    return "inappropriate" in lowered or "certain audiences" in lowered
