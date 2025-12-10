# config.py
# Конфигурация бота — хранит токен, пути и ограничения.
# Токен должен лежать в переменной окружения TELEGRAM_BOT_TOKEN
# (рекомендуется хранить в системной переменной или .env, НЕ в коде).

import os
from pathlib import Path

# Telegram token — читаем из окружения
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "<PUT_YOUR_TOKEN_HERE>")  # замените или экспортируйте переменную

# Папка для временных файлов (если не существует, будет создана)
TEMP_DIR = Path(os.environ.get("TEMP_DIR", "./tmp"))
TEMP_DIR.mkdir(parents=True, exist_ok=True)

# Ограничения
TELEGRAM_MAX_FILE_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB
DOWNLOAD_TIMEOUT_SECONDS = int(os.environ.get("DOWNLOAD_TIMEOUT", 20 * 60))  # таймаут скачивания (по умолчанию 20 минут)

# Анти-спам: минимальный интервал (в секундах) между запросами от одного пользователя
USER_COOLDOWN_SECONDS = 10

# Логирование (уровень и путь можно переопределить)
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
# опционально
YTDLP_COOKIES_FILE = os.environ.get("YTDLP_COOKIES_FILE", None)

