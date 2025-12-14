"""Helpers for subscription plans, quota snapshots, and enforcement."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

import sqlalchemy as sa

import config
from db import ensure_user_quota, get_engine, subscription_plans, user_quotas
from .referrals import active_bonus_for_user

UTC = timezone.utc
_engine = get_engine()

_QUOTA_SELECT = (
    sa.select(
        user_quotas.c.user_id,
        user_quotas.c.plan,
        sa.func.coalesce(user_quotas.c.custom_daily_quota, subscription_plans.c.daily_quota).label("daily_limit"),
        sa.func.coalesce(user_quotas.c.custom_monthly_quota, subscription_plans.c.monthly_quota).label("monthly_limit"),
        user_quotas.c.daily_used,
        user_quotas.c.monthly_used,
        user_quotas.c.daily_reset_at,
        user_quotas.c.current_period_start,
        subscription_plans.c.display_name,
    )
    .select_from(user_quotas.outerjoin(subscription_plans, subscription_plans.c.plan == user_quotas.c.plan))
    .where(user_quotas.c.user_id == sa.bindparam("user_id"))
    .limit(1)
)


@dataclass
class QuotaSnapshot:
    user_id: int
    plan_key: str
    plan_label: str
    daily_limit: int
    daily_used: int
    monthly_limit: int
    monthly_used: int
    daily_reset_at: Optional[datetime]
    period_start: Optional[datetime]


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


def _start_of_day(moment: datetime) -> datetime:
    return datetime(moment.year, moment.month, moment.day, tzinfo=UTC)


def _parse_dt(value: Optional[object]) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def _plan_defaults(plan_key: Optional[str]) -> Dict[str, object]:
    plans = config.SUBSCRIPTION_PLANS or {}
    if not plans:
        return {
            "label": "Free",
            "daily_quota": 5,
            "monthly_quota": 60,
        }
    normalized_key = (plan_key or config.DEFAULT_SUBSCRIPTION_PLAN or "free").strip().lower() or "free"
    if normalized_key not in plans:
        normalized_key = config.DEFAULT_SUBSCRIPTION_PLAN
    return plans.get(normalized_key) or next(iter(plans.values()))


def _refresh_quota_row(conn, user_id: int, now: datetime) -> Optional[Dict[str, object]]:
    row = conn.execute(_QUOTA_SELECT, {"user_id": user_id}).mappings().first()
    if not row:
        return None

    updates: Dict[str, object] = {}
    daily_reset_at = _parse_dt(row.get("daily_reset_at"))
    day_anchor = _start_of_day(now)
    if daily_reset_at is None or daily_reset_at < day_anchor:
        updates.update({"daily_used": 0, "daily_reset_at": now})

    period_start = _parse_dt(row.get("current_period_start"))
    period_days = max(1, int(getattr(config, "SUBSCRIPTION_PERIOD_DAYS", 30)))
    if period_start is None:
        updates.update({"current_period_start": now, "monthly_used": 0})
    elif now - period_start >= timedelta(days=period_days):
        updates.update({"current_period_start": now, "monthly_used": 0})

    if updates:
        updates["updated_at"] = sa.func.now()
        conn.execute(
            user_quotas.update().where(user_quotas.c.user_id == user_id).values(**updates)
        )
        row = conn.execute(_QUOTA_SELECT, {"user_id": user_id}).mappings().first()
    return row


def get_quota_snapshot(user_id: int) -> QuotaSnapshot:
    ensure_user_quota(user_id)
    now = _utcnow()
    with _engine.begin() as conn:
        row = _refresh_quota_row(conn, user_id, now)

    plan_key = (row["plan"] if row else None) or config.DEFAULT_SUBSCRIPTION_PLAN
    defaults = _plan_defaults(plan_key)
    plan_label = (row.get("display_name") if row else None) or defaults.get("label", plan_key.title())
    daily_limit = int((row.get("daily_limit") if row else None) or defaults.get("daily_quota", 0) or 0)
    monthly_limit = int((row.get("monthly_limit") if row else None) or defaults.get("monthly_quota", 0) or 0)
    daily_used = int((row.get("daily_used") if row else None) or 0) if row else 0
    monthly_used = int((row.get("monthly_used") if row else None) or 0) if row else 0

    return QuotaSnapshot(
        user_id=user_id,
        plan_key=str(plan_key).lower(),
        plan_label=str(plan_label),
        daily_limit=daily_limit,
        daily_used=daily_used,
        monthly_limit=monthly_limit,
        monthly_used=monthly_used,
        daily_reset_at=_parse_dt(row.get("daily_reset_at")) if row else None,
        period_start=_parse_dt(row.get("current_period_start")) if row else None,
    )


def build_enforcement_plan(user_id: int) -> Dict[str, object]:
    """Return derived counters and reset metadata for quota decisions."""

    snapshot = get_quota_snapshot(user_id)
    now = _utcnow()
    period_days = max(1, int(getattr(config, "SUBSCRIPTION_PERIOD_DAYS", 30)))

    bonuses = active_bonus_for_user(snapshot.user_id)
    bonus_daily = int(bonuses.get("daily", 0))
    bonus_monthly = int(bonuses.get("monthly", 0))

    daily_limit_total = snapshot.daily_limit + bonus_daily
    monthly_limit_total = snapshot.monthly_limit + bonus_monthly

    daily_remaining = None
    if daily_limit_total > 0:
        daily_remaining = max(daily_limit_total - snapshot.daily_used, 0)

    monthly_remaining = None
    if monthly_limit_total > 0:
        monthly_remaining = max(monthly_limit_total - snapshot.monthly_used, 0)

    blocked_reason: Optional[str] = None
    if daily_remaining is not None and daily_remaining <= 0:
        blocked_reason = "daily"
    elif monthly_remaining is not None and monthly_remaining <= 0:
        blocked_reason = "monthly"

    next_daily_reset = _start_of_day(now) + timedelta(days=1)
    period_start = snapshot.period_start or now
    next_monthly_reset = period_start + timedelta(days=period_days)

    return {
        "user_id": snapshot.user_id,
        "plan": snapshot.plan_key,
        "plan_label": snapshot.plan_label,
        "limits": {
            "daily": daily_limit_total,
            "monthly": monthly_limit_total,
        },
        "limit_base": {
            "daily": snapshot.daily_limit,
            "monthly": snapshot.monthly_limit,
        },
        "bonuses": {
            "daily": bonus_daily,
            "monthly": bonus_monthly,
        },
        "counters": {
            "daily": snapshot.daily_used,
            "monthly": snapshot.monthly_used,
        },
        "remaining": {
            "daily": daily_remaining,
            "monthly": monthly_remaining,
        },
        "next_reset": {
            "daily": next_daily_reset,
            "monthly": next_monthly_reset,
        },
        "blocked": blocked_reason is not None,
        "blocked_reason": blocked_reason,
    }


def consume_success(user_id: int, *, downloads: int = 1) -> None:
    """Increment quota counters after a successful download."""

    ensure_user_quota(user_id)
    now = _utcnow()
    with _engine.begin() as conn:
        row = _refresh_quota_row(conn, user_id, now)
        if not row:
            return
        conn.execute(
            user_quotas.update()
            .where(user_quotas.c.user_id == user_id)
            .values(
                daily_used=user_quotas.c.daily_used + downloads,
                monthly_used=user_quotas.c.monthly_used + downloads,
                updated_at=sa.func.now(),
            )
        )


def assign_plan(
    user_id: int,
    plan_key: str,
    *,
    custom_daily: Optional[int] = None,
    custom_monthly: Optional[int] = None,
) -> Dict[str, object]:
    """Force-set user plan (optionally overriding limits)."""

    key = (plan_key or "").strip().lower()
    if not key or key not in (config.SUBSCRIPTION_PLANS or {}):
        raise ValueError("Неизвестный тариф. Доступно: " + ", ".join(sorted((config.SUBSCRIPTION_PLANS or {}).keys())))

    ensure_user_quota(user_id, plan=key)
    def _clean(value: Optional[int]) -> Optional[int]:
        if value is None:
            return None
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("Override limits должны быть целыми числами") from exc
        return max(0, parsed)

    with _engine.begin() as conn:
        conn.execute(
            user_quotas.update()
            .where(user_quotas.c.user_id == user_id)
            .values(
                plan=key,
                custom_daily_quota=_clean(custom_daily),
                custom_monthly_quota=_clean(custom_monthly),
                daily_used=0,
                monthly_used=0,
                daily_reset_at=sa.func.now(),
                current_period_start=sa.func.now(),
                updated_at=sa.func.now(),
            )
        )
    return build_enforcement_plan(user_id)


def available_plans() -> Dict[str, Dict[str, object]]:
    """Expose configured plan catalog for admin helpers."""

    return config.SUBSCRIPTION_PLANS or {}


__all__ = [
    "QuotaSnapshot",
    "get_quota_snapshot",
    "build_enforcement_plan",
    "consume_success",
    "assign_plan",
    "available_plans",
]
