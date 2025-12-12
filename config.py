# config.py
# Конфигурация бота — хранит токен, пути и ограничения.
# Токен должен лежать в переменной окружения TELEGRAM_BOT_TOKEN
# (рекомендуется хранить в системной переменной или .env, НЕ в коде).

import os
from pathlib import Path
from typing import Optional

try:
	from dotenv import load_dotenv
except ImportError:  # python-dotenv is optional but recommended
	def load_dotenv(*_args, **_kwargs):  # type: ignore
		return None


load_dotenv()


def _normalize_database_url(raw: Optional[str]) -> Optional[str]:

	if not raw:
		return None

	url = raw.strip()
	if not url:
		return None

	psql_prefix = "psql "
	if url.lower().startswith(psql_prefix):
		url = url[len(psql_prefix) :].strip()

	if url and url[0] in {'"', "'"}:
		quote = url[0]
		if url.endswith(quote):
			url = url[1:-1].strip()

	return url or None

# Telegram token — читаем из окружения
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "<PUT_YOUR_TOKEN_HERE>")  # замените или экспортируйте переменную

# Хранилище истории: если DATABASE_URL не задан, используется локальная SQLite по пути HISTORY_DB_PATH
DATABASE_URL = _normalize_database_url(os.environ.get("DATABASE_URL"))
HISTORY_DB_PATH = Path(os.environ.get("HISTORY_DB_PATH", "./data/history.db"))

# Папка для временных файлов (если не существует, будет создана)
TEMP_DIR = Path(os.environ.get("TEMP_DIR", "./tmp"))
TEMP_DIR.mkdir(parents=True, exist_ok=True)

# Ограничения
TELEGRAM_MAX_FILE_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB
DOWNLOAD_TIMEOUT_SECONDS = int(os.environ.get("DOWNLOAD_TIMEOUT", 20 * 60))  # таймаут скачивания (по умолчанию 20 минут)

# Анти-спам: минимальный интервал (в секундах) между запросами от одного пользователя
USER_COOLDOWN_SECONDS = 10
# Максимальное время ожидания зависшей загрузки до принудительного сброса счётчиков
DOWNLOAD_STUCK_TIMEOUT_SECONDS = int(os.environ.get("DOWNLOAD_STUCK_TIMEOUT_SECONDS", str(15 * 60)))
# TTL для хранениия пользовательских таймстампов (после этого чистим словари)
USER_STATE_TTL_SECONDS = int(os.environ.get("USER_STATE_TTL_SECONDS", str(60 * 60)))
# Периодическая очистка ожидающих скачиваний (pending_downloads)
PENDING_CLEANUP_INTERVAL_SECONDS = int(os.environ.get("PENDING_CLEANUP_INTERVAL_SECONDS", "60"))

# Логирование (уровень и путь можно переопределить)
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
# Путь до файла логов (опционально). Если задан — будет использоваться ротация.
LOG_FILE = os.environ.get("LOG_FILE", "./logs/bot.log")
if LOG_FILE:
	# Готовим директорию для файла логов заранее
	log_path = Path(LOG_FILE)
	log_path.parent.mkdir(parents=True, exist_ok=True)
	LOG_FILE = str(log_path)
LOG_MAX_BYTES = int(os.environ.get("LOG_MAX_BYTES", str(10 * 1024 * 1024)))  # 10 MB
LOG_BACKUP_COUNT = int(os.environ.get("LOG_BACKUP_COUNT", "5"))
STRUCTURED_LOGS = os.environ.get("STRUCTURED_LOGS", "false").lower() in ("true", "1", "yes")
# Sentry DSN (опционально). Если не задано — Sentry не инициализируется.
SENTRY_DSN = os.environ.get("SENTRY_DSN", None)
# Healthcheck server configuration
HEALTHCHECK_ENABLED = os.environ.get("HEALTHCHECK_ENABLED", "true").lower() in ("true", "1", "yes")
HEALTHCHECK_HOST = os.environ.get("HEALTHCHECK_HOST", "0.0.0.0")
HEALTHCHECK_PORT = int(os.environ.get("HEALTHCHECK_PORT", "8080"))
# Глобальное ограничение одновременных загрузок (по всей программе)
# Можно переопределить через окружение MAX_GLOBAL_CONCURRENT_DOWNLOADS
MAX_GLOBAL_CONCURRENT_DOWNLOADS = int(os.environ.get("MAX_GLOBAL_CONCURRENT_DOWNLOADS", "4"))
# опционально
YTDLP_COOKIES_FILE = os.environ.get("YTDLP_COOKIES_FILE", None)

# Кэш загруженных видео
VIDEO_CACHE_ENABLED = os.environ.get("VIDEO_CACHE_ENABLED", "true").lower() in ("true", "1", "yes")
VIDEO_CACHE_DIR = os.environ.get("VIDEO_CACHE_DIR", "./tmp/video_cache")
try:
	VIDEO_CACHE_TTL_SECONDS = max(60, int(os.environ.get("VIDEO_CACHE_TTL_SECONDS", "3600")))
except ValueError:
	VIDEO_CACHE_TTL_SECONDS = 3600
try:
	VIDEO_CACHE_MAX_ITEMS = max(10, int(os.environ.get("VIDEO_CACHE_MAX_ITEMS", "200")))
except ValueError:
	VIDEO_CACHE_MAX_ITEMS = 200
if VIDEO_CACHE_ENABLED and VIDEO_CACHE_DIR:
	_cache_path = Path(VIDEO_CACHE_DIR)
	_cache_path.mkdir(parents=True, exist_ok=True)
	VIDEO_CACHE_DIR = str(_cache_path)

# === Instagram cookie auto-refresh ===
IG_COOKIES_AUTO_REFRESH = os.environ.get("IG_COOKIES_AUTO_REFRESH", "false").lower() in ("true", "1", "yes")
IG_LOGIN = os.environ.get("IG_LOGIN")
IG_PASSWORD = os.environ.get("IG_PASSWORD")
IG_COOKIES_PATH = os.environ.get("IG_COOKIES_PATH", "./tmp/instagram_cookies.txt")
try:
	IG_COOKIES_REFRESH_INTERVAL_HOURS = max(1.0, float(os.environ.get("IG_COOKIES_REFRESH_INTERVAL_HOURS", "6")))
except ValueError:
	IG_COOKIES_REFRESH_INTERVAL_HOURS = 6.0
_ig_backup_codes = os.environ.get("IG_2FA_BACKUP_CODES", "")
IG_2FA_BACKUP_CODES = [code.strip() for code in _ig_backup_codes.split(",") if code.strip()]

if IG_COOKIES_AUTO_REFRESH and IG_COOKIES_PATH:
	ig_path = Path(IG_COOKIES_PATH)
	ig_path.parent.mkdir(parents=True, exist_ok=True)
	IG_COOKIES_PATH = str(ig_path)
	if not YTDLP_COOKIES_FILE:
		YTDLP_COOKIES_FILE = IG_COOKIES_PATH

# === Режимы ограничения доступа ===
# WHITELIST_MODE: если True, только пользователи из ALLOWED_USER_IDS могут использовать бота
WHITELIST_MODE = os.environ.get("WHITELIST_MODE", "false").lower() in ("true", "1", "yes")

# ALLOWED_USER_IDS: список ID пользователей, которым разрешена загрузка (если WHITELIST_MODE=true)
# Формат: "123456,789012,345678" (разделены запятыми)
_allowed_users_str = os.environ.get("ALLOWED_USER_IDS", "")
ALLOWED_USER_IDS = set(int(uid.strip()) for uid in _allowed_users_str.split(",") if uid.strip().isdigit())

# ADMIN_ONLY: если True, только администраторы групп/каналов могут использовать бота
ADMIN_ONLY = os.environ.get("ADMIN_ONLY", "false").lower() in ("true", "1", "yes")

# ADMIN_USER_IDS: дополнительные ID администраторов (помимо админов групп)
# Формат: "123456,789012,345678" (разделены запятыми)
_admin_users_str = os.environ.get("ADMIN_USER_IDS", "")
ADMIN_USER_IDS = set(int(uid.strip()) for uid in _admin_users_str.split(",") if uid.strip().isdigit())

# === История загрузок (SQLite) ===
# ENABLE_HISTORY: если True, сохранять историю загрузок в SQLite БД
ENABLE_HISTORY = os.environ.get("ENABLE_HISTORY", "true").lower() in ("true", "1", "yes")
# CLEANUP_OLD_RECORDS_DAYS: удалять записи старше N дней (0 = никогда)
CLEANUP_OLD_RECORDS_DAYS = int(os.environ.get("CLEANUP_OLD_RECORDS_DAYS", "30"))

# === Веб-админка ===
ADMIN_PANEL_ENABLED = os.environ.get("ADMIN_PANEL_ENABLED", "true").lower() in ("true", "1", "yes")
ADMIN_PANEL_HOST = os.environ.get("ADMIN_PANEL_HOST", "0.0.0.0")
_admin_panel_port_raw = os.environ.get("ADMIN_PANEL_PORT", "8090")
if _admin_panel_port_raw.startswith("$"):
	# Railway/Render: allow referencing another env var like $PORT
	_admin_panel_port_raw = os.environ.get(_admin_panel_port_raw[1:], _admin_panel_port_raw)
try:
	ADMIN_PANEL_PORT = int(_admin_panel_port_raw)
except ValueError:
	raise ValueError(
		f"ADMIN_PANEL_PORT must be an integer, got {_admin_panel_port_raw!r}. "
		"Set ADMIN_PANEL_PORT to \"$PORT\" only if the PORT env var is defined."
	)
ADMIN_PANEL_TOKEN = os.environ.get("ADMIN_PANEL_TOKEN")
