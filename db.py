"""Модуль для управления SQLite базой данных истории загрузок.

Хранит информацию о всех загрузках видео для аналитики и администрирования.
"""
import sqlite3
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# Путь к файлу базы данных
DB_PATH = Path("./data/history.db")


def init_db():
    """Инициализировать базу данных (создать таблицы если их нет)."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        
        # Таблица истории загрузок
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS downloads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                platform TEXT,
                url TEXT,
                status TEXT DEFAULT 'success',
                file_size_bytes INTEGER,
                duration_seconds REAL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                error_message TEXT
            )
        """)
        
        # Таблица статистики пользователей
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_stats (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                total_downloads INTEGER DEFAULT 0,
                total_bytes INTEGER DEFAULT 0,
                last_download DATETIME,
                first_download DATETIME DEFAULT CURRENT_TIMESTAMP,
                failed_count INTEGER DEFAULT 0
            )
        """)
        
        # Таблица статистики платформ
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS platform_stats (
                platform TEXT PRIMARY KEY,
                download_count INTEGER DEFAULT 0,
                total_bytes INTEGER DEFAULT 0,
                failed_count INTEGER DEFAULT 0
            )
        """)

        # Таблица авторизованных админов (self-service)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS authorized_admins (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                added_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        conn.commit()
        conn.close()
        logger.info("✓ База данных инициализирована: %s", DB_PATH)
    except Exception as e:
        logger.error("Ошибка при инициализации БД: %s", e)
        raise


def add_download(
    user_id: int,
    username: Optional[str],
    platform: str,
    url: str,
    status: str = "success",
    file_size_bytes: Optional[int] = None,
    duration_seconds: Optional[float] = None,
    error_message: Optional[str] = None
) -> bool:
    """Добавить запись о загрузке в историю."""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        
        # Добавляем запись в таблицу downloads
        cursor.execute("""
            INSERT INTO downloads 
            (user_id, username, platform, url, status, file_size_bytes, duration_seconds, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, username, platform, url, status, file_size_bytes, duration_seconds, error_message))
        
        # Обновляем статистику пользователя
        cursor.execute("""
            INSERT INTO user_stats (user_id, username, total_downloads, total_bytes, last_download)
            VALUES (?, ?, 1, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                total_downloads = total_downloads + 1,
                total_bytes = total_bytes + ?,
                last_download = CURRENT_TIMESTAMP,
                failed_count = CASE WHEN ? = 'success' THEN failed_count ELSE failed_count + 1 END
        """, (user_id, username, file_size_bytes or 0, file_size_bytes or 0, status))
        
        # Обновляем статистику платформы
        cursor.execute("""
            INSERT INTO platform_stats (platform, download_count, total_bytes)
            VALUES (?, 1, ?)
            ON CONFLICT(platform) DO UPDATE SET
                download_count = download_count + 1,
                total_bytes = total_bytes + ?,
                failed_count = CASE WHEN ? = 'success' THEN failed_count ELSE failed_count + 1 END
        """, (platform, file_size_bytes or 0, file_size_bytes or 0, status))
        
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error("Ошибка при добавлении записи в БД: %s", e)
        return False


def get_user_stats(user_id: int) -> Optional[Dict]:
    """Получить статистику пользователя."""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM user_stats WHERE user_id = ?
        """, (user_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return dict(row)
        return None
    except Exception as e:
        logger.error("Ошибка при получении статистики пользователя: %s", e)
        return None


def get_all_user_stats(limit: int = 10) -> List[Dict]:
    """Получить топ пользователей по количеству загрузок."""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM user_stats 
            ORDER BY total_downloads DESC 
            LIMIT ?
        """, (limit,))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error("Ошибка при получении статистики пользователей: %s", e)
        return []


def get_platform_stats() -> List[Dict]:
    """Получить статистику по платформам."""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM platform_stats 
            ORDER BY download_count DESC
        """)
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error("Ошибка при получении статистики платформ: %s", e)
        return []


def get_recent_downloads(limit: int = 20) -> List[Dict]:
    """Получить последние загрузки."""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM downloads 
            ORDER BY timestamp DESC 
            LIMIT ?
        """, (limit,))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error("Ошибка при получении последних загрузок: %s", e)
        return []


def get_stats_summary() -> Dict:
    """Получить общую статистику."""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        
        # Общее количество загрузок
        cursor.execute("SELECT COUNT(*) FROM downloads")
        total_downloads = cursor.fetchone()[0]
        
        # Количество успешных загрузок
        cursor.execute("SELECT COUNT(*) FROM downloads WHERE status = 'success'")
        successful_downloads = cursor.fetchone()[0]
        
        # Количество неудачных загрузок
        cursor.execute("SELECT COUNT(*) FROM downloads WHERE status != 'success'")
        failed_downloads = cursor.fetchone()[0]
        
        # Общий объём скачанных данных
        cursor.execute("SELECT SUM(file_size_bytes) FROM downloads WHERE file_size_bytes IS NOT NULL")
        total_bytes = cursor.fetchone()[0] or 0
        
        # Количество уникальных пользователей
        cursor.execute("SELECT COUNT(DISTINCT user_id) FROM downloads")
        unique_users = cursor.fetchone()[0]
        
        conn.close()
        
        return {
            "total_downloads": total_downloads,
            "successful_downloads": successful_downloads,
            "failed_downloads": failed_downloads,
            "total_bytes": total_bytes,
            "total_mb": round(total_bytes / (1024 * 1024), 2),
            "unique_users": unique_users,
        }
    except Exception as e:
        logger.error("Ошибка при получении общей статистики: %s", e)
        return {}


def cleanup_old_records(days: int = 30) -> int:
    """Удалить старые записи (старше N дней)."""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        
        cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()
        
        cursor.execute("DELETE FROM downloads WHERE timestamp < ?", (cutoff_date,))
        deleted_count = cursor.rowcount
        
        conn.commit()
        conn.close()
        
        logger.info("✓ Удалено %d старых записей (старше %d дней)", deleted_count, days)
        return deleted_count
    except Exception as e:
        logger.error("Ошибка при очистке старых записей: %s", e)
        return 0


# ----------------- Управление авторизованными админами -----------------
def add_authorized_admin(user_id: int, username: Optional[str] = None) -> bool:
    """Добавить пользователя в список авторизованных админов (self-service)."""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO authorized_admins (user_id, username) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET username = excluded.username
        """, (user_id, username))
        conn.commit()
        conn.close()
        logger.info("Добавлен авторизованный админ: %s", user_id)
        return True
    except Exception as e:
        logger.error("Ошибка при добавлении авторизованного админа: %s", e)
        return False


def remove_authorized_admin(user_id: int) -> bool:
    """Удалить пользователя из списка авторизованных админов."""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        cursor.execute("DELETE FROM authorized_admins WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
        logger.info("Удалён авторизованный админ: %s", user_id)
        return True
    except Exception as e:
        logger.error("Ошибка при удалении авторизованного админа: %s", e)
        return False


def is_authorized_admin(user_id: int) -> bool:
    """Проверить, добавлен ли пользователь в список авторизованных админов."""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM authorized_admins WHERE user_id = ? LIMIT 1", (user_id,))
        row = cursor.fetchone()
        conn.close()
        return bool(row)
    except Exception as e:
        logger.error("Ошибка при проверке авторизованного админа: %s", e)
        return False


def list_authorized_admins() -> List[Dict]:
    """Вернуть список авторизованных админов."""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM authorized_admins ORDER BY added_at DESC")
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error("Ошибка при получении списка авторизованных админов: %s", e)
        return []
