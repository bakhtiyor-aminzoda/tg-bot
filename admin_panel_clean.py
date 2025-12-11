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
from bot_app.helpers import resolve_chat_title
from db import is_authorized_admin, upsert_chat
from services import stats as stats_service

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


def _resolve_scope(message: types.Message) -> tuple[int, bool, Optional[str]]:
    """Return (chat_id, is_group, escaped_title)."""

    chat = getattr(message, "chat", None)
    if not chat:
        return 0, False, None
    chat_id = getattr(chat, "id", 0)
    chat_type = getattr(chat, "type", "private")
    display_title = resolve_chat_title(chat)

    if config.ENABLE_HISTORY:
        try:
            upsert_chat(chat_id, display_title, chat_type)
        except Exception:
            logger.debug("Не удалось обновить сведения о чате (admin panel)", exc_info=True)

    if chat_type in ("group", "supergroup"):
        title = _escape_html(display_title or getattr(chat, "title", str(chat_id)))
        return chat_id, True, title
    return chat_id, False, None


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
    chat_id, is_group, chat_title = _resolve_scope(message)
    stats = stats_service.get_summary(chat_id)

    if (stats or {}).get('total_downloads', 0) == 0:
        await message.reply('📊 В этом чате ещё не было загрузок.')
        return

    title = (
        f"Статистика по группе ({chat_title})" if is_group else "Статистика вашего диалога с ботом"
    )

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
        f"📊 <b>{title}</b>\n"
        "------------------------\n"
        f"• Всего загрузок: <b>{total_downloads}</b>\n"
        f"• Успешных: <b>{successful}</b>\n"
        f"• Ошибок: <b>{failed_count}</b>\n"
        "------------------------\n"
        f"📈 Объём данных: <b>{total_mb_escaped} MB</b>\n"
        f"👥 Уникальных пользователей: <b>{unique_users}</b>"
    )
    await message.reply(text, parse_mode='HTML')


async def cmd_top_users(message: types.Message):
    chat_id, is_group, chat_title = _resolve_scope(message)
    users = stats_service.get_top_users(chat_id, limit=10)

    if not users:
        await message.reply('👥 В этом чате ещё не было загрузок.')
        return

    if is_group:
        header = (
            f"👥 <b>Активность участников ({chat_title})</b>\n"
            "------------------------"
        )
    else:
        header = '👥 <b>Ваша активность в этом диалоге</b>\n------------------------'

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
        lines.append(f"   • Загрузок: <b>{downloads}</b> (ошибок: <b>{failed}</b>)")
        lines.append(f"   • Данные: <b>{total_mb} MB</b>\n")

    text = '\n'.join(lines)
    await message.reply(text, parse_mode='HTML')


async def cmd_platform_stats(message: types.Message):
    chat_id, is_group, chat_title = _resolve_scope(message)
    platforms = stats_service.get_platform_stats(chat_id)

    if not platforms:
        await message.reply('🌐 В этом чате ещё нет загрузок по платформам.')
        return

    if is_group:
        header = (
            f"🌐 <b>Платформы в чате ({chat_title})</b>\n"
            "------------------------"
        )
    else:
        header = '🌐 <b>Платформы в вашем диалоге</b>\n------------------------'

    lines = [header]
    for p in platforms:
        name = _escape_html((p.get('platform') or 'unknown').upper())
        count = _escape_html(str(p.get('download_count', 0)))
        total_bytes = p.get('total_bytes', 0)
        total_mb = _escape_html(str(round(total_bytes / (1024 * 1024), 2)))
        failed = _escape_html(str(p.get('failed_count', 0)))

        lines.append(f"<b>{name}</b>")
        lines.append(f"   • Загрузок: <b>{count}</b> (ошибок: <b>{failed}</b>)")
        lines.append(f"   • Данные: <b>{total_mb} MB</b>\n")

    text = '\n'.join(lines)
    await message.reply(text, parse_mode='HTML')


async def cmd_user_stats(message: types.Message):
    user_id = message.from_user.id
    chat_id, is_group, _ = _resolve_scope(message)
    stats = stats_service.get_user_stats(user_id, chat_id)

    if not stats:
        await message.reply('📊 В этом чате у вас пока нет загрузок.')
        return

    total_bytes = stats.get('total_bytes', 0)
    total_mb = _escape_html(str(round(total_bytes / (1024 * 1024), 2)))
    first = _escape_html(stats.get('first_download', 'N/A'))
    last = _escape_html(stats.get('last_download', 'N/A'))
    
    # Экранируем числовые значения
    total_downloads = _escape_html(str(stats.get('total_downloads', 0)))
    failed_count = _escape_html(str(stats.get('failed_count', 0)))

    text = (
        "📊 <b>Ваша статистика</b>\n"
        "------------------------\n"
        f"• Загрузок: <b>{total_downloads}</b>\n"
        f"• Ошибок: <b>{failed_count}</b>\n"
        f"• Данные: <b>{total_mb} MB</b>\n"
        "------------------------\n"
        f"📅 Первая загрузка: <code>{first}</code>\n"
        f"📅 Последняя загрузка: <code>{last}</code>"
    )
    await message.reply(text, parse_mode='HTML')


async def cmd_recent(message: types.Message):
    if not await is_admin(message):
        await message.reply('🔒 Только администраторы могут просматривать последние загрузки.')
        return

    chat_id, is_group, chat_title = _resolve_scope(message)
    downloads = stats_service.get_recent_downloads(chat_id, limit=15)

    if is_group:
        header = (
            f"📥 <b>Последние загрузки ({chat_title})</b>\n"
            "------------------------"
        )
    else:
        header = '📥 <b>Последние загрузки в вашем диалоге</b>\n------------------------'

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

        lines.append(f"{status} <b>{display}</b> - {platform} - <b>{size_mb} MB</b>")
        lines.append(f"   🕐 <code>{timestamp}</code>")
        if err:
            lines.append(f"   ⚠️ Ошибка: <i>{err}</i>")
        lines.append('')

    text = '\n'.join(lines)
    await message.reply(text, parse_mode='HTML')


def register_admin_commands(dp):
    pass
