"""Handlers for inline callback confirmations."""

from __future__ import annotations

import math
import shutil
import time
from pathlib import Path
from typing import Optional
from uuid import uuid4

from aiogram import types
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import FSInputFile

import config
from bot_app import quota as quota_ui
from bot_app.referral import build_referral_card
from bot_app.helpers import detect_platform, resolve_chat_title, resolve_user_display
from bot_app.runtime import bot, dp, global_download_semaphore, logger
from bot_app import state
from bot_app.ui import status as status_ui
from bot_app.ui.i18n import get_locale, translate
from monitoring import (
    add_breadcrumb,
    capture_exception,
    increment_metric,
    request_context,
    set_metric_gauge,
)
from bot_app.metrics import update_active_downloads_gauge, update_pending_tokens_gauge, update_queue_gauges
from utils.access_control import is_user_allowed, get_access_denied_message, check_and_log_access
from services.file_scanner import ensure_file_is_safe
from utils.downloader import download_video, DownloadError, is_image_file
from utils.url_validation import ensure_safe_public_url, UnsafeURLError
from services import quotas as quota_service
from services import referrals as referral_service


async def _update_referral_card(callback: types.CallbackQuery, locale: str) -> None:
    if not callback.message:
        return
    text, markup = build_referral_card(callback.from_user.id, locale)
    try:
        await callback.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest:
        await callback.message.answer(text, reply_markup=markup)


@dp.callback_query(lambda c: (c.data or "").startswith("referral:"))
async def handle_referral_callback(callback: types.CallbackQuery):
    data = callback.data or ""
    parts = data.split(":", 2)
    action = parts[1] if len(parts) > 1 else ""
    locale = get_locale(getattr(callback.from_user, "language_code", None))

    if action == "gen":
        try:
            referral_service.create_referral_code(callback.from_user.id)
        except ValueError as exc:
            await callback.answer(str(exc), show_alert=True)
            return
        await _update_referral_card(callback, locale)
        await callback.answer("✅")
        return
    if action == "copy":
        code = parts[2] if len(parts) > 2 else ""
        if not code:
            await callback.answer(translate("referral.copy_fail", locale), show_alert=True)
            return
        await callback.answer(f"{translate('referral.copy_success', locale)}\n{code}", show_alert=True)
        return
    if action == "leaderboard":
        rows = referral_service.referral_leaderboard(limit=5)
        if not rows:
            await callback.answer(translate("referral.leaderboard_empty", locale), show_alert=True)
            return
        lines = [translate("referral.leaderboard_header", locale)]
        for idx, row in enumerate(rows, start=1):
            lines.append(
                translate(
                    "referral.leaderboard_line",
                    locale,
                    place=idx,
                    user=row.get("user_id"),
                    count=row.get("rewarded", 0),
                    daily=row.get("daily_bonus", 0),
                    monthly=row.get("monthly_bonus", 0),
                )
            )
        text = "\n".join(lines)
        if callback.message:
            await callback.message.answer(text)
        await callback.answer()
        return

    await callback.answer()


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


def _consume_chat_rate_slot(chat_id: int | None, now: float) -> bool:
    cooldown = getattr(config, "CALLBACK_CHAT_COOLDOWN_SECONDS", 0)
    if not chat_id or cooldown <= 0:
        return True
    last = state.chat_last_callback_ts.get(chat_id, 0.0)
    if last and now - last < cooldown:
        return False
    state.chat_last_callback_ts[chat_id] = now
    return True


def _consume_global_rate_slot(now: float) -> bool:
    limit = getattr(config, "CALLBACK_GLOBAL_MAX_CALLS", 0)
    window = getattr(config, "CALLBACK_GLOBAL_WINDOW_SECONDS", 60)
    if limit <= 0 or window <= 0:
        return True
    events = state.global_callback_events
    while events and now - events[0] > window:
        events.popleft()
    if len(events) >= limit:
        return False
    events.append(now)
    return True


@dp.callback_query(lambda c: (c.data or "").startswith("download:"))
async def handle_download_callback(callback: types.CallbackQuery):
    """Handle inline Download button clicks (callback_data: download:<token>)."""
    logger.info("Received callback_query: %s from %s", callback.data, getattr(callback.from_user, "id", None))
    data = callback.data or ""
    token = data.split(":", 1)[1]
    entry = state.pending_downloads.pop(token, None)
    update_pending_tokens_gauge()
    locale = get_locale(getattr(callback.from_user, "language_code", None))
    if not entry:
        await callback.answer(translate("download.pending_missing", locale), show_alert=True)
        return

    if time.time() - entry.get("ts", 0) > state.PENDING_TOKEN_TTL:
        await callback.answer(translate("download.pending_expired", locale), show_alert=True)
        return

    url = entry.get("url")
    uid = callback.from_user.id
    username = resolve_user_display(callback.from_user)
    initiator_id = entry.get("initiator_id")
    source_chat_id = entry.get("source_chat_id")
    source_message_id = entry.get("source_message_id")
    process_started = time.perf_counter()
    request_id = uuid4().hex
    message_chat = getattr(callback, "message", None)
    tg_chat = getattr(message_chat, "chat", None)
    chat_id = getattr(tg_chat, "id", None)
    chat_type = getattr(tg_chat, "type", "")
    tmpdir: Optional[Path] = None
    status_msg: Optional[types.Message] = None
    active_slot_acquired = False

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

    with request_context(
        request_id=request_id,
        user_id=uid,
        chat_id=chat_id,
        channel=chat_type,
        source="callback",
        token=token,
        initiator_id=initiator_id,
    ) as ctx:
        ctx["locale"] = locale
        add_breadcrumb("callback.start", token=token, source_chat=source_chat_id)
        increment_metric("downloads.total")

        try:
            if not await is_user_allowed(callback.message):
                increment_metric("downloads.denied")
                await callback.answer(get_access_denied_message(), show_alert=True)
                await check_and_log_access(callback.message)
                return

            if not url:
                increment_metric("downloads.unsupported")
                await callback.answer(translate("download.source_unavailable", locale), show_alert=True)
                return

            try:
                ensure_safe_public_url(url)
            except UnsafeURLError as err:
                increment_metric("downloads.blocked")
                await callback.answer(str(err), show_alert=True)
                return

            quota_plan = None
            if config.ENABLE_HISTORY:
                try:
                    quota_plan = quota_service.build_enforcement_plan(uid)
                except Exception:
                    logger.debug("Не удалось получить данные квот (callback)", exc_info=True)
            if quota_plan and quota_plan.get("blocked"):
                await callback.answer(quota_ui.quota_block_message(quota_plan, locale), show_alert=True)
                return

            now = time.time()
            if not _consume_chat_rate_slot(chat_id, now):
                await callback.answer(
                    translate("download.chat_rate_limited", locale),
                    show_alert=True,
                )
                return
            if not _consume_global_rate_slot(now):
                await callback.answer(
                    translate("download.global_rate_limited", locale),
                    show_alert=True,
                )
                return

            active = state.user_active_downloads.get(uid, 0)
            max_per_user = getattr(config, "MAX_CONCURRENT_PER_USER", 2)
            if active >= max_per_user:
                await callback.answer(
                    translate("download.active_limit", locale, active=active, limit=max_per_user),
                    show_alert=True,
                )
                return

            cooldown = max(0, getattr(config, "USER_COOLDOWN_SECONDS", 5))
            last_ts = state.user_last_request_ts.get(uid, 0.0)
            if cooldown and last_ts:
                elapsed = now - last_ts
                if elapsed < cooldown:
                    wait = max(1, math.ceil(cooldown - elapsed))
                    await callback.answer(
                        translate("download.cooldown", locale, seconds=wait),
                        show_alert=True,
                    )
                    return

            try:
                await callback.answer(translate("download.starting", locale))
            except Exception:
                pass

            state.user_last_request_ts[uid] = now
            state.user_active_downloads[uid] = active + 1
            active_slot_acquired = True
            update_active_downloads_gauge()

            platform = detect_platform(url)
            ctx["platform"] = platform
            if not platform:
                increment_metric("downloads.unsupported")
                await callback.answer(
                    translate("download.unsupported", locale),
                    show_alert=True,
                )
                return
            platform_label = (platform or "unknown").capitalize()

            status_msg = await callback.message.reply(
                status_ui.waiting(
                    platform,
                    state.user_active_downloads.get(uid, 0),
                    max_per_user,
                    locale=locale,
                )
            )
            tmpdir = Path(config.TEMP_DIR) / f"{uid}_{token[:8]}_{uuid4().hex[:6]}"
            tmpdir.mkdir(parents=True, exist_ok=True)

            cookies_file = getattr(config, "YTDLP_COOKIES_FILE", None)
            logger.info("Waiting for global download slot (callback)...")
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
                logger.info("Acquired global download slot (callback)")
                downloaded_path = await download_video(
                    url,
                    tmpdir,
                    timeout=config.DOWNLOAD_TIMEOUT_SECONDS,
                    cookies_file=cookies_file,
                    progress_cb=progress_callback,
                )
            logger.info("Released global download slot (callback)")
            update_queue_gauges()
            await ensure_file_is_safe(downloaded_path)
            await _safe_status_edit(status_msg, status_ui.processing(platform, locale=locale))

            size = downloaded_path.stat().st_size
            if size > config.TELEGRAM_MAX_FILE_BYTES:
                await _safe_status_edit(status_msg, translate("download.large_file_limit", locale))
                return

            is_photo = is_image_file(downloaded_path)
            caption_key = "download.caption.photo" if is_photo else "download.caption.video"
            doc_caption_key = (
                "download.document_caption.photo" if is_photo else "download.document_caption.video"
            )
            caption = translate(caption_key, locale, platform=platform_label)
            doc_caption = translate(doc_caption_key, locale, platform=platform_label)
            try:
                await _safe_status_edit(status_msg, status_ui.sending(platform, locale=locale))
                file_obj = FSInputFile(path=str(downloaded_path))
                if is_photo:
                    await bot.send_photo(
                        chat_id=callback.message.chat.id,
                        photo=file_obj,
                        caption=caption,
                    )
                else:
                    await bot.send_video(
                        chat_id=callback.message.chat.id,
                        video=file_obj,
                        caption=caption,
                        supports_streaming=True,
                    )
            except TelegramBadRequest as e:
                mode = "photo" if is_photo else "video"
                logger.warning("send_%s failed (callback, %s), fallback to document", mode, e)
                try:
                    capture_exception(e)
                except Exception:
                    pass
                try:
                    await _safe_status_edit(status_msg, status_ui.sending(platform, locale=locale))
                    file_obj = FSInputFile(path=str(downloaded_path))
                    await bot.send_document(
                        chat_id=callback.message.chat.id,
                        document=file_obj,
                        caption=doc_caption,
                    )
                except Exception as e2:
                    logger.exception("Не удалось отправить файл в группу: %s", e2)
                    try:
                        capture_exception(e2)
                    except Exception:
                        pass
                    await _safe_status_edit(
                        status_msg,
                        translate("download.telegram_send_error", locale, reason=str(e2)),
                    )
                    return

            try:
                await callback.message.delete()
            except Exception:
                logger.debug("Не удалось удалить сообщение с кнопкой (возможно нет прав).")

            await _safe_status_edit(
                status_msg,
                status_ui.success(platform, locale=locale),
                reply_markup=status_ui.success_markup(url, locale=locale),
            )
            await _safe_delete_original_message(source_chat_id, source_message_id)

            increment_metric("downloads.success")
            add_breadcrumb("callback.success", platform=platform, size=size)

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
                    try:
                        quota_service.consume_success(uid)
                    except Exception:
                        logger.debug("Не удалось обновить счётчик квот (callback)", exc_info=True)
                except Exception as log_err:
                    logger.debug("Failed to log success to DB: %s", log_err)

        except DownloadError as e:
            increment_metric("downloads.failure")
            await _log_and_report_callback_error(
                callback,
                status_msg,
                e,
                url,
                uid,
                username,
                ctx.get("platform"),
                locale,
            )
        except Exception as e:
            increment_metric("downloads.failure")
            await _log_and_report_callback_error(
                callback,
                status_msg,
                e,
                url,
                uid,
                username,
                ctx.get("platform"),
                locale,
            )
        finally:
            duration_ms = int((time.perf_counter() - process_started) * 1000)
            increment_metric("downloads.duration_ms_total", duration_ms)
            increment_metric("downloads.duration_events")
            if active_slot_acquired:
                state.user_active_downloads[uid] = max(0, state.user_active_downloads.get(uid, 0) - 1)
                update_active_downloads_gauge()
            if tmpdir:
                shutil.rmtree(tmpdir, ignore_errors=True)


async def _log_and_report_callback_error(
    callback: types.CallbackQuery,
    status_msg: types.Message | None,
    error: Exception,
    url: str,
    uid: int,
    username: str | None,
    platform: str | None,
    locale: str,
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
    await _safe_status_edit(status_msg, status_ui.error(str(error), locale=locale))
