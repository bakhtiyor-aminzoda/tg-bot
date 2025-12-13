"""In-memory state shared across handlers."""

from __future__ import annotations

from collections import deque
from typing import Deque, Dict, Any

# Per-user throttling bookkeeping
user_last_request_ts: Dict[int, float] = {}
user_active_downloads: Dict[int, int] = {}

# Per-chat/global callback throttling
chat_last_callback_ts: Dict[int, float] = {}
global_callback_events: Deque[float] = deque()

# Pending downloads triggered via inline buttons
token_payload = Dict[str, Any]
pending_downloads: Dict[str, token_payload] = {}
PENDING_TOKEN_TTL = 10 * 60  # seconds

# Pending quality selection (private chats)
pending_quality_requests: Dict[str, token_payload] = {}
QUALITY_TOKEN_TTL = 5 * 60  # seconds


def total_active_downloads() -> int:
    return sum(user_active_downloads.values())


def pending_tokens_count() -> int:
    return len(pending_downloads)


__all__ = [
    "user_last_request_ts",
    "user_active_downloads",
    "pending_downloads",
    "pending_quality_requests",
    "chat_last_callback_ts",
    "global_callback_events",
    "total_active_downloads",
    "pending_tokens_count",
    "PENDING_TOKEN_TTL",
    "QUALITY_TOKEN_TTL",
]
