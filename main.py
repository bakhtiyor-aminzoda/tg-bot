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
from datetime import datetime
from typing import Optional

from aiogram import F, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import config
import bot_app.handlers.callbacks  # noqa: F401
import bot_app.handlers.downloads  # noqa: F401
from bot_app.maintenance import start_background_tasks, stop_background_tasks
from bot_app.runtime import bot, dp
from bot_app.ui.i18n import get_locale, translate
from bot_app.referral import build_profile_view
from monitoring import HealthCheckServer
from admin_panel_web import AdminPanelServer

logger = logging.getLogger(__name__)

START_CTA_KEYBOARD = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="📥 Скачать без лишних вопросов", callback_data="start:download")],
        [InlineKeyboardButton(text="🕳 Что здесь вообще происходит?", callback_data="start:howto")],
        [InlineKeyboardButton(text="📇 Профиль", callback_data="profile:section:overview")],
    ]
)

def _extract_start_payload(message: types.Message) -> str:
    text = message.text or ""
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        return ""
    return parts[1].strip()

async def _handle_start_referral(user_id: int, locale: str, payload: str) -> Optional[str]:
    if not config.ENABLE_HISTORY or not payload or not user_id:
        return None
    normalized = payload.strip()
    if not normalized.lower().startswith("ref_"):
        return None
    code = normalized[4:].strip()
    if not code:
        return None
    try:
        referral_service.register_referral(code, user_id)
    except ValueError as exc:
        logger.info("Auto referral registration skipped: %s", exc)
        return None
    return translate("referral.register_success", locale)


async def _send_profile(
    message: types.Message,
    locale: str,
    *,
    section: str = "overview",
    reply: bool = False,
) -> types.Message:
    text, markup = build_profile_view(message.from_user.id, locale, section=section)
    sender = message.reply if reply else message.answer
    return await sender(text, reply_markup=markup)

# === История загрузок (опционально) ===
if config.ENABLE_HISTORY:
    from db import init_db, add_authorized_admin, remove_authorized_admin
    from admin_panel_clean import (
        cmd_stats, cmd_top_users, cmd_platform_stats,
        cmd_user_stats, cmd_recent, cmd_referral_overview,
        cmd_confirm_referral, is_admin,
    )
    from bot_app import quota as quota_ui
    from services import quotas as quota_service
    from services import referrals as referral_service
    from services import alerts as alert_service
    from db import sync_subscription_plans

    try:
        init_db()
        sync_subscription_plans(config.SUBSCRIPTION_PLANS)
    except Exception as e:
        logger.warning("Не удалось инициализировать БД истории: %s", e)
        config.ENABLE_HISTORY = False

# ---------- Базовые команды ----------


@dp.message(Command("start"))
async def cmd_start_handler(message: types.Message):
    """Приветственное сообщение с чёрным юмором и быстрыми CTA."""

    chat_type = getattr(message.chat, "type", "private")
    in_private = chat_type == "private"
    locale = get_locale(getattr(getattr(message, "from_user", None), "language_code", None))
    start_payload = _extract_start_payload(message)

    opener_lines = [
        "😈 <b>Media Bandit на связи.</b>",
        "Я похищаю ваши видео быстрее, чем их автор успевает нажать «удалить».",
        "Если нужна совесть — ищи другой бот, здесь только быстрый дамп ссылок.",
    ]

    if in_private:
        usage_hint = (
            "🔒 <b>Личные сообщения:</b> просто швыряй ссылку сюда. "
            "Можно с подписью, можно ответом на своё же сообщение — я всё равно вскрою контент."
        )
    else:
        usage_hint = (
            "👥 <b>Группы и супергруппы:</b> ответь на сообщение с ссылкой или вставь URL в чат. "
            "Я тихо отработаю и удалю хвосты, пока модеры делают вид, что всё под контролем."
        )

    outro = (
        "💀 Нажми кнопку ниже: одно касание, и у тебя официальный алиби — будто ты просто грузил котиков." 
        " Попутно можешь звать друзей командой /referral, пусть тоже страдают от изобилия контента."
    )

    referral_notice = await _handle_start_referral(message.from_user.id, locale, start_payload)

    text = "\n\n".join(opener_lines + [usage_hint, outro])
    await message.reply(text, parse_mode="HTML", reply_markup=START_CTA_KEYBOARD)

    if referral_notice:
        await message.answer(referral_notice)
    profile_section = "referrals" if referral_notice else "overview"
    await _send_profile(message, locale, section=profile_section)


@dp.callback_query(lambda cq: (cq.data or "").startswith("start:"))
async def start_cta_callback(callback_query: types.CallbackQuery):
    """Обработчик инлайн-кнопок на /start."""

    payload = (callback_query.data or "start:download").split(":", 1)[1]
    message = getattr(callback_query, "message", None)
    chat_type = getattr(message, "chat", None)
    chat_type = getattr(chat_type, "type", "private")
    in_private = chat_type == "private"

    if payload == "howto":
        toast = "Гайд прилетел 👇"
        text = (
            "🕳 <b>Суровый мануал:</b>\n"
            "• До 3 параллельных загрузок на пользователя, чтобы сервера не вспыхнули.\n"
            "• Ограничения видно в /quota, апгрейд — через /upgrade (или через шантаж, но мы за честность).\n"
            "• Если бот молчит, повтори запрос: иногда CDN засыпает, мы его будим электрошейкером."
        )
    else:
        if in_private:
            toast = "Кидай ссылку, не тяни 😈"
            text = (
                "📥 <b>Личный режим грабежа:</b> кидай ссылку, жди файл. "
                "Можно сразу несколько — анти-спам переживёт, а совесть мы уже выключили."
            )
        else:
            toast = "Групповой режим активен 👀"
            text = (
                "📥 <b>Групповой налёт:</b> ответь на чужое сообщение с ссылкой или брось URL отдельно. "
                "Я отмечу исполнителя и шепну в личку, если что-то пойдёт не так."
            )

    await callback_query.answer(toast, show_alert=False)
    if message:
        await message.answer(text, parse_mode="HTML")


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

    @dp.message(Command("upgrade"))
    async def cmd_upgrade_handler(message: types.Message):
        """Показать тарифы и подсветить текущий план пользователя."""

        locale = get_locale(getattr(getattr(message, "from_user", None), "language_code", None))
        plans = quota_service.available_plans()
        if not plans:
            await message.reply(translate("upgrade.no_plans", locale))
            return

        try:
            current = quota_service.build_enforcement_plan(message.from_user.id)
        except Exception:
            logger.debug("Не удалось получить текущий план пользователя", exc_info=True)
            current = None

        def _fmt_limit(value: Optional[int]) -> str:
            return "∞" if not value else str(value)

        lines = [translate("upgrade.header", locale)]
        limits = current.get("limits", {}) if current else {}
        if current:
            lines.append(
                translate(
                    "upgrade.current_plan",
                    locale,
                    plan=current.get("plan_label", current.get("plan", "")),
                    daily=_fmt_limit(limits.get("daily")),
                    monthly=_fmt_limit(limits.get("monthly")),
                )
            )
        lines.append("")
        lines.append(translate("upgrade.pick_plan", locale))

        ordered = sorted(plans.items(), key=lambda item: item[1].get("priority", 0))
        for plan_key, info in ordered:
            label = str(info.get("label") or plan_key.title())
            if current and plan_key == current.get("plan"):
                label = f"{label} ✅"
            daily_limit = _fmt_limit(info.get("daily_quota"))
            monthly_limit = _fmt_limit(info.get("monthly_quota"))
            try:
                price_value = int(info.get("price_usd", 0) or 0)
            except (TypeError, ValueError):
                price_value = 0
            price_label = (
                translate("upgrade.price_free", locale)
                if price_value <= 0
                else translate("upgrade.price_paid", locale, price=price_value)
            )
            description = info.get("description")
            desc_suffix = f" — {description}" if description else ""
            lines.append(
                translate(
                    "upgrade.plan_line",
                    locale,
                    label=label,
                    daily=daily_limit,
                    monthly=monthly_limit,
                    price=price_label,
                    desc=desc_suffix,
                )
            )

        lines.append("")
        lines.append(translate("upgrade.cta", locale))
        text = "\n".join(line for line in lines if line is not None)

        support_link = getattr(config, "UPGRADE_SUPPORT_LINK", None)
        reply_markup = None
        if support_link:
            reply_markup = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=translate("upgrade.button_contact", locale),
                            url=support_link,
                        )
                    ]
                ]
            )
        await message.reply(text, parse_mode="HTML", reply_markup=reply_markup)

    @dp.message(Command("profile"))
    async def cmd_profile_handler(message: types.Message):
        locale = get_locale(getattr(getattr(message, "from_user", None), "language_code", None))
        await _send_profile(message, locale, section="overview", reply=True)


    @dp.message(Command("referral"))
    async def cmd_referral_handler(message: types.Message):
        locale = get_locale(getattr(getattr(message, "from_user", None), "language_code", None))
        await _send_profile(message, locale, section="referrals", reply=True)

    @dp.message(Command("use_referral"))
    async def cmd_use_referral_handler(message: types.Message):
        locale = get_locale(getattr(getattr(message, "from_user", None), "language_code", None))
        args = (message.text or "").split()
        if len(args) < 2:
            await message.reply(translate("referral.enter_code_prompt", locale))
            return
        code = args[1]
        try:
            referral_service.register_referral(code, message.from_user.id)
        except ValueError as exc:
            await message.reply(translate("referral.register_error", locale, reason=str(exc)))
            return
        await message.reply(translate("referral.register_success", locale))
        await _send_profile(message, locale, section="referrals")

    @dp.message(Command("ref_leaderboard"))
    async def cmd_ref_leaderboard_handler(message: types.Message):
        locale = get_locale(getattr(getattr(message, "from_user", None), "language_code", None))
        rows = referral_service.referral_leaderboard(limit=10)
        if not rows:
            await message.reply(translate("referral.leaderboard_empty", locale))
            return
        text_lines = [translate("referral.leaderboard_header", locale)]
        for idx, row in enumerate(rows, start=1):
            username = row.get("user_id")
            count = row.get("rewarded") or 0
            text_lines.append(
                translate(
                    "referral.leaderboard_line",
                    locale,
                    place=idx,
                    user=username,
                    count=count,
                    daily=row.get("daily_bonus", 0),
                    monthly=row.get("monthly_bonus", 0),
                )
            )
        text_lines.append(translate("referral.leaderboard_footer", locale))
        await message.reply("\n".join(text_lines))

    @dp.message(Command("referral_admin"))
    async def cmd_referral_admin_handler(message: types.Message):
        if not await is_admin(message):
            await message.reply("🔒 Только администраторы могут использовать эту команду.")
            return
        target_id = message.from_user.id
        parts = (message.text or "").split()[1:]
        if message.reply_to_message:
            target_id = getattr(getattr(message.reply_to_message, "from_user", None), "id", target_id)
        elif parts:
            try:
                target_id = int(parts[0])
            except ValueError:
                await message.reply("user_id должен быть числом.")
                return
        await cmd_referral_overview(message, target_id)

    @dp.message(Command("confirm_referral"))
    async def cmd_confirm_referral_handler(message: types.Message):
        await cmd_confirm_referral(message)

    def _format_alert_ts(value: Optional[object]) -> str:
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d %H:%M:%S")
        if not value:
            return "—"
        return str(value)

    @dp.message(Command("alerts"))
    async def cmd_alerts_handler(message: types.Message):
        if not await is_admin(message):
            await message.reply("🔒 Только администраторы могут просматривать алерты.")
            return
        alerts = alert_service.recent_alerts(limit=10)
        if not alerts:
            await message.reply("✅ Активных алертов нет.")
            return
        lines = ["⚠️ Последние алерты:"]
        for alert in alerts:
            severity = str(alert.get("severity", "warning")).upper()
            status = str(alert.get("status", "open"))
            code = alert.get("code", "unknown")
            created = _format_alert_ts(alert.get("created_at"))
            message_text = alert.get("message", "")
            lines.append(f"• [{severity}/{status}] {code} — {message_text} ({created})")
        lines.append("\nЧтобы закрыть алерт вручную: /alert_ack <code>")
        await message.reply("\n".join(lines))

    @dp.message(Command("alert_ack"))
    async def cmd_alert_ack_handler(message: types.Message):
        if not await is_admin(message):
            await message.reply("🔒 Только администраторы могут подтверждать алерты.")
            return
        parts = (message.text or "").split()
        if len(parts) < 2:
            await message.reply("Использование: /alert_ack <code>. Пример: /alert_ack errors.spike")
            return
        code = parts[1].strip().lower()
        if not code:
            await message.reply("Укажите код алерта: /alert_ack errors.spike")
            return
        resolved = alert_service.resolve_alert(code)
        if resolved:
            await message.reply(f"✅ Алерт {code} помечен как resolved.")
        else:
            await message.reply("ℹ️ Активный алерт с таким кодом не найден.")
    @dp.message(Command("quota"))
    async def cmd_quota_handler(message: types.Message):
        locale = get_locale(getattr(getattr(message, "from_user", None), "language_code", None))
        target_id = message.from_user.id
        admin_view = await is_admin(message)
        parts = (message.text or "").strip().split()

        if message.reply_to_message:
            reply_user = getattr(getattr(message.reply_to_message, "from_user", None), "id", None)
            if reply_user and reply_user != target_id:
                if not admin_view:
                    await message.reply("🔒 Только администраторы могут просматривать чужие лимиты.")
                    return
                target_id = reply_user
        elif admin_view and len(parts) > 1:
            try:
                target_id = int(parts[1])
            except ValueError:
                await message.reply("⚠️ user_id должен быть числом.")
                return
        elif len(parts) > 1 and not admin_view:
            await message.reply("🔒 Только администраторы могут просматривать чужие лимиты.")
            return

        try:
            plan = quota_service.build_enforcement_plan(target_id)
        except Exception:
            logger.exception("Не удалось получить квоты пользователя %s", target_id)
            await message.reply("⚠️ Не удалось получить информацию о тарифе.")
            return

        summary = quota_ui.quota_summary(
            plan,
            locale,
            admin=admin_view and target_id != message.from_user.id,
            target_user_id=target_id if admin_view else None,
        )
        await message.reply(summary, parse_mode="HTML")

    @dp.message(Command("set_plan"))
    async def cmd_set_plan_handler(message: types.Message):
        if not await is_admin(message):
            await message.reply("🔒 Эта команда доступна только администраторам.")
            return

        args = (message.text or "").strip().split()[1:]
        target_id: Optional[int] = None
        plan_key: Optional[str] = None
        overrides: list[str] = []

        if message.reply_to_message:
            if not args:
                await message.reply("Использование: /set_plan <plan> [daily_override] [monthly_override]")
                return
            target_id = getattr(getattr(message.reply_to_message, "from_user", None), "id", None)
            plan_key = args[0]
            overrides = args[1:]
        else:
            if len(args) < 2:
                await message.reply("Использование: /set_plan <user_id> <plan> [daily_override] [monthly_override]")
                return
            try:
                target_id = int(args[0])
            except ValueError:
                await message.reply("⚠️ user_id должен быть числом.")
                return
            plan_key = args[1]
            overrides = args[2:]

        if not target_id or not plan_key:
            await message.reply("⚠️ Не удалось определить пользователя или тариф.")
            return

        daily_override = None
        monthly_override = None
        if overrides:
            try:
                daily_override = int(overrides[0])
            except ValueError:
                await message.reply("⚠️ daily_override должен быть числом.")
                return
        if len(overrides) > 1:
            try:
                monthly_override = int(overrides[1])
            except ValueError:
                await message.reply("⚠️ monthly_override должен быть числом.")
                return

        try:
            plan = quota_service.assign_plan(
                target_id,
                plan_key,
                custom_daily=daily_override,
                custom_monthly=monthly_override,
            )
        except ValueError as exc:
            await message.reply(str(exc))
            return

        locale = get_locale(getattr(getattr(message, "from_user", None), "language_code", None))
        summary = quota_ui.quota_summary(plan, locale, admin=True, target_user_id=target_id)
        await message.reply(f"✅ Тариф обновлён.\n\n{summary}", parse_mode="HTML")

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

