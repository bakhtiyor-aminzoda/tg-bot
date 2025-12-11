"""Handlers for inline callback confirmations."""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from aiogram import types
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import FSInputFile

import config
from bot_app.helpers import detect_platform, resolve_chat_title
from bot_app.runtime import bot, dp, global_download_semaphore, logger
from bot_app import state
from bot_app.ui import status as status_ui
from monitoring import capture_exception
from utils.access_control import is_user_allowed, get_access_denied_message, check_and_log_access
from utils.downloader import download_video, DownloadError


async def _safe_status_edit(status_msg: types.Message, text: str, **kwargs) -> None:
    if not status_msg:
        return
    try:
        await status_msg.edit_text(text, **kwargs)
    except Exception:
        logger.debug("Не удалось обновить статусное сообщение (callback)", exc_info=True)


async def _safe_delete_original_message(chat_id: int | None, message_id: int | None) -> None:
    if chat_id is None or message_id is None:
        return
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception:
        logger.debug("Не удалось удалить исходное сообщение пользователя (group)", exc_info=True)


@dp.callback_query()
async def handle_download_callback(callback: types.CallbackQuery):
    """Handle inline Download button clicks (callback_data: download:<token>)."""
    logger.info("Received callback_query: %s from %s", callback.data, getattr(callback.from_user, "id", None))
    data = callback.data or ""
    if not data.startswith("download:"):
        return

    token = data.split(":", 1)[1]
    entry = state.pending_downloads.pop(token, None)
    if not entry:
        await callback.answer("Ссылка устарела или недоступна.", show_alert=True)
        return

    if time.time() - entry.get("ts", 0) > state.PENDING_TOKEN_TTL:
        await callback.answer("Срок действия кнопки истёк.", show_alert=True)
        return

    url = entry.get("url")
    uid = callback.from_user.id
    username = callback.from_user.username
    initiator_id = entry.get("initiator_id")
    source_chat_id = entry.get("source_chat_id")
    source_message_id = entry.get("source_message_id")

    if config.ENABLE_HISTORY and getattr(callback, "message", None):
        try:
            from db import upsert_chat

            upsert_chat(
                chat_id=callback.message.chat.id,
                title=resolve_chat_title(callback.message.chat),
                chat_type=getattr(callback.message.chat, "type", None),
            )
        except Exception:
            logger.debug("Не удалось обновить сведения о чате (callback)", exc_info=True)

    if not await is_user_allowed(callback.message):
        await callback.answer(get_access_denied_message(), show_alert=True)
        await check_and_log_access(callback.message)
        return

    active = state.user_active_downloads.get(uid, 0)
    max_per_user = getattr(config, "MAX_CONCURRENT_PER_USER", 2)
    if active >= max_per_user:
        await callback.answer(f"У вас уже {active} активных загрузок (максимум {max_per_user}).", show_alert=True)
        return

    last_ts = state.user_last_request_ts.get(uid, 0)
    if active == 0 and (time.time() - last_ts) < config.USER_COOLDOWN_SECONDS:
        await callback.answer("Слишком часто! Подождите немного.", show_alert=True)
        return

    state.user_last_request_ts[uid] = time.time()
    state.user_active_downloads[uid] = active + 1

    try:
        await callback.answer("Запускаю...")
    except Exception:
        pass

    platform = detect_platform(url)
    if not platform:
        state.user_active_downloads[uid] = max(0, state.user_active_downloads.get(uid, 1) - 1)
        await callback.answer("Неподдерживаемая ссылка. Доступно: YouTube, TikTok, Instagram.", show_alert=True)
        return

    status_msg = await callback.message.reply(
        status_ui.waiting(platform, state.user_active_downloads.get(uid, 0), max_per_user)
    )
    tmpdir = Path(config.TEMP_DIR) / f"{uid}_{int(time.time())}"
    tmpdir.mkdir(parents=True, exist_ok=True)
    try:
        cookies_file = getattr(config, "YTDLP_COOKIES_FILE", None)
        logger.info("Waiting for global download slot (callback)...")
        await _safe_status_edit(status_msg, status_ui.downloading(platform))
        async with global_download_semaphore:
            logger.info("Acquired global download slot (callback)")
            downloaded_path = await download_video(
                url,
                tmpdir,
                timeout=config.DOWNLOAD_TIMEOUT_SECONDS,
                cookies_file=cookies_file,
            )
        logger.info("Released global download slot (callback)")
        await _safe_status_edit(status_msg, status_ui.processing(platform))

        size = downloaded_path.stat().st_size
        if size > config.TELEGRAM_MAX_FILE_BYTES:
            await _safe_status_edit(status_msg, "Видео слишком большое для Telegram (лимит 2 ГБ).")
            return

        try:
            await _safe_status_edit(status_msg, status_ui.sending(platform))
            file_obj = FSInputFile(path=str(downloaded_path))
            await bot.send_video(
                chat_id=callback.message.chat.id,
                video=file_obj,
                caption="Видео скачано — @MediaBanditbot",
            )
        except TelegramBadRequest as e:
            try:
                capture_exception(e)
            except Exception:
                pass
            try:
                await _safe_status_edit(status_msg, status_ui.sending(platform))
                file_obj = FSInputFile(path=str(downloaded_path))
                await bot.send_document(
                    chat_id=callback.message.chat.id,
                    document=file_obj,
                    caption="Видео (файл) — скачано с помощью @MediaBanditbot",
                )
            except Exception as e2:
                logger.exception("Не удалось отправить файл в группу: %s", e2)
                try:
                    capture_exception(e2)
                except Exception:
                    pass
                await _safe_status_edit(status_msg, "Ошибка отправки файла в Telegram: " + str(e2))
                return

        try:
            await callback.message.delete()
        except Exception:
            logger.debug("Не удалось удалить сообщение с кнопкой (возможно нет прав).")

        await _safe_status_edit(
            status_msg,
            status_ui.success(platform),
            reply_markup=status_ui.success_markup(url),
        )
        await _safe_delete_original_message(source_chat_id, source_message_id)

        if config.ENABLE_HISTORY:
            try:
                from db import add_download

                add_download(
                    user_id=uid,
                    username=username,
                    platform=platform,
                    url=url,
                    chat_id=callback.message.chat.id,
                    status="success",
                    file_size_bytes=size,
                )
            except Exception as log_err:
                logger.debug("Failed to log success to DB: %s", log_err)

    except DownloadError as e:
        await _log_and_report_callback_error(callback, status_msg, e, url, uid, username, platform)
    except Exception as e:
        await _log_and_report_callback_error(callback, status_msg, e, url, uid, username, platform)
    finally:
        state.user_active_downloads[uid] = max(0, state.user_active_downloads.get(uid, 1) - 1)
        shutil.rmtree(tmpdir, ignore_errors=True)


async def _log_and_report_callback_error(
    callback: types.CallbackQuery,
    status_msg: types.Message | None,
    error: Exception,
    url: str,
    uid: int,
    username: str,
    platform: str,
):
    logger.exception("Ошибка при обработке callback: %s", error)
    try:
        capture_exception(error)
    except Exception:
        pass
    if config.ENABLE_HISTORY:
        try:
            from db import add_download

            add_download(
                user_id=uid,
                username=username,
                platform=platform,
                url=url,
                chat_id=callback.message.chat.id,
                status="error",
                file_size_bytes=0,
                error_message=str(error),
            )
        except Exception as log_err:
            logger.debug("Failed to log error to DB: %s", log_err)
    await _safe_status_edit(status_msg, status_ui.error(str(error)))
