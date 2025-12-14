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
import re
from dataclasses import dataclass
from pathlib import Path
import logging
from typing import Awaitable, Callable, Optional

import config

try:
    from services import video_cache
except Exception:  # pragma: no cover - cache unavailable in some envs
    video_cache = None  # type: ignore

try:
    from services import instagram_direct
except Exception:  # pragma: no cover - fallback unavailable in some envs
    instagram_direct = None  # type: ignore

logger = logging.getLogger(__name__)


@dataclass
class DownloadProgress:
    percent: Optional[float] = None
    downloaded_bytes: Optional[int] = None
    total_bytes: Optional[int] = None
    speed_bytes_per_sec: Optional[float] = None
    eta_seconds: Optional[int] = None


ProgressCallback = Callable[[DownloadProgress], Awaitable[None]]

_PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)%")
_TOTAL_RE = re.compile(r"of\s+(?:~)?([\d\.]+)([KMGTP]?iB)", re.IGNORECASE)
_SPEED_RE = re.compile(r"at\s+([\d\.]+)([KMGTP]?iB/s)", re.IGNORECASE)
_ETA_RE = re.compile(r"ETA\s+([0-9:]+)")


def _convert_unit(value: str, unit: str) -> Optional[float]:
    try:
        amount = float(value)
    except ValueError:
        return None
    normalized = unit.lower().rstrip("/s")
    multiplier_map = {
        "b": 1,
        "kib": 1024,
        "mib": 1024 ** 2,
        "gib": 1024 ** 3,
        "tib": 1024 ** 4,
    }
    factor = multiplier_map.get(normalized, 1)
    return amount * factor


def _parse_eta(raw: str) -> Optional[int]:
    parts = raw.split(":")
    if not parts or any(not segment.isdigit() for segment in parts):
        return None
    seconds = 0
    for segment in parts:
        seconds = seconds * 60 + int(segment)
    return seconds


def _parse_progress_line(line: str) -> Optional[DownloadProgress]:
    clean = line.replace("\r", "").strip()
    if not clean.startswith("[download]"):
        return None
    percent = None
    percent_match = _PERCENT_RE.search(clean)
    if percent_match:
        try:
            percent = float(percent_match.group(1))
        except ValueError:
            percent = None

    total_bytes = None
    total_match = _TOTAL_RE.search(clean)
    if total_match:
        total_bytes = _convert_unit(total_match.group(1), total_match.group(2))

    downloaded_bytes = None
    if percent is not None and total_bytes:
        downloaded_bytes = int(total_bytes * (percent / 100))

    speed = None
    speed_match = _SPEED_RE.search(clean)
    if speed_match:
        speed = _convert_unit(speed_match.group(1), speed_match.group(2))

    eta_seconds = None
    eta_match = _ETA_RE.search(clean)
    if eta_match:
        eta_seconds = _parse_eta(eta_match.group(1))

    if all(value is None for value in (percent, downloaded_bytes, total_bytes, speed, eta_seconds)):
        return None

    return DownloadProgress(
        percent=percent,
        downloaded_bytes=downloaded_bytes,
        total_bytes=int(total_bytes) if total_bytes is not None else None,
        speed_bytes_per_sec=speed,
        eta_seconds=eta_seconds,
    )

class DownloadError(Exception):
    pass

async def _run_cmd(cmd: list[str], timeout: int, *, cwd: Optional[str] = None):
    """Run subprocess, return (stdout, stderr, returncode)."""
    logger.debug("Run command: %s", " ".join(shlex.quote(x) for x in cmd))
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        raise DownloadError("Таймаут выполнения внешней команды.")
    return stdout.decode(errors="ignore"), stderr.decode(errors="ignore"), proc.returncode


async def _run_yt_dlp(
    cmd: list[str],
    timeout: int,
    progress_cb: Optional[ProgressCallback] = None,
    *,
    cwd: Optional[str] = None,
) -> tuple[str, str, int]:
    """Run yt-dlp command while streaming stdout for progress updates."""

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []

    async def _drain_stream(stream: Optional[asyncio.StreamReader], chunks: list[bytes], parse_progress: bool) -> None:
        if stream is None:
            return
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise asyncio.TimeoutError
            line = await asyncio.wait_for(stream.readline(), remaining)
            if not line:
                break
            chunks.append(line)
            if parse_progress and progress_cb:
                event = _parse_progress_line(line.decode(errors="ignore"))
                if event:
                    await progress_cb(event)

    try:
        await asyncio.gather(
            _drain_stream(proc.stdout, stdout_chunks, True),
            _drain_stream(proc.stderr, stderr_chunks, False),
        )
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise asyncio.TimeoutError
        await asyncio.wait_for(proc.wait(), remaining)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        raise DownloadError("Таймаут выполнения внешней команды.")

    stdout = b"".join(stdout_chunks).decode(errors="ignore")
    stderr = b"".join(stderr_chunks).decode(errors="ignore")
    return stdout, stderr, proc.returncode

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

async def download_video(
    url: str,
    output_dir: Path,
    timeout: int = 20 * 60,
    cookies_file: Optional[str] = None,
    progress_cb: Optional[ProgressCallback] = None,
    format_spec: Optional[str] = None,
    expect_audio: bool = True,
    expect_video: bool = True,
) -> Path:
    """Скачивает видео, транслируя прогресс и обновляя Instagram-cookies при необходимости."""
    output_dir.mkdir(parents=True, exist_ok=True)
    cached_path = await _try_cache_get(url, output_dir)
    if cached_path:
        return cached_path
    attempts = 2
    last_error: Optional[DownloadError] = None
    for attempt in range(attempts):
        try:
            result = await _download_once(
                url,
                output_dir,
                timeout,
                cookies_file,
                progress_cb=progress_cb,
                format_spec=format_spec,
                expect_audio=expect_audio,
                expect_video=expect_video,
            )
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


async def _download_once(
    url: str,
    output_dir: Path,
    timeout: int,
    cookies_file: Optional[str],
    *,
    progress_cb: Optional[ProgressCallback] = None,
    format_spec: Optional[str] = None,
    expect_audio: bool = True,
    expect_video: bool = True,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    workdir = output_dir.resolve()
    workdir_str = str(workdir)
    output_template = "%(title).100s-%(id)s.%(ext)s"
    user_agent = os.environ.get(
        "YTDLP_USER_AGENT",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
    )
    cmd = [
        "yt-dlp",
        "--no-playlist",
        "--newline",
        "-f",
        format_spec or "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best",
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
        stdout, stderr, rc = await _run_yt_dlp(
            cmd + [url],
            timeout=timeout,
            progress_cb=progress_cb,
            cwd=workdir_str,
        )
    except FileNotFoundError as e:
        logger.exception("yt-dlp не найден.")
        raise DownloadError("yt-dlp не найден. Убедитесь, что он установлен и доступен в PATH.") from e
    except DownloadError as e:
        logger.exception("Ошибка yt-dlp (timeout?)")
        raise

    if rc != 0:
        logger.error("yt-dlp завершился с кодом %s: %s", rc, stderr[:2000])
        last_line = stderr.splitlines()[-1] if stderr else "unknown error"
        cookies_path = _resolve_instagram_cookies_path(cookies_file)
        if _should_try_instagram_fallback(url, last_line, cookies_path):
            logger.warning("Instagram reported restricted media, invoking API fallback")
            try:
                assert instagram_direct is not None  # for type checkers
                return await instagram_direct.download_sensitive_media(
                    url=url,
                    output_dir=workdir,
                    cookies_file=cookies_path,
                )
            except Exception as fallback_err:
                logger.warning("Instagram API fallback failed: %s", fallback_err)
                last_line = f"{last_line} (fallback failed: {fallback_err})"
        raise DownloadError(f"Ошибка yt-dlp: {last_line}")

    candidates = [p for p in workdir.iterdir() if p.is_file()]
    if not candidates:
        raise DownloadError("Файл не найден после завершения yt-dlp.")

    downloaded = sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)[0]
    logger.info("Первичный файл: %s (%.2f MB)", downloaded, downloaded.stat().st_size / 1024 / 1024)

    # Проверяем с помощью ffprobe наличие аудио+видео
    probes = await _ffprobe_has_audio_or_video(downloaded)
    logger.debug("ffprobe result: %s", probes)

    has_video = probes.get("has_video")
    has_audio = probes.get("has_audio")
    needs_audio = expect_audio and not has_audio
    needs_video = expect_video and not has_video

    if not needs_audio and not needs_video:
        return downloaded

    if needs_audio and not needs_video and has_video:
        logger.info("Файл не содержит аудио. Пробуем скачать аудио отдельно и смержить.")
        audio_template = "%(title).100s-%(id)s.%(ext)s"
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

        stdout_a, stderr_a, rc_a = await _run_yt_dlp(
            audio_cmd + [url],
            timeout=timeout,
            cwd=workdir_str,
        )
        if rc_a != 0:
            last_line = (stderr_a.splitlines()[-1].strip() if stderr_a else "unknown error")
            logger.error("Не удалось скачать аудио отдельно: %s", last_line)
            if "requested format is not available" in last_line.lower():
                logger.warning("Аудио-трек недоступен как отдельный формат. Возвращаем исходный файл без доп. мерджа.")
                return downloaded
            raise DownloadError(f"Не удалось скачать аудио для объединения: {last_line}")

        # Найдём скачанный аудиофайл
        candidates2 = [p for p in workdir.iterdir() if p.is_file() and p != downloaded]
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

    if needs_video and not needs_audio and has_audio:
        logger.info("Файл содержит только аудио. Пробуем скачать video отдельно и смержить.")
        video_template = "%(title).100s-%(id)s.%(ext)s"
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

        stdout_v, stderr_v, rc_v = await _run_yt_dlp(
            video_cmd + [url],
            timeout=timeout,
            cwd=workdir_str,
        )
        if rc_v != 0:
            last_line = (stderr_v.splitlines()[-1].strip() if stderr_v else "unknown error")
            logger.error("Не удалось скачать video отдельно: %s", last_line)
            if "requested format is not available" in last_line.lower():
                logger.warning("Видео-трек недоступен как отдельный формат. Возвращаем исходный файл без доп. мерджа.")
                return downloaded
            raise DownloadError(f"Не удалось скачать видео для объединения: {last_line}")

        # Найдём скачанный видеофайл
        candidates3 = [p for p in workdir.iterdir() if p.is_file() and p != downloaded]
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


def _resolve_instagram_cookies_path(explicit: Optional[str]) -> Optional[str]:
    if explicit:
        return explicit
    fallback = getattr(config, "YTDLP_COOKIES_FILE", None) or getattr(config, "IG_COOKIES_PATH", None)
    return fallback


def _should_try_instagram_fallback(url: str, error_line: str, cookies_path: Optional[str]) -> bool:
    if not error_line:
        return False
    if "instagram.com" not in url.lower():
        return False
    if instagram_direct is None:
        logger.warning("Instagram fallback unavailable: services.instagram_direct not imported")
        return False
    if not cookies_path:
        logger.warning("Instagram fallback skipped: cookies path unavailable")
        return False
    lowered = error_line.lower()
    trigger_phrases = (
        "inappropriate",
        "certain audiences",
        "login",
        "private",
        "not available",
        "no video formats",
        "owner restricted",
    )
    return any(phrase in lowered for phrase in trigger_phrases)
