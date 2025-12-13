# main.py
# Обновлённый основной файл бота Media Bandit
# - авто-распознавание ссылок (в сообщении, в caption и в reply)
# - смягчённый анти-спам: до N параллельных загрузок на пользователя + cooldown
# - поддержка YouTube / TikTok / Instagram
# - надёжная отправка файлов через FSInputFile
# - удаление: статусного сообщения, текущего сообщения и оригинального reply (после успешной отправки)
# - использует utils/downloader.download_video (ffmpeg-aware)

import asyncio
import logging

from aiogram import types
from aiogram.filters import Command

import config
import bot_app.handlers.callbacks  # noqa: F401
import bot_app.handlers.downloads  # noqa: F401
from bot_app.maintenance import start_background_tasks, stop_background_tasks
from bot_app.runtime import bot, dp
from monitoring import HealthCheckServer
from admin_panel_web import AdminPanelServer

logger = logging.getLogger(__name__)

# === История загрузок (опционально) ===
if config.ENABLE_HISTORY:
    from db import init_db, add_authorized_admin, remove_authorized_admin
    from admin_panel_clean import (
        cmd_stats, cmd_top_users, cmd_platform_stats,
        cmd_user_stats, cmd_recent,
    )

    try:
        init_db()
    except Exception as e:
        logger.warning("Не удалось инициализировать БД истории: %s", e)
        config.ENABLE_HISTORY = False

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
    health_server = None
    admin_panel_server = None
    try:
        if getattr(config, "HEALTHCHECK_ENABLED", False):
            health_server = HealthCheckServer(
                host=getattr(config, "HEALTHCHECK_HOST", "0.0.0.0"),
                port=getattr(config, "HEALTHCHECK_PORT", 8080),
            )
            health_server.ensure_running()
        if getattr(config, "ADMIN_PANEL_ENABLED", False):
            if not getattr(config, "ENABLE_HISTORY", False):
                logger.warning("Веб-админка включена, но ENABLE_HISTORY=false — панель покажет пустые данные.")
            loop = asyncio.get_running_loop()
            admin_panel_server = AdminPanelServer(
                host=getattr(config, "ADMIN_PANEL_HOST", "127.0.0.1"),
                port=getattr(config, "ADMIN_PANEL_PORT", 8090),
                access_token=getattr(config, "ADMIN_PANEL_TOKEN", None),
                admin_accounts=getattr(config, "ADMIN_PANEL_ADMINS", {}),
                cookie_secret=getattr(config, "ADMIN_PANEL_SESSION_SECRET", None),
                session_ttl=getattr(config, "ADMIN_PANEL_SESSION_TTL_SECONDS", 6 * 60 * 60),
                bot_loop=loop,
            )
            admin_panel_server.ensure_running()
        start_background_tasks()
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
        await stop_background_tasks()
        if health_server:
            health_server.shutdown()
        if admin_panel_server:
            admin_panel_server.shutdown()
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен.")

