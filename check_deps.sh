#!/bin/bash
# Скрипт для проверки зависимостей бота

echo "=== Проверка окружения Telegram Video Downloader Bot ==="
echo ""

# Проверка Python
echo "✓ Python:"
python3 --version || echo "✗ Python не установлен"
echo ""

# Проверка ffmpeg
echo "✓ FFmpeg:"
ffmpeg -version 2>/dev/null | head -n 1 || echo "✗ FFmpeg не установлен"
echo ""

# Проверка ffprobe
echo "✓ FFprobe:"
ffprobe -version 2>/dev/null | head -n 1 || echo "✗ FFprobe не установлен"
echo ""

# Проверка yt-dlp
echo "✓ yt-dlp:"
python3 -c "import yt_dlp; print(yt_dlp.__version__)" 2>/dev/null || echo "✗ yt-dlp не установлен"
echo ""

# Проверка aiogram
echo "✓ aiogram:"
python3 -c "import aiogram; print(aiogram.__version__)" 2>/dev/null || echo "✗ aiogram не установлен"
echo ""

# Проверка sentry-sdk (опционально)
echo "✓ sentry-sdk (опционально):"
python3 -c "import sentry_sdk; print(sentry_sdk.__version__)" 2>/dev/null || echo "⊘ sentry-sdk не установлен (опционально)"
echo ""

# Проверка TELEGRAM_BOT_TOKEN
echo "✓ Переменные окружения:"
if [ -z "$TELEGRAM_BOT_TOKEN" ]; then
    echo "⊘ TELEGRAM_BOT_TOKEN не установлен"
else
    echo "✓ TELEGRAM_BOT_TOKEN установлен"
fi
echo ""

echo "=== Проверка завершена ==="
