"""Handlers responsible for processing download requests."""

from __future__ import annotations

import asyncio
import math
import shutil
import time
from pathlib import Path
from typing import Optional
from uuid import uuid4

from aiogram import types
from aiogram.exceptions import TelegramBadRequest, TelegramAPIError
from aiogram.filters import Command
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton

import config
from bot_app.helpers import (
    detect_platform,
    extract_url_from_entities,
    extract_first_url_from_text,
    resolve_chat_title,
    resolve_user_display,
)
from bot_app.runtime import bot, dp, global_download_semaphore, logger
from bot_app import state
from bot_app.ui import status as status_ui
from monitoring import capture_exception
from utils.access_control import is_user_allowed, get_access_denied_message, check_and_log_access
from utils.downloader import download_video, DownloadError


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

    if not url and getattr(message, "reply_to_message", None):
        reply = message.reply_to_message
        url = extract_url_from_entities(reply) or extract_first_url_from_text(reply.text or reply.caption or "")

    if not url:
        await message.reply(
            "Пришлите ссылку после /download или ответьте этой командой на сообщение с ссылкой."
        )
        return

    await _process_download_flow(message, url)


@dp.message(lambda message: not ((message.text or message.caption or "").strip().startswith("/")))
async def universal_handler(message: types.Message):
    """Entry point for all download requests that are not commands."""
    text = _choose_text_source(message)
    if not text:
        return

    url = extract_url_from_entities(message) or extract_first_url_from_text(text)

    if not url:
        return

    await _process_download_flow(message, url)


async def _process_download_flow(message: types.Message, url: str) -> None:
    if not await is_user_allowed(message):
        try:
            await message.reply(get_access_denied_message())
        except Exception:
            logger.exception("Не удалось отправить сообщение об отказе в доступе")
        await check_and_log_access(message)
        return

    if config.ENABLE_HISTORY:
        try:
            from db import upsert_chat

            upsert_chat(
                chat_id=message.chat.id,
                title=resolve_chat_title(message.chat),
                chat_type=getattr(message.chat, "type", None),
            )
        except Exception:
            logger.debug("Не удалось обновить сведения о чате", exc_info=True)

    uid = message.from_user.id
    user_display = resolve_user_display(message.from_user)
    chat_type = getattr(message.chat, "type", "")
    platform = detect_platform(url)
    if not platform:
        if chat_type not in ("group", "supergroup"):
            await message.reply("Неподдерживаемая ссылка. Доступно: YouTube, TikTok, Instagram.")
        return

    max_per_user = getattr(config, "MAX_CONCURRENT_PER_USER", 2)
    active = state.user_active_downloads.get(uid, 0)
    if active >= max_per_user and chat_type not in ("group", "supergroup"):
        await message.reply(f"У вас уже {active} активных загрузок (максимум {max_per_user}). Подождите их завершения.")
        return

    cooldown = max(0, getattr(config, "USER_COOLDOWN_SECONDS", 5))
    now = time.time()
    last_ts = state.user_last_request_ts.get(uid, 0.0)
    if cooldown and last_ts:
        elapsed = now - last_ts
        if elapsed < cooldown:
            wait = max(1, math.ceil(cooldown - elapsed))
            await message.reply(f"Слишком часто! Подождите ещё {wait} с.")
            return

    if chat_type in ("group", "supergroup"):
        token = uuid4().hex
        state.pending_downloads[token] = {
            "url": url,
            "initiator_id": uid,
            "ts": time.time(),
            "source_chat_id": message.chat.id,
            "source_message_id": getattr(message, "message_id", None),
        }
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="Download", callback_data=f"download:{token}")]]
        )
        try:
            await message.reply("Нажмите кнопку, чтобы скачать видео.", reply_markup=kb)
        except Exception as e:
            logger.exception("Не удалось отправить сообщение с кнопкой в группе.")
            try:
                capture_exception(e)
            except Exception:
                pass
        return

    state.user_last_request_ts[uid] = now
    state.user_active_downloads[uid] = active + 1

    status_msg = await message.reply(
        status_ui.waiting(platform, state.user_active_downloads.get(uid, 0), max_per_user)
    )

    tmpdir = Path(config.TEMP_DIR) / f"{uid}_{int(time.time())}"
    tmpdir.mkdir(parents=True, exist_ok=True)

    try:
        cookies_file = getattr(config, "YTDLP_COOKIES_FILE", None)
        logger.info("Waiting for global download slot...")
        await _safe_status_edit(status_msg, status_ui.downloading(platform))
        async with global_download_semaphore:
            logger.info("Acquired global download slot")
            downloaded_path = await download_video(
                url,
                tmpdir,
                timeout=config.DOWNLOAD_TIMEOUT_SECONDS,
                cookies_file=cookies_file,
            )
        logger.info("Released global download slot")
        await _safe_status_edit(status_msg, status_ui.processing(platform))

        size = downloaded_path.stat().st_size
        if size > config.TELEGRAM_MAX_FILE_BYTES:
            await _safe_status_edit(status_msg, "Видео слишком большое для Telegram (лимит 2 ГБ).")
            return

        try:
            await _safe_status_edit(status_msg, status_ui.sending(platform))
            file_obj = FSInputFile(path=str(downloaded_path))
            await bot.send_video(
                chat_id=message.chat.id,
                video=file_obj,
                caption=f"Видео скачано с {platform} — @MediaBanditbot",
                supports_streaming=True,
            )
        except TelegramBadRequest as e:
            logger.warning("send_video failed (%s), trying send_document", e)
            try:
                capture_exception(e)
            except Exception:
                pass
            try:
                await _safe_status_edit(status_msg, status_ui.sending(platform))
                file_obj = FSInputFile(path=str(downloaded_path))
                await bot.send_document(
                    chat_id=message.chat.id,
                    document=file_obj,
                    caption=f"Видео (файл) — скачано с помощью @MediaBanditbot",
                )
            except Exception as e2:
                logger.exception("Не удалось отправить как документ: %s", e2)
                try:
                    capture_exception(e2)
                except Exception:
                    pass
                await _safe_status_edit(status_msg, "Ошибка отправки файла в Telegram: " + str(e2))
                return

        await _safe_status_edit(
            status_msg,
            status_ui.success(platform),
            reply_markup=status_ui.success_markup(url),
        )
        await _safe_delete_message(message)

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
            except Exception as e:
                logger.debug("Ошибка при логировании в БД: %s", e)

    except DownloadError as e:
        logger.exception("DownloadError: %s", e)
        try:
            capture_exception(e)
        except Exception:
            pass
        await _safe_status_edit(status_msg, status_ui.error(str(e)))
        if config.ENABLE_HISTORY:
            try:
                from db import add_download

                add_download(
                    user_id=uid,
                    username=user_display,
                    platform=platform,
                    url=url,
                    chat_id=message.chat.id,
                    status="error",
                    error_message=str(e),
                )
            except Exception:
                logger.debug("Ошибка при логировании ошибки в БД")
    except Exception as e:
        logger.exception("Непредвиданная ошибка", exc_info=e)
        try:
            capture_exception(e)
        except Exception:
            pass
        await _safe_status_edit(status_msg, status_ui.error(str(e)))
        if config.ENABLE_HISTORY:
            try:
                from db import add_download

                add_download(
                    user_id=uid,
                    username=user_display,
                    platform=platform,
                    url=url,
                    chat_id=message.chat.id,
                    status="error",
                    error_message=str(e),
                )
            except Exception:
                logger.debug("Ошибка при логировании в БД")
    finally:
        state.user_active_downloads[uid] = max(0, state.user_active_downloads.get(uid, 1) - 1)
        shutil.rmtree(tmpdir, ignore_errors=True)
