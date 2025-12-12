"""Database helpers for download history and admin info.

Supports both local SQLite (default) and external Postgres (e.g. Neon) using
SQLAlchemy Core, while keeping the synchronous API expected by the bot.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import sqlalchemy as sa
from sqlalchemy import func, select
from sqlalchemy.engine import Engine

import config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Engine & metadata
# ---------------------------------------------------------------------------
if config.DATABASE_URL:
    DATABASE_URL = config.DATABASE_URL
    CONNECT_ARGS: Dict[str, object] = {}
else:
    db_path = Path(config.HISTORY_DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    DATABASE_URL = f"sqlite:///{db_path}"
    CONNECT_ARGS = {"check_same_thread": False}

_engine: Engine = sa.create_engine(
    DATABASE_URL,
    future=True,
    pool_pre_ping=True,
    connect_args=CONNECT_ARGS,
)

metadata = sa.MetaData()

# ---------------------------------------------------------------------------
# Table definitions
# ---------------------------------------------------------------------------
downloads = sa.Table(
    "downloads",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("user_id", sa.BigInteger, nullable=False),
    sa.Column("username", sa.Text),
    sa.Column("platform", sa.Text),
    sa.Column("url", sa.Text),
    sa.Column("chat_id", sa.BigInteger),
    sa.Column("status", sa.Text, server_default="success"),
    sa.Column("file_size_bytes", sa.BigInteger),
    sa.Column("duration_seconds", sa.Float),
    sa.Column("timestamp", sa.DateTime(timezone=True), server_default=func.now()),
    sa.Column("error_message", sa.Text),
)

user_stats = sa.Table(
    "user_stats",
    metadata,
    sa.Column("user_id", sa.BigInteger, primary_key=True),
    sa.Column("username", sa.Text),
    sa.Column("total_downloads", sa.Integer, nullable=False, server_default="0"),
    sa.Column("total_bytes", sa.BigInteger, nullable=False, server_default="0"),
    sa.Column("last_download", sa.DateTime(timezone=True)),
    sa.Column("first_download", sa.DateTime(timezone=True), server_default=func.now()),
    sa.Column("failed_count", sa.Integer, nullable=False, server_default="0"),
)

platform_stats = sa.Table(
    "platform_stats",
    metadata,
    sa.Column("platform", sa.Text, primary_key=True),
    sa.Column("download_count", sa.Integer, nullable=False, server_default="0"),
    sa.Column("total_bytes", sa.BigInteger, nullable=False, server_default="0"),
    sa.Column("failed_count", sa.Integer, nullable=False, server_default="0"),
)

authorized_admins = sa.Table(
    "authorized_admins",
    metadata,
    sa.Column("user_id", sa.BigInteger, primary_key=True),
    sa.Column("username", sa.Text),
    sa.Column("added_at", sa.DateTime(timezone=True), server_default=func.now()),
)

chats = sa.Table(
    "chats",
    metadata,
    sa.Column("chat_id", sa.BigInteger, primary_key=True),
    sa.Column("title", sa.Text),
    sa.Column("chat_type", sa.Text),
    sa.Column("updated_at", sa.DateTime(timezone=True), server_default=func.now()),
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dialect_name() -> str:
    return _engine.dialect.name


def _dialect_insert(table: sa.Table) -> sa.sql.dml.Insert:
    name = _dialect_name()
    if name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as dialect_insert
    elif name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as dialect_insert
    else:  # pragma: no cover
        dialect_insert = sa.insert
    return dialect_insert(table)


def _fetch_one(query) -> Optional[Dict]:
    with _engine.connect() as conn:
        row = conn.execute(query).mappings().first()
        return dict(row) if row else None


def _fetch_all(query) -> List[Dict]:
    with _engine.connect() as conn:
        return [dict(row) for row in conn.execute(query).mappings().all()]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def init_db() -> None:
    """Create tables if they do not exist."""
    metadata.create_all(_engine, checkfirst=True)
    logger.info("✓ База данных инициализирована: %s", DATABASE_URL)


def add_download(
    user_id: int,
    username: Optional[str],
    platform: str,
    url: str,
    chat_id: Optional[int] = None,
    status: str = "success",
    file_size_bytes: Optional[int] = None,
    duration_seconds: Optional[float] = None,
    error_message: Optional[str] = None,
) -> bool:
    size = file_size_bytes or 0
    failures = 0 if status == "success" else 1
    try:
        with _engine.begin() as conn:
            conn.execute(
                downloads.insert().values(
                    user_id=user_id,
                    username=username,
                    platform=platform,
                    url=url,
                    chat_id=chat_id,
                    status=status,
                    file_size_bytes=file_size_bytes,
                    duration_seconds=duration_seconds,
                    error_message=error_message,
                )
            )

            user_stmt = _dialect_insert(user_stats).values(
                user_id=user_id,
                username=username,
                total_downloads=1,
                total_bytes=size,
                last_download=func.now(),
                failed_count=failures,
            )
            user_stmt = user_stmt.on_conflict_do_update(
                index_elements=[user_stats.c.user_id],
                set_={
                    "username": func.coalesce(user_stmt.excluded.username, user_stats.c.username),
                    "total_downloads": user_stats.c.total_downloads + user_stmt.excluded.total_downloads,
                    "total_bytes": user_stats.c.total_bytes + user_stmt.excluded.total_bytes,
                    "last_download": func.now(),
                    "failed_count": user_stats.c.failed_count + user_stmt.excluded.failed_count,
                },
            )
            conn.execute(user_stmt)

            platform_stmt = _dialect_insert(platform_stats).values(
                platform=platform,
                download_count=1,
                total_bytes=size,
                failed_count=failures,
            )
            platform_stmt = platform_stmt.on_conflict_do_update(
                index_elements=[platform_stats.c.platform],
                set_={
                    "download_count": platform_stats.c.download_count + platform_stmt.excluded.download_count,
                    "total_bytes": platform_stats.c.total_bytes + platform_stmt.excluded.total_bytes,
                    "failed_count": platform_stats.c.failed_count + platform_stmt.excluded.failed_count,
                },
            )
            conn.execute(platform_stmt)
        logger.info(
            "✓ Запись о загрузке сохранена в БД: user=%s, platform=%s, status=%s, chat_id=%s",
            user_id,
            platform,
            status,
            chat_id,
        )
        return True
    except Exception:
        logger.exception("Ошибка при добавлении записи в БД")
        return False


def upsert_chat(chat_id: int, title: Optional[str], chat_type: Optional[str]) -> None:
    if not chat_id:
        return
    stmt = _dialect_insert(chats).values(
        chat_id=chat_id,
        title=(title or "").strip() or None,
        chat_type=(chat_type or "").strip() or None,
        updated_at=func.now(),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[chats.c.chat_id],
        set_={
            "title": func.coalesce(stmt.excluded.title, chats.c.title),
            "chat_type": func.coalesce(stmt.excluded.chat_type, chats.c.chat_type),
            "updated_at": func.now(),
        },
    )
    with _engine.begin() as conn:
        conn.execute(stmt)


def get_user_stats(user_id: int) -> Optional[Dict]:
    return _fetch_one(select(user_stats).where(user_stats.c.user_id == user_id))


def get_all_user_stats(limit: int = 10) -> List[Dict]:
    query = select(user_stats).order_by(user_stats.c.total_downloads.desc()).limit(limit)
    return _fetch_all(query)


def get_platform_stats() -> List[Dict]:
    query = select(platform_stats).order_by(platform_stats.c.download_count.desc())
    return _fetch_all(query)


def get_group_top_users(chat_id: int, limit: int = 10) -> List[Dict]:
    failed_case = sa.case((downloads.c.status != "success", 1), else_=0)
    query = (
        select(
            downloads.c.user_id,
            downloads.c.username,
            func.count().label("total_downloads"),
            func.sum(func.coalesce(downloads.c.file_size_bytes, 0)).label("total_bytes"),
            func.sum(failed_case).label("failed_count"),
        )
        .where(downloads.c.chat_id == chat_id)
        .group_by(downloads.c.user_id, downloads.c.username)
        .order_by(sa.text("total_downloads DESC"))
        .limit(limit)
    )
    return _fetch_all(query)


def get_group_stats_summary(chat_id: int) -> Dict:
    with _engine.connect() as conn:
        total = conn.execute(select(func.count()).where(downloads.c.chat_id == chat_id)).scalar() or 0
        successes = conn.execute(
            select(func.count()).where(downloads.c.chat_id == chat_id, downloads.c.status == "success")
        ).scalar() or 0
        failures = conn.execute(
            select(func.count()).where(downloads.c.chat_id == chat_id, downloads.c.status != "success")
        ).scalar() or 0
        total_bytes = conn.execute(
            select(func.sum(downloads.c.file_size_bytes)).where(
                downloads.c.chat_id == chat_id, downloads.c.file_size_bytes.is_not(None)
            )
        ).scalar() or 0
        unique_users = conn.execute(
            select(func.count(sa.distinct(downloads.c.user_id))).where(downloads.c.chat_id == chat_id)
        ).scalar() or 0
    return {
        "total_downloads": total,
        "successful_downloads": successes,
        "failed_downloads": failures,
        "total_bytes": total_bytes,
        "total_mb": round((total_bytes or 0) / (1024 * 1024), 2),
        "unique_users": unique_users,
    }


def get_group_recent_downloads(chat_id: int, limit: int = 20) -> List[Dict]:
    query = (
        select(downloads)
        .where(downloads.c.chat_id == chat_id)
        .order_by(downloads.c.timestamp.desc())
        .limit(limit)
    )
    return _fetch_all(query)


def get_group_platform_stats(chat_id: int) -> List[Dict]:
    failed_case = sa.case((downloads.c.status != "success", 1), else_=0)
    query = (
        select(
            func.coalesce(downloads.c.platform, "unknown").label("platform"),
            func.count().label("download_count"),
            func.sum(func.coalesce(downloads.c.file_size_bytes, 0)).label("total_bytes"),
            func.sum(failed_case).label("failed_count"),
        )
        .where(downloads.c.chat_id == chat_id)
        .group_by(sa.text("platform"))
        .order_by(sa.text("download_count DESC"))
    )
    return _fetch_all(query)


def get_recent_downloads(limit: int = 20) -> List[Dict]:
    query = select(downloads).order_by(downloads.c.timestamp.desc()).limit(limit)
    return _fetch_all(query)


def get_stats_summary() -> Dict:
    with _engine.connect() as conn:
        total = conn.execute(select(func.count()).select_from(downloads)).scalar() or 0
        successes = conn.execute(
            select(func.count()).where(downloads.c.status == "success")
        ).scalar() or 0
        failures = conn.execute(
            select(func.count()).where(downloads.c.status != "success")
        ).scalar() or 0
        total_bytes = conn.execute(
            select(func.sum(downloads.c.file_size_bytes)).where(downloads.c.file_size_bytes.is_not(None))
        ).scalar() or 0
        unique_users = conn.execute(select(func.count(sa.distinct(downloads.c.user_id)))).scalar() or 0
    return {
        "total_downloads": total,
        "successful_downloads": successes,
        "failed_downloads": failures,
        "total_bytes": total_bytes,
        "total_mb": round((total_bytes or 0) / (1024 * 1024), 2),
        "unique_users": unique_users,
    }


def cleanup_old_records(days: int = 30) -> int:
    cutoff = datetime.utcnow() - timedelta(days=days)
    with _engine.begin() as conn:
        result = conn.execute(downloads.delete().where(downloads.c.timestamp < cutoff))
    deleted = result.rowcount or 0
    logger.info("✓ Удалено %d старых записей (старше %d дней)", deleted, days)
    return deleted


def add_authorized_admin(user_id: int, username: Optional[str] = None) -> bool:
    stmt = _dialect_insert(authorized_admins).values(user_id=user_id, username=username)
    stmt = stmt.on_conflict_do_update(
        index_elements=[authorized_admins.c.user_id],
        set_={"username": stmt.excluded.username, "added_at": func.now()},
    )
    try:
        with _engine.begin() as conn:
            conn.execute(stmt)
        logger.info("Добавлен авторизованный админ: %s", user_id)
        return True
    except Exception:
        logger.exception("Ошибка при добавлении авторизованного админа")
        return False


def remove_authorized_admin(user_id: int) -> bool:
    try:
        with _engine.begin() as conn:
            conn.execute(authorized_admins.delete().where(authorized_admins.c.user_id == user_id))
        logger.info("Удалён авторизованный админ: %s", user_id)
        return True
    except Exception:
        logger.exception("Ошибка при удалении авторизованного админа")
        return False


def is_authorized_admin(user_id: int) -> bool:
    query = select(authorized_admins.c.user_id).where(authorized_admins.c.user_id == user_id).limit(1)
    with _engine.connect() as conn:
        return conn.execute(query).first() is not None


def list_authorized_admins() -> List[Dict]:
    query = select(authorized_admins).order_by(authorized_admins.c.added_at.desc())
    return _fetch_all(query)


def get_engine() -> Engine:
    """Expose SQLAlchemy engine for advanced analytics helpers."""
    return _engine


__all__ = [
    "init_db",
    "add_download",
    "upsert_chat",
    "get_user_stats",
    "get_all_user_stats",
    "get_platform_stats",
    "get_group_top_users",
    "get_group_stats_summary",
    "get_group_recent_downloads",
    "get_group_platform_stats",
    "get_recent_downloads",
    "get_stats_summary",
    "cleanup_old_records",
    "add_authorized_admin",
    "remove_authorized_admin",
    "is_authorized_admin",
    "list_authorized_admins",
    "get_engine",
    "downloads",
    "chats",
]
