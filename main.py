# main.py
# Запуск бота, обработчики, логика команды /download
# В этой версии: смягчённый анти-спам — разрешено до N параллельных загрузок на пользователя.

import asyncio
import logging
import shutil
import time
from pathlib import Path

from aiogram import Bot, Dispatcher, types
from aiogram.types import FSInputFile
from aiogram.exceptions import TelegramBadRequest, TelegramAPIError

import config
from utils.downloader import download_video, DownloadError

# Логирование
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

bot = Bot(token=config.TOKEN)
dp = Dispatcher()

# Anti-spam: user -> last_request_timestamp
user_last_request_ts: dict[int, float] = {}
# Active downloads per user: user_id -> count
user_active_downloads: dict[int, int] = {}

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

@dp.message()
async def handle_download_command(message: types.Message):
    text = (message.text or "").strip()
    if not text:
        return

    if not text.split()[0].startswith("/download"):
        return

    uid = message.from_user.id
    now = time.time()

    # Текущее число активных загрузок пользователя
    active = user_active_downloads.get(uid, 0)

    # Проверка лимита одновременных загрузок для пользователя
    max_per_user = getattr(config, "MAX_CONCURRENT_PER_USER", 2)
    if active >= max_per_user:
        await message.reply(f"У вас уже {active} активных загрузок (максимум {max_per_user}). Подождите их завершения.")
        return

    # Смягчённый cooldown:
    # - если у пользователя нет активных задач (active == 0), проверяем cooldown
    # - если есть хотя бы одна активная задача, разрешаем запустить ещё одну даже если cooldown не истёк
    last_ts = user_last_request_ts.get(uid, 0)
    if active == 0 and (now - last_ts) < config.USER_COOLDOWN_SECONDS:
        await message.reply("Слишком часто! Попробуйте через несколько секунд.")
        return

    # Готовы принять запрос — обновляем временные метки и счётчик активных задач
    user_last_request_ts[uid] = now
    user_active_downloads[uid] = active + 1

    # Парсим ссылку (в той же строке или на новой)
    parts = text.split(None, 1)
    url = parts[1].strip() if len(parts) > 1 else ""

    if not url:
        # Уменьшаем счётчик, т.к. мы не будем выполнять загрузку
        user_active_downloads[uid] = max(0, user_active_downloads.get(uid, 1) - 1)
        await message.reply("Ошибка: вы не указали ссылку.\nИспользование:\n/download <ссылка>")
        return

    platform = detect_platform(url)
    if not platform:
        user_active_downloads[uid] = max(0, user_active_downloads.get(uid, 1) - 1)
        await message.reply("Неподдерживаемая ссылка. Доступно: YouTube, TikTok, Instagram.")
        return

    status_msg = await message.reply(f"Платформа: {platform}. Скачиваю... ⏳")

    tmpdir = Path(config.TEMP_DIR) / f"{uid}_{int(time.time())}"
    tmpdir.mkdir(parents=True, exist_ok=True)

    try:
        downloaded_path = await download_video(url, tmpdir, timeout=config.DOWNLOAD_TIMEOUT_SECONDS, cookies_file=config.YTDLP_COOKIES_FILE)

        # Проверка размера
        size = downloaded_path.stat().st_size
        if size > config.TELEGRAM_MAX_FILE_BYTES:
            await status_msg.edit_text("Видео слишком большое для Telegram (лимит 2 ГБ).")
            return

        # Отправка файла: используем FSInputFile
        try:
            file_obj = FSInputFile(path=str(downloaded_path))
            await bot.send_video(chat_id=message.chat.id, video=file_obj, caption=f"Видео скачано с {platform}")
        except TelegramBadRequest as e:
            logger.warning("send_video не подошёл (%s), пробуем send_document", e)
            try:
                file_obj = FSInputFile(path=str(downloaded_path))
                await bot.send_document(chat_id=message.chat.id, document=file_obj, caption=f"Видео (файл) скачали с помощью @MediaBanditbot")
            except Exception as e2:
                logger.exception("Не удалось отправить как документ: %s", e2)
                await status_msg.edit_text("Ошибка отправки файла в Telegram: " + str(e2))
                return

        # Удаляем статусное сообщение
        try:
            await status_msg.delete()
        except TelegramAPIError as e:
            if "forbidden" in str(e).lower() or getattr(e, "status_code", None) == 403:
                logger.warning("Нет прав удалять статусное сообщение.")
            else:
                logger.exception("Ошибка удаления статусного сообщения: %s", e)
        except Exception:
            logger.exception("Не удалось удалить статусное сообщение.")

        # Удаляем сообщение пользователя (если группа/супергруппа)
        if message.chat.type in ("group", "supergroup"):
            try:
                await bot.delete_message(message.chat.id, message.message_id)
            except TelegramAPIError as e:
                if "forbidden" in str(e).lower() or getattr(e, "status_code", None) == 403:
                    logger.warning("Нет прав удалять сообщение пользователя.")
                else:
                    logger.exception("Ошибка при удалении сообщения пользователя: %s", e)
            except Exception:
                logger.exception("Ошибка при попытке удалить сообщение пользователя.")

    except DownloadError as e:
        logger.exception("DownloadError: %s", e)
        await status_msg.edit_text(f"Ошибка скачивания: {e}")
    except Exception as e:
        logger.exception("Непредвиденная ошибка", exc_info=e)
        await status_msg.edit_text(f"Ошибка: {e}")
    finally:
        # Всегда уменьшаем счётчик активных загрузок пользователя и очищаем tmp
        user_active_downloads[uid] = max(0, user_active_downloads.get(uid, 1) - 1)
        shutil.rmtree(tmpdir, ignore_errors=True)


async def main():
    logger.info("Бот запущен.")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен.")
