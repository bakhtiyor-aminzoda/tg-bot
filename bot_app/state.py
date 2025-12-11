"""In-memory state shared across handlers."""

from __future__ import annotations

from typing import Dict, Any

# Per-user throttling bookkeeping
user_last_request_ts: Dict[int, float] = {}
user_active_downloads: Dict[int, int] = {}

# Pending downloads triggered via inline buttons
token_payload = Dict[str, Any]
pending_downloads: Dict[str, token_payload] = {}
PENDING_TOKEN_TTL = 10 * 60  # seconds

__all__ = [
    "user_last_request_ts",
    "user_active_downloads",
    "pending_downloads",
    "PENDING_TOKEN_TTL",
]
