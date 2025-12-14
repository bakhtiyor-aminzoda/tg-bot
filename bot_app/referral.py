"""Rendering helpers for referral flows."""

from __future__ import annotations

from typing import List

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot_app.ui.i18n import translate
from services import referrals as referral_service


def build_referral_card(user_id: int, locale: str) -> tuple[str, InlineKeyboardMarkup]:
    overview = referral_service.get_referral_overview(user_id)
    codes = overview.get("codes", [])
    bonuses = overview.get("bonuses", {"daily": 0, "monthly": 0})

    lines: List[str] = [translate("referral.header", locale)]
    if bonuses.get("daily") or bonuses.get("monthly"):
        lines.append(
            translate(
                "referral.single_bonus",
                locale,
                daily=bonuses.get("daily", 0),
                monthly=bonuses.get("monthly", 0),
            )
        )
    else:
        lines.append(translate("referral.no_bonus", locale))

    if not codes:
        lines.append("")
        lines.append(translate("referral.generate", locale))
    else:
        for entry in codes[:3]:
            max_uses = entry.get("max_uses") or "∞"
            lines.append(
                translate(
                    "referral.code_line",
                    locale,
                    code=entry.get("code"),
                    used=entry.get("usage_count", 0),
                    max=max_uses,
                )
            )
        lines.append("")
        lines.append(
            translate(
                "referral.share_hint",
                locale,
                code=codes[0].get("code"),
            )
        )

    buttons: List[List[InlineKeyboardButton]] = [[]]
    if not codes:
        buttons[0].append(
            InlineKeyboardButton(text=translate("referral.button_generate", locale), callback_data="referral:gen")
        )
    else:
        buttons[0].append(
            InlineKeyboardButton(
                text=translate("referral.button_copy", locale),
                callback_data=f"referral:copy:{codes[0].get('code')}",
            )
        )
    buttons[0].append(
        InlineKeyboardButton(text=translate("referral.button_leaderboard", locale), callback_data="referral:leaderboard")
    )
    markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    return "\n".join(lines), markup


__all__ = ["build_referral_card"]

