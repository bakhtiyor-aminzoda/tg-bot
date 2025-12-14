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
            "⬇️ Скачиваем медиа из {platform}...\n"
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
            "✅ Готово! Медиа из {platform} уже у вас.\n"
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
        "download.caption.video": "Видео скачано с {platform} — @MediaBanditbot",
        "download.caption.photo": "Фото скачано с {platform} — @MediaBanditbot",
        "download.document_caption.video": "Видео (файл) — скачано с помощью @MediaBanditbot",
        "download.document_caption.photo": "Фото (файл) — скачано с помощью @MediaBanditbot",
        "download.quota_daily_exceeded": "🚦 Тариф {plan} позволяет {limit} загрузок в день. Лимит обновится через {reset}.",
        "download.quota_monthly_exceeded": "🚦 Вы исчерпали месячный лимит ({limit}) по тарифу {plan}. Лимит обновится через {reset}.",
        "download.quota_upgrade_hint": "Нужен больший лимит? Напишите @MediaBanditSupport или оформите /upgrade.",
        "upgrade.header": "🚀 Хотите больше лимитов? Посмотрите доступные тарифы ниже.",
        "upgrade.current_plan": "Текущий тариф: {plan} — {daily}/день и {monthly}/мес.",
        "upgrade.pick_plan": "Доступные опции:",
        "upgrade.plan_line": "• {label}: до {daily}/день и {monthly}/мес · {price}{desc}",
        "upgrade.price_free": "Бесплатно",
        "upgrade.price_paid": "${price}/мес",
        "upgrade.cta": "Оставьте заявку через @MediaBanditSupport или по кнопке ниже — мы подключим тариф за пару минут.",
        "upgrade.button_contact": "Связаться с поддержкой",
        "upgrade.no_plans": "Тарифы временно недоступны. Попробуйте позже.",
        "referral.header": "🎁 Приглашайте друзей и получайте дополнительные лимиты!",
        "referral.bonus_line": "+{daily}/день · +{monthly}/мес активного бонуса",
        "referral.no_bonus": "Бонусы пока не получены.",
        "referral.code_line": "• Код {code} — использований {used}/{max}",
        "referral.single_bonus": "Активный бонус: +{daily}/день · +{monthly}/мес",
        "referral.copy_success": "Скопировано!",
        "referral.copy_fail": "Не удалось скопировать.",
        "referral.enter_code_prompt": "Введите реферальный код через пробел, например /use_referral MB-XXXX.",
        "referral.leaderboard_footer": "Используйте /ref_leaderboard, чтобы увидеть полный рейтинг.",
        "referral.generate": "Нажмите кнопку ниже, чтобы получить личный код.",
        "referral.share_hint": "Поделитесь кодом: {code} — и получите бонус после 1-й успешной загрузки друга.",
        "referral.button_generate": "Сгенерировать код",
        "referral.button_copy": "Скопировать код",
        "referral.button_leaderboard": "Топ рефералов",
        "referral.leaderboard_header": "🏆 Топ рефералов",
        "referral.leaderboard_line": "{place}. {user} — {count} подтверждений (+{daily}/день · +{monthly}/мес)",
        "referral.leaderboard_empty": "Пока нет подтверждённых приглашений.",
        "referral.register_success": "✅ Код принят! Дождитесь первой загрузки, чтобы получить бонус.",
        "referral.register_error": "⚠️ {reason}",
        "referral.admin_confirmed": "Реферал подтверждён: +{daily}/день и +{monthly}/мес до {expiry}.",
    },
    "en": {
        "status.waiting": (
            "🎯 Platform: {platform}\n"
            "⏳ Status: waiting for a free slot\n"
            "👤 Your downloads: {active}/{limit}\n"
            "We'll notify you as soon as the transfer starts."
        ),
        "status.downloading": (
            "⬇️ Downloading media from {platform}...\n"
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
            "✅ Done! The {platform} media is already with you.\n"
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
        "download.caption.video": "Video downloaded from {platform} — @MediaBanditbot",
        "download.caption.photo": "Photo downloaded from {platform} — @MediaBanditbot",
        "download.document_caption.video": "Video (file) — downloaded via @MediaBanditbot",
        "download.document_caption.photo": "Photo (file) — downloaded via @MediaBanditbot",
        "download.quota_daily_exceeded": "🚦 Your {plan} plan allows {limit} downloads per day. Limit resets in {reset}.",
        "download.quota_monthly_exceeded": "🚦 You've reached the monthly limit ({limit}) on {plan}. Limit resets in {reset}.",
        "download.quota_upgrade_hint": "Need more? Reach out to @MediaBanditSupport or use /upgrade to unlock bigger limits.",
        "upgrade.header": "🚀 Need more downloads? Check the plans below.",
        "upgrade.current_plan": "Your current plan: {plan} — {daily}/day and {monthly}/month.",
        "upgrade.pick_plan": "Available options:",
        "upgrade.plan_line": "• {label}: up to {daily}/day and {monthly}/month · {price}{desc}",
        "upgrade.price_free": "Free",
        "upgrade.price_paid": "${price}/mo",
        "upgrade.cta": "Tap the button or message @MediaBanditSupport to upgrade in minutes.",
        "upgrade.button_contact": "Talk to support",
        "upgrade.no_plans": "Plans are temporarily unavailable. Please try again soon.",
        "referral.header": "🎁 Invite friends to earn extra limits!",
        "referral.bonus_line": "+{daily}/day · +{monthly}/month active bonus",
        "referral.no_bonus": "No active bonuses yet.",
        "referral.code_line": "• Code {code} — uses {used}/{max}",
        "referral.single_bonus": "Active bonus: +{daily}/day · +{monthly}/month",
        "referral.copy_success": "Copied!",
        "referral.copy_fail": "Failed to copy.",
        "referral.enter_code_prompt": "Provide a referral code like /use_referral MB-XXXX.",
        "referral.leaderboard_footer": "Use /ref_leaderboard to see the full board.",
        "referral.generate": "Tap the button below to generate your personal code.",
        "referral.share_hint": "Share your code {code} and receive a boost after the first successful download.",
        "referral.button_generate": "Generate code",
        "referral.button_copy": "Copy code",
        "referral.button_leaderboard": "Referral leaderboard",
        "referral.leaderboard_header": "🏆 Top referrers",
        "referral.leaderboard_line": "{place}. {user} — {count} confirmations (+{daily}/day · +{monthly}/month)",
        "referral.leaderboard_empty": "No confirmed invites yet.",
        "referral.register_success": "✅ Code accepted! Wait for the first download to activate the bonus.",
        "referral.register_error": "⚠️ {reason}",
        "referral.admin_confirmed": "Referral rewarded: +{daily}/day and +{monthly}/month until {expiry}.",
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
