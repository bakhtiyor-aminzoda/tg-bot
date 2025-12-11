"""Aggregated statistics helpers scoped per chat or globally."""

from __future__ import annotations

import sqlite3
from typing import Dict, List, Optional

from db import DB_PATH


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _chat_clause(chat_id: Optional[int], alias: str = "") -> tuple[str, List[object]]:
    if chat_id is None:
        return "", []
    column = f"{alias + '.' if alias else ''}chat_id"
    return f"WHERE {column} = ?", [chat_id]


def get_summary(chat_id: Optional[int] = None) -> Dict[str, int]:
    """Return aggregated totals optionally scoped to a chat."""

    where_clause, params = _chat_clause(chat_id)
    query = f"""
        SELECT
            COUNT(*) AS total_downloads,
            SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS successful_downloads,
            SUM(CASE WHEN status != 'success' THEN 1 ELSE 0 END) AS failed_downloads,
            COALESCE(SUM(file_size_bytes), 0) AS total_bytes,
            COUNT(DISTINCT user_id) AS unique_users
        FROM downloads
        {where_clause}
    """

    with _connect() as conn:
        row = conn.execute(query, params).fetchone()

    if not row:
        return {
            "total_downloads": 0,
            "successful_downloads": 0,
            "failed_downloads": 0,
            "total_bytes": 0,
            "unique_users": 0,
        }

    return {
        "total_downloads": row["total_downloads"] or 0,
        "successful_downloads": row["successful_downloads"] or 0,
        "failed_downloads": row["failed_downloads"] or 0,
        "total_bytes": row["total_bytes"] or 0,
        "unique_users": row["unique_users"] or 0,
    }


def get_top_users(chat_id: Optional[int] = None, limit: int = 10) -> List[Dict]:
    """Return top users within the given chat (or globally)."""

    where_clause, params = _chat_clause(chat_id, alias="d")
    query = f"""
        SELECT
            d.user_id,
            MAX(d.username) AS username,
            COUNT(*) AS total_downloads,
            SUM(COALESCE(d.file_size_bytes, 0)) AS total_bytes,
            SUM(CASE WHEN d.status != 'success' THEN 1 ELSE 0 END) AS failed_count
        FROM downloads d
        {where_clause}
        GROUP BY d.user_id
        ORDER BY total_downloads DESC, total_bytes DESC
        LIMIT ?
    """

    params = params + [limit]
    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def get_platform_stats(chat_id: Optional[int] = None) -> List[Dict]:
    """Return platform breakdown scoped to chat."""

    where_clause, params = _chat_clause(chat_id, alias="d")
    query = f"""
        SELECT
            COALESCE(d.platform, 'unknown') AS platform,
            COUNT(*) AS download_count,
            SUM(COALESCE(d.file_size_bytes, 0)) AS total_bytes,
            SUM(CASE WHEN d.status != 'success' THEN 1 ELSE 0 END) AS failed_count
        FROM downloads d
        {where_clause}
        GROUP BY platform
        ORDER BY download_count DESC
    """

    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def get_user_stats(user_id: int, chat_id: Optional[int] = None) -> Optional[Dict]:
    """Return per-user stats scoped by chat (or globally)."""

    where_clause, params = _chat_clause(chat_id, alias="d")
    if where_clause:
        where_clause += " AND d.user_id = ?"
    else:
        where_clause = "WHERE d.user_id = ?"
    params.append(user_id)

    query = f"""
        SELECT
            d.user_id,
            MAX(d.username) AS username,
            COUNT(*) AS total_downloads,
            SUM(COALESCE(d.file_size_bytes, 0)) AS total_bytes,
            SUM(CASE WHEN d.status != 'success' THEN 1 ELSE 0 END) AS failed_count,
            MIN(d.timestamp) AS first_download,
            MAX(d.timestamp) AS last_download
        FROM downloads d
        {where_clause}
    """

    with _connect() as conn:
        row = conn.execute(query, params).fetchone()

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

    where_clause, params = _chat_clause(chat_id, alias="d")
    query = f"""
        SELECT
            d.id,
            d.user_id,
            d.username,
            d.platform,
            d.url,
            d.chat_id,
            d.status,
            d.file_size_bytes,
            d.timestamp,
            d.error_message
        FROM downloads d
        {where_clause}
        ORDER BY d.timestamp DESC
        LIMIT ?
    """

    params = params + [limit]
    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]
