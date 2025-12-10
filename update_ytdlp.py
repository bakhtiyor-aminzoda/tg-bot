#!/usr/bin/env python3
"""Скрипт для ручного обновления yt-dlp с проверками и отчётом."""

import sys
import logging
from pathlib import Path

# Добавляем родительскую директорию в путь для импорта
sys.path.insert(0, str(Path(__file__).parent))

from utils.ytdlp_manager import (
    get_current_version,
    get_latest_version,
    compare_versions,
    update_ytdlp,
    test_ytdlp_basic,
    ensure_minimum_version,
    MIN_YTDLP_VERSION,
)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)


def main():
    """Главная функция скрипта обновления."""
    logger.info("=== Обновление yt-dlp ===")
    logger.info("")

    # 1. Проверяем текущую версию
    current = get_current_version()
    if not current:
        logger.error("✗ Не удалось определить текущую версию yt-dlp")
        logger.info("Установите yt-dlp: pip install yt-dlp")
        return 1

    logger.info("✓ Текущая версия yt-dlp: %s", current)

    # 2. Проверяем минимальную версию
    if not ensure_minimum_version():
        logger.warning("⚠ Ваша версия ниже минимальной (%s)", MIN_YTDLP_VERSION)

    # 3. Проверяем последнюю версию
    latest = get_latest_version()
    if not latest:
        logger.warning("⚠ Не удалось получить последнюю версию из PyPI")
        logger.info("Вы можете обновить вручную: pip install --upgrade yt-dlp")
        return 0

    logger.info("✓ Последняя версия: %s", latest)

    # 4. Сравниваем версии
    cmp_result = compare_versions(current, latest)
    if cmp_result >= 0:
        logger.info("✓ yt-dlp уже на последней версии!")
        return 0

    logger.info("")
    logger.info("Доступно обновление: %s -> %s", current, latest)
    logger.info("")

    # 5. Обновляем
    logger.info("Обновляю yt-dlp...")
    success, msg = update_ytdlp()
    logger.info("Результат: %s", msg)

    if not success:
        logger.error("✗ Ошибка при обновлении!")
        return 1

    # 6. Тестируем
    logger.info("")
    logger.info("Проверяю функционал...")
    if test_ytdlp_basic():
        logger.info("✓ yt-dlp работает корректно!")
    else:
        logger.error("✗ Ошибка при проверке yt-dlp!")
        return 1

    # 7. Финальная проверка версии
    new_version = get_current_version()
    logger.info("")
    logger.info("✓ Обновление успешно завершено!")
    logger.info("  Версия: %s -> %s", current, new_version)

    return 0


if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("")
        logger.info("Отменено пользователем")
        sys.exit(1)
    except Exception as e:
        logger.exception("Непредвиденная ошибка: %s", e)
        sys.exit(1)
