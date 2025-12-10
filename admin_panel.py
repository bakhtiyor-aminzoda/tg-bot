"""Команды админ-панели для просмотра статистики и истории.

Позволяет администраторам получать отчёты о использовании бота через Telegram.
"""
import logging
from datetime import datetime

from aiogram import types

import config
from db import (
    get_user_stats,
    get_all_user_stats,
    get_platform_stats,
    get_recent_downloads,
    get_stats_summary,
    is_authorized_admin,
)

logger = logging.getLogger(__name__)


async def is_admin(message: types.Message) -> bool:
    """Проверить, является ли пользователь администратором.

    Проверяем в следующем порядке:
    - пользователь в `config.ADMIN_USER_IDS`
    - для групповых сообщений — является ли пользователь администратором чата
    - в противном случае — не является
    """
    user_id = message.from_user.id

    # Сначала проверяем авторизацию в БД (self-service)
    try:
        if is_authorized_admin(user_id):
            return True
    except Exception:
        # не критично, продолжаем проверять другие варианты
        pass

    # Проверяем специальный список админов из конфигурации
    if user_id in config.ADMIN_USER_IDS:
        return True

    # Для приватного чата — пользователь не считается админом по умолчанию
    if message.chat.type == "private":
        return False

    # Для групп/каналов проверяем статус участника
    try:
        member = await message.bot.get_chat_member(message.chat.id, user_id)
        return member.status in ("administrator", "creator")
    except Exception as e:
        logger.warning("Ошибка при проверке прав администратора: %s", e)
        return False


async def format_bytes(bytes_count: int) -> str:
    """Форматировать количество байт в читаемый вид."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_count < 1024:
            return f"{bytes_count:.1f} {unit}"
        bytes_count /= 1024
    return f"{bytes_count:.1f} TB"


async def cmd_stats(message: types.Message):
    """Команда /stats — общая статистика."""
    if not await is_admin(message):
        await message.reply("🔒 Только администраторы могут просматривать статистику.")
        return
    
    stats = get_stats_summary()
    
    if not stats:
        await message.reply("📊 Статистика недоступна или БД пуста.")
        return
    
    total_mb = stats.get("total_mb", 0)
    total_gb = round(total_mb / 1024, 2)
    
    text = f"""
📊 **Общая статистика бота:**

✓ Всего загрузок: {stats.get('total_downloads', 0)}
✓ Успешных: {stats.get('successful_downloads', 0)}
✗ Ошибок: {stats.get('failed_downloads', 0)}

📈 Загруженные данные:
   • {total_mb:.1f} MB ({total_gb:.2f} GB)

👥 Уникальных пользователей: {stats.get('unique_users', 0)}
"""
    
    await message.reply(text, parse_mode="Markdown")


async def cmd_top_users(message: types.Message):
    """Команда /top_users — топ пользователей."""
    if not await is_admin(message):
        await message.reply("🔒 Только администраторы могут просматривать топ.")
        return
    
    users = get_all_user_stats(limit=10)
    
    if not users:
        await message.reply("👥 Нет данных о пользователях.")
        return
    
    text = "👥 **Топ 10 пользователей:**\n\n"
    
    for i, user in enumerate(users, 1):
        username = user.get('username') or f"user_{user.get('user_id')}"
        downloads = user.get('total_downloads', 0)
        total_bytes = user.get('total_bytes', 0)
        total_mb = round(total_bytes / (1024 * 1024), 2)
        failed = user.get('failed_count', 0)
        
        text += f"{i}. @{username}\n"
        text += f"   Загрузок: {downloads} (ошибок: {failed})\n"
        text += f"   Данные: {total_mb} MB\n\n"
    
    await message.reply(text, parse_mode="Markdown")


async def cmd_platform_stats(message: types.Message):
    """Команда /platform_stats — статистика по платформам."""
    if not await is_admin(message):
        await message.reply("🔒 Только администраторы могут просматривать статистику платформ.")
        return
    
    platforms = get_platform_stats()
    
    if not platforms:
        await message.reply("🌐 Нет данных о платформах.")
        return
    
    text = "🌐 **Статистика по платформам:**\n\n"
    
    for platform in platforms:
        name = platform.get('platform', 'unknown').upper()
        count = platform.get('download_count', 0)
        total_bytes = platform.get('total_bytes', 0)
        total_mb = round(total_bytes / (1024 * 1024), 2)
        failed = platform.get('failed_count', 0)
        
        text += f"**{name}**\n"
        text += f"  Загрузок: {count} (ошибок: {failed})\n"
        text += f"  Данные: {total_mb} MB\n\n"
    
    await message.reply(text, parse_mode="Markdown")


async def cmd_user_stats(message: types.Message):
    """Команда /my_stats — статистика текущего пользователя."""
    user_id = message.from_user.id
    username = message.from_user.username or f"user_{user_id}"
    
    stats = get_user_stats(user_id)
    
    if not stats:
        await message.reply("📊 У вас пока нет загрузок.")
        return
    
    total_bytes = stats.get('total_bytes', 0)
    total_mb = round(total_bytes / (1024 * 1024), 2)
    
    text = f"""
📊 **Ваша статистика:**

✓ Загрузок: {stats.get('total_downloads', 0)}
✗ Ошибок: {stats.get('failed_count', 0)}

📈 Загруженные данные: {total_mb} MB

📅 Первая загрузка: {stats.get('first_download', 'N/A')}
📅 Последняя загрузка: {stats.get('last_download', 'N/A')}
"""
    
    await message.reply(text, parse_mode="Markdown")


async def cmd_recent(message: types.Message):
    """Команда /recent — последние загрузки (только для админов)."""
    if not await is_admin(message):
        await message.reply("🔒 Только администраторы могут просматривать последние загрузки.")
        return
    
    downloads = get_recent_downloads(limit=15)
    
    if not downloads:
        await message.reply("📥 История загрузок пуста.")
        return
    
    text = "📥 **Последние 15 загрузок:**\n\n"
    
    for dl in downloads:
        username = dl.get('username') or f"user_{dl.get('user_id')}"
        platform = dl.get('platform', 'unknown').upper()
        status = "✓" if dl.get('status') == 'success' else "✗"
        size_mb = round((dl.get('file_size_bytes') or 0) / (1024 * 1024), 1)
        timestamp = dl.get('timestamp', 'N/A')
        
        text += f"{status} @{username} ({platform}) — {size_mb} MB\n"
        text += f"   {timestamp}\n"
        if dl.get('error_message'):
            text += f"   Ошибка: {dl.get('error_message')}\n"
        text += "\n"
    
    await message.reply(text, parse_mode="Markdown")


def register_admin_commands(dp):
    """Зарегистрировать команды админ-панели в dispatcher."""
    # Для регистрации команд нужно использовать message handler с проверкой текста
    # Это будет сделано в main.py
    pass
