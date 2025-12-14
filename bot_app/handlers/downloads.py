"""Handlers responsible for processing download requests."""

from __future__ import annotations

import math
import shutil
import time
from pathlib import Path
from typing import Optional
from uuid import uuid4

from aiogram import types
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup

import config
from bot_app import quota as quota_ui
from bot_app import state
from bot_app.helpers import (
    detect_platform,
    extract_first_url_from_text,
    extract_url_from_entities,
    resolve_chat_title,
    resolve_user_display,
)
from bot_app.metrics import update_active_downloads_gauge, update_pending_tokens_gauge, update_queue_gauges
from bot_app.runtime import bot, dp, global_download_semaphore, logger
from bot_app.ui import status as status_ui
from bot_app.ui.i18n import get_locale, translate
from monitoring import add_breadcrumb, capture_exception, increment_metric, request_context, set_metric_gauge
from services.file_scanner import ensure_file_is_safe
from services import quotas as quota_service
from utils.access_control import check_and_log_access, get_access_denied_message, is_user_allowed
from utils.downloader import DownloadError, download_video
from utils.url_validation import UnsafeURLError, ensure_safe_public_url


def _choose_text_source(message: types.Message) -> str:
    """Return preferred textual payload for URL parsing."""

    return (message.text or message.caption or "").strip()


async def _safe_status_edit(status_msg: types.Message, text: str, **kwargs) -> None:
    if not status_msg:
        return
    try:
        await status_msg.edit_text(text, **kwargs)
    except Exception:
        logger.debug("Не удалось обновить статусное сообщение", exc_info=True)


async def _safe_delete_message(message: types.Message) -> None:
    if not message:
        return
    try:
        await message.delete()
    except TelegramAPIError as e:
        if "forbidden" in str(e).lower() or getattr(e, "status_code", None) == 403:
            logger.warning("Нет прав удалить сообщение пользователя")
        else:
            logger.exception("Ошибка удаления сообщения пользователя: %s", e)
    except Exception:
        logger.debug("Не удалось удалить сообщение пользователя", exc_info=True)


@dp.message(Command("download"))
async def download_command_handler(message: types.Message):
    """Handle /download commands (optionally replying to a message)."""

    text = _choose_text_source(message)
    parts = text.split(None, 1)
    url = parts[1].strip() if len(parts) > 1 else None
    locale = get_locale(getattr(getattr(message, "from_user", None), "language_code", None))

    if not url and getattr(message, "reply_to_message", None):
        reply = message.reply_to_message
        url = extract_url_from_entities(reply) or extract_first_url_from_text(reply.text or reply.caption or "")

    if not url:
        await message.reply(translate("download.prompt_url", locale))
        return

    await _process_download_flow(message, url, locale)


@dp.message(lambda message: not ((message.text or message.caption or "").strip().startswith("/")))
async def universal_handler(message: types.Message):
    """Entry point for all download requests that are not commands."""

    text = _choose_text_source(message)
    if not text:
        return

    url = extract_url_from_entities(message) or extract_first_url_from_text(text)

    if not url:
        return

    locale = get_locale(getattr(getattr(message, "from_user", None), "language_code", None))
    await _process_download_flow(message, url, locale)


async def _process_download_flow(
    message: types.Message,
    url: str,
    locale: str,
    *,
    request_id: Optional[str] = None,
) -> None:
    process_started = time.perf_counter()
    uid = getattr(message.from_user, "id", 0)
    chat_id = getattr(message.chat, "id", None)
    chat_type = getattr(message.chat, "type", "")
    context_source = "group" if chat_type in ("group", "supergroup") else "direct"
    request_id = request_id or uuid4().hex
    tmpdir: Optional[Path] = None
    status_msg: Optional[types.Message] = None
    active_slot_acquired = False

    with request_context(
        request_id=request_id,
        user_id=uid,
        chat_id=chat_id,
        channel=chat_type,
        source=context_source,
    ) as ctx:
        ctx["locale"] = locale
        add_breadcrumb("download.start", chat_type=chat_type, url=url)
        increment_metric("downloads.total")

        try:
            if not await is_user_allowed(message):
                increment_metric("downloads.denied")
                try:
                    await message.reply(get_access_denied_message())
                except Exception:
                    logger.exception("Не удалось отправить сообщение об отказе в доступе")
                await check_and_log_access(message)
                return

            try:
                ensure_safe_public_url(url)
            except UnsafeURLError as err:
                increment_metric("downloads.blocked")
                await message.reply(str(err))
                return

            if config.ENABLE_HISTORY:
                try:
                    from db import upsert_chat

                    upsert_chat(
                        chat_id=chat_id,
                        title=resolve_chat_title(message.chat),
                        chat_type=chat_type,
                    )
                except Exception:
                    logger.debug("Не удалось обновить сведения о чате", exc_info=True)

            user_display = resolve_user_display(message.from_user)

            platform = detect_platform(url)
            ctx["platform"] = platform
            if not platform:
                increment_metric("downloads.unsupported")
                if chat_type not in ("group", "supergroup"):
                    await message.reply(translate("download.unsupported", locale))
                return
            platform_label = (platform or "unknown").capitalize()

            quota_plan = None
            if config.ENABLE_HISTORY:
                try:
                    quota_plan = quota_service.build_enforcement_plan(uid)
                except Exception:
                    logger.debug("Не удалось получить данные квот", exc_info=True)
            if quota_plan and quota_plan.get("blocked"):
                block_text = quota_ui.quota_block_message(quota_plan, locale) or translate(
                    "download.cooldown", locale, seconds=60
                )
                await message.reply(block_text)
                return

            max_per_user = getattr(config, "MAX_CONCURRENT_PER_USER", 2)
            active = state.user_active_downloads.get(uid, 0)
            if active >= max_per_user and chat_type not in ("group", "supergroup"):
                await message.reply(
                    translate("download.active_limit", locale, active=active, limit=max_per_user)
                )
                return

            cooldown = max(0, getattr(config, "USER_COOLDOWN_SECONDS", 5))
            now = time.time()
            last_ts = state.user_last_request_ts.get(uid, 0.0)
            if cooldown and last_ts:
                elapsed = now - last_ts
                if elapsed < cooldown:
                    wait = max(1, math.ceil(cooldown - elapsed))
                    await message.reply(translate("download.cooldown", locale, seconds=wait))
                    return

            if chat_type in ("group", "supergroup"):
                token = uuid4().hex
                state.pending_downloads[token] = {
                    "url": url,
                    "initiator_id": uid,
                    "ts": time.time(),
                    "source_chat_id": chat_id,
                    "source_message_id": getattr(message, "message_id", None),
                }
                update_pending_tokens_gauge()
                kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text=translate("download.group_button", locale),
                                callback_data=f"download:{token}",
                            )
                        ]
                    ]
                )
                try:
                    await message.reply(translate("download.group_button_prompt", locale), reply_markup=kb)
                except Exception as e:
                    logger.exception("Не удалось отправить сообщение с кнопкой в группе.")
                    try:
                        capture_exception(e)
                    except Exception:
                        pass
                return

            state.user_last_request_ts[uid] = now
            state.user_active_downloads[uid] = active + 1
            active_slot_acquired = True
            update_active_downloads_gauge()

            status_msg = await message.reply(
                status_ui.waiting(
                    platform,
                    state.user_active_downloads.get(uid, 0),
                    max_per_user,
                    locale=locale,
                )
            )

            tmpdir = Path(config.TEMP_DIR) / f"{uid}_{uuid4().hex[:12]}"
            tmpdir.mkdir(parents=True, exist_ok=True)

            cookies_file = getattr(config, "YTDLP_COOKIES_FILE", None)
            logger.info("Waiting for global download slot...")
            await _safe_status_edit(status_msg, status_ui.downloading(platform, locale=locale))
            progress_callback = None
            if status_msg:
                progress_callback = status_ui.build_progress_callback(
                    lambda text: _safe_status_edit(status_msg, text),
                    platform,
                    locale=locale,
                )
            wait_started = time.perf_counter()
            async with global_download_semaphore:
                wait_ms = int((time.perf_counter() - wait_started) * 1000)
                increment_metric("downloads.wait_time_ms_total", wait_ms)
                increment_metric("downloads.wait_time_events")
                set_metric_gauge("downloads.wait_last_ms", wait_ms)
                update_queue_gauges()
                logger.info("Acquired global download slot")
                downloaded_path = await download_video(
                    url,
                    tmpdir,
                    timeout=config.DOWNLOAD_TIMEOUT_SECONDS,
                    cookies_file=cookies_file,
                    progress_cb=progress_callback,
                )
            logger.info("Released global download slot")
            update_queue_gauges()
            await ensure_file_is_safe(downloaded_path)
            await _safe_status_edit(status_msg, status_ui.processing(platform, locale=locale))

            size = downloaded_path.stat().st_size
            if size > config.TELEGRAM_MAX_FILE_BYTES:
                await _safe_status_edit(status_msg, translate("download.large_file_limit", locale))
                return

            caption = translate("download.video_caption", locale, platform=platform_label)
            try:
                await _safe_status_edit(status_msg, status_ui.sending(platform, locale=locale))
                file_obj = FSInputFile(path=str(downloaded_path))
                await bot.send_video(
                    chat_id=message.chat.id,
                    video=file_obj,
                    caption=caption,
                    supports_streaming=True,
                )
            except TelegramBadRequest as e:
                logger.warning("send_video failed (%s), trying send_document", e)
                try:
                    capture_exception(e)
                except Exception:
                    pass
                try:
                    await _safe_status_edit(status_msg, status_ui.sending(platform, locale=locale))
                    file_obj = FSInputFile(path=str(downloaded_path))
                    await bot.send_document(
                        chat_id=message.chat.id,
                        document=file_obj,
                        caption=caption,
                    )
                except Exception as e2:
                    logger.exception("Не удалось отправить как документ: %s", e2)
                    try:
                        capture_exception(e2)
                    except Exception:
                        pass
                    await _safe_status_edit(
                        status_msg,
                        translate("download.telegram_send_error", locale, reason=str(e2)),
                    )
                    return

            await _safe_status_edit(
                status_msg,
                status_ui.success(platform, locale=locale),
                reply_markup=status_ui.success_markup(url, locale=locale),
            )
            await _safe_delete_message(message)
            increment_metric("downloads.success")
            add_breadcrumb("download.success", size=size, platform=platform)

            if config.ENABLE_HISTORY:
                try:
                    from db import add_download  # local import to avoid cycles

                    add_download(
                        user_id=uid,
                        username=user_display,
                        platform=platform,
                        url=url,
                        chat_id=message.chat.id,
                        status="success",
                        file_size_bytes=size,
                    )
                    try:
                        quota_service.consume_success(uid)
                    except Exception:
                        logger.debug("Не удалось обновить счётчик квот", exc_info=True)
                except Exception as e:
                    logger.debug("Ошибка при логировании в БД: %s", e)

        except DownloadError as e:
            increment_metric("downloads.failure")
            logger.exception("DownloadError: %s", e)
            try:
                capture_exception(e)
            except Exception:
                pass
            await _safe_status_edit(status_msg, status_ui.error(str(e), locale=locale))
            if config.ENABLE_HISTORY:
                try:
                    from db import add_download

                    add_download(
                        user_id=uid,
                        username=user_display,
                        platform=ctx.get("platform"),
                        url=url,
                        chat_id=message.chat.id,
                        status="error",
                        error_message=str(e),
                    )
                except Exception:
                    logger.debug("Ошибка при логировании ошибки в БД")
        except Exception as e:
            increment_metric("downloads.failure")
            logger.exception("Непредвиданная ошибка", exc_info=e)
            try:
                capture_exception(e)
            except Exception:
                pass
            await _safe_status_edit(status_msg, status_ui.error(str(e), locale=locale))
            if config.ENABLE_HISTORY:
                try:
                    from db import add_download

                    add_download(
                        user_id=uid,
                        username=user_display,
                        platform=ctx.get("platform"),
                        url=url,
                        chat_id=message.chat.id,
                        status="error",
                        error_message=str(e),
                    )
                except Exception:
                    logger.debug("Ошибка при логировании в БД")
        finally:
            duration_ms = int((time.perf_counter() - process_started) * 1000)
            increment_metric("downloads.duration_ms_total", duration_ms)
            increment_metric("downloads.duration_events")
            if active_slot_acquired:
                state.user_active_downloads[uid] = max(0, state.user_active_downloads.get(uid, 0) - 1)
                update_active_downloads_gauge()
            if tmpdir:
                shutil.rmtree(tmpdir, ignore_errors=True)
