"""Helper utilities shared across handlers."""

from __future__ import annotations

import re
from typing import Optional

from aiogram import types

URL_REGEX = re.compile(r"(https?://[^\s]+)", flags=re.IGNORECASE)


def detect_platform(url: str) -> str:
    """Return platform keyword inferred from URL."""
    u = (url or "").lower()
    if "youtu.be" in u or "youtube.com" in u:
        return "youtube"
    if "tiktok.com" in u or "vm.tiktok.com" in u:
        return "tiktok"
    if "instagram.com" in u or "instagr.am" in u:
        return "instagram"
    return ""


def extract_url_from_entities(message: types.Message) -> Optional[str]:
    """Return the first URL extracted from Telegram entities/caption entities."""
    if not message:
        return None

    entities = []
    if getattr(message, "entities", None):
        entities.extend(message.entities)
    if getattr(message, "caption_entities", None):
        entities.extend(message.caption_entities)

    text = message.text or message.caption or ""
    for ent in entities:
        if ent.type == "text_link" and getattr(ent, "url", None):
            return ent.url
        if ent.type == "url":
            try:
                return text[ent.offset : ent.offset + ent.length]
            except Exception:
                continue
    return None


def extract_first_url_from_text(text: str) -> Optional[str]:
    """Fallback regex-based URL extraction."""
    if not text:
        return None
    match = URL_REGEX.search(text)
    if match:
        return match.group(1)
    return None


def resolve_chat_title(chat: types.Chat) -> str:
    """Return human-friendly chat title for storing in DB/UI."""

    if not chat:
        return ""

    chat_type = (getattr(chat, "type", "") or "").lower()
    if chat_type == "private":
        name_parts = [getattr(chat, "first_name", None), getattr(chat, "last_name", None)]
        display = " ".join([part for part in name_parts if part])
        if not display:
            display = getattr(chat, "username", None)
        if display:
            return display
        return f"user_{getattr(chat, 'id', 'unknown')}"

    title = getattr(chat, "title", None)
    if title:
        return title
    username = getattr(chat, "username", None)
    if username:
        return f"@{username}"
    return f"chat_{getattr(chat, 'id', 'unknown')}"

__all__ = [
    "detect_platform",
    "extract_url_from_entities",
    "extract_first_url_from_text",
    "resolve_chat_title",
]
