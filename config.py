# config.py
# Конфигурация бота — хранит токен, пути и ограничения.
# Токен должен лежать в переменной окружения TELEGRAM_BOT_TOKEN
# (рекомендуется хранить в системной переменной или .env, НЕ в коде).

import json
import os
from pathlib import Path
from typing import Dict, Optional

try:
	from dotenv import load_dotenv
except ImportError:  # python-dotenv is optional but recommended
	def load_dotenv(*_args, **_kwargs):  # type: ignore
		return None


load_dotenv()


def _require_env_var(name: str, *, example: Optional[str] = None) -> str:
	"""Read required env var with a helpful error if missing."""
	value = os.environ.get(name, "")
	if value is None:
		raise RuntimeError(f"Environment variable {name} must be set.")
	value = value.strip()
	if not value:
		hint = f"Provide it via .env or export {name}."
		if example:
			hint += f" Example: {name}={example}"
		raise RuntimeError(hint)
	return value


def _int_setting(
	name: str,
	default: int,
	*,
	min_value: int,
	max_value: Optional[int] = None,
) -> int:
	"""Parse bounded integer env vars with descriptive errors."""
	raw = os.environ.get(name)
	value = default if raw is None or not raw.strip() else raw.strip()
	try:
		parsed = int(value)
	except (TypeError, ValueError):
		raise ValueError(f"{name} must be an integer, got {value!r}") from None
	if parsed < min_value:
		raise ValueError(f"{name} must be >= {min_value}, got {parsed}")
	if max_value is not None and parsed > max_value:
		raise ValueError(f"{name} must be <= {max_value}, got {parsed}")
	return parsed


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

	prefix = url.split("://", 1)[0].lower() if "://" in url else ""
	if prefix == "postgres":
		url = "postgresql://" + url.split("://", 1)[1]
		prefix = "postgresql"
	if prefix == "postgresql" and "+" not in prefix:
		url = "postgresql+psycopg://" + url.split("://", 1)[1]

	return url or None

# Telegram token — читаем из окружения
TOKEN = _require_env_var("TELEGRAM_BOT_TOKEN", example="123456:ABCDEF")
_bot_username_raw = os.environ.get("BOT_USERNAME", "").strip()
BOT_USERNAME = _bot_username_raw.lstrip("@") if _bot_username_raw else None

# Хранилище истории: DATABASE_URL обязателен (можно использовать sqlite DSN)
_raw_db_url = _require_env_var("DATABASE_URL", example="postgresql+psycopg://user:pass@host/db")
DATABASE_URL = _normalize_database_url(_raw_db_url)
if not DATABASE_URL:
	raise RuntimeError("DATABASE_URL is required and must be a valid SQLAlchemy URL")
HISTORY_DB_PATH = Path(os.environ.get("HISTORY_DB_PATH", "./data/history.db"))

# Папка для временных файлов (если не существует, будет создана)
TEMP_DIR = Path(os.environ.get("TEMP_DIR", "./tmp"))
TEMP_DIR.mkdir(parents=True, exist_ok=True)

# Ограничения
TELEGRAM_MAX_FILE_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB
DOWNLOAD_TIMEOUT_SECONDS = _int_setting(
	"DOWNLOAD_TIMEOUT",
	default=20 * 60,
	min_value=60,
	max_value=6 * 60 * 60,
)

# Анти-спам: минимальный интервал (в секундах) между запросами от одного пользователя
USER_COOLDOWN_SECONDS = _int_setting(
	"USER_COOLDOWN_SECONDS",
	default=5,
	min_value=1,
	max_value=3600,
)
# Максимум одновременных загрузок на одного пользователя (в личке)
MAX_CONCURRENT_PER_USER = _int_setting(
	"MAX_CONCURRENT_PER_USER",
	default=2,
	min_value=1,
	max_value=8,
)
# Минимальный интервал между callback-запусками из одного чата
CALLBACK_CHAT_COOLDOWN_SECONDS = _int_setting(
	"CALLBACK_CHAT_COOLDOWN_SECONDS",
	default=3,
	min_value=0,
	max_value=60,
)
# Глобальный лимит callback-запусков в окне по времени
CALLBACK_GLOBAL_MAX_CALLS = _int_setting(
	"CALLBACK_GLOBAL_MAX_CALLS",
	default=30,
	min_value=1,
	max_value=500,
)
CALLBACK_GLOBAL_WINDOW_SECONDS = _int_setting(
	"CALLBACK_GLOBAL_WINDOW_SECONDS",
	default=60,
	min_value=5,
	max_value=600,
)
# Максимальное время ожидания зависшей загрузки до принудительного сброса счётчиков
DOWNLOAD_STUCK_TIMEOUT_SECONDS = _int_setting(
	"DOWNLOAD_STUCK_TIMEOUT_SECONDS",
	default=15 * 60,
	min_value=30,
	max_value=6 * 60 * 60,
)
# TTL для хранениия пользовательских таймстампов (после этого чистим словари)
USER_STATE_TTL_SECONDS = _int_setting(
	"USER_STATE_TTL_SECONDS",
	default=60 * 60,
	min_value=60,
	max_value=24 * 60 * 60,
)
# Периодическая очистка ожидающих скачиваний (pending_downloads)
PENDING_CLEANUP_INTERVAL_SECONDS = _int_setting(
	"PENDING_CLEANUP_INTERVAL_SECONDS",
	default=60,
	min_value=10,
	max_value=60 * 60,
)

# Логирование (уровень и путь можно переопределить)
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
# Путь до файла логов (опционально). Если задан — будет использоваться ротация.
LOG_FILE = os.environ.get("LOG_FILE", "./logs/bot.log")
if LOG_FILE:
	# Готовим директорию для файла логов заранее
	log_path = Path(LOG_FILE)
	log_path.parent.mkdir(parents=True, exist_ok=True)
	LOG_FILE = str(log_path)
LOG_MAX_BYTES = _int_setting(
	"LOG_MAX_BYTES",
	default=10 * 1024 * 1024,
	min_value=1024,
	max_value=500 * 1024 * 1024,
)
LOG_BACKUP_COUNT = _int_setting("LOG_BACKUP_COUNT", default=5, min_value=1, max_value=50)
STRUCTURED_LOGS = os.environ.get("STRUCTURED_LOGS", "false").lower() in ("true", "1", "yes")
# Sentry DSN (опционально). Если не задано — Sentry не инициализируется.
SENTRY_DSN = os.environ.get("SENTRY_DSN", None)
# Healthcheck server configuration
HEALTHCHECK_ENABLED = os.environ.get("HEALTHCHECK_ENABLED", "true").lower() in ("true", "1", "yes")
HEALTHCHECK_HOST = os.environ.get("HEALTHCHECK_HOST", "0.0.0.0")
HEALTHCHECK_PORT = _int_setting("HEALTHCHECK_PORT", default=8080, min_value=1, max_value=65535)
# Глобальное ограничение одновременных загрузок (по всей программе)
# Можно переопределить через окружение MAX_GLOBAL_CONCURRENT_DOWNLOADS
MAX_GLOBAL_CONCURRENT_DOWNLOADS = _int_setting(
	"MAX_GLOBAL_CONCURRENT_DOWNLOADS",
	default=4,
	min_value=1,
	max_value=32,
)
# опционально
YTDLP_COOKIES_FILE = os.environ.get("YTDLP_COOKIES_FILE", None)

# Опциональная проверка файлов внешним сканером (например, clamscan)
MEDIA_SCAN_COMMAND = os.environ.get("MEDIA_SCAN_COMMAND", "").strip()
MEDIA_SCAN_TIMEOUT_SECONDS = _int_setting(
	"MEDIA_SCAN_TIMEOUT_SECONDS",
	default=45,
	min_value=5,
	max_value=5 * 60,
)

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
def _parse_admin_accounts(raw: Optional[str]) -> Dict[str, Dict[str, str]]:
	"""Parse ADMIN_PANEL_ADMINS env string into structured accounts."""
	accounts: Dict[str, Dict[str, str]] = {}
	if not raw:
		return accounts
	for chunk in raw.split(","):
		item = chunk.strip()
		if not item or ":" not in item:
			continue
		key, token = item.split(":", 1)
		slug_part = key.strip()
		secret = token.strip()
		if not slug_part or not secret:
			continue
		if "|" in slug_part:
			slug, display = [part.strip() for part in slug_part.split("|", 1)]
			if not slug:
				slug = display
		else:
			slug = slug_part
			display = slug_part
		if not slug:
			continue
		accounts[slug] = {"token": secret, "display": display or slug}
	return accounts


ADMIN_PANEL_TOKEN = os.environ.get("ADMIN_PANEL_TOKEN")
ADMIN_PANEL_ADMINS = _parse_admin_accounts(os.environ.get("ADMIN_PANEL_ADMINS"))
ADMIN_PANEL_SESSION_SECRET = os.environ.get("ADMIN_PANEL_SESSION_SECRET")
ADMIN_PANEL_SESSION_TTL_SECONDS = _int_setting(
	"ADMIN_PANEL_SESSION_TTL_SECONDS",
	default=6 * 60 * 60,
	min_value=300,
	max_value=7 * 24 * 60 * 60,
)


def _coerce_positive_int(value, default: int) -> int:
	try:
		parsed = int(value)
	except (TypeError, ValueError):
		return default
	return max(0, parsed)


def _normalized_subscription_plans() -> Dict[str, Dict[str, object]]:
	baseline = {
		"free": {
			"label": "Free",
			"daily_quota": 30,
			"monthly_quota": 60,
			"max_parallel_downloads": 1,
			"priority": 0,
			"price_usd": 0,
			"description": "Базовый тариф для новых пользователей",
		},
		"power": {
			"label": "Power",
			"daily_quota": 30,
			"monthly_quota": 400,
			"max_parallel_downloads": 2,
			"priority": 10,
			"price_usd": 9,
			"description": "Для активных загрузчиков и креаторов",
		},
		"team": {
			"label": "Team",
			"daily_quota": 30,
			"monthly_quota": 1500,
			"max_parallel_downloads": 4,
			"priority": 20,
			"price_usd": 25,
			"description": "Общий тариф для студий и медиа-команд",
		},
	}

	raw_overrides = os.environ.get("SUBSCRIPTION_PLANS_JSON",
		"",
	)
	if raw_overrides.strip():
		try:
			payload = json.loads(raw_overrides)
		except json.JSONDecodeError as exc:  # pragma: no cover - config guardrail
			raise ValueError("SUBSCRIPTION_PLANS_JSON must be a valid JSON object") from exc
		if not isinstance(payload, dict):
			raise ValueError("SUBSCRIPTION_PLANS_JSON must be a JSON object with plan definitions")
		for key, definition in payload.items():
			if not isinstance(definition, dict):
				continue
			plan_key = str(key).strip().lower()
			if not plan_key:
				continue
			current = baseline.get(plan_key, {})
			baseline[plan_key] = {
				"label": definition.get("label") or current.get("label") or plan_key.title(),
				"daily_quota": _coerce_positive_int(definition.get("daily_quota"), current.get("daily_quota", 30)),
				"monthly_quota": _coerce_positive_int(definition.get("monthly_quota"), current.get("monthly_quota", 60)),
				"max_parallel_downloads": max(1, _coerce_positive_int(definition.get("max_parallel_downloads"), current.get("max_parallel_downloads", 1))),
				"priority": _coerce_positive_int(definition.get("priority"), current.get("priority", 0)),
				"price_usd": _coerce_positive_int(definition.get("price_usd"), current.get("price_usd", 0)),
				"description": definition.get("description") or current.get("description"),
			}
	return baseline


SUBSCRIPTION_PLANS: Dict[str, Dict[str, object]] = _normalized_subscription_plans()
DEFAULT_SUBSCRIPTION_PLAN = os.environ.get("DEFAULT_SUBSCRIPTION_PLAN", "free").strip().lower() or "free"
if DEFAULT_SUBSCRIPTION_PLAN not in SUBSCRIPTION_PLANS:
	DEFAULT_SUBSCRIPTION_PLAN = "free"
SUBSCRIPTION_PERIOD_DAYS = _int_setting("SUBSCRIPTION_PERIOD_DAYS", default=30, min_value=1, max_value=120)
UPGRADE_SUPPORT_LINK = os.environ.get("UPGRADE_SUPPORT_LINK", "https://t.me/MediaBanditSupport").strip() or None

# === Alerts & health monitoring ===
try:
	ADMIN_ALERT_CHAT_ID = int(os.environ.get("ADMIN_ALERT_CHAT_ID", "0")) or None
except ValueError:
	ADMIN_ALERT_CHAT_ID = None
ALERT_MONITOR_INTERVAL_SECONDS = _int_setting(
	"ALERT_MONITOR_INTERVAL_SECONDS",
	default=60,
	min_value=15,
	max_value=15 * 60,
)
ALERT_ERROR_SPIKE_THRESHOLD = _int_setting(
	"ALERT_ERROR_SPIKE_THRESHOLD",
	default=8,
	min_value=1,
	max_value=1000,
)
ALERT_PENDING_THRESHOLD = _int_setting(
	"ALERT_PENDING_THRESHOLD",
	default=15,
	min_value=1,
	max_value=10_000,
)
ALERT_STUCK_ACTIVE_MINUTES = _int_setting(
	"ALERT_STUCK_ACTIVE_MINUTES",
	default=3,
	min_value=1,
	max_value=60,
)
ALERT_NOTIFY_COOLDOWN_MINUTES = _int_setting(
	"ALERT_NOTIFY_COOLDOWN_MINUTES",
	default=60,
	min_value=1,
	max_value=24 * 60,
)
