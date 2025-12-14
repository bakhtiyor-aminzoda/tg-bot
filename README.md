# Telegram Video Downloader Bot (MVP)

Бот скачивает видео и фото с YouTube, TikTok, Instagram и отправляет в Telegram.
Реализация: Python + aiogram 3.x + yt-dlp.

## Структура
```
project/
│── main.py
│── config.py
│── requirements.txt
│── README.md
└── utils/
    └── downloader.py
```

## Быстрый старт (локально)

1. Клонируйте/скопируйте проект:
```bash
git clone <repo> && cd project
```

2. Создайте виртуальное окружение и активируйте:
```bash
python3 -m venv venv
source venv/bin/activate    # Linux / macOS
# venv\Scripts\activate     # Windows (PowerShell: .\venv\Scripts\Activate.ps1)
```

3. Установите зависимости:
```bash
pip install -r requirements.txt
```

4. Установите `yt-dlp` (локально или глобально). Если не хотите ставить глобально, установите в venv:
```bash
pip install yt-dlp
```
> Убедитесь, что `yt-dlp` доступен в PATH (из того же окружения, где запускаете бота).

5. Настройте переменные окружения через `.env` (оба значения обязательны):
```bash
cp .env.example .env
echo "TELEGRAM_BOT_TOKEN=123456:ABCDEF..." >> .env
echo "DATABASE_URL=sqlite:///./data/history.db" >> .env
```
Файл будет автоматически прочитан благодаря `python-dotenv`. При желании можно применять и прямое
`export TELEGRAM_BOT_TOKEN=...` и `export DATABASE_URL=...` (Windows: `setx TELEGRAM_BOT_TOKEN ...`). Не коммитьте `.env` в git.

6. Запустите бота:
```bash
python main.py
```

### Миграции БД (Alembic)

Схема базы версии отслеживается через Alembic (каталог `alembic/`).

1. Убедитесь, что переменные окружения заданы:
  ```bash
  export TELEGRAM_BOT_TOKEN=123456:ABCDEF
  export DATABASE_URL=postgresql+psycopg://user:pass@host/dbname
  ```
2. Примените миграции:
  ```bash
  ALEMBIC_DATABASE_URL="$DATABASE_URL" alembic upgrade head
  ```
3. Чтобы сгенерировать новую миграцию после изменения схемы, выполните:
  ```bash
  alembic revision --autogenerate -m "add new table"
  ALEMBIC_DATABASE_URL="$DATABASE_URL" alembic upgrade head
  ```

Для локальной SQLite можно опустить `ALEMBIC_DATABASE_URL` (используется значение из `alembic.ini`).

## Локальные проверки качества

```bash
make check   # Ruff lint (E/F/W/B/I/UP/N rules)
make fmt     # Ruff formatter (переписывает файлы)
make test    # python -m unittest discover
```
Команды опираются на установленный `ruff` (устанавливается автоматически в CI и может быть
установлен локально через `pip install ruff`).

## Управление секретами

- **Локально:** копируйте шаблон `cp .env.example .env`, заполните `TELEGRAM_BOT_TOKEN` и другие
  значения. Файл `.env` находится в `.gitignore`, поэтому реальные токены не попадут в git.
- **Docker / docker-compose:** тот же `.env` подхватывается автоматически, можно переопределять
  переменные через `docker run -e ...`.
- **CI / GitHub Actions:** храните значения в `Repository Settings → Secrets and variables → Actions`
  (например, `TELEGRAM_BOT_TOKEN`, `SENTRY_DSN`). Workflow берёт тестовый токен из переменных
  окружения, для продакшн-сборок задайте секреты и считывайте их через `${{ secrets.NAME }}`.

## Пример использования
- Отправьте в чат:
```
/download https://youtu.be/xxxx
```
или
```
/download
https://vm.tiktok.com/xxxx
```

Бот ответит статусом, скачает и пришлёт видео. Если файл > 2 ГБ — выдаст сообщение и не попытается отправить.

- Для QA/релиз-менеджеров есть чек-лист `docs/QA.md`, а ключевые новинки перечислены ниже.

### Новое в релизе “UX Boost”

- Локализованные статусы и кнопки: бот автоматически выбирает язык (RU/EN) и поддерживает одинаковый UX в личках и группах.
- Живой прогресс: статусные сообщения обновляются по мере загрузки (процент, скорость, ETA, объём) без спама.
- Instagram-фото: бот корректно скачивает и отправляет посты с изображениями (как фото или документ, если Telegram жалуется на формат).
- Авто-режим загрузки: в личных чатах бот сразу стартует скачивание в лучшем доступном качестве без дополнительных клавиатур (выбор пресетов временно отключён для стабильности).
- Опция “Download” в группах: каждое сообщение получает кнопку, которая запускает отдельное скачивание и показывает те же статусы.
- Дополнительные тесты: обновлённый `tests/test_handlers_downloads.py` покрывает rate-limit, fallback на `send_document` и сценарии для групп.
- Тихие тесты: suite отключает болтливые логи yt-dlp и status-хендлеров, поэтому CI вывод чище.
### UX-фичи

- Бот автоматически определяет язык Telegram-клиента и показывает статусы/кнопки на русском или английском без дополнительных настроек.
- Пока видео скачивается, статусное сообщение обновляется в реальном времени: проценты, скорость, ETA и объём уже загруженных данных.
- В личных чатах загрузка запускается сразу и использует авто-качество — минимум кликов и нулевые ошибки при выборе пресетов.

## Деплой

### Docker (локально или в облаке)

#### Локальная разработка с docker-compose
```bash
# 1. Установите Docker и docker-compose
# https://docs.docker.com/get-docker/

# 2. Создайте файл .env с токеном
cat > .env << EOF
TELEGRAM_BOT_TOKEN=your_token_here
SENTRY_DSN=https://your-sentry-dsn-here (опционально)
EOF

# 3. Запустите контейнер
docker-compose up -d

# 4. Смотрите логи
docker-compose logs -f bot

# 5. Остановите контейнер
docker-compose down
```

#### Сборка и запуск вручную
```bash
# Сборка образа
docker build -t tg-video-downloader:latest .

# Запуск с переменными окружения
docker run -d \
  -e TELEGRAM_BOT_TOKEN="your_token_here" \
  -e LOG_FILE=/app/logs/bot.log \
  -e SENTRY_DSN="https://your-sentry-dsn" \
  -v $(pwd)/logs:/app/logs \
  --restart unless-stopped \
  --name tg_video_bot \
  tg-video-downloader:latest

# Просмотр логов
docker logs -f tg_video_bot

# Остановка контейнера
docker stop tg_video_bot
docker rm tg_video_bot
```

#### Проверка установки ffmpeg в образе
```bash
docker run --rm tg-video-downloader:latest ffmpeg -version | head -n 1
docker run --rm tg-video-downloader:latest ffprobe -version | head -n 1
```

### Railway / Render
- Подключите репозиторий.
- В переменных окружения (Environment) добавьте TELEGRAM_BOT_TOKEN.
- Убедитесь, что requirements.txt содержит yt-dlp и sentry-sdk.
- Start Command: `python main.py`.

**Обязательные переменные окружения**
- `TELEGRAM_BOT_TOKEN` — токен вашего бота в BotFather. Без него приложение не стартует.
- `DATABASE_URL` — DSN для SQLite/Postgres/Neon. Для локальной разработки оставьте `sqlite:///./data/history.db`, для продакшена укажите `postgresql+psycopg://...`.

**Дополнительные переменные окружения** (логирование и Sentry)
- `LOG_FILE` — путь к файлу логов (по умолчанию `/app/logs/bot.log` в Docker). Если задан, бот будет писать ротационные логи в этот файл.
- `LOG_MAX_BYTES` и `LOG_BACKUP_COUNT` — параметры ротации (по умолчанию 10MB и 5 файлов).
- `SENTRY_DSN` — если указан, бот попытается инициализировать Sentry (требует `sentry-sdk` в `requirements.txt`).
- `MAX_GLOBAL_CONCURRENT_DOWNLOADS` — ограничение одновременных загрузок (по умолчанию 4).
- `MAX_CONCURRENT_PER_USER` — сколько параллельных загрузок разрешено одному пользователю в личке (по умолчанию 2).
- `USER_COOLDOWN_SECONDS` — минимальный интервал между запросами одного пользователя (по умолчанию 5 секунд).
- `CALLBACK_CHAT_COOLDOWN_SECONDS` — минимальный интервал между нажатиями Download в одном чате (по умолчанию 3 секунды).
- `CALLBACK_GLOBAL_MAX_CALLS` и `CALLBACK_GLOBAL_WINDOW_SECONDS` — глобальный лимит на количество callback-запусков в скользящем окне (по умолчанию 30 запросов в минуту).
- `DOWNLOAD_TIMEOUT` — таймаут скачивания в секундах (по умолчанию 1200 = 20 минут).
- `STRUCTURED_LOGS` — если `true`, включает JSON-логи (подходит для централизованного сбора логов). По умолчанию `false`.
- `HEALTHCHECK_ENABLED` — включает лёгкий HTTP-сервер `/health` (статус) и `/metrics` (снимок внутренних метрик). По умолчанию `true`.
- `HEALTHCHECK_HOST`/`HEALTHCHECK_PORT` — адрес и порт healthcheck-сервера (по умолчанию `0.0.0.0:8079`, ставьте отличный от порта админ-панели).
- `ADMIN_PANEL_HOST`/`ADMIN_PANEL_PORT` — параметры HTML-админки. Для Railway/Render ставьте `ADMIN_PANEL_HOST=0.0.0.0` и `ADMIN_PANEL_PORT=$PORT`, иначе панель останется доступна только локально.
- `ADMIN_PANEL_TOKEN` — общий токен для простого режима авторизации. Если не задано (и нет `ADMIN_PANEL_ADMINS`), панель будет доступна без пароля.
- `ADMIN_PANEL_ADMINS` — список персональных токенов в формате `slug|Display:token`. Пример: `ADMIN_PANEL_ADMINS="oleg|Олег:token1,irina|Ирина:token2"`. Каждый администратор получает собственный логин и подпись cookie.
- `ADMIN_PANEL_SESSION_SECRET` / `ADMIN_PANEL_SESSION_TTL_SECONDS` — переопределяют секрет подписи и время жизни cookie в многоадминном режиме (по умолчанию 6 часов).
- `VIDEO_CACHE_ENABLED`, `VIDEO_CACHE_DIR`, `VIDEO_CACHE_TTL_SECONDS`, `VIDEO_CACHE_MAX_ITEMS` — управляют файловым кэшем скачанных видео. При повторных запросах к тем же ссылкам бот просто копирует уже готовый файл и не запускает `yt-dlp`.
- `IG_COOKIES_AUTO_REFRESH`, `IG_LOGIN`, `IG_PASSWORD`, `IG_COOKIES_PATH`, `IG_COOKIES_REFRESH_INTERVAL_HOURS`, `IG_2FA_BACKUP_CODES` — включают автоматический логин в Instagram и сохранение cookies, чтобы yt-dlp всегда использовал свежую авторизованную сессию.
- `MEDIA_SCAN_COMMAND` и `MEDIA_SCAN_TIMEOUT_SECONDS` — позволяют подключить внешний сканер (например, `clamscan`). Если команда указана, бот прогоняет каждый файл через неё и блокирует заражённые результаты.

**Пример** (Railway / Render): добавьте `SENTRY_DSN` в секреты проекта и остальные переменные в Environment.

## Мониторинг и healthcheck

- Установите `STRUCTURED_LOGS=true`, чтобы получать JSON-структурированные записи (подойдут для Loki/ELK). Поля включают timestamp, уровень, имя логгера и сообщение.
- При `HEALTHCHECK_ENABLED=true` бот поднимает фоновый aiohttp-сервер с двумя endpoint'ами:
  - `GET /health` — возвращает `{ "status": "ok" }`, пригодно для k8s liveness/readiness probe.
  - `GET /metrics` — отдаёт JSON-снимок внутренних счётчиков и gauge-метрик (количество вызовов, кастомные показатели).
- Настройте `HEALTHCHECK_HOST` и `HEALTHCHECK_PORT`, чтобы ограничить доступ (например, `127.0.0.1:9000` за reverse-proxy).

Оба механизма работают независимо от Sentry и не блокируют основной event loop.

### Структурированные логи и request context

При включённом `STRUCTURED_LOGS=true` каждая запись дополняется полями из request context:

| Поле         | Значение                                                            |
|--------------|---------------------------------------------------------------------|
| `request_id` | Уникальный идентификатор запроса/загрузки (можно искать в логах).   |
| `user_id`    | Telegram ID пользователя, инициировавшего загрузку/колбэк.          |
| `chat_id`    | ID чата, где пришёл запрос (личка, группа, канал).                  |
| `channel`    | Тип чата (`private`, `group`, `supergroup`).                         |
| `source`     | Точка входа (`direct`, `group`, `callback`).                         |
| `platform`   | Определённая платформа ссылки (YouTube, TikTok, Instagram, ...).    |

Это же контекст попадает в Sentry breadcrumbs, поэтому достаточно ID запроса, чтобы отследить полный путь обработки.

### Метрики `/metrics`

Endpoint возвращает JSON вида:

```json
{
  "timestamp": 1734032400,
  "counters": {"downloads.total": 12, ...},
  "gauges": {"downloads.active": 1, ...}
}
```

Основные метрики:

| Имя                              | Тип      | Назначение                                                                                      |
|----------------------------------|----------|--------------------------------------------------------------------------------------------------|
| `downloads.total`                | counter  | Общее количество попыток скачивания (прямых и callback).                                         |
| `downloads.success`              | counter  | Успешно завершённые выдачи файла.                                                                 |
| `downloads.failure`              | counter  | Ошибки загрузки/отправки (DownloadError, Telegram errors и т.п.).                                |
| `downloads.denied`               | counter  | Заблокированные пользователи/чаты (access control).                                             |
| `downloads.blocked`              | counter  | Заблокированные ссылки (SSRF/unsafe URL).                                                        |
| `downloads.unsupported`          | counter  | Неподдерживаемые платформы или пустые URL.                                                       |
| `downloads.wait_time_ms_total`   | counter  | Сумма ожиданий глобального семафора (мс). Делите на `downloads.wait_time_events` для среднего.   |
| `downloads.wait_time_events`     | counter  | Количество ожиданий слота скачивания.                                                            |
| `downloads.duration_ms_total`    | counter  | Совокупное время обработки запросов (мс). Делиться на `downloads.duration_events`.               |
| `downloads.duration_events`      | counter  | Количество завершённых запросов (успехи + ошибки).                                               |
| `downloads.active`               | gauge    | Количество активных скачиваний прямо сейчас.                                                     |
| `downloads.pending_tokens`       | gauge    | Сколько callback-токенов ожидания в группах.                                                     |
| `downloads.queue_in_use`         | gauge    | Число занятых слотов глобального семафора.                                                       |
| `downloads.queue_available`      | gauge    | Свободные слоты глобального семафора.                                                            |
| `downloads.wait_last_ms`         | gauge    | Время ожидания последнего скачивания в очереди (мс).                                             |

Проверка endpoints локально:

```bash
curl -s http://127.0.0.1:8080/health | jq
curl -s http://127.0.0.1:8080/metrics | jq
```

Если `HEALTHCHECK_HOST=0.0.0.0`, убедитесь, что порт недоступен публично (через firewall или прокси).

## Обновление yt-dlp

yt-dlp регулярно обновляется, добавляя поддержку новых платформ и исправляя ошибки. Есть несколько способов обновления:

### Автоматическое обновление (GitHub Actions)
Если вы используете GitHub, репозиторий содержит workflow `.github/workflows/update-ytdlp.yml`, который:
- Еженедельно (по среда в 3 утра UTC) проверяет новые версии yt-dlp
- Автоматически обновляет и создаёт pull request
- Тестирует базовый функционал перед PR

Для использования:
1. Убедитесь, что GitHub Actions включена в вашем репозитории
2. Workflow автоматически запустится по расписанию или нажмите кнопку "Run workflow" вручную

### Ручное обновление

#### Способ 1: Используя скрипт
```bash
python3 update_ytdlp.py
```
Скрипт:
- Проверит текущую версию yt-dlp
- Получит последнюю версию из PyPI
- Обновит, если доступна новая версия
- Протестирует функционал после обновления

#### Способ 2: Используя Makefile
```bash
make update-ytdlp
```

#### Способ 3: Прямой pip команда
```bash
pip install --upgrade yt-dlp
```

### Обновление в Docker
Если используете Docker, образ автоматически получит последнюю версию yt-dlp из `requirements.txt`:
```bash
docker build --no-cache -t tg-video-downloader:latest .
docker-compose up -d
```

### Откат к предыдущей версии
Если после обновления возникли проблемы:
```bash
# Откатиться к конкретной версии
pip install yt-dlp==2023.12.0
```

## Автообновление cookies Instagram

Instagram всё чаще требует авторизованный доступ даже к публичным рилсам. Чтобы не выгружать cookies вручную, бот может сам логиниться и обновлять файл для yt-dlp.

1. Установите Playwright вместе с Chromium: `pip install playwright` и `playwright install chromium`. В Docker обязательно добавьте `RUN playwright install --with-deps chromium`.
2. В `.env` укажите:
  ```dotenv
  IG_COOKIES_AUTO_REFRESH=true
  IG_LOGIN=ваш_логин
  IG_PASSWORD=ваш_пароль
  # по желанию: IG_COOKIES_PATH=/app/instagram_cookies.txt
  # по желанию: IG_2FA_BACKUP_CODES=code1,code2
  ```
3. Перезапустите приложение. При первом запуске поднимется headless Chromium, выполнит вход на `instagram.com`, сохранит cookies в `IG_COOKIES_PATH` и автоматически пропишет путь в `YTDLP_COOKIES_FILE`.
4. Раз в `IG_COOKIES_REFRESH_INTERVAL_HOURS` часов (по умолчанию 6) бот повторяет вход, чтобы избежать протухания cookies. Если Instagram запросит 2FA, бот запишет это в логи; добавьте резервные коды или выполните ручной логин, чтобы разблокировать процесс.

Состояние обновления отражается в логах и health-дашборде админки (последнее успешное время, ошибки, причина автоперезапуска).

## Кеширование скачанных видео

Чтобы не ждать повторное скачивание крупных рилсов, бот записывает финальные MP4 в локальный кэш и переиспользует их, если ссылка запрашивается снова в течение `VIDEO_CACHE_TTL_SECONDS` (по умолчанию 1 час).

- В `.env` параметры уже включены (`VIDEO_CACHE_ENABLED=true`). При необходимости можно увеличить `VIDEO_CACHE_MAX_ITEMS` или изменить директорию (`VIDEO_CACHE_DIR=/app/video_cache`).
- Повторные скачивания теперь происходят мгновенно: бот копирует файл из кэша в личную временную папку пользователя и сразу начинает отправку в Telegram.
- Состояние кэша (включён/выкл, количество попаданий/промахов, время последнего сохранения) видно в блоке Health админ-панели.

Если дисковое пространство ограничено, уменьшите `VIDEO_CACHE_MAX_ITEMS` или отключите кэш, установив `VIDEO_CACHE_ENABLED=false`.

## CI и автоматические проверки

GitHub Actions workflow `.github/workflows/ci.yml` запускается на каждом push/pull request и выполняет:

- базовую статическую проверку (`ruff` с критичными правилами E/F);
- установку зависимостей и прогон `python -m unittest discover -s tests` через `make test`;
- выгрузку `test.log` в артефакты для последующего анализа.

Локально тот же сценарий можно повторить командой `make test` либо `python -m unittest`. Следите за
актуальностью `.env` при прогоне тестов: токен можно оставить пустым, но файл должен существовать.

## Режимы ограничения доступа

Бот поддерживает несколько режимов для ограничения доступа:

### 1. Whitelist режим (только авторизованные пользователи)

Разрешить загружать видео только конкретным пользователям:

```bash
export WHITELIST_MODE=true
export ALLOWED_USER_IDS="123456789,987654321,111111111"
python main.py
```

Или через переменную окружения в Docker:
```yaml
environment:
  WHITELIST_MODE: "true"
  ALLOWED_USER_IDS: "123456789,987654321,111111111"
```

**Как найти свой User ID:**
1. Напишите боту сообщение
2. Посмотрите логи или используйте Sentry для просмотра ID

### 2. Admin-only режим (только администраторы)

Разрешить загружать видео только администраторам:

```bash
export ADMIN_ONLY=true
python main.py
```

В группах/каналах проверяется, что пользователь является администратором.
Для приватных чатов используется список `ADMIN_USER_IDS`.

Дополнительно можно указать своих администраторов:
```bash
export ADMIN_ONLY=true
export ADMIN_USER_IDS="123456789,987654321"
python main.py
```

### 3. Комбинированный режим

Можно использовать оба режима одновременно:
```bash
export WHITELIST_MODE=true
export ALLOWED_USER_IDS="123456789,987654321"
export ADMIN_ONLY=true
export ADMIN_USER_IDS="111111111"
python main.py
```

В этом случае пользователь должен быть И в whitelist, И администратором.

### 4. Без ограничений (по умолчанию)

Если оба режима отключены (или не установлены), бот доступен всем:
```bash
python main.py
```

## Безопасность и борьба со злоупотреблениями

- Все входящие ссылки проходят проверку схемы и хоста, чтобы предотвратить SSRF (блокируются `localhost`, приватные подсети и нестандартные протоколы).
- Callback запросы из групп ограничиваются по чату (`CALLBACK_CHAT_COOLDOWN_SECONDS`) и глобально (`CALLBACK_GLOBAL_MAX_CALLS` в окне `CALLBACK_GLOBAL_WINDOW_SECONDS`), поэтому единичный чат не сможет «зафлудить» бот.
- При наличии `MEDIA_SCAN_COMMAND` каждый файл прогоняется через внешний сканер (например, `clamscan`). Заражённые или подозрительные файлы блокируются до отправки в Telegram.

Эти меры дополняют whitelist/admin режимы и помогают удерживать бот в безопасном состоянии даже при высокой нагрузке в группах.

## История загрузок и админ-панель

Бот может сохранять историю всех загрузок в SQLite БД и предоставлять админ-панель со статистикой.

### Включение истории

История включена по умолчанию. Чтобы отключить:
```bash
export ENABLE_HISTORY=false
python main.py
```

### Команды админ-панели

Следующие команды доступны администраторам (указаны в `ADMIN_USER_IDS` или админам групп):

#### `/stats` — общая статистика
Показывает:
- Всего загрузок (успешных и ошибок)
- Общий объём загруженных данных (MB/GB)
- Количество уникальных пользователей

#### `/top_users` — топ 10 пользователей
Показывает пользователей по количеству загрузок:
- Имя пользователя
- Количество загрузок и ошибок
- Объём загруженных данных

#### `/platform_stats` — статистика по платформам
Показывает статистику для каждой платформы (YouTube, TikTok, Instagram):
- Количество загрузок
- Объём данных
- Количество ошибок

#### `/my_stats` — ваша личная статистика
Доступна всем пользователям. Показывает:
- Количество ваших загрузок
- Объём загруженных данных
- Дата первой и последней загрузки

#### `/recent` — последние 15 загрузок
Только для администраторов. Показывает последние загрузки со статусом, платформой и размером файла.

### Веб-админка

Помимо Telegram-команд можно включить отдельную HTML-панель с расширенной статистикой.

1. В `.env` включите панель и задайте адрес:
  ```bash
  ADMIN_PANEL_ENABLED=true
  ADMIN_PANEL_HOST=0.0.0.0
  ADMIN_PANEL_PORT=8090
  ```
2. Выберите режим авторизации:
  - **Один токен.** Задайте `ADMIN_PANEL_TOKEN=supersecret` и делитесь им со всеми администраторами.
  - **Несколько админов.** Задайте `ADMIN_PANEL_ADMINS="oleg|Олег:token1,irina|Ирина:token2"`. Первый вход по `?token=` или заголовку `X-Admin-Token` выдаёт подписанную cookie, дальше логин не нужен. Опционально задайте `ADMIN_PANEL_SESSION_SECRET` (строка >= 32 символов) и `ADMIN_PANEL_SESSION_TTL_SECONDS` (например, `28800`), чтобы контролировать подпись и срок действия сессий.

3. Запустите бота как обычно. При поднятии появится сервер на `http://127.0.0.1:8090/admin` (или вашем хосте/порту).
4. В простом режиме добавляйте `?token=...` или заголовок `X-Admin-Token`. В многоадминном режиме токен нужен только один раз, cookie продлевается автоматически; выйти можно по `http://host:port/admin?logout=1`.

> Railway / Render: выставьте `ADMIN_PANEL_HOST=0.0.0.0` и используйте порт платформы (`ADMIN_PANEL_PORT=$PORT`), чтобы панель была доступна снаружи.

На странице показываются:
- карточки с основными метриками (загрузки, ошибки, общий объём данных);
- таблица чатов с поиском и сортировкой по активности/объёму/ошибкам;
- таблица топа пользователей;
- разбивка по платформам;
- последние 20 загрузок с размерами и статусами;
- блок очереди скачиваний: активные задачи, ожидающие подтверждения ссылки и набор действий (отменить загрузки пользователя, сбросить pending-токен, очистить очередь);
- свежие ошибки из файла `LOG_FILE`.
- мини-дашборд healthcheck (статус, аптайм, counters/gauges из `/metrics`).

Форма в шапке позволяет фильтровать статистику по `chat_id`, искать чат по названию и переключать сортировку всех разделов. Блок очереди обновляется вместе со сводкой: можно мгновенно отменить зависшие загрузки или очистить pending-очередь прямо из браузера. Панель работает только при включённой истории (`ENABLE_HISTORY=true`). Health-блок отображается, если `HEALTHCHECK_ENABLED=true`. В многоадминном режиме в шапке показывается имя вошедшего администратора.

Чтобы блок ошибок заполнялся, укажите `LOG_FILE` на реальный путь (например, `/app/logs/bot.log` в Docker) и убедитесь, что у процесса есть права записи.

### Примеры использования

**Запуск с админ-панелью:**
```bash
export ENABLE_HISTORY=true
export ADMIN_USER_IDS="123456789,987654321"
python main.py
```

**Отключение истории:**
```bash
export ENABLE_HISTORY=false
python main.py
```

**Настройка удаления старых записей (по умолчанию 30 дней):**
```bash
export CLEANUP_OLD_RECORDS_DAYS=60
python main.py
```

### VPS (systemd)
Создайте systemd unit:
```
[Unit]
Description=Telegram Video Downloader Bot
After=network.target

[Service]
User=youruser
WorkingDirectory=/home/youruser/project
Environment=TELEGRAM_BOT_TOKEN=ВАШ_TOKEN
Environment=WHITELIST_MODE=false
Environment=ADMIN_ONLY=false
ExecStart=/home/youruser/venv/bin/python /home/youruser/project/main.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```
Затем:
```
sudo systemctl daemon-reload
sudo systemctl enable tgdownloader
sudo systemctl start tgdownloader
sudo journalctl -u tgdownloader -f
```

## Советы по безопасности
1. **Токен**: храните `TELEGRAM_BOT_TOKEN` как секрет (переменная окружения, Secret в Railway/Render). Никогда не коммитите токен в git.
2. **Ограничение доступа**:
   - Если бот будет в группе — настройте права (например, только админы могут удалять сообщения).
   - При необходимости — реализуйте белый список user_id в `config.py` и проверку перед скачиванием.
3. **Логи**: не логируйте токен и длинные личные данные.
4. **Обновление yt-dlp**: периодически обновляйте `yt-dlp`.
5. **Ограничение размера и времени**: вы уже ограничили размер (2GB) и можно настроить `DOWNLOAD_TIMEOUT_SECONDS`.
6. **Ограничение нагрузки**: подумайте о бэкенде очередей (Redis / Celery) если ожидается много пользователей; MVP использует простой в-памяти лимит.

## Зависимости
- aiogram>=3.0.0b7,<4.0.0
- aiohttp>=3.9.0
- yt-dlp>=2023.12.0
- python-dotenv>=1.0.0 (опционально)

## Пример вывода
Пользователь отправляет:
```
/download https://youtu.be/dQw4w9WgXcQ
```

Бот отвечает:
```
Платформа: youtube. Начинаю скачивание... ⏳
```
(через некоторое время отправит видео или сообщение об ошибке)

## Примечания
- Убедитесь, что `yt-dlp` доступен в PATH для процесса, запускающего бота.
- Для больших нагрузок и хранения больших файлов используйте внешнее хранилище или очередь.
