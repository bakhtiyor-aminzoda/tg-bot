# Dockerfile — для Railway / Docker Hub / Render
FROM python:3.11-slim

# Установим зависимости ОС (ffmpeg + инструменты)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      ffmpeg \
      git \
      build-essential \
      ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Скопируем только файлы зависимостей сначала для кэширования слоёв
COPY requirements.txt .

# Установим Python зависимости
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# Копируем весь проект
COPY . .

# Убедимся, что tmp папка существует
RUN mkdir -p /app/tmp

# Переменные среды можно переопределить в Railway UI
ENV PYTHONUNBUFFERED=1

# Команда запуска
CMD ["python", "main.py"]
