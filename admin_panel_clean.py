"""Clean admin panel commands for stats and history.

This is a replacement for the broken `admin_panel.py`. It provides the
same functions but lives in a new module to avoid import-time issues while
we stabilize the original file.
"""
import html
import logging
from typing import Optional

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
from db import (
    get_group_top_users,
    get_group_stats_summary,
    get_group_recent_downloads,
    get_group_platform_stats,
)

logger = logging.getLogger(__name__)


def _escape_html(text: Optional[str]) -> str:
    """Escape user-supplied text for Telegram HTML parse mode."""
    if text is None:
        return ""
    return html.escape(str(text), quote=True)


def _display_user_name(username: Optional[str], first_name: Optional[str], last_name: Optional[str], user_id: int) -> str:
    if username:
        return f"@{_escape_html(username)}"
    name_parts = [p for p in (first_name, last_name) if p]
    if name_parts:
        return _escape_html(' '.join(name_parts))
    return f"user_{user_id}"


async def is_admin(message: types.Message) -> bool:
    user_id = message.from_user.id
    try:
        if is_authorized_admin(user_id):
            return True
    except Exception:
        logger.debug('is_authorized_admin check failed', exc_info=True)

    if user_id in getattr(config, 'ADMIN_USER_IDS', []):
        return True

    if message.chat.type == 'private':
        return False

    try:
        member = await message.bot.get_chat_member(message.chat.id, user_id)
        return member.status in ('administrator', 'creator')
    except Exception as e:
        logger.warning('Error checking admin status: %s', e)
        return False


async def cmd_stats(message: types.Message):
    if not await is_admin(message):
        await message.reply('🔒 Только администраторы могут просматривать статистику.')
        return

    if message.chat.type in ('group', 'supergroup'):
        stats = get_group_stats_summary(message.chat.id)
        chat_title = _escape_html(getattr(message.chat, 'title', str(message.chat.id)))
        title = f"Статистика по группе ({chat_title})"
    else:
        stats = get_stats_summary()
        title = 'Общая статистика бота'

    if not stats:
        await message.reply('📊 Статистика недоступна или БД пуста.')
        return

    total_bytes = stats.get('total_bytes', 0)
    total_mb = round(total_bytes / (1024 * 1024), 2)
    
    # Экранируем числовые значения (точки в числах)
    total_downloads = _escape_html(str(stats.get('total_downloads', 0)))
    successful = _escape_html(str(stats.get('successful_downloads', 0)))
    failed_count = _escape_html(str(stats.get('failed_downloads', 0)))
    total_mb_escaped = _escape_html(str(total_mb))
    unique_users = _escape_html(str(stats.get('unique_users', 0)))

    text = (
        f"📊 <b>{title}</b>\n\n"
        f"✓ Всего загрузок: <b>{total_downloads}</b>\n"
        f"✓ Успешных: <b>{successful}</b>\n"
        f"✗ Ошибок: <b>{failed_count}</b>\n\n"
        f"📈 Загруженные данные:\n   • <b>{total_mb_escaped} MB</b>\n\n"
        f"👥 Уникальных пользователей: <b>{unique_users}</b>"
    )
    await message.reply(text, parse_mode='HTML')


async def cmd_top_users(message: types.Message):
    if not await is_admin(message):
        await message.reply('🔒 Только администраторы могут просматривать топ.')
        return

    if message.chat.type in ('group', 'supergroup'):
        users = get_group_top_users(message.chat.id, limit=10)
        chat_title = _escape_html(getattr(message.chat, 'title', str(message.chat.id)))
        header = f"👥 <b>Топ пользователей в группе ({chat_title})</b>:\n\n"
    else:
        users = get_all_user_stats(limit=10)
        header = '👥 <b>Топ 10 пользователей</b>:\n\n'

    if not users:
        await message.reply('👥 Нет данных о пользователях.')
        return

    lines = [header]
    for i, user in enumerate(users, 1):
        username = user.get('username')
        first = user.get('first_name') if 'first_name' in user else None
        last = user.get('last_name') if 'last_name' in user else None
        display = _display_user_name(username, first, last, user.get('user_id'))
        
        # Экранируем числовые значения
        downloads = _escape_html(str(user.get('total_downloads', 0)))
        total_bytes = user.get('total_bytes', 0)
        total_mb = _escape_html(str(round(total_bytes / (1024 * 1024), 2)))
        failed = _escape_html(str(user.get('failed_count', 0)))

        lines.append(f"<b>{i}. {display}</b>")
        lines.append(f"&nbsp;&nbsp;↪ Загрузок: <b>{downloads}</b> (ошибок: <b>{failed}</b>)")
        lines.append(f"&nbsp;&nbsp;↪ Данные: <b>{total_mb} MB</b>\n")

    text = '\n'.join(lines)
    await message.reply(text, parse_mode='HTML')


async def cmd_platform_stats(message: types.Message):
    if not await is_admin(message):
        await message.reply('🔒 Только администраторы могут просматривать статистику платформ.')
        return

    if message.chat.type in ('group', 'supergroup'):
        platforms = get_group_platform_stats(message.chat.id)
        chat_title = _escape_html(getattr(message.chat, 'title', str(message.chat.id)))
        header = f"🌐 <b>Статистика по платформам (группа: {chat_title})</b>:\n\n"
    else:
        platforms = get_platform_stats()
        header = '🌐 <b>Статистика по платформам</b>:\n\n'

    if not platforms:
        await message.reply('🌐 Нет данных о платформах.')
        return

    lines = [header]
    for p in platforms:
        name = _escape_html((p.get('platform') or 'unknown').upper())
        count = _escape_html(str(p.get('download_count', 0)))
        total_bytes = p.get('total_bytes', 0)
        total_mb = _escape_html(str(round(total_bytes / (1024 * 1024), 2)))
        failed = _escape_html(str(p.get('failed_count', 0)))

        lines.append(f"<b>{name}</b>")
        lines.append(f"&nbsp;&nbsp;↪ Загрузок: <b>{count}</b> (ошибок: <b>{failed}</b>)")
        lines.append(f"&nbsp;&nbsp;↪ Данные: <b>{total_mb} MB</b>\n")

    text = '\n'.join(lines)
    await message.reply(text, parse_mode='HTML')


async def cmd_user_stats(message: types.Message):
    user_id = message.from_user.id
    stats = get_user_stats(user_id)

    if not stats:
        await message.reply('📊 У вас пока нет загрузок.')
        return

    total_bytes = stats.get('total_bytes', 0)
    total_mb = _escape_html(str(round(total_bytes / (1024 * 1024), 2)))
    first = _escape_html(stats.get('first_download', 'N/A'))
    last = _escape_html(stats.get('last_download', 'N/A'))
    
    # Экранируем числовые значения
    total_downloads = _escape_html(str(stats.get('total_downloads', 0)))
    failed_count = _escape_html(str(stats.get('failed_count', 0)))

    text = (
        f"📊 <b>Ваша статистика</b>:\n\n"
        f"✓ Загрузок: <b>{total_downloads}</b>\n"
        f"✗ Ошибок: <b>{failed_count}</b>\n\n"
        f"📈 Загруженные данные: <b>{total_mb} MB</b>\n\n"
        f"📅 Первая загрузка: <code>{first}</code>\n"
        f"📅 Последняя загрузка: <code>{last}</code>"
    )
    await message.reply(text, parse_mode='HTML')


async def cmd_recent(message: types.Message):
    if not await is_admin(message):
        await message.reply('🔒 Только администраторы могут просматривать последние загрузки.')
        return

    if message.chat.type in ('group', 'supergroup'):
        downloads = get_group_recent_downloads(message.chat.id, limit=15)
        chat_title = _escape_html(getattr(message.chat, 'title', str(message.chat.id)))
        header = f"📥 <b>Последние загрузки в группе ({chat_title})</b>:\n\n"
    else:
        downloads = get_recent_downloads(limit=15)
        header = '📥 <b>Последние 15 загрузок</b>:\n\n'

    if not downloads:
        await message.reply('📥 История загрузок пуста.')
        return

    lines = [header]
    for dl in downloads:
        uname = dl.get('username')
        first = dl.get('first_name') if 'first_name' in dl else None
        last = dl.get('last_name') if 'last_name' in dl else None
        display = _display_user_name(uname, first, last, dl.get('user_id'))
        platform = _escape_html((dl.get('platform') or 'unknown').upper())
        status = '✓' if dl.get('status') == 'success' else '✗'
        size_mb = _escape_html(str(round((dl.get('file_size_bytes') or 0) / (1024 * 1024), 1)))
        timestamp = _escape_html(dl.get('timestamp', 'N/A'))
        err = _escape_html(dl.get('error_message')) if dl.get('error_message') else None

        lines.append(f"{status} <b>{display}</b> ({platform}) — <b>{size_mb} MB</b>")
        lines.append(f"&nbsp;&nbsp;🕐 <code>{timestamp}</code>")
        if err:
            lines.append(f"&nbsp;&nbsp;⚠️ Ошибка: <i>{err}</i>")
        lines.append('')

    text = '\n'.join(lines)
    await message.reply(text, parse_mode='HTML')


def register_admin_commands(dp):
    pass
