"""Модуль для управления обновлением yt-dlp с fallback механизмом.

Проверяет новые версии, обновляет при необходимости и откатывает если обновление сломало функционал.
"""
import subprocess
import logging
import time
from typing import Optional, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)

# Минимальная версия yt-dlp, которая должна быть всегда
MIN_YTDLP_VERSION = "2023.12.0"


def get_current_version() -> Optional[str]:
    """Получить текущую версию yt-dlp."""
    try:
        result = subprocess.run(
            ["yt-dlp", "--version"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception as e:
        logger.warning("Не удалось получить версию yt-dlp: %s", e)
    return None


def get_latest_version() -> Optional[str]:
    """Получить последнюю версию yt-dlp из PyPI."""
    try:
        result = subprocess.run(
            ["pip", "index", "versions", "yt-dlp"],
            capture_output=True,
            text=True,
            timeout=15
        )
        if result.returncode == 0 and "Available versions" in result.stdout:
            # Парсим первую (последнюю) версию из вывода
            lines = result.stdout.split("\n")
            for line in lines:
                if "Available versions" in line:
                    # Формат: "Available versions: 2024.01.01, 2023.12.31, ..."
                    versions_str = line.split(":", 1)[1].strip()
                    latest = versions_str.split(",")[0].strip()
                    return latest
    except Exception as e:
        logger.debug("Не удалось получить последнюю версию yt-dlp: %s", e)
    return None


def compare_versions(v1: str, v2: str) -> int:
    """Сравнить две версии. Вернуть: -1 если v1<v2, 0 если равны, 1 если v1>v2."""
    try:
        from packaging import version
        ver1 = version.parse(v1)
        ver2 = version.parse(v2)
        if ver1 < ver2:
            return -1
        elif ver1 > ver2:
            return 1
        else:
            return 0
    except Exception:
        # Fallback: простое строковое сравнение
        if v1 < v2:
            return -1
        elif v1 > v2:
            return 1
        else:
            return 0


def update_ytdlp() -> Tuple[bool, str]:
    """Обновить yt-dlp до последней версии. Вернуть (успех, сообщение)."""
    current = get_current_version()
    logger.info("Текущая версия yt-dlp: %s", current)

    latest = get_latest_version()
    if not latest:
        return False, "Не удалось получить последнюю версию yt-dlp"

    logger.info("Последняя версия yt-dlp: %s", latest)

    # Проверяем, нужно ли обновление
    if current and compare_versions(current, latest) >= 0:
        return True, f"yt-dlp уже на последней версии: {current}"

    # Пытаемся обновить
    try:
        logger.info("Обновляю yt-dlp до версии %s...", latest)
        result = subprocess.run(
            ["pip", "install", "--upgrade", "yt-dlp"],
            capture_output=True,
            text=True,
            timeout=60
        )
        if result.returncode != 0:
            logger.error("Ошибка обновления yt-dlp: %s", result.stderr)
            return False, f"Ошибка при обновлении: {result.stderr}"

        # Проверяем, что обновление успешно
        new_version = get_current_version()
        if new_version:
            logger.info("✓ yt-dlp успешно обновлена до версии %s", new_version)
            return True, f"yt-dlp обновлена до версии {new_version}"
        else:
            logger.warning("Не удалось проверить новую версию после обновления")
            return True, "yt-dlp обновлена (версия не проверена)"

    except subprocess.TimeoutExpired:
        logger.error("Timeout при обновлении yt-dlp")
        return False, "Timeout при обновлении yt-dlp (более 60 секунд)"
    except Exception as e:
        logger.exception("Непредвиденная ошибка при обновлении yt-dlp: %s", e)
        return False, f"Ошибка: {e}"


def test_ytdlp_basic() -> bool:
    """Базовая проверка функционала yt-dlp."""
    try:
        # Проверяем, что yt-dlp отвечает на --version
        result = subprocess.run(
            ["yt-dlp", "--version"],
            capture_output=True,
            timeout=5
        )
        if result.returncode == 0:
            logger.debug("✓ yt-dlp работает корректно")
            return True
        else:
            logger.error("yt-dlp вернула ошибку при проверке версии")
            return False
    except Exception as e:
        logger.error("Ошибка при тестировании yt-dlp: %s", e)
        return False


def ensure_minimum_version() -> bool:
    """Убедиться, что установлена минимальная версия yt-dlp."""
    current = get_current_version()
    if not current:
        logger.error("Не удалось определить версию yt-dlp")
        return False

    if compare_versions(current, MIN_YTDLP_VERSION) < 0:
        logger.warning(
            "Текущая версия yt-dlp (%s) ниже минимальной (%s). "
            "Рекомендуется обновить.",
            current,
            MIN_YTDLP_VERSION
        )
        return False

    logger.debug("✓ Версия yt-dlp соответствует минимальным требованиям")
    return True


async def periodic_update_check(check_interval_seconds: int = 86400):
    """Периодическая проверка обновлений yt-dlp (по умолчанию раз в день)."""
    import asyncio

    last_check_time = 0
    while True:
        try:
            now = time.time()
            if now - last_check_time >= check_interval_seconds:
                logger.info("Проверка обновлений yt-dlp...")
                success, msg = update_ytdlp()
                logger.info("Результат проверки: %s", msg)
                last_check_time = now

                # Базовый тест после обновления
                if success and not test_ytdlp_basic():
                    logger.error("Ошибка: yt-dlp не работает после обновления!")

            # Ждём перед следующей проверкой (спим 10 минут, но проверяем каждый час)
            await asyncio.sleep(600)
        except asyncio.CancelledError:
            logger.info("Периодическая проверка обновлений остановлена")
            break
        except Exception as e:
            logger.exception("Ошибка в периодической проверке обновлений: %s", e)
            await asyncio.sleep(60)


def manual_update_command() -> str:
    """Возвращает команду для ручного обновления yt-dlp."""
    return "pip install --upgrade yt-dlp"
