"""Quality selection helpers for inline keyboards."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .i18n import DEFAULT_LOCALE, translate


@dataclass(frozen=True)
class QualityPreset:
    slug: str
    format_spec: Optional[str]
    expect_audio: bool = True
    expect_video: bool = True


PRESETS: Dict[str, QualityPreset] = {
    "auto": QualityPreset(slug="auto", format_spec=None, expect_audio=True, expect_video=True),
    "720p": QualityPreset(
        slug="720p",
        format_spec="bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]",
        expect_audio=True,
        expect_video=True,
    ),
    "480p": QualityPreset(
        slug="480p",
        format_spec="bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480]",
        expect_audio=True,
        expect_video=True,
    ),
    "audio": QualityPreset(
        slug="audio",
        format_spec="bestaudio[ext=m4a]/bestaudio",
        expect_audio=True,
        expect_video=False,
    ),
}

DEFAULT_PRESET = PRESETS["auto"]


def get_preset(slug: str) -> QualityPreset:
    return PRESETS.get(slug, DEFAULT_PRESET)


def build_keyboard(token: str, locale: str = DEFAULT_LOCALE) -> InlineKeyboardMarkup:
    buttons = []
    row = []
    for slug in ("auto", "720p", "480p", "audio"):
        label = translate(f"quality.option.{slug}", locale)
        row.append(InlineKeyboardButton(text=label, callback_data=f"quality:{token}:{slug}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)


__all__ = ["QualityPreset", "PRESETS", "DEFAULT_PRESET", "build_keyboard", "get_preset"]
