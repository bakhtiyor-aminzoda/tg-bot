"""Referral code management helpers."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import sqlalchemy as sa
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from db import get_engine, referral_codes, referral_events

_engine = get_engine()
UTC = timezone.utc
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_CODE_LENGTH = 8


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


def _normalize_code(value: str) -> str:
    return value.strip().upper().replace(" ", "")


def _generate_code(prefix: str = "MB") -> str:
    token = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))
    return f"{prefix}-{token}"


def _coerce_positive(value: Optional[int]) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)


def _fetch_code(conn, code: str) -> Optional[Dict]:
    stmt = sa.select(referral_codes).where(referral_codes.c.code == code).limit(1)
    row = conn.execute(stmt).mappings().first()
    return dict(row) if row else None


def create_referral_code(
    user_id: int,
    *,
    max_uses: Optional[int] = 0,
    expires_in_days: Optional[int] = None,
    expires_at: Optional[datetime] = None,
    boost_daily_quota: int = 0,
    boost_monthly_quota: int = 0,
    notes: Optional[str] = None,
    code: Optional[str] = None,
) -> Dict[str, object]:
    """Create a referral code for a user."""

    if not user_id:
        raise ValueError("user_id is required")

    max_uses = _coerce_positive(max_uses)
    boost_daily_quota = _coerce_positive(boost_daily_quota)
    boost_monthly_quota = _coerce_positive(boost_monthly_quota)

    target_expires_at = expires_at
    if target_expires_at is None and expires_in_days:
        target_expires_at = _utcnow() + timedelta(days=max(0, expires_in_days))

    with _engine.begin() as conn:
        payload = {
            "code": _normalize_code(code) if code else _generate_code(),
            "user_id": user_id,
            "max_uses": max_uses,
            "usage_count": 0,
            "expires_at": target_expires_at,
            "boost_daily_quota": boost_daily_quota,
            "boost_monthly_quota": boost_monthly_quota,
            "notes": notes,
        }
        while True:
            try:
                conn.execute(referral_codes.insert().values(**payload))
                break
            except IntegrityError:
                # Rare collision — regenerate code and retry.
                payload["code"] = _generate_code()
        row = _fetch_code(conn, payload["code"])
    return row or payload


def list_user_codes(user_id: int) -> List[Dict[str, object]]:
    """Return referral codes created by the given user."""

    stmt = (
        sa.select(referral_codes)
        .where(referral_codes.c.user_id == user_id)
        .order_by(referral_codes.c.created_at.desc())
    )
    with _engine.connect() as conn:
        return [dict(row) for row in conn.execute(stmt).mappings().all()]


def register_referral(code_value: str, referred_user_id: int) -> Dict[str, object]:
    """Link a referred user to a code (pending confirmation)."""

    if not code_value or not referred_user_id:
        raise ValueError("code and referred_user_id are required")

    normalized = _normalize_code(code_value)
    now = _utcnow()

    with _engine.begin() as conn:
        code_row = _fetch_code(conn, normalized)
        if not code_row:
            raise ValueError("Указанный реферальный код не найден.")
        if code_row["user_id"] == referred_user_id:
            raise ValueError("Нельзя использовать собственный код.")
        expires_at = code_row.get("expires_at")
        if expires_at and expires_at <= now:
            raise ValueError("Срок действия кода истёк.")
        max_uses = code_row.get("max_uses") or 0
        used = code_row.get("usage_count") or 0
        if max_uses and used >= max_uses:
            raise ValueError("Лимит использований этого кода уже исчерпан.")
        existing = conn.execute(
            sa.select(referral_events.c.id).where(referral_events.c.referred_user_id == referred_user_id)
        ).first()
        if existing:
            raise ValueError("Пользователь уже привязан к другому коду.")

        insert_stmt = referral_events.insert().values(
            code_id=code_row["id"],
            referrer_user_id=code_row["user_id"],
            referred_user_id=referred_user_id,
            status="pending",
        ).returning(referral_events.c.id)
        event_id = conn.execute(insert_stmt).scalar_one()

        conn.execute(
            referral_codes.update()
            .where(referral_codes.c.id == code_row["id"])
            .values(
                usage_count=referral_codes.c.usage_count + 1,
                updated_at=func.now(),
            )
        )

        event_row = conn.execute(
            sa.select(referral_events).where(referral_events.c.id == event_id)
        ).mappings().first()

    return dict(event_row)


def confirm_referral(
    referred_user_id: int,
    *,
    daily_bonus: Optional[int] = None,
    monthly_bonus: Optional[int] = None,
    reward_ttl_days: Optional[int] = 30,
    status: str = "rewarded",
) -> Dict[str, object]:
    """Mark referral as rewarded and store the granted bonuses."""

    if not referred_user_id:
        raise ValueError("referred_user_id is required")

    now = _utcnow()

    join_stmt = (
        sa.select(
            referral_events.c.id,
            referral_events.c.status,
            referral_events.c.code_id,
            referral_events.c.referrer_user_id,
            referral_codes.c.boost_daily_quota,
            referral_codes.c.boost_monthly_quota,
        )
        .join(referral_codes, referral_codes.c.id == referral_events.c.code_id)
        .where(referral_events.c.referred_user_id == referred_user_id)
        .limit(1)
    )

    with _engine.begin() as conn:
        row = conn.execute(join_stmt).mappings().first()
        if not row:
            raise ValueError("Запись о реферале не найдена.")
        if row["status"] == "rewarded":
            existing = conn.execute(
                sa.select(referral_events).where(referral_events.c.id == row["id"])
            ).mappings().first()
            if existing:
                return dict(existing)

        bonus_daily = _coerce_positive(daily_bonus if daily_bonus is not None else row.get("boost_daily_quota"))
        bonus_monthly = _coerce_positive(
            monthly_bonus if monthly_bonus is not None else row.get("boost_monthly_quota")
        )
        reward_expiry = None
        if reward_ttl_days and reward_ttl_days > 0:
            reward_expiry = now + timedelta(days=reward_ttl_days)

        conn.execute(
            referral_events.update()
            .where(referral_events.c.id == row["id"])
            .values(
                status=status,
                reward_daily_bonus=bonus_daily,
                reward_monthly_bonus=bonus_monthly,
                reward_expires_at=reward_expiry,
                confirmed_at=now,
                updated_at=func.now(),
            )
        )
        updated = conn.execute(
            sa.select(referral_events).where(referral_events.c.id == row["id"])
        ).mappings().first()

    return dict(updated)


def active_bonus_for_user(user_id: int) -> Dict[str, int]:
    """Aggregate active (non-expired) bonuses for referrer."""

    if not user_id:
        return {"daily": 0, "monthly": 0}

    now = _utcnow()
    stmt = (
        sa.select(
            func.coalesce(func.sum(referral_events.c.reward_daily_bonus), 0).label("daily"),
            func.coalesce(func.sum(referral_events.c.reward_monthly_bonus), 0).label("monthly"),
        )
        .where(
            referral_events.c.referrer_user_id == user_id,
            referral_events.c.status == "rewarded",
            sa.or_(
                referral_events.c.reward_expires_at.is_(None),
                referral_events.c.reward_expires_at > now,
            ),
        )
        .limit(1)
    )
    with _engine.connect() as conn:
        row = conn.execute(stmt).mappings().first()
    if not row:
        return {"daily": 0, "monthly": 0}
    return {"daily": int(row.get("daily") or 0), "monthly": int(row.get("monthly") or 0)}


def get_referral_overview(user_id: int) -> Dict[str, object]:
    """Return codes and stats for a referrer."""

    codes = list_user_codes(user_id)
    stmt = (
        sa.select(
            referral_events.c.status,
            func.count().label("count"),
            func.coalesce(func.sum(referral_events.c.reward_daily_bonus), 0).label("daily"),
            func.coalesce(func.sum(referral_events.c.reward_monthly_bonus), 0).label("monthly"),
        )
        .where(referral_events.c.referrer_user_id == user_id)
        .group_by(referral_events.c.status)
    )
    summary = {"pending": 0, "rewarded": 0, "expired": 0}
    totals = {"daily": 0, "monthly": 0}
    with _engine.connect() as conn:
        for row in conn.execute(stmt).mappings().all():
            status = row["status"]
            summary[status] = row["count"]
            if status == "rewarded":
                totals["daily"] = int(row["daily"] or 0)
                totals["monthly"] = int(row["monthly"] or 0)

    bonuses = active_bonus_for_user(user_id)
    return {
        "codes": codes,
        "summary": summary,
        "bonuses": bonuses,
        "reward_totals": totals,
    }


def referral_leaderboard(limit: int = 10) -> List[Dict[str, object]]:
    """Return top referrers ordered by rewarded invites."""

    limit = max(1, min(limit, 100))
    rewarded_case = sa.case((referral_events.c.status == "rewarded", 1), else_=0)
    stmt = (
        sa.select(
            referral_events.c.referrer_user_id.label("user_id"),
            func.count().label("total"),
            func.sum(rewarded_case).label("rewarded"),
            func.coalesce(func.sum(referral_events.c.reward_daily_bonus), 0).label("daily_bonus"),
            func.coalesce(func.sum(referral_events.c.reward_monthly_bonus), 0).label("monthly_bonus"),
        )
        .group_by(referral_events.c.referrer_user_id)
        .order_by(func.sum(rewarded_case).desc(), func.count().desc())
        .limit(limit)
    )
    with _engine.connect() as conn:
        return [dict(row) for row in conn.execute(stmt).mappings().all()]


__all__ = [
    "create_referral_code",
    "list_user_codes",
    "register_referral",
    "confirm_referral",
    "active_bonus_for_user",
    "get_referral_overview",
    "referral_leaderboard",
]
