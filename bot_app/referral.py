"""Rendering helpers for user profile and referral flows."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import config
from bot_app.ui.i18n import translate
from services import quotas as quota_service
from services import referrals as referral_service

logger = logging.getLogger(__name__)

_VALID_SECTIONS = {"overview", "referrals"}


def _fmt_limit(value: Optional[int]) -> str:
    if not value:
        return "∞"
    return str(value)


def _fmt_usage(used: Optional[int], limit: Optional[int]) -> str:
    used_val = int(used or 0)
    if not limit:
        return f"{used_val}/∞"
    limit_val = max(0, int(limit))
    return f"{min(used_val, limit_val)}/{limit_val}"


def _format_ts(value: Optional[datetime]) -> str:
    if not value:
        return "—"
    try:
        return value.strftime("%d.%m %H:%M")
    except Exception:
        return str(value)


def _normalize_section(section: Optional[str]) -> str:
    section_key = (section or "overview").strip().lower()
    return section_key if section_key in _VALID_SECTIONS else "overview"


def _build_referral_link(code: Optional[str]) -> Optional[str]:
    username = getattr(config, "BOT_USERNAME", None)
    if not username or not code:
        return None
    slug = str(code).strip().replace(" ", "")
    if not slug:
        return None
    return f"https://t.me/{username}?start=ref_{slug}"


def _nav_button(label_key: str, active: bool, locale: str, target: str) -> InlineKeyboardButton:
    label = translate(label_key, locale)
    if active:
        label = f"• {label}"
    return InlineKeyboardButton(text=label, callback_data=f"profile:section:{target}")


def _build_markup(section: str, locale: str, share_link: Optional[str]) -> InlineKeyboardMarkup:
    nav_row = [
        _nav_button("profile.nav_overview", section == "overview", locale, "overview"),
        _nav_button("profile.nav_referrals", section == "referrals", locale, "referrals"),
    ]
    rows: List[List[InlineKeyboardButton]] = [nav_row]
    if share_link:
        rows.append([
            InlineKeyboardButton(text=translate("profile.button_share_link", locale), url=share_link)
        ])
    rows.append([
        InlineKeyboardButton(text=translate("profile.button_leaderboard", locale), callback_data="profile:leaderboard")
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _render_overview(plan: Optional[Dict[str, object]], locale: str) -> str:
    if not plan:
        return translate("profile.overview_unavailable", locale)

    limits = plan.get("limits") or {}
    counters = plan.get("counters") or {}
    bonuses = plan.get("bonuses") or {}
    next_reset = plan.get("next_reset") or {}

    lines = [translate("profile.overview_title", locale)]
    lines.append(
        translate(
            "profile.plan_summary",
            locale,
            plan=plan.get("plan_label") or plan.get("plan") or "—",
        )
    )
    lines.append(
        translate(
            "profile.daily_usage",
            locale,
            usage=_fmt_usage(counters.get("daily"), limits.get("daily")),
        )
    )
    lines.append(
        translate(
            "profile.monthly_usage",
            locale,
            usage=_fmt_usage(counters.get("monthly"), limits.get("monthly")),
        )
    )

    if bonuses.get("daily") or bonuses.get("monthly"):
        lines.append(
            translate(
                "profile.bonus_line",
                locale,
                daily=bonuses.get("daily", 0),
                monthly=bonuses.get("monthly", 0),
            )
        )
    else:
        lines.append(translate("profile.bonus_none", locale))

    lines.append(
        translate(
            "profile.next_reset_daily",
            locale,
            timestamp=_format_ts(next_reset.get("daily")),
        )
    )
    lines.append(
        translate(
            "profile.next_reset_monthly",
            locale,
            timestamp=_format_ts(next_reset.get("monthly")),
        )
    )
    return "\n".join(lines)


def _render_referrals(overview: Dict[str, object], share_link: Optional[str], locale: str) -> str:
    summary = overview.get("summary") or {}
    bonuses = overview.get("bonuses") or {}
    pending = summary.get("pending", 0)
    rewarded = summary.get("rewarded", 0)

    lines = [translate("profile.referral_title", locale)]
    if share_link:
        lines.append(translate("profile.referral_link", locale, link=share_link))
    else:
        lines.append(translate("profile.referral_link_missing", locale))

    lines.append(
        translate(
            "profile.referral_stats",
            locale,
            rewarded=rewarded,
            pending=pending,
        )
    )

    if bonuses.get("daily") or bonuses.get("monthly"):
        lines.append(
            translate(
                "profile.referral_bonus_line",
                locale,
                daily=bonuses.get("daily", 0),
                monthly=bonuses.get("monthly", 0),
            )
        )
    else:
        lines.append(translate("profile.referral_bonus_none", locale))

    lines.append(translate("profile.referral_hint", locale))
    return "\n".join(lines)


def build_profile_view(user_id: int, locale: str, *, section: str = "overview") -> Tuple[str, InlineKeyboardMarkup]:
    section_key = _normalize_section(section)

    plan = None
    try:
        plan = quota_service.build_enforcement_plan(user_id)
    except Exception:
        logger.debug("Не удалось получить данные квот для пользователя %s", user_id, exc_info=True)

    overview: Dict[str, object] = {"summary": {}, "bonuses": {}}
    try:
        overview = referral_service.get_referral_overview(user_id)
    except Exception:
        logger.debug("Не удалось получить данные рефералов для пользователя %s", user_id, exc_info=True)

    personal_code = None
    try:
        personal_code = referral_service.ensure_personal_code(user_id)
    except Exception:
        logger.debug("Не удалось создать реферальный код для пользователя %s", user_id, exc_info=True)

    share_link = _build_referral_link((personal_code or {}).get("code"))

    if section_key == "referrals":
        text = _render_referrals(overview, share_link, locale)
    else:
        text = _render_overview(plan, locale)

    markup = _build_markup(section_key, locale, share_link)
    return text, markup


def build_referral_card(user_id: int, locale: str) -> Tuple[str, InlineKeyboardMarkup]:
    """Backward-compatible wrapper for legacy handlers."""

    return build_profile_view(user_id, locale, section="referrals")


__all__ = ["build_profile_view", "build_referral_card"]

