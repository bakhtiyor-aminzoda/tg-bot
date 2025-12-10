# main.py
# Обновлённый основной файл бота Media Bandit
# - авто-распознавание ссылок (в сообщении и в reply)
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
from typing import Optional

from aiogram import Bot, Dispatcher, types
from aiogram.types import FSInputFile
from aiogram.exceptions import TelegramBadRequest, TelegramAPIError

import config
from utils.downloader import download_video, DownloadError

# ---------- Настройка логирования ----------
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

# ---------- Инициализация бота ----------
bot = Bot(token=config.TOKEN)
dp = Dispatcher()

# ---------- Анти-спам / лимиты ----------
user_last_request_ts: dict[int, float] = {}      # last start timestamp per user
user_active_downloads: dict[int, int] = {}       # active concurrent downloads per user

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
    """Извлекает первую URL из message.entities (text_link или url)."""
    if not message:
        return None
    # entities бывает None
    ents = getattr(message, "entities", None)
    text = message.text or ""
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
@dp.message()
async def universal_handler(message: types.Message):
    """
    Универсальный обработчик:
      - автозапуск по ссылке в сообщении (или скрытой ссылке через entities)
      - поддержка /download <link>, /download (reply на сообщение со ссылкой)
      - соблюдает смягчённый анти-спам (MAX_CONCURRENT_PER_USER, USER_COOLDOWN_SECONDS)
    """
    # Получаем текст (могут быть None)
    text = (message.text or "").strip() if getattr(message, "text", None) else ""
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
        url = extract_url_from_entities(reply) or extract_first_url_from_text(reply.text or "")

    # 3) если не команда — ищем ссылку прямо в сообщении
    if not is_command:
        url = extract_url_from_entities(message) or extract_first_url_from_text(text)

    # 4) если всё ещё нет ссылки — пробуем взять из reply (для случая обычного сообщения-ответа)
    if not url and getattr(message, "reply_to_message", None):
        reply = message.reply_to_message
        url = extract_url_from_entities(reply) or extract_first_url_from_text(reply.text or "")

    # Если ссылки нет — выходим (ничего не делаем)
    if not url:
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
        downloaded_path = await download_video(url, tmpdir, timeout=config.DOWNLOAD_TIMEOUT_SECONDS, cookies_file=cookies_file)

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
                file_obj = FSInputFile(path=str(downloaded_path))
                await bot.send_document(chat_id=message.chat.id, document=file_obj, caption=f"Видео (файл) — скачано с помощью @MediaBanditbot")
            except Exception as e2:
                logger.exception("Не удалось отправить как документ: %s", e2)
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

        # 2) удаляем текущее сообщение (команда или сообщение со ссылкой)
        try:
            await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
        except TelegramAPIError as e:
            if "forbidden" in str(e).lower() or getattr(e, "status_code", None) == 403:
                logger.warning("Нет прав удалять сообщение пользователя (self).")
            else:
                logger.exception("TelegramAPIError при удалении сообщения пользователя: %s", e)
        except Exception:
            logger.exception("Ошибка при попытке удалить сообщение пользователя.")

        # 3) если сообщение былo reply — удаляем и оригинальное сообщение (с ссылкой)
        if getattr(message, "reply_to_message", None):
            try:
                orig = message.reply_to_message
                if getattr(orig, "message_id", None):
                    await bot.delete_message(chat_id=message.chat.id, message_id=orig.message_id)
            except TelegramAPIError as e:
                if "forbidden" in str(e).lower() or getattr(e, "status_code", None) == 403:
                    logger.warning("Нет прав удалять исходное reply-сообщение (с ссылкой).")
                else:
                    logger.exception("TelegramAPIError при удалении исходного сообщения (reply): %s", e)
            except Exception:
                logger.exception("Ошибка при попытке удалить исходное reply-сообщение.")

    except DownloadError as e:
        logger.exception("DownloadError: %s", e)
        # информируем пользователя (не удаляем исходные сообщения)
        try:
            await status_msg.edit_text(f"Ошибка скачивания: {e}")
        except Exception:
            logger.exception("Не удалось обновить статусное сообщение при ошибке скачивания.")
    except Exception as e:
        logger.exception("Непредвиденная ошибка", exc_info=e)
        try:
            await status_msg.edit_text(f"Ошибка: {e}")
        except Exception:
            logger.exception("Не удалось обновить статусное сообщение при неожиданной ошибке.")
    finally:
        # Снижаем счётчик активных загрузок и очищаем tmp
        user_active_downloads[uid] = max(0, user_active_downloads.get(uid, 1) - 1)
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------- Запуск polling ----------
async def main():
    logger.info("Бот запущен (long-polling).")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен.")
