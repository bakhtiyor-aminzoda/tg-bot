"""Health alert storage and helpers."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import sqlalchemy as sa

from db import get_engine, health_alerts

UTC = timezone.utc
_engine = get_engine()


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _serialize(details: Optional[Dict[str, object]]) -> Optional[str]:
    if not details:
        return None
    try:
        return json.dumps(details, ensure_ascii=False)
    except TypeError:
        return json.dumps({"value": str(details)})


def _hydrate(row: sa.Row | Dict[str, object] | None) -> Optional[Dict[str, object]]:
    if not row:
        return None
    data = dict(row)
    details = data.get("details")
    if isinstance(details, str):
        try:
            data["details"] = json.loads(details)
        except json.JSONDecodeError:
            pass
    return data


def record_alert(
    code: str,
    message: str,
    *,
    severity: str = "warning",
    details: Optional[Dict[str, object]] = None,
) -> Tuple[Dict[str, object], bool]:
    """Create or update an open alert and return (row, created_flag)."""

    if not code:
        raise ValueError("code is required for alert")
    normalized_code = code.strip().lower()
    with _engine.begin() as conn:
        existing = (
            conn.execute(
                sa.select(health_alerts)
                .where(health_alerts.c.code == normalized_code, health_alerts.c.status == "open")
                .order_by(health_alerts.c.created_at.desc())
                .limit(1)
            )
            .mappings()
            .first()
        )

        if existing:
            conn.execute(
                health_alerts.update()
                .where(health_alerts.c.id == existing["id"])
                .values(
                    message=message,
                    severity=severity,
                    details=_serialize(details),
                    updated_at=sa.func.now(),
                )
            )
            row = conn.execute(sa.select(health_alerts).where(health_alerts.c.id == existing["id"])).mappings().first()
            return _hydrate(row) or {}, False

        insert_stmt = (
            health_alerts.insert()
            .values(
                code=normalized_code,
                message=message,
                severity=severity,
                details=_serialize(details),
                status="open",
                created_at=_now(),
                updated_at=_now(),
            )
            .returning(health_alerts.c.id)
        )
        alert_id = conn.execute(insert_stmt).scalar_one()
        row = conn.execute(sa.select(health_alerts).where(health_alerts.c.id == alert_id)).mappings().first()
    return _hydrate(row) or {}, True


def resolve_alert(code: str) -> Optional[Dict[str, object]]:
    if not code:
        return None
    normalized_code = code.strip().lower()
    with _engine.begin() as conn:
        row = (
            conn.execute(
                sa.select(health_alerts)
                .where(health_alerts.c.code == normalized_code, health_alerts.c.status == "open")
                .order_by(health_alerts.c.created_at.desc())
                .limit(1)
            )
            .mappings()
            .first()
        )
        if not row:
            return None
        conn.execute(
            health_alerts.update()
            .where(health_alerts.c.id == row["id"])
            .values(status="resolved", resolved_at=_now(), updated_at=_now())
        )
        updated = conn.execute(sa.select(health_alerts).where(health_alerts.c.id == row["id"])).mappings().first()
    return _hydrate(updated)


def mark_alert_notified(alert_id: int) -> None:
    if not alert_id:
        return
    with _engine.begin() as conn:
        conn.execute(
            health_alerts.update()
            .where(health_alerts.c.id == alert_id)
            .values(last_notified_at=_now(), updated_at=_now())
        )


def recent_alerts(limit: int = 20) -> List[Dict[str, object]]:
    limit = max(1, min(limit, 200))
    stmt = sa.select(health_alerts).order_by(health_alerts.c.created_at.desc()).limit(limit)
    with _engine.connect() as conn:
        rows = [dict(row) for row in conn.execute(stmt).mappings().all()]
    return [row for item in rows if (row := _hydrate(item))]


__all__ = [
    "record_alert",
    "resolve_alert",
    "recent_alerts",
    "mark_alert_notified",
]
