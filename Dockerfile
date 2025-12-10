# Dockerfile — для Railway / Docker Hub / Render
# Многоэтапная сборка для надёжного декодирования видео
FROM python:3.11-slim

# Устанавливаем зависимости ОС (ffmpeg, требуемый для yt-dlp + git для некоторых источников)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      ffmpeg \
      git \
      curl \
      ca-certificates \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

WORKDIR /app

# Копируем только requirements.txt для кэширования слоёв Docker
COPY requirements.txt .

# Обновляем pip и устанавливаем Python зависимости
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# Копируем весь исходный код проекта
COPY . .

# Создаём необходимые каталоги
RUN mkdir -p /app/tmp /app/logs && \
    chmod 755 /app/tmp /app/logs

# Проверим, что ffmpeg доступен
RUN ffmpeg -version | head -n 1

# Переменные окружения
ENV PYTHONUNBUFFERED=1 \
    LOG_FILE=/app/logs/bot.log \
    DOWNLOAD_TIMEOUT=1200 \
    MAX_GLOBAL_CONCURRENT_DOWNLOADS=4

# Health check (проверяет, что бот работает)
# Примечание: это базовая проверка; для полного health check нужен дополнительный механизм
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/health 2>/dev/null || exit 1 || true

# Команда запуска бота
CMD ["python", "main.py"]
