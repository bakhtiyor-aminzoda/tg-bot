"""Lightweight translation helpers for user-facing strings."""

from __future__ import annotations

from typing import Dict, Optional

DEFAULT_LOCALE = "ru"
SUPPORTED_LOCALES = {"ru", "en"}

_TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "ru": {
        "status.waiting": (
            "🎯 Платформа: {platform}\n"
            "⏳ Состояние: ждём свободное окно\n"
            "👤 Ваши загрузки: {active}/{limit}\n"
            "Мы сообщим, как только стартуем скачивание."
        ),
        "status.downloading": (
            "⬇️ Скачиваем видео с {platform}...\n"
            "Это может занять пару минут — можно продолжать переписку."
        ),
        "status.downloading_progress": (
            "⬇️ {platform}: {percent}\n"
            "⚡️ Скорость: {speed}\n"
            "⌛️ ETA: {eta}\n"
            "💾 {downloaded} / {total}"
        ),
        "status.processing": "🛠 Обрабатываем файл {platform}...\nПочти готово!",
        "status.sending": "📤 Отправляем файл из {platform}...\nТелеграм готовит вложение.",
        "status.success": (
            "✅ Готово! Видео с {platform} уже у вас.\n"
            "Смело делитесь и возвращайтесь за новыми ссылками."
        ),
        "status.error": "⚠️ Ошибка: {reason}\nПопробуйте ещё раз или проверьте ссылку.",
        "buttons.download_more": "↻ Скачать ещё",
        "buttons.open_source": "🔗 Открыть источник",
        "buttons.share_bot": "📣 Поделиться ботом",
        "download.prompt_url": (
            "Пришлите ссылку после /download или ответьте этой командой на сообщение с ссылкой."
        ),
        "download.unsupported": "Неподдерживаемая ссылка. Доступно: YouTube, TikTok, Instagram.",
        "download.group_button_prompt": "Нажмите кнопку, чтобы скачать видео.",
        "download.group_button": "⬇️ Скачать",
        "download.pending_missing": "Ссылка устарела или недоступна.",
        "download.pending_expired": "Срок действия кнопки истёк.",
        "download.chat_rate_limited": "В этом чате слишком много одновременных загрузок. Попробуйте позже.",
        "download.global_rate_limited": "Бот обрабатывает слишком много запросов. Попробуйте чуть позже.",
        "download.active_limit": "У вас уже {active} активных загрузок (максимум {limit}). Подождите их завершения.",
        "download.cooldown": "Слишком часто! Подождите ещё {seconds} с.",
        "download.large_file_limit": "Видео слишком большое для Telegram (лимит 2 ГБ).",
        "download.starting": "Запускаю...",
        "download.source_unavailable": "Ссылка недоступна.",
        "download.telegram_send_error": "Ошибка отправки файла в Telegram: {reason}",
        "download.video_caption": "Видео скачано с {platform} — @MediaBanditbot",
    },
    "en": {
        "status.waiting": (
            "🎯 Platform: {platform}\n"
            "⏳ Status: waiting for a free slot\n"
            "👤 Your downloads: {active}/{limit}\n"
            "We'll notify you as soon as the transfer starts."
        ),
        "status.downloading": (
            "⬇️ Downloading from {platform}...\n"
            "This may take a minute—feel free to keep chatting."
        ),
        "status.downloading_progress": (
            "⬇️ {platform}: {percent}\n"
            "⚡️ Speed: {speed}\n"
            "⌛️ ETA: {eta}\n"
            "💾 {downloaded} / {total}"
        ),
        "status.processing": "🛠 Processing the {platform} file...\nAlmost there!",
        "status.sending": "📤 Sending the file from {platform}...\nTelegram is preparing the attachment.",
        "status.success": (
            "✅ Done! The {platform} video is already with you.\n"
            "Share it or send another link anytime."
        ),
        "status.error": "⚠️ Error: {reason}\nTry again or double-check the link.",
        "buttons.download_more": "↻ Download more",
        "buttons.open_source": "🔗 Open source",
        "buttons.share_bot": "📣 Share the bot",
        "download.prompt_url": "Send a link after /download or reply to a message that already contains one.",
        "download.unsupported": "Unsupported link. Available sources: YouTube, TikTok, Instagram.",
        "download.group_button_prompt": "Press the button to fetch the video.",
        "download.group_button": "⬇️ Download",
        "download.pending_missing": "The link expired or is unavailable.",
        "download.pending_expired": "The button has expired.",
        "download.chat_rate_limited": "Too many downloads are running in this chat. Please try again in a moment.",
        "download.global_rate_limited": "The bot is processing too many requests. Please try again shortly.",
        "download.active_limit": "You already have {active} active downloads (limit {limit}). Please wait for them to finish.",
        "download.cooldown": "Too fast! Please wait another {seconds}s.",
        "download.large_file_limit": "The video is too large for Telegram (2 GB limit).",
        "download.starting": "Starting...",
        "download.source_unavailable": "Link unavailable.",
        "download.telegram_send_error": "Failed to send the file to Telegram: {reason}",
        "download.video_caption": "Video downloaded from {platform} — @MediaBanditbot",
    },
}

def get_locale(language_code: Optional[str]) -> str:
    """Normalize Telegram language codes to our supported locales."""

    if not language_code:
        return DEFAULT_LOCALE
    normalized = language_code.split("-")[0].lower()
    return normalized if normalized in SUPPORTED_LOCALES else DEFAULT_LOCALE


def translate(key: str, locale: Optional[str] = None, **kwargs) -> str:
    """Return translated text for the given key with graceful fallback."""

    lang = locale or DEFAULT_LOCALE
    if lang not in _TRANSLATIONS:
        lang = DEFAULT_LOCALE
    template = _TRANSLATIONS[lang].get(key)
    if template is None:
        template = _TRANSLATIONS[DEFAULT_LOCALE].get(key, key)
    try:
        return template.format(**kwargs)
    except Exception:
        # As a last resort, return the raw template to avoid crashing user handlers.
        return template


__all__ = ["DEFAULT_LOCALE", "SUPPORTED_LOCALES", "get_locale", "translate"]
