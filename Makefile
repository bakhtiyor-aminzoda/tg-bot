.PHONY: help build run stop logs clean test check-deps update-ytdlp dev

PYTHON := python3
ifneq (,$(wildcard venv/bin/python))
	PYTHON := venv/bin/python
endif

help:
	@echo "Telegram Video Downloader Bot - Доступные команды:"
	@echo ""
	@echo "  make build          - Сборка Docker образа"
	@echo "  make run            - Запуск бота в Docker контейнере"
	@echo "  make stop           - Остановка контейнера"
	@echo "  make logs           - Просмотр логов"
	@echo "  make clean          - Удаление контейнера и очистка"
	@echo "  make check-deps     - Проверка зависимостей"
	@echo "  make update-ytdlp   - Обновить yt-dlp до последней версии"
	@echo "  make check          - Проверить стиль/линтеры"
	@echo "  make fmt            - Отформатировать код ruff formatter'ом"
	@echo "  make dev            - Запуск локально (requires yt-dlp, ffmpeg)"
	@echo ""

build:
	@if command -v docker >/dev/null 2>&1; then \
		echo "📦 Сборка Docker образа..."; \
		docker build -t tg-video-downloader:latest .; \
		echo "✓ Образ собран"; \
	else \
		echo "✗ Docker не установлен"; \
		echo "  Для локальной разработки используйте: make dev"; \
		echo "  Для установки Docker: https://docs.docker.com/get-docker/"; \
		exit 1; \
	fi

run:
	@if command -v docker-compose >/dev/null 2>&1; then \
		echo "🚀 Запуск бота в Docker..."; \
		docker-compose up -d; \
		echo "✓ Бот запущен. Логи:"; \
		docker-compose logs -f; \
	else \
		echo "✗ Docker Compose не установлен"; \
		echo "  Для локальной разработки используйте: make dev"; \
		echo "  Для установки Docker: https://docs.docker.com/get-docker/"; \
		exit 1; \
	fi

stop:
	@if command -v docker-compose >/dev/null 2>&1; then \
		echo "⏹️  Остановка контейнера..."; \
		docker-compose down; \
		echo "✓ Контейнер остановлен"; \
	else \
		echo "✗ Docker Compose не установлен"; \
		exit 1; \
	fi

logs:
	@if command -v docker-compose >/dev/null 2>&1; then \
		echo "📋 Логи бота:"; \
		docker-compose logs -f; \
	else \
		echo "✗ Docker Compose не установлен"; \
		exit 1; \
	fi

clean:
	@if command -v docker-compose >/dev/null 2>&1; then \
		echo "🧹 Очистка Docker ресурсов..."; \
		docker-compose down -v; \
		docker rmi tg-video-downloader:latest 2>/dev/null || true; \
	fi
	@echo "🧹 Очистка локальных файлов..."; \
	rm -rf tmp logs __pycache__ .pytest_cache *.pyc; \
	echo "✓ Очищено"

check-deps:
	@echo "✅ Проверка зависимостей..."
	@bash check_deps.sh

update-ytdlp:
	@echo "🔄 Обновление yt-dlp..."
	@$(PYTHON) update_ytdlp.py

check:
	@echo "🔍 Ruff lint..."
	ruff check .

fmt:
	@echo "🪄 Ruff formatter..."
	ruff format .

test:
	@echo "🧪 Запуск тестов..."
	$(PYTHON) -m unittest discover -s tests -p "test_*.py"

dev:
	@echo "👨‍💻 Запуск локально..."
	$(PYTHON) main.py

.DEFAULT_GOAL := help

