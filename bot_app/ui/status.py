"""UX helpers for status texts and inline markups."""

from __future__ import annotations

from typing import Optional

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

BOT_LINK = "https://t.me/MediaBanditbot"
SHARE_LINK = (
    "https://t.me/share/url?url=https://t.me/MediaBanditbot&text=%F0%9F%8E%A5%20"
    "%D0%9F%D0%BE%D0%BF%D1%80%D0%BE%D0%B1%D1%83%D0%B9%20Media%20Bandit%20%E2%9E%A1%EF%B8%8F"
)


def _format_platform(platform: str) -> str:
    return (platform or "unknown").capitalize()


def waiting(platform: str, active: int, max_per_user: int) -> str:
    return (
        f"🎯 Платформа: {_format_platform(platform)}\n"
        "⏳ Состояние: ожидаем свободное окно\n"
        f"👤 Ваши загрузки: {active}/{max_per_user}\n"
        "Мы пришлём обновление, как только начнём скачивание."
    )


def downloading(platform: str) -> str:
    return (
        f"⬇️ Скачиваем видео с {_format_platform(platform)}...\n"
        "Это может занять пару минут — можно продолжать переписку."
    )


def processing(platform: str) -> str:
    return (
        f"🛠 Обрабатываем файл {_format_platform(platform)}...\n"
        "Почти готово!"
    )


def sending(platform: str) -> str:
    return (
        f"📤 Отправляем файл из {_format_platform(platform)}...\n"
        "Телеграм готовит вложение."
    )


def success(platform: str) -> str:
    return (
        f"✅ Готово! Видео с {_format_platform(platform)} уже у вас.\n"
        "Смело делитесь и возвращайтесь за новыми ссылками."
    )


def error(reason: str) -> str:
    return f"⚠️ Ошибка: {reason}\nПопробуйте ещё раз или проверьте ссылку."


def success_markup(source_url: Optional[str]) -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(text="↻ Скачать ещё", url=BOT_LINK)]]
    row = []
    if source_url:
        row.append(InlineKeyboardButton(text="🔗 Открыть источник", url=source_url))
    row.append(InlineKeyboardButton(text="📣 Поделиться ботом", url=SHARE_LINK))
    buttons.append(row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)
