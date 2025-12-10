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

5. Задайте токен:
```bash
export TELEGRAM_BOT_TOKEN="123456:ABCDEF..."   # Linux / macOS
# setx TELEGRAM_BOT_TOKEN "123456:ABCDEF..."   # Windows (перезапуск терминала)
```
Или замените `config.TOKEN` (не рекомендуется) или используйте `.env` с python-dotenv.

6. Запустите бота:
```bash
python main.py
```

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
### Railway / Render
- Подключите репозиторий.
- В переменных окружения (Environment) добавьте TELEGRAM_BOT_TOKEN.
- Убедитесь, что requirements.txt содержит yt-dlp.
- Start Command: `python main.py`.

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
