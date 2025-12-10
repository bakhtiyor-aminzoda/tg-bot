"""Модуль для проверки доступа и авторизации пользователя.

Поддерживает:
- Whitelist режим (только разрешённые пользователи)
- Admin-only режим (только администраторы)
- Комбинированный режим
"""
import logging
from typing import Optional

from aiogram import types

import config

logger = logging.getLogger(__name__)


async def is_user_allowed(message: types.Message) -> bool:
    """Проверить, разрешена ли загрузка данному пользователю.
    
    Возвращает True если:
    - Все режимы отключены, или
    - Пользователь в списке разрешённых, или
    - Пользователь является администратором (если ADMIN_ONLY=True)
    """
    user_id = message.from_user.id
    
    # Если оба режима отключены — разрешаем всем
    if not config.WHITELIST_MODE and not config.ADMIN_ONLY:
        return True
    
    # Проверка whitelist режима
    if config.WHITELIST_MODE:
        if user_id not in config.ALLOWED_USER_IDS:
            logger.warning("Пользователь %d не в whitelist", user_id)
            return False
    
    # Проверка admin-only режима
    if config.ADMIN_ONLY:
        # Проверяем, является ли пользователь администратором
        is_admin = await _is_admin(message)
        if not is_admin:
            logger.warning("Пользователь %d не администратор", user_id)
            return False
    
    return True


async def _is_admin(message: types.Message) -> bool:
    """Проверить, является ли пользователь администратором.
    
    Администратор если:
    - В списке ADMIN_USER_IDS, или
    - Администратор в группе/канале (для групповых сообщений)
    """
    user_id = message.from_user.id
    
    # Проверяем специальный список админов
    if user_id in config.ADMIN_USER_IDS:
        return True
    
    # Для личных сообщений (private chat) не проверяем права группы
    if message.chat.type == "private":
        return False
    
    # Для групп/каналов проверяем права администратора
    try:
        member = await message.bot.get_chat_member(message.chat.id, user_id)
        # Проверяем, является ли пользователь администратором
        return member.status in ("administrator", "creator")
    except Exception as e:
        logger.warning("Ошибка при проверке прав администратора: %s", e)
        return False


def get_access_denied_message() -> str:
    """Получить сообщение об отказе в доступе в зависимости от режима."""
    if config.WHITELIST_MODE and config.ADMIN_ONLY:
        return "🔒 Доступ разрешён только администраторам или авторизованным пользователям."
    elif config.WHITELIST_MODE:
        return "🔒 Доступ разрешён только авторизованным пользователям."
    elif config.ADMIN_ONLY:
        return "🔒 Доступ разрешён только администраторам."
    else:
        return "🔒 Доступ запрещён."


async def check_and_log_access(message: types.Message) -> bool:
    """Проверить доступ и залогировать результат. Возвращает True если разрешено."""
    user_id = message.from_user.id
    username = message.from_user.username or f"user_{user_id}"
    
    if await is_user_allowed(message):
        logger.info("✓ Доступ разрешен пользователю %s (ID: %d)", username, user_id)
        return True
    else:
        logger.warning("✗ Доступ запрещен пользователю %s (ID: %d)", username, user_id)
        return False
