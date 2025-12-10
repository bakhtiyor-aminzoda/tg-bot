# main.py
# Обновлённый основной файл бота Media Bandit
# - авто-распознавание ссылок (в сообщении, в caption и в reply)
# - смягчённый анти-спам: до N параллельных загрузок на пользователя + cooldown
# - поддержка YouTube / TikTok / Instagram
# - надёжная отправка файлов через FSInputFile
# - удаление: статусного сообщения, текущего сообщения и оригинального reply (после успешной отправки)
# - использует utils/downloader.download_video (ffmpeg-aware)

import re
import asyncio
import logging
import shutil
import time
from pathlib import Path
from typing import Optional, Dict

from aiogram import Bot, Dispatcher, types
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest, TelegramAPIError
from aiogram.filters import Command

import config
from uuid import uuid4
from utils.downloader import download_video, DownloadError
from utils.access_control import is_user_allowed, get_access_denied_message, check_and_log_access

# === История загрузок (опционально) ===
if config.ENABLE_HISTORY:
    from db import init_db, add_download, add_authorized_admin, remove_authorized_admin, is_authorized_admin
    from admin_panel_clean import (
        cmd_stats, cmd_top_users, cmd_platform_stats, 
        cmd_user_stats, cmd_recent, is_admin as is_admin_check
    )
    try:
        init_db()
    except Exception as e:
        logger.warning("Не удалось инициализировать БД истории: %s", e)
        config.ENABLE_HISTORY = False

# ---------- Настройка логирования (console + optional file + Sentry) ----------
from monitoring import setup_logging, capture_exception

setup_logging(
    level=config.LOG_LEVEL,
    log_file=getattr(config, "LOG_FILE", None),
    max_bytes=getattr(config, "LOG_MAX_BYTES", 10 * 1024 * 1024),
    backup_count=getattr(config, "LOG_BACKUP_COUNT", 5),
    sentry_dsn=getattr(config, "SENTRY_DSN", None),
)

logger = logging.getLogger(__name__)

# ---------- Инициализация бота ----------
bot = Bot(token=config.TOKEN)
dp = Dispatcher()

# Global semaphore to limit concurrent downloads across the whole process
global_download_semaphore = asyncio.Semaphore(getattr(config, "MAX_GLOBAL_CONCURRENT_DOWNLOADS", 4))

# ---------- Анти-спам / лимиты ----------
user_last_request_ts: Dict[int, float] = {}      # last start timestamp per user
user_active_downloads: Dict[int, int] = {}       # active concurrent downloads per user
# Temporary store for pending group-download requests: token -> {url, initiator_id, ts}
pending_downloads: Dict[str, Dict] = {}
PENDING_TOKEN_TTL = 10 * 60  # seconds

# ---------- Регексы и вспомогательные функции ----------
URL_REGEX = re.compile(r"(https?://[^\s]+)", flags=re.IGNORECASE)

def detect_platform(url: str) -> str:
    """Определяет платформу по ссылке (youtube, tiktok, instagram)."""
    u = (url or "").lower()
    if "youtu.be" in u or "youtube.com" in u:
        return "youtube"
    if "tiktok.com" in u or "vm.tiktok.com" in u:
        return "tiktok"
    if "instagram.com" in u or "instagr.am" in u:
        return "instagram"
    return ""

def extract_url_from_entities(message: types.Message) -> Optional[str]:
    """Извлекает первую URL из message.entities / caption_entities (text_link или url).

    Поддерживает извлечение ссылок как из обычного текста, так и из подписи медиа
    (`message.caption_entities`). Для извлечения по offset-ам используется
    `message.text` если есть, иначе `message.caption`.
    """
    if not message:
        return None

    # Собираем все сущности (entities и caption_entities)
    ents = []
    if getattr(message, "entities", None):
        ents.extend(message.entities)
    if getattr(message, "caption_entities", None):
        ents.extend(message.caption_entities)

    # текст для извлечения из offset-ов: предпочитаем message.text, иначе caption
    text = message.text or message.caption or ""
    if ents:
        for ent in ents:
            # text_link: ссылка в ent.url
            if ent.type == "text_link" and getattr(ent, "url", None):
                return ent.url
            # url: берем подстроку
            if ent.type == "url":
                try:
                    return text[ent.offset: ent.offset + ent.length]
                except Exception:
                    continue
    return None

def extract_first_url_from_text(text: str) -> Optional[str]:
    """Фоллбек: простой regex для поиска первой ссылки в тексте."""
    if not text:
        return None
    m = URL_REGEX.search(text)
    if m:
        return m.group(1)
    return None

# ---------- Основной обработчик (универсальный) ----------
# Не перехватываем команды (сообщения, начинающиеся с `/`),
# чтобы командные обработчики могли срабатывать позже.
@dp.message(lambda message: not ( (message.text or message.caption or "").strip().startswith("/")))
async def universal_handler(message: types.Message):
    """
    Универсальный обработчик:
      - автозапуск по ссылке в сообщении (или скрытой ссылке через entities)
      - поддержка /download <link>, /download (reply на сообщение со ссылкой)
      - соблюдает смягчённый анти-спам (MAX_CONCURRENT_PER_USER, USER_COOLDOWN_SECONDS)
    """
    # Получаем текст (могут быть None). Если нет plain text — используем caption (для медиа).
    text = (message.text or message.caption or "").strip()
    if not text and not getattr(message, "reply_to_message", None):
        return  # пустое сообщение — ничего не делаем

    # --- Этап извлечения ссылки (приоритеты) ---
    url: Optional[str] = None
    is_command = False

    # 1) если сообщение начинается с /download
    if text.split() and text.split()[0].startswith("/download"):
        is_command = True
        parts = text.split(None, 1)
        if len(parts) > 1:
            url = parts[1].strip()

    # 2) если команда без аргумента, но reply_to_message содержит ссылку
    if is_command and not url and getattr(message, "reply_to_message", None):
        reply = message.reply_to_message
        url = extract_url_from_entities(reply) or extract_first_url_from_text(reply.text or reply.caption or "")

    # 3) если не команда — ищем ссылку прямо в сообщении
    if not is_command:
        url = extract_url_from_entities(message) or extract_first_url_from_text(text)

    # 4) если всё ещё нет ссылки — пробуем взять из reply (для случая обычного сообщения-ответа)
    if not url and getattr(message, "reply_to_message", None):
        reply = message.reply_to_message
        url = extract_url_from_entities(reply) or extract_first_url_from_text(reply.text or reply.caption or "")

    # Если ссылки нет — выходим (ничего не делаем)
    if not url:
        return

    # === Проверка доступа (Whitelist / Admin-only режимы) ===
    if not await is_user_allowed(message):
        try:
            await message.reply(get_access_denied_message())
        except Exception:
            logger.exception("Не удалось отправить сообщение об отказе в доступе")
        await check_and_log_access(message)  # Логируем отказ
        return

    # If we're in a group/supergroup, don't auto-start: send compact message with inline Download button.
    chat_type = getattr(message.chat, "type", "")
    if chat_type in ("group", "supergroup"):
        token = uuid4().hex
        pending_downloads[token] = {"url": url, "initiator_id": message.from_user.id, "ts": time.time()}
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Download", callback_data=f"download:{token}")]])
        try:
            await message.reply("Нажмите кнопку, чтобы скачать видео.", reply_markup=kb)
        except Exception as e:
            logger.exception("Не удалось отправить сообщение с кнопкой в группе.")
            try:
                capture_exception(e)
            except Exception:
                pass
        return

    # --- Анти-спам: проверка лимитов и cooldown ---
    uid = message.from_user.id
    now = time.time()
    active = user_active_downloads.get(uid, 0)
    max_per_user = getattr(config, "MAX_CONCURRENT_PER_USER", 2)
    if active >= max_per_user:
        await message.reply(f"У вас уже {active} активных загрузок (максимум {max_per_user}). Подождите их завершения.")
        return

    last_ts = user_last_request_ts.get(uid, 0)
    # если нет активных задач — применяем cooldown
    if active == 0 and (now - last_ts) < config.USER_COOLDOWN_SECONDS:
        await message.reply("Слишком часто! Попробуйте через несколько секунд.")
        return

    # принимаем запрос: увеличиваем счётчик и ставим last_ts
    user_last_request_ts[uid] = now
    user_active_downloads[uid] = active + 1

    # --- Определяем платформу и валидируем ---
    platform = detect_platform(url)
    if not platform:
        # откатываем счётчик т.к. не будем выполнять загрузку
        user_active_downloads[uid] = max(0, user_active_downloads.get(uid, 1) - 1)
        await message.reply("Неподдерживаемая ссылка. Доступно: YouTube, TikTok, Instagram.")
        return

    # Статусное сообщение
    status_msg = await message.reply(f"Платформа: {platform}. Скачиваю... ⏳")

    # Создаём временную папку
    tmpdir = Path(config.TEMP_DIR) / f"{uid}_{int(time.time())}"
    tmpdir.mkdir(parents=True, exist_ok=True)

    try:
        # Передаём cookies_file, если он задан в config (опционально)
        cookies_file = getattr(config, "YTDLP_COOKIES_FILE", None)
        logger.info("Waiting for global download slot...")
        async with global_download_semaphore:
            logger.info("Acquired global download slot")
            downloaded_path = await download_video(url, tmpdir, timeout=config.DOWNLOAD_TIMEOUT_SECONDS, cookies_file=cookies_file)
        logger.info("Released global download slot")

        # Проверка размера
        size = downloaded_path.stat().st_size
        if size > config.TELEGRAM_MAX_FILE_BYTES:
            await status_msg.edit_text("Видео слишком большое для Telegram (лимит 2 ГБ).")
            return

        # Отправляем файл (FSInputFile)
        try:
            file_obj = FSInputFile(path=str(downloaded_path))
            await bot.send_video(chat_id=message.chat.id, video=file_obj, caption=f"Видео скачано с {platform} — @MediaBanditbot")
        except TelegramBadRequest as e:
            logger.warning("send_video failed (%s), trying send_document", e)
            try:
                # capture the problematic exception as well
                try:
                    capture_exception(e)
                except Exception:
                    pass
                file_obj = FSInputFile(path=str(downloaded_path))
                await bot.send_document(chat_id=message.chat.id, document=file_obj, caption=f"Видео (файл) — скачано с помощью @MediaBanditbot")
            except Exception as e2:
                logger.exception("Не удалось отправить как документ: %s", e2)
                try:
                    capture_exception(e2)
                except Exception:
                    pass
                await status_msg.edit_text("Ошибка отправки файла в Telegram: " + str(e2))
                return

        # --- После успешной отправки: удаляем статус и сообщения ---
        # 1) удаляем статусное сообщение
        try:
            await status_msg.delete()
        except TelegramAPIError as e:
            if "forbidden" in str(e).lower() or getattr(e, "status_code", None) == 403:
                logger.warning("Нет прав удалять статусное сообщение.")
            else:
                logger.exception("Ошибка удаления статусного сообщения: %s", e)
        except Exception:
            logger.exception("Не удалось удалить статусное сообщение.")

        # NOTE: keep the user's original message and any reply intact (don't delete links)
        logger.debug("Оставляем исходное сообщение пользователя в чате (не удаляем).")
        
        # === Логирование успешной загрузки в БД ===
        if config.ENABLE_HISTORY:
            try:
                add_download(
                    user_id=uid,
                    username=message.from_user.username,
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
        # информируем пользователя (не удаляем исходные сообщения)
        try:
            await status_msg.edit_text(f"Ошибка скачивания: {e}")
        except Exception as e2:
            logger.exception("Не удалось обновить статусное сообщение при ошибке скачивания.")
            try:
                capture_exception(e2)
            except Exception:
                pass
        # === Логирование ошибки в БД ===
        if config.ENABLE_HISTORY:
            try:
                add_download(
                    user_id=uid,
                    username=message.from_user.username,
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
        try:
            await status_msg.edit_text(f"Ошибка: {e}")
        except Exception as e2:
            logger.exception("Не удалось обновить статусное сообщение при неожиданной ошибке.")
            try:
                capture_exception(e2)
            except Exception:
                pass
        # === Логирование непредвиденной ошибки в БД ===
        if config.ENABLE_HISTORY:
            try:
                add_download(
                    user_id=uid,
                    username=message.from_user.username,
                    platform=platform,
                    url=url,
                    chat_id=message.chat.id,
                    status="error",
                    error_message=str(e),
                )
            except Exception:
                logger.debug("Ошибка при логировании в БД")
    finally:
        # Снижаем счётчик активных загрузок и очищаем tmp
        user_active_downloads[uid] = max(0, user_active_downloads.get(uid, 1) - 1)
        shutil.rmtree(tmpdir, ignore_errors=True)


@dp.callback_query()
async def handle_download_callback(callback: types.CallbackQuery):
    """Handle inline Download button clicks (callback_data: download:<token>)."""
    logger.info("Received callback_query: %s from %s", callback.data, getattr(callback.from_user, 'id', None))
    data = callback.data or ""
    if not data.startswith("download:"):
        return
    token = data.split(":", 1)[1]
    entry = pending_downloads.pop(token, None)
    if not entry:
        await callback.answer("Ссылка устарела или недоступна.", show_alert=True)
        return
    # TTL check
    if time.time() - entry.get("ts", 0) > PENDING_TOKEN_TTL:
        await callback.answer("Срок действия кнопки истёк.", show_alert=True)
        return

    url = entry.get("url")
    uid = callback.from_user.id
    username = callback.from_user.username  # Добавляем username, которая была потеряна

    # === Проверка доступа (Whitelist / Admin-only режимы) ===
    if not await is_user_allowed(callback.message):
        await callback.answer(get_access_denied_message(), show_alert=True)
        await check_and_log_access(callback.message)  # Логируем отказ
        return

    # Anti-spam per-user checks (reuse same logic)
    active = user_active_downloads.get(uid, 0)
    max_per_user = getattr(config, "MAX_CONCURRENT_PER_USER", 2)
    if active >= max_per_user:
        await callback.answer(f"У вас уже {active} активных загрузок (максимум {max_per_user}).", show_alert=True)
        return

    last_ts = user_last_request_ts.get(uid, 0)
    if active == 0 and (time.time() - last_ts) < config.USER_COOLDOWN_SECONDS:
        await callback.answer("Слишком часто! Подождите немного.", show_alert=True)
        return

    # Accept request
    user_last_request_ts[uid] = time.time()
    user_active_downloads[uid] = active + 1

    # Acknowledge callback early so client stops showing "Loading..."
    try:
        await callback.answer("Запускаю...")
    except Exception:
        pass

    platform = detect_platform(url)
    status_msg = None
    try:
        status_msg = await callback.message.reply(f"Платформа: {platform or 'unknown'}. Скачиваю... ⏳")

        tmpdir = Path(config.TEMP_DIR) / f"{uid}_{int(time.time())}"
        tmpdir.mkdir(parents=True, exist_ok=True)
        cookies_file = getattr(config, "YTDLP_COOKIES_FILE", None)
        logger.info("Waiting for global download slot (callback)...")
        async with global_download_semaphore:
            logger.info("Acquired global download slot (callback)")
            downloaded_path = await download_video(url, tmpdir, timeout=config.DOWNLOAD_TIMEOUT_SECONDS, cookies_file=cookies_file)
        logger.info("Released global download slot (callback)")

        size = downloaded_path.stat().st_size
        if size > config.TELEGRAM_MAX_FILE_BYTES:
            try:
                await status_msg.edit_text("Видео слишком большое для Telegram (лимит 2 ГБ).")
            except Exception:
                logger.exception("Не удалось обновить статус при большом файле.")
            return

        try:
            file_obj = FSInputFile(path=str(downloaded_path))
            await bot.send_video(chat_id=callback.message.chat.id, video=file_obj, caption=f"Видео скачано — @MediaBanditbot")
        except TelegramBadRequest as e:
            try:
                # capture the problematic exception as well
                try:
                    capture_exception(e)
                except Exception:
                    pass
                file_obj = FSInputFile(path=str(downloaded_path))
                await bot.send_document(chat_id=callback.message.chat.id, document=file_obj, caption=f"Видео (файл) — скачано с помощью @MediaBanditbot")
            except Exception as e2:
                logger.exception("Не удалось отправить файл в группу: %s", e2)
                try:
                    capture_exception(e2)
                except Exception:
                    pass
                try:
                    await status_msg.edit_text("Ошибка отправки файла в Telegram: " + str(e2))
                except Exception as e3:
                    logger.exception("Не удалось обновить статусное сообщение после ошибки отправки.")
                    try:
                        capture_exception(e3)
                    except Exception:
                        pass
                return

        # Try to delete the compact message with the button
        try:
            await callback.message.delete()
        except Exception:
            logger.debug("Не удалось удалить сообщение с кнопкой (возможно нет прав).")

        # Delete status message if possible
        if status_msg:
            try:
                await status_msg.delete()
            except Exception:
                logger.debug("Не удалось удалить статусное сообщение после отправки.")

    except DownloadError as e:
        logger.exception("DownloadError in callback: %s", e)
        try:
            capture_exception(e)
        except Exception:
            pass
        # Log error to database
        if config.ENABLE_HISTORY:
            try:
                add_download(
                    user_id=uid,
                    username=username,
                    platform=platform,
                    url=url,
                    chat_id=callback.message.chat.id,
                    status="error",
                    file_size_bytes=0,
                    error_message=str(e)
                )
            except Exception as log_err:
                logger.debug(f"Failed to log error to DB: {log_err}")
        try:
            if status_msg:
                await status_msg.edit_text(f"Ошибка скачивания: {e}")
        except Exception as e2:
            logger.exception("Не удалось обновить статус при ошибке скачивания.")
            try:
                capture_exception(e2)
            except Exception:
                pass
    except Exception as e:
        logger.exception("Unexpected error in callback", exc_info=e)
        try:
            capture_exception(e)
        except Exception:
            pass
        # Log error to database
        if config.ENABLE_HISTORY:
            try:
                add_download(
                    user_id=uid,
                    username=username,
                    platform=platform,
                    url=url,
                    chat_id=callback.message.chat.id,
                    status="error",
                    file_size_bytes=0,
                    error_message=str(e)
                )
            except Exception as log_err:
                logger.debug(f"Failed to log error to DB: {log_err}")
        try:
            if status_msg:
                await status_msg.edit_text(f"Ошибка: {e}")
        except Exception as e2:
            logger.exception("Не удалось обновить статус при неожиданной ошибке.")
            try:
                capture_exception(e2)
            except Exception:
                pass
    finally:
        user_active_downloads[uid] = max(0, user_active_downloads.get(uid, 1) - 1)
        try:
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass


# ---------- Команды админ-панели ----------
if config.ENABLE_HISTORY:
    @dp.message(Command("debug"))
    async def cmd_debug_handler(message: types.Message):
        """Обработчик команды /debug — информация о пользователе."""
        text = f"""
🔧 **Информация отладки:**

👤 Ваш ID: `{message.from_user.id}`
👤 Ваше имя: {message.from_user.username or 'не установлено'}

🔐 Администраторы: {config.ADMIN_USER_IDS if config.ADMIN_USER_IDS else 'не настроены'}
📜 История включена: {config.ENABLE_HISTORY}

Чтобы стать администратором, экспортируйте переменную:
```
export ADMIN_USER_IDS="{message.from_user.id}"
```
"""
        await message.reply(text, parse_mode="Markdown")
    
    @dp.message(Command("stats"))
    async def cmd_stats_handler(message: types.Message):
        """Обработчик команды /stats."""
        logger.info(f"Команда /stats от пользователя {message.from_user.id} ({message.from_user.username})")
        await cmd_stats(message)

    @dp.message(Command("authorize_me"))
    async def cmd_authorize_me_handler(message: types.Message):
        """Команда /authorize_me — авторизовать себя как админ для статистики (запускать в группе)."""
        # Prefer authorizing in group context
        if message.chat.type == "private":
            await message.reply("⚠️ Пожалуйста, выполните эту команду в группе, где вы являетесь администратором.")
            return

        uid = message.from_user.id
        try:
            member = await message.bot.get_chat_member(message.chat.id, uid)
            if member.status not in ("administrator", "creator"):
                await message.reply("🔒 Вы не администратор этой группы — авторизация невозможна.")
                return
        except Exception as e:
            logger.warning("Ошибка проверки статуса участника: %s", e)
            await message.reply("❗ Не удалось проверить ваш статус администратора.")
            return

        try:
            ok = add_authorized_admin(uid, message.from_user.username)
            if ok:
                await message.reply("✅ Вы успешно авторизованы для просмотра статистики в личных сообщениях.")
            else:
                await message.reply("❗ Не удалось сохранить авторизацию. Посмотрите логи.")
        except Exception as e:
            logger.exception("Ошибка при добавлении авторизации: %s", e)
            await message.reply("❗ Внутренняя ошибка при авторизации.")

    @dp.message(Command("revoke_me"))
    async def cmd_revoke_me_handler(message: types.Message):
        """Команда /revoke_me — отозвать свою авторизацию."""
        uid = message.from_user.id
        try:
            ok = remove_authorized_admin(uid)
            if ok:
                await message.reply("✅ Ваша авторизация отозвана.")
            else:
                await message.reply("ℹ️ Вы не были авторизованы или произошла ошибка.")
        except Exception as e:
            logger.exception("Ошибка при отзыве авторизации: %s", e)
            await message.reply("❗ Внутренняя ошибка при отзыве авторизации.")
    
    @dp.message(Command("top_users"))
    async def cmd_top_users_handler(message: types.Message):
        """Обработчик команды /top_users."""
        logger.info(f"Команда /top_users от пользователя {message.from_user.id} ({message.from_user.username})")
        await cmd_top_users(message)
    
    @dp.message(Command("platform_stats"))
    async def cmd_platform_stats_handler(message: types.Message):
        """Обработчик команды /platform_stats."""
        logger.info(f"Команда /platform_stats от пользователя {message.from_user.id} ({message.from_user.username})")
        await cmd_platform_stats(message)
    
    @dp.message(Command("my_stats"))
    async def cmd_user_stats_handler(message: types.Message):
        """Обработчик команды /my_stats."""
        logger.info(f"Команда /my_stats от пользователя {message.from_user.id} ({message.from_user.username})")
        await cmd_user_stats(message)
    
    @dp.message(Command("recent"))
    async def cmd_recent_handler(message: types.Message):
        """Обработчик команды /recent."""
        logger.info(f"Команда /recent от пользователя {message.from_user.id} ({message.from_user.username})")
        await cmd_recent(message)

    @dp.my_chat_member()
    async def handle_my_chat_member(update: types.ChatMemberUpdated):
        """Автоматически авторизовать админов группы, когда бот добавляется в чат.

        При добавлении бота в группу/канал бот получает список администраторов
        и добавляет их в `authorized_admins` (чтобы они могли в лс получать статистику).
        """
        try:
            new_status = getattr(update, 'new_chat_member', None)
            if not new_status:
                return
            status = getattr(new_status, 'status', None)
            # Если бот теперь участник/админ/создатель — сканируем админов
            if status in ("member", "administrator", "creator"):
                chat = update.chat
                chat_id = getattr(chat, 'id', None)
                if not chat_id:
                    return
                try:
                    admins = await bot.get_chat_administrators(chat_id)
                    count = 0
                    for adm in admins:
                        try:
                            uid = adm.user.id
                            uname = adm.user.username
                            add_authorized_admin(uid, uname)
                            count += 1
                        except Exception:
                            logger.debug("Не удалось добавить админа %s в БД авторизации", adm.user.id)
                    logger.info("Auto-authorized %d admins from chat %s", count, chat_id)
                except Exception as e:
                    logger.exception("Не удалось получить администраторов чата %s: %s", chat_id, e)
        except Exception as e:
            logger.exception("Ошибка в обработчике my_chat_member: %s", e)


# ---------- Запуск polling ----------
async def main():
    logger.info("Бот запущен (long-polling).")
    try:
        # Удаляем старые апдейты из очереди перед стартом polling'а
        # чтобы не обрабатывать сообщения из истории
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Старые апдейты удалены из очереди")
        
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),  # обрабатываем только нужные типы апдейтов
            skip_updates=True  # пропускаем ещё остающиеся старые апдейты
        )
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен.")

