# Telegram Video Downloader Bot (MVP)

Бот скачивает видео с YouTube и TikTok и отправляет в Telegram.
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

5. Настройте переменные окружения через `.env`:
```bash
cp .env.example .env
echo "TELEGRAM_BOT_TOKEN=123456:ABCDEF..." >> .env
```
Файл будет автоматически прочитан благодаря `python-dotenv`. При желании можно применять и прямое
`export TELEGRAM_BOT_TOKEN=...` (Windows: `setx TELEGRAM_BOT_TOKEN ...`). Не коммитьте `.env` в git.

6. Запустите бота:
```bash
python main.py
```

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

**Дополнительные переменные окружения** (логирование и Sentry)
- `LOG_FILE` — путь к файлу логов (по умолчанию `/app/logs/bot.log` в Docker). Если задан, бот будет писать ротационные логи в этот файл.
- `LOG_MAX_BYTES` и `LOG_BACKUP_COUNT` — параметры ротации (по умолчанию 10MB и 5 файлов).
- `SENTRY_DSN` — если указан, бот попытается инициализировать Sentry (требует `sentry-sdk` в `requirements.txt`).
- `MAX_GLOBAL_CONCURRENT_DOWNLOADS` — ограничение одновременных загрузок (по умолчанию 4).
- `DOWNLOAD_TIMEOUT` — таймаут скачивания в секундах (по умолчанию 1200 = 20 минут).
- `STRUCTURED_LOGS` — если `true`, включает JSON-логи (подходит для централизованного сбора логов). По умолчанию `false`.
- `HEALTHCHECK_ENABLED` — включает лёгкий HTTP-сервер `/health` (статус) и `/metrics` (снимок внутренних метрик). По умолчанию `true`.
- `HEALTHCHECK_HOST`/`HEALTHCHECK_PORT` — адрес и порт healthcheck-сервера (по умолчанию `0.0.0.0:8080`).

**Пример** (Railway / Render): добавьте `SENTRY_DSN` в секреты проекта и остальные переменные в Environment.

## Мониторинг и healthcheck

- Установите `STRUCTURED_LOGS=true`, чтобы получать JSON-структурированные записи (подойдут для Loki/ELK). Поля включают timestamp, уровень, имя логгера и сообщение.
- При `HEALTHCHECK_ENABLED=true` бот поднимает фоновый aiohttp-сервер с двумя endpoint'ами:
  - `GET /health` — возвращает `{ "status": "ok" }`, пригодно для k8s liveness/readiness probe.
  - `GET /metrics` — отдаёт JSON-снимок внутренних счётчиков и gauge-метрик (количество вызовов, кастомные показатели).
- Настройте `HEALTHCHECK_HOST` и `HEALTHCHECK_PORT`, чтобы ограничить доступ (например, `127.0.0.1:9000` за reverse-proxy).

Оба механизма работают независимо от Sentry и не блокируют основной event loop.

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
