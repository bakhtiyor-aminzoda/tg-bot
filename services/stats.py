"""Aggregated statistics helpers scoped per chat or globally."""

from __future__ import annotations

from typing import Dict, List, Mapping, Optional

import sqlalchemy as sa
from sqlalchemy import func, select

from db import chats, downloads, subscription_plans, user_quotas, get_engine

_engine = get_engine()


def _chat_filters(chat_id: Optional[int], column) -> List[sa.sql.ClauseElement]:
    return [column == chat_id] if chat_id is not None else []


def _fetch_all(stmt) -> List[Dict]:
    with _engine.connect() as conn:
        return [dict(row) for row in conn.execute(stmt).mappings().all()]


def _fetch_one(stmt) -> Optional[Dict]:
    with _engine.connect() as conn:
        row = conn.execute(stmt).mappings().first()
        return dict(row) if row else None


def get_summary(chat_id: Optional[int] = None) -> Dict[str, object]:
    """Return aggregated totals optionally scoped to a chat."""

    filters = _chat_filters(chat_id, downloads.c.chat_id)
    stmt = select(
        func.count().label("total_downloads"),
        func.sum(sa.case((downloads.c.status == "success", 1), else_=0)).label("successful_downloads"),
        func.sum(sa.case((downloads.c.status != "success", 1), else_=0)).label("failed_downloads"),
        func.coalesce(func.sum(downloads.c.file_size_bytes), 0).label("total_bytes"),
        func.count(sa.distinct(downloads.c.user_id)).label("unique_users"),
        func.max(downloads.c.timestamp).label("last_activity"),
    ).where(*filters)

    with _engine.connect() as conn:
        row = conn.execute(stmt).mappings().first()

    if not row:
        return {
            "total_downloads": 0,
            "successful_downloads": 0,
            "failed_downloads": 0,
            "total_bytes": 0,
            "unique_users": 0,
            "last_activity": None,
        }

    return {
        "total_downloads": row["total_downloads"] or 0,
        "successful_downloads": row["successful_downloads"] or 0,
        "failed_downloads": row["failed_downloads"] or 0,
        "total_bytes": row["total_bytes"] or 0,
        "unique_users": row["unique_users"] or 0,
        "last_activity": row["last_activity"],
    }


def _resolve_order(mapping: Mapping[str, object], requested: Optional[str], default_key: str) -> str:
    key = (requested or "").lower()
    if key not in mapping:
        key = default_key
    return key


def get_top_users(chat_id: Optional[int] = None, limit: int = 10, order_by: str = "downloads") -> List[Dict]:
    """Return top users within the given chat (or globally)."""
    filters = _chat_filters(chat_id, downloads.c.chat_id)
    total_downloads_col = func.count().label("total_downloads")
    total_bytes_col = func.sum(func.coalesce(downloads.c.file_size_bytes, 0)).label("total_bytes")
    failed_col = func.sum(sa.case((downloads.c.status != "success", 1), else_=0)).label("failed_count")
    plan_col = func.max(user_quotas.c.plan).label("plan_key")
    plan_name_col = func.max(subscription_plans.c.display_name).label("plan_label")
    daily_limit_col = func.max(
        func.coalesce(user_quotas.c.custom_daily_quota, subscription_plans.c.daily_quota)
    ).label("daily_quota")
    monthly_limit_col = func.max(
        func.coalesce(user_quotas.c.custom_monthly_quota, subscription_plans.c.monthly_quota)
    ).label("monthly_quota")
    daily_used_col = func.max(func.coalesce(user_quotas.c.daily_used, 0)).label("daily_used")
    monthly_used_col = func.max(func.coalesce(user_quotas.c.monthly_used, 0)).label("monthly_used")
    stmt = (
        select(
            downloads.c.user_id,
            func.max(downloads.c.username).label("username"),
            total_downloads_col,
            total_bytes_col,
            failed_col,
            plan_col,
            plan_name_col,
            daily_limit_col,
            monthly_limit_col,
            daily_used_col,
            monthly_used_col,
        )
        .select_from(
            downloads.outerjoin(user_quotas, user_quotas.c.user_id == downloads.c.user_id)
            .outerjoin(subscription_plans, subscription_plans.c.plan == user_quotas.c.plan)
        )
        .where(*filters)
        .group_by(downloads.c.user_id)
        .limit(limit)
    )

    order_map = {
        "downloads": (total_downloads_col.desc(), total_bytes_col.desc()),
        "data": (total_bytes_col.desc(), total_downloads_col.desc()),
        "errors": (failed_col.desc(), total_downloads_col.desc()),
        "name": (func.coalesce(func.max(downloads.c.username), downloads.c.user_id).asc(),),
    }
    order_key = _resolve_order(order_map, order_by, "downloads")
    stmt = stmt.order_by(*order_map[order_key])

    return _fetch_all(stmt)


def get_platform_stats(chat_id: Optional[int] = None, order_by: str = "downloads") -> List[Dict]:
    """Return platform breakdown scoped to chat."""
    filters = _chat_filters(chat_id, downloads.c.chat_id)
    download_count_col = func.count().label("download_count")
    total_bytes_col = func.sum(func.coalesce(downloads.c.file_size_bytes, 0)).label("total_bytes")
    failed_col = func.sum(sa.case((downloads.c.status != "success", 1), else_=0)).label("failed_count")
    stmt = (
        select(
            func.coalesce(downloads.c.platform, "unknown").label("platform"),
            download_count_col,
            total_bytes_col,
            failed_col,
        )
        .where(*filters)
        .group_by(sa.text("platform"))
    )
    order_map = {
        "downloads": (download_count_col.desc(),),
        "data": (total_bytes_col.desc(),),
        "errors": (failed_col.desc(),),
        "name": (sa.text("platform ASC"),),
    }
    order_key = _resolve_order(order_map, order_by, "downloads")
    stmt = stmt.order_by(*order_map[order_key])
    return _fetch_all(stmt)


def get_user_stats(user_id: int, chat_id: Optional[int] = None) -> Optional[Dict]:
    """Return per-user stats scoped by chat (or globally)."""

    filters = _chat_filters(chat_id, downloads.c.chat_id) + [downloads.c.user_id == user_id]
    stmt = select(
        downloads.c.user_id,
        func.max(downloads.c.username).label("username"),
        func.count().label("total_downloads"),
        func.sum(func.coalesce(downloads.c.file_size_bytes, 0)).label("total_bytes"),
        func.sum(sa.case((downloads.c.status != "success", 1), else_=0)).label("failed_count"),
        func.min(downloads.c.timestamp).label("first_download"),
        func.max(downloads.c.timestamp).label("last_download"),
    ).where(*filters).group_by(downloads.c.user_id)

    row = _fetch_one(stmt)

    if not row or (row["total_downloads"] or 0) == 0:
        return None

    return {
        "user_id": row["user_id"],
        "username": row["username"],
        "total_downloads": row["total_downloads"] or 0,
        "total_bytes": row["total_bytes"] or 0,
        "failed_count": row["failed_count"] or 0,
        "first_download": row["first_download"],
        "last_download": row["last_download"],
    }


def get_recent_downloads(chat_id: Optional[int] = None, limit: int = 20) -> List[Dict]:
    """Return latest downloads for the given scope."""

    filters = _chat_filters(chat_id, downloads.c.chat_id)
    stmt = (
        select(downloads)
        .where(*filters)
        .order_by(downloads.c.timestamp.desc())
        .limit(limit)
    )
    return _fetch_all(stmt)


def get_recent_failures(chat_id: Optional[int] = None, limit: int = 10) -> List[Dict]:
    """Return the latest failed downloads for the given scope."""

    filters = _chat_filters(chat_id, downloads.c.chat_id) + [downloads.c.status != "success"]
    stmt = (
        select(downloads)
        .where(*filters)
        .order_by(downloads.c.timestamp.desc())
        .limit(limit)
    )
    return _fetch_all(stmt)


def list_chats(order_by: str = "recent", search: Optional[str] = None, limit: int = 50) -> List[Dict]:
    """Return known chats with aggregated stats for admin panel."""

    orders = {
        "recent": "last_activity DESC",
        "downloads": "total_downloads DESC",
        "data": "total_bytes DESC",
        "errors": "failed_downloads DESC",
        "name": "title ASC",
    }
    order_key = _resolve_order(orders, order_by, "recent")
    order_clause = orders[order_key]

    where = ""
    bind_params: Dict[str, object] = {"limit": limit}
    if search:
        where = "WHERE (LOWER(COALESCE(c.title, '')) LIKE :search OR CAST(b.chat_id AS TEXT) LIKE :search_raw)"
        bind_params["search"] = f"%{search.lower()}%"
        bind_params["search_raw"] = f"%{search}%"

    query = f"""
        WITH stats AS (
            SELECT
                chat_id,
                COUNT(*) AS total_downloads,
                SUM(CASE WHEN status != 'success' THEN 1 ELSE 0 END) AS failed_downloads,
                SUM(COALESCE(file_size_bytes, 0)) AS total_bytes,
                COUNT(DISTINCT user_id) AS unique_users,
                MAX(timestamp) AS last_download
            FROM downloads
            WHERE chat_id IS NOT NULL
            GROUP BY chat_id
        ),
        base AS (
            SELECT DISTINCT chat_id FROM downloads WHERE chat_id IS NOT NULL
            UNION
            SELECT chat_id FROM chats
        )
        SELECT
            b.chat_id AS chat_id,
            CASE
                WHEN c.title IS NOT NULL AND TRIM(c.title) != '' THEN c.title
                ELSE 'Chat #' || b.chat_id
            END AS title,
            COALESCE(NULLIF(TRIM(c.chat_type), ''), 'unknown') AS chat_type,
            COALESCE(s.total_downloads, 0) AS total_downloads,
            COALESCE(s.total_bytes, 0) AS total_bytes,
            COALESCE(s.failed_downloads, 0) AS failed_downloads,
            COALESCE(s.unique_users, 0) AS unique_users,
            COALESCE(s.last_download, c.updated_at) AS last_activity
        FROM base b
        LEFT JOIN chats c ON c.chat_id = b.chat_id
        LEFT JOIN stats s ON s.chat_id = b.chat_id
        {where}
        ORDER BY {order_clause}
        LIMIT :limit
    """

    stmt = sa.text(query)
    with _engine.connect() as conn:
        rows = conn.execute(stmt, bind_params).mappings().all()
    return [dict(row) for row in rows]
