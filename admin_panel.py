"""Admin panel commands for stats and history.

Provides admin-only commands to view bot statistics and recent downloads.
All dynamic fields are escaped for Telegram MarkdownV2 to avoid parse errors.
"""
import logging
import re
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


def _escape_md_v2(text: Optional[str]) -> str:
    """Escape text for Telegram MarkdownV2 (safe for dynamic fields)."""
    if text is None:
        return ""
    s = str(text)
    # Escape characters that MarkdownV2 treats as special
    return re.sub(r'([_\*\[\]()~`>#+\-=|{}\\.!])', r"\\\\\1", s)


def _display_user_name(username: Optional[str], first_name: Optional[str], last_name: Optional[str], user_id: int) -> str:
    """Return a display string for a user: prefer @username, else full name, else id.

    The returned string is safe to include in MarkdownV2 messages (we escape names).
    """
    if username:
        # username should not contain spaces, but escape anyway
        return f"@{_escape_md_v2(username)}"
    name_parts = [p for p in (first_name, last_name) if p]
    if name_parts:
        return _escape_md_v2(' '.join(name_parts))
    return f"user_{user_id}"


async def is_admin(message: types.Message) -> bool:
    """Check whether the sender is an admin for the context of this bot.

    Order of checks:
    - self-service DB authorized admins
    - `config.ADMIN_USER_IDS`
    - for groups: chat admin/creator status
    - otherwise False
    """
    user_id = message.from_user.id
    try:
        if is_authorized_admin(user_id):
            return True
    except Exception:
        # DB check failed — continue with other checks
        logger.debug('is_authorized_admin check failed', exc_info=True)

    if user_id in getattr(config, 'ADMIN_USER_IDS', []):
        return True

    # Private chats: do not treat user as admin by default
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
        chat_title = _escape_md_v2(getattr(message.chat, 'title', str(message.chat.id)))
        header = f"📊 *Статистика по группе ({chat_title})*: \n\n"
    else:
        stats = get_stats_summary()
        header = '📊 *Общая статистика бота*: \n\n'

    if not stats:
        await message.reply('📊 Статистика недоступна или БД пуста.')
        return

    total_bytes = stats.get('total_bytes', 0)
    total_mb = round(total_bytes / (1024 * 1024), 2)

    text = (
        f"{header}"
        f"✓ Всего загрузок: {stats.get('total_downloads', 0)}\n"
        f"✓ Успешных: {stats.get('successful_downloads', 0)}\n"
        f"✗ Ошибок: {stats.get('failed_downloads', 0)}\n\n"
        f"📈 Загруженные данные:\n   • {total_mb:.1f} MB\n\n"
        f"👥 Уникальных пользователей: {stats.get('unique_users', 0)}"
    )
    await message.reply(text, parse_mode='MarkdownV2')


async def cmd_top_users(message: types.Message):
    if not await is_admin(message):
        await message.reply('🔒 Только администраторы могут просматривать топ.')
        return

    if message.chat.type in ('group', 'supergroup'):
        users = get_group_top_users(message.chat.id, limit=10)
        chat_title = _escape_md_v2(getattr(message.chat, 'title', str(message.chat.id)))
        header = f"👥 *Топ пользователей в группе ({chat_title})*: \n\n"
    else:
        users = get_all_user_stats(limit=10)
        header = '👥 *Топ 10 пользователей:*\n\n'

    if not users:
        await message.reply('👥 Нет данных о пользователях.')
        return

    lines = [header]
    for i, user in enumerate(users, 1):
        username = user.get('username')
        first = user.get('first_name') if 'first_name' in user else None
        last = user.get('last_name') if 'last_name' in user else None
        display = _display_user_name(username, first, last, user.get('user_id'))
        downloads = user.get('total_downloads', 0)
        total_bytes = user.get('total_bytes', 0)
        total_mb = round(total_bytes / (1024 * 1024), 2)
        failed = user.get('failed_count', 0)

        lines.append(f"{i}. {display}")
        lines.append(f"   Загрузок: {downloads} (ошибок: {failed})")
        lines.append(f"   Данные: {total_mb} MB\n")

    text = '\n'.join(lines)
    await message.reply(text, parse_mode='MarkdownV2')


async def cmd_platform_stats(message: types.Message):
# end-of-file: keep only the first implementation above; duplicates removed

    text = '\n'.join(lines)
    await message.reply(text, parse_mode='MarkdownV2')


async def cmd_platform_stats(message: types.Message):
    if not await is_admin(message):
        await message.reply('🔒 Только администраторы могут просматривать статистику платформ.')
        return

    if message.chat.type in ('group', 'supergroup'):
        platforms = get_group_platform_stats(message.chat.id)
        chat_title = _escape_md_v2(getattr(message.chat, 'title', str(message.chat.id)))
        header = f"🌐 *Статистика по платформам (группа: {chat_title})*: \n\n"
    else:
        platforms = get_platform_stats()
        header = '🌐 *Статистика по платформам:*\n\n'

    if not platforms:
        await message.reply('🌐 Нет данных о платформах.')
        return

    lines = [header]
    for p in platforms:
        name = _escape_md_v2((p.get('platform') or 'unknown').upper())
        count = p.get('download_count', 0)
        total_bytes = p.get('total_bytes', 0)
        total_mb = round(total_bytes / (1024 * 1024), 2)
        failed = p.get('failed_count', 0)

        lines.append(f"*{name}*")
        lines.append(f"  Загрузок: {count} (ошибок: {failed})")
        lines.append(f"  Данные: {total_mb} MB\n")

    text = '\n'.join(lines)
    await message.reply(text, parse_mode='MarkdownV2')


async def cmd_user_stats(message: types.Message):
    user_id = message.from_user.id
    stats = get_user_stats(user_id)

    if not stats:
        await message.reply('📊 У вас пока нет загрузок.')
        return

    total_bytes = stats.get('total_bytes', 0)
    total_mb = round(total_bytes / (1024 * 1024), 2)
    first = _escape_md_v2(stats.get('first_download', 'N/A'))
    last = _escape_md_v2(stats.get('last_download', 'N/A'))

    text = (
        f"📊 *Ваша статистика:*\n\n"
        f"✓ Загрузок: {stats.get('total_downloads', 0)}\n"
        f"✗ Ошибок: {stats.get('failed_count', 0)}\n\n"
        f"📈 Загруженные данные: {total_mb} MB\n\n"
        f"📅 Первая загрузка: {first}\n"
        f"📅 Последняя загрузка: {last}"
    )
    await message.reply(text, parse_mode='MarkdownV2')


async def cmd_recent(message: types.Message):
    if not await is_admin(message):
        await message.reply('🔒 Только администраторы могут просматривать последние загрузки.')
        return

    if message.chat.type in ('group', 'supergroup'):
        downloads = get_group_recent_downloads(message.chat.id, limit=15)
        chat_title = _escape_md_v2(getattr(message.chat, 'title', str(message.chat.id)))
        header = f"📥 *Последние загрузки в группе ({chat_title})*: \n\n"
    else:
        downloads = get_recent_downloads(limit=15)
        header = '📥 *Последние 15 загрузок:*\n\n'

    if not downloads:
        await message.reply('📥 История загрузок пуста.')
        return

    lines = [header]
    for dl in downloads:
        uname = dl.get('username')
        first = dl.get('first_name') if 'first_name' in dl else None
        last = dl.get('last_name') if 'last_name' in dl else None
        display = _display_user_name(uname, first, last, dl.get('user_id'))
        platform = _escape_md_v2((dl.get('platform') or 'unknown').upper())
        status = '✓' if dl.get('status') == 'success' else '✗'
        size_mb = round((dl.get('file_size_bytes') or 0) / (1024 * 1024), 1)
        timestamp = _escape_md_v2(dl.get('timestamp', 'N/A'))
        err = _escape_md_v2(dl.get('error_message')) if dl.get('error_message') else None

        lines.append(f"{status} {display} ({platform}) — {size_mb} MB")
        lines.append(f"   {timestamp}")
        if err:
            lines.append(f"   Ошибка: {err}")
        lines.append('')

    text = '\n'.join(lines)
    await message.reply(text, parse_mode='MarkdownV2')


def register_admin_commands(dp):
    """Placeholder for registering handlers with a Dispatcher/Router in main.

    Keep as a no-op to avoid coupling to dispatcher API here — main.py may
    register these functions directly.
    """
    pass
"""Admin panel commands for stats and history.

Provides commands for admins to view usage reports via Telegram.
"""
import logging
import re
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
from db import (
    get_group_top_users,
    get_group_stats_summary,
    get_group_recent_downloads,
    get_group_platform_stats,
)

logger = logging.getLogger(__name__)


def _escape_md_v2(text: str) -> str:
    """Escape text for Telegram MarkdownV2 (safe for dynamic fields)."""
    if text is None:
        return ""
    s = str(text)
    return re.sub(r'([_\*\[\]()~`>#+\-=|{}\.!])', r'\\\\\1', s)


async def is_admin(message: types.Message) -> bool:
    user_id = message.from_user.id
    try:
        if is_authorized_admin(user_id):
            return True
    except Exception:
        pass
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


def _display_user_name(username: str, first_name: str, last_name: str, user_id: int) -> str:
    """Return a display string for a user: prefer @username, else full name, else id."""
    if username:
        return f"@{username}"
    name_parts = [p for p in (first_name, last_name) if p]
    if name_parts:
        # escape names when used in MarkdownV2
        return _escape_md_v2(' '.join(name_parts))
    return f"user_{user_id}"


async def cmd_stats(message: types.Message):
    if not await is_admin(message):
        await message.reply('🔒 Только администраторы могут просматривать статистику.')
        return

    if message.chat.type in ('group', 'supergroup'):
        stats = get_group_stats_summary(message.chat.id)
        chat_title = _escape_md_v2(getattr(message.chat, 'title', str(message.chat.id)))
        header = f"📊 *Статистика по группе ({chat_title})*: \n\n"
    else:
        stats = get_stats_summary()
        header = '📊 *Общая статистика бота*: \n\n'

    if not stats:
        await message.reply('📊 Статистика недоступна или БД пуста.')
        return

    total_bytes = stats.get('total_bytes', 0)
    total_mb = round(total_bytes / (1024 * 1024), 2)

    text = (
        f"{header}"
        f"✓ Всего загрузок: {stats.get('total_downloads', 0)}\n"
        f"✓ Успешных: {stats.get('successful_downloads', 0)}\n"
        f"✗ Ошибок: {stats.get('failed_downloads', 0)}\n\n"
        f"📈 Загруженные данные:\n   • {total_mb:.1f} MB\n\n"
        f"👥 Уникальных пользователей: {stats.get('unique_users', 0)}"
    )
    await message.reply(text, parse_mode='MarkdownV2')


async def cmd_top_users(message: types.Message):
    if not await is_admin(message):
        await message.reply('🔒 Только администраторы могут просматривать топ.')
        return

    if message.chat.type in ('group', 'supergroup'):
        users = get_group_top_users(message.chat.id, limit=10)
        chat_title = _escape_md_v2(getattr(message.chat, 'title', str(message.chat.id)))
        header = f"👥 *Топ пользователей в группе ({chat_title})*: \n\n"
    else:
        users = get_all_user_stats(limit=10)
        header = '👥 *Топ 10 пользователей:*\n\n'

    if not users:
        await message.reply('👥 Нет данных о пользователях.')
        return

    lines = [header]
    for i, user in enumerate(users, 1):
        username = user.get('username')
        first = user.get('first_name') if 'first_name' in user else None
        last = user.get('last_name') if 'last_name' in user else None
        display = _display_user_name(username, first, last, user.get('user_id'))
        downloads = user.get('total_downloads', 0)
        total_bytes = user.get('total_bytes', 0)
        total_mb = round(total_bytes / (1024 * 1024), 2)
        failed = user.get('failed_count', 0)

        lines.append(f"{i}. {display}")
        lines.append(f"   Загрузок: {downloads} (ошибок: {failed})")
        lines.append(f"   Данные: {total_mb} MB\n")

    text = '\n'.join(lines)
    await message.reply(text, parse_mode='MarkdownV2')


async def cmd_platform_stats(message: types.Message):
    if not await is_admin(message):
        await message.reply('🔒 Только администраторы могут просматривать статистику платформ.')
        return

    if message.chat.type in ('group', 'supergroup'):
        platforms = get_group_platform_stats(message.chat.id)
        chat_title = _escape_md_v2(getattr(message.chat, 'title', str(message.chat.id)))
        header = f"🌐 *Статистика по платформам (группа: {chat_title})*: \n\n"
    else:
        platforms = get_platform_stats()
        header = '🌐 *Статистика по платформам:*\n\n'

    if not platforms:
        await message.reply('🌐 Нет данных о платформах.')
        return

    lines = [header]
    for p in platforms:
        name = _escape_md_v2((p.get('platform') or 'unknown').upper())
        count = p.get('download_count', 0)
        total_bytes = p.get('total_bytes', 0)
        total_mb = round(total_bytes / (1024 * 1024), 2)
        failed = p.get('failed_count', 0)

        lines.append(f"*{name}*")
        lines.append(f"  Загрузок: {count} (ошибок: {failed})")
        lines.append(f"  Данные: {total_mb} MB\n")

    text = '\n'.join(lines)
    await message.reply(text, parse_mode='MarkdownV2')


async def cmd_user_stats(message: types.Message):
    user_id = message.from_user.id
    stats = get_user_stats(user_id)

    if not stats:
        await message.reply('📊 У вас пока нет загрузок.')
        return

    total_bytes = stats.get('total_bytes', 0)
    total_mb = round(total_bytes / (1024 * 1024), 2)
    first = _escape_md_v2(stats.get('first_download', 'N/A'))
    last = _escape_md_v2(stats.get('last_download', 'N/A'))

    text = (
        f"📊 *Ваша статистика:*\n\n"
        f"✓ Загрузок: {stats.get('total_downloads', 0)}\n"
        f"✗ Ошибок: {stats.get('failed_count', 0)}\n\n"
        f"📈 Загруженные данные: {total_mb} MB\n\n"
        f"📅 Первая загрузка: {first}\n"
        f"📅 Последняя загрузка: {last}"
    )
    await message.reply(text, parse_mode='MarkdownV2')


async def cmd_recent(message: types.Message):
    if not await is_admin(message):
        await message.reply('🔒 Только администраторы могут просматривать последние загрузки.')
        return

    if message.chat.type in ('group', 'supergroup'):
        downloads = get_group_recent_downloads(message.chat.id, limit=15)
        chat_title = _escape_md_v2(getattr(message.chat, 'title', str(message.chat.id)))
        header = f"📥 *Последние загрузки в группе ({chat_title})*: \n\n"
    else:
        downloads = get_recent_downloads(limit=15)
        header = '📥 *Последние 15 загрузок:*\n\n'

    if not downloads:
        await message.reply('📥 История загрузок пуста.')
        return

    lines = [header]
    for dl in downloads:
        uname = dl.get('username')
        first = dl.get('first_name') if 'first_name' in dl else None
        last = dl.get('last_name') if 'last_name' in dl else None
        display = _display_user_name(uname, first, last, dl.get('user_id'))
        platform = _escape_md_v2((dl.get('platform') or 'unknown').upper())
        status = '✓' if dl.get('status') == 'success' else '✗'
        size_mb = round((dl.get('file_size_bytes') or 0) / (1024 * 1024), 1)
        timestamp = _escape_md_v2(dl.get('timestamp', 'N/A'))
        err = _escape_md_v2(dl.get('error_message')) if dl.get('error_message') else None

        lines.append(f"{status} {display} ({platform}) — {size_mb} MB")
        lines.append(f"   {timestamp}")
        if err:
            lines.append(f"   Ошибка: {err}")
        lines.append('')

    text = '\n'.join(lines)
    await message.reply(text, parse_mode='MarkdownV2')


def register_admin_commands(dp):
    pass
"""Admin panel commands for stats and history.

Provides commands for admins to view usage reports via Telegram.
"""
import logging
import re
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
from db import (
    get_group_top_users,
    get_group_stats_summary,
    get_group_recent_downloads,
    get_group_platform_stats,
)

logger = logging.getLogger(__name__)


def _escape_md_v2(text: str) -> str:
    """Escape text for Telegram MarkdownV2 (safe for dynamic fields)."""
    if text is None:
        return ""
    s = str(text)
    return re.sub(r'([_\*\[\]()~`>#+\-=|{}\.!])', r'\\\\\1', s)


async def is_admin(message: types.Message) -> bool:
    user_id = message.from_user.id
    try:
        if is_authorized_admin(user_id):
            return True
    except Exception:
        pass
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


def _display_user_name(username: str, first_name: str, last_name: str, user_id: int) -> str:
    """Return a display string for a user: prefer @username, else full name, else id."""
    if username:
        return f"@{username}"
    name_parts = [p for p in (first_name, last_name) if p]
    if name_parts:
        # escape names when used in MarkdownV2
        return _escape_md_v2(' '.join(name_parts))
    return f"user_{user_id}"


async def cmd_stats(message: types.Message):
    if not await is_admin(message):
        await message.reply('🔒 Только администраторы могут просматривать статистику.')
        return

    if message.chat.type in ('group', 'supergroup'):
        stats = get_group_stats_summary(message.chat.id)
        chat_title = _escape_md_v2(getattr(message.chat, 'title', str(message.chat.id)))
        header = f"📊 *Статистика по группе ({chat_title})*:\n\n"
    else:
        stats = get_stats_summary()
        header = "📊 *Общая статистика бота*: \n\n"

    if not stats:
        await message.reply('📊 Статистика недоступна или БД пуста.')
        return

    total_bytes = stats.get('total_bytes', 0)
    total_mb = round(total_bytes / (1024 * 1024), 2)

    text = (
        f"{header}"
        f"✓ Всего загрузок: {stats.get('total_downloads', 0)}\n"
        f"✓ Успешных: {stats.get('successful_downloads', 0)}\n"
        f"✗ Ошибок: {stats.get('failed_downloads', 0)}\n\n"
        f"📈 Загруженные данные:\n   • {total_mb:.1f} MB\n\n"
        f"👥 Уникальных пользователей: {stats.get('unique_users', 0)}"
    )
    await message.reply(text, parse_mode='MarkdownV2')


async def cmd_top_users(message: types.Message):
    if not await is_admin(message):
        await message.reply('🔒 Только администраторы могут просматривать топ.')
        return

    if message.chat.type in ('group', 'supergroup'):
        users = get_group_top_users(message.chat.id, limit=10)
        chat_title = _escape_md_v2(getattr(message.chat, 'title', str(message.chat.id)))
        header = f"👥 *Топ пользователей в группе ({chat_title})*: \n\n"
    else:
        users = get_all_user_stats(limit=10)
        header = '👥 *Топ 10 пользователей:*\n\n'

    if not users:
        await message.reply('👥 Нет данных о пользователях.')
        return

    lines = [header]
    for i, user in enumerate(users, 1):
        username = user.get('username')
        first = user.get('first_name') if 'first_name' in user else None
        last = user.get('last_name') if 'last_name' in user else None
        display = _display_user_name(username, first, last, user.get('user_id'))
        downloads = user.get('total_downloads', 0)
        total_bytes = user.get('total_bytes', 0)
        total_mb = round(total_bytes / (1024 * 1024), 2)
        failed = user.get('failed_count', 0)

        lines.append(f"{i}. {display}")
        lines.append(f"   Загрузок: {downloads} (ошибок: {failed})")
        lines.append(f"   Данные: {total_mb} MB\n")

    text = '\n'.join(lines)
    await message.reply(text, parse_mode='MarkdownV2')


async def cmd_platform_stats(message: types.Message):
    if not await is_admin(message):
        await message.reply('🔒 Только администраторы могут просматривать статистику платформ.')
        return

    if message.chat.type in ('group', 'supergroup'):
        platforms = get_group_platform_stats(message.chat.id)
        chat_title = _escape_md_v2(getattr(message.chat, 'title', str(message.chat.id)))
        header = f"🌐 *Статистика по платформам (группа: {chat_title})*: \n\n"
    else:
        platforms = get_platform_stats()
        header = '🌐 *Статистика по платформам:*\n\n'

    if not platforms:
        await message.reply('🌐 Нет данных о платформах.')
        return

    lines = [header]
    for p in platforms:
        name = _escape_md_v2((p.get('platform') or 'unknown').upper())
        count = p.get('download_count', 0)
        total_bytes = p.get('total_bytes', 0)
        total_mb = round(total_bytes / (1024 * 1024), 2)
        failed = p.get('failed_count', 0)

        lines.append(f"*{name}*")
        lines.append(f"  Загрузок: {count} (ошибок: {failed})")
        lines.append(f"  Данные: {total_mb} MB\n")

    text = '\n'.join(lines)
    await message.reply(text, parse_mode='MarkdownV2')


async def cmd_user_stats(message: types.Message):
    user_id = message.from_user.id
    stats = get_user_stats(user_id)

    if not stats:
        await message.reply('📊 У вас пока нет загрузок.')
        return

    total_bytes = stats.get('total_bytes', 0)
    total_mb = round(total_bytes / (1024 * 1024), 2)
    first = _escape_md_v2(stats.get('first_download', 'N/A'))
    last = _escape_md_v2(stats.get('last_download', 'N/A'))

    text = (
        f"📊 *Ваша статистика:*\n\n"
        f"✓ Загрузок: {stats.get('total_downloads', 0)}\n"
        f"✗ Ошибок: {stats.get('failed_count', 0)}\n\n"
        f"📈 Загруженные данные: {total_mb} MB\n\n"
        f"📅 Первая загрузка: {first}\n"
        f"📅 Последняя загрузка: {last}"
    )
    await message.reply(text, parse_mode='MarkdownV2')


async def cmd_recent(message: types.Message):
    if not await is_admin(message):
        await message.reply('🔒 Только администраторы могут просматривать последние загрузки.')
        return

    if message.chat.type in ('group', 'supergroup'):
        downloads = get_group_recent_downloads(message.chat.id, limit=15)
        chat_title = _escape_md_v2(getattr(message.chat, 'title', str(message.chat.id)))
        header = f"📥 *Последние загрузки в группе ({chat_title})*: \n\n"
    else:
        downloads = get_recent_downloads(limit=15)
        header = '📥 *Последние 15 загрузок:*\n\n'

    if not downloads:
        await message.reply('📥 История загрузок пуста.')
        return

    lines = [header]
    for dl in downloads:
        uname = dl.get('username')
        first = dl.get('first_name') if 'first_name' in dl else None
        last = dl.get('last_name') if 'last_name' in dl else None
        display = _display_user_name(uname, first, last, dl.get('user_id'))
        platform = _escape_md_v2((dl.get('platform') or 'unknown').upper())
        status = '✓' if dl.get('status') == 'success' else '✗'
        size_mb = round((dl.get('file_size_bytes') or 0) / (1024 * 1024), 1)
        timestamp = _escape_md_v2(dl.get('timestamp', 'N/A'))
        err = _escape_md_v2(dl.get('error_message')) if dl.get('error_message') else None

        lines.append(f"{status} {display} ({platform}) — {size_mb} MB")
        lines.append(f"   {timestamp}")
        if err:
            lines.append(f"   Ошибка: {err}")
        lines.append('')

    text = '\n'.join(lines)
    await message.reply(text, parse_mode='MarkdownV2')


def register_admin_commands(dp):
    pass
"""Команды админ-панели для просмотра статистики и истории.

Позволяет администраторам получать отчёты о использовании бота через Telegram.
"""
import logging
import re
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
from db import (
    get_group_top_users,
    get_group_stats_summary,
    get_group_recent_downloads,
    get_group_platform_stats,
)

logger = logging.getLogger(__name__)


def _escape_md_v2(text: str) -> str:
    """Escape text for Telegram MarkdownV2.

    Telegram MarkdownV2 requires a number of characters to be escaped.
    This helper ensures any dynamic content (usernames, titles, errors)
    won't break message parsing.
    """
    if text is None:
        return ""
    s = str(text)
    return re.sub(r'([_\*\[\]()~`>#+\-=|{}\.!])', r'\\\1', s)


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

    # Если команда вызвана в группе — показываем статистику только по этой группе
    if message.chat.type in ("group", "supergroup"):
        stats = get_group_stats_summary(message.chat.id)
        header = f"📊 Статистика по группе ({getattr(message.chat, 'title', message.chat.id)}) :\n\n"
    else:
        stats = get_stats_summary()
        header = "📊 Общая статистика бота:\n\n"

    if not stats:
        await message.reply("📊 У вас пока нет загрузок.")
        return

    total_bytes = stats.get('total_bytes', 0)
    total_mb = round(total_bytes / (1024 * 1024), 2)

    # Escape dynamic values
    first = _escape_md_v2(stats.get('first_download', 'N/A'))
    last = _escape_md_v2(stats.get('last_download', 'N/A'))

    text = (
        f"📊 *Ваша статистика:*\n\n"
        f"✓ Загрузок: {stats.get('total_downloads', 0)}\n"
        f"✗ Ошибок: {stats.get('failed_count', 0)}\n\n"
        f"📈 Загруженные данные: {total_mb} MB\n\n"
        f"📅 Первая загрузка: {first}\n"
        f"📅 Последняя загрузка: {last}"
    )
    await message.reply(text, parse_mode="MarkdownV2")
async def cmd_top_users(message: types.Message):
    """Команда /top_users — топ пользователей."""
    if not await is_admin(message):
        await message.reply("🔒 Только администраторы могут просматривать топ.")
        return
    # По умолчанию — глобально. Если вызвано в группе — по этой группе.
    if message.chat.type in ("group", "supergroup"):
        users = get_group_top_users(message.chat.id, limit=10)
        header = f"👥 **Топ пользователей в группе ({getattr(message.chat, 'title', message.chat.id)}):**\n\n"
    else:
        users = get_all_user_stats(limit=10)
        header = "👥 **Топ 10 пользователей:**\n\n"
    
    if not users:
        await message.reply("👥 Нет данных о пользователях.")
        return
    
    text = header
    
    for i, user in enumerate(users, 1):
        username = user.get('username') or f"user_{user.get('user_id')}"
        downloads = user.get('total_downloads', 0)
        total_bytes = user.get('total_bytes', 0)
        total_mb = round(total_bytes / (1024 * 1024), 2)
        failed = user.get('failed_count', 0)
        
        text += f"{i}. @{username}\n"
        text += f"   Загрузок: {downloads} (ошибок: {failed})\n"
        text += f"   Данные: {total_mb} MB\n\n"
    
    await message.reply(text)


async def cmd_platform_stats(message: types.Message):
    """Команда /platform_stats — статистика по платформам."""
    if not await is_admin(message):
        await message.reply("🔒 Только администраторы могут просматривать статистику платформ.")
        return
    # Групповая или глобальная статистика по платформам
    if message.chat.type in ("group", "supergroup"):
        platforms = get_group_platform_stats(message.chat.id)
        header = f"🌐 **Статистика по платформам (группа: {getattr(message.chat, 'title', message.chat.id)}):**\n\n"
    else:
        platforms = get_platform_stats()
        header = "🌐 **Статистика по платформам:**\n\n"
    
    if not users:
        await message.reply("👥 Нет данных о пользователях.")
        return

    # Build markdown-safe text
    header_esc = _escape_md_v2(header)
    lines = [header_esc]
    for i, user in enumerate(users, 1):
        username = user.get('username') or f"user_{user.get('user_id')}"
        downloads = user.get('total_downloads', 0)
        total_bytes = user.get('total_bytes', 0)
        total_mb = round(total_bytes / (1024 * 1024), 2)
        failed = user.get('failed_count', 0)

        u_esc = _escape_md_v2(username)
        lines.append(f"{i}. @{u_esc}")
        lines.append(f"   Загрузок: {downloads} (ошибок: {failed})")
        lines.append(f"   Данные: {total_mb} MB\n")

    text = "\n".join(lines)
    await message.reply(text, parse_mode="MarkdownV2")
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
    
    await message.reply(text)


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
            platform = _escape_md_v2((dl.get('platform') or 'unknown').upper())
            status = "✓" if dl.get('status') == 'success' else "✗"
            size_mb = round((dl.get('file_size_bytes') or 0) / (1024 * 1024), 1)
            timestamp = _escape_md_v2(dl.get('timestamp', 'N/A'))
            err = _escape_md_v2(dl.get('error_message')) if dl.get('error_message') else None

            u_esc = _escape_md_v2(username)
            text += f"{status} @{u_esc} ({platform}) — {size_mb} MB\n"
            text += f"   {timestamp}\n"
            if err:
                text += f"   Ошибка: {err}\n"
            text += "\n"
    
    await message.reply(text)


def register_admin_commands(dp):
    """Зарегистрировать команды админ-панели в dispatcher."""
    # Для регистрации команд нужно использовать message handler с проверкой текста
    # Это будет сделано в main.py
    pass
