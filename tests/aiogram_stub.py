"""Helper for providing a lightweight aiogram stub during unit tests."""

from __future__ import annotations

import asyncio
import sys
import types


def ensure_aiogram_stub() -> None:
    """Register minimal aiogram modules if the real package is unavailable."""
    if "aiogram" in sys.modules:
        return

    aiogram_module = types.ModuleType("aiogram")
    aiogram_types_module = types.ModuleType("aiogram.types")
    aiogram_filters_module = types.ModuleType("aiogram.filters")
    aiogram_exceptions_module = types.ModuleType("aiogram.exceptions")

    class DummyBot:
        def __init__(self, token: str | None = None):
            self.token = token

            async def close() -> None:
                return None

            self.session = types.SimpleNamespace(close=close)

        async def send_video(self, *args, **kwargs):  # pragma: no cover - overridden in tests
            return None

        async def send_document(self, *args, **kwargs):  # pragma: no cover - overridden in tests
            return None

        async def delete_message(self, *args, **kwargs):  # pragma: no cover - overridden in tests
            return None

        async def get_chat_administrators(self, *_args, **_kwargs):
            return []

    class DummyDispatcher:
        def __init__(self):
            self._handlers = {}

        def message(self, *args, **kwargs):
            return self._identity

        def callback_query(self, *args, **kwargs):
            return self._identity

        def my_chat_member(self, *args, **kwargs):
            return self._identity

        async def start_polling(self, *args, **kwargs):  # pragma: no cover - not used in tests
            return None

        def resolve_used_update_types(self):  # pragma: no cover - not used in tests
            return []

        @staticmethod
        def _identity(func):
            return func

    class DummyCommand:
        def __init__(self, *args, **kwargs):  # pragma: no cover - used for type compatibility
            pass

    class DummyFSInputFile:
        def __init__(self, path: str | bytes):
            self.path = path

    class DummyInlineKeyboardButton:
        def __init__(self, text: str, callback_data: str | None = None, url: str | None = None):
            self.text = text
            self.callback_data = callback_data
            self.url = url

    class DummyInlineKeyboardMarkup:
        def __init__(self, inline_keyboard):
            self.inline_keyboard = inline_keyboard

    class DummyTelegramBadRequest(Exception):
        def __init__(self, *args, **_kwargs):
            super().__init__(*args)

    class DummyTelegramAPIError(Exception):
        def __init__(self, message: str = "", status_code: int | None = None):
            super().__init__(message)
            self.status_code = status_code

    aiogram_module.Bot = DummyBot
    aiogram_module.Dispatcher = DummyDispatcher
    aiogram_module.types = aiogram_types_module
    aiogram_module.filters = aiogram_filters_module

    aiogram_types_module.FSInputFile = DummyFSInputFile
    aiogram_types_module.InlineKeyboardButton = DummyInlineKeyboardButton
    aiogram_types_module.InlineKeyboardMarkup = DummyInlineKeyboardMarkup

    aiogram_filters_module.Command = DummyCommand

    aiogram_exceptions_module.TelegramBadRequest = DummyTelegramBadRequest
    aiogram_exceptions_module.TelegramAPIError = DummyTelegramAPIError

    sys.modules["aiogram"] = aiogram_module
    sys.modules["aiogram.types"] = aiogram_types_module
    sys.modules["aiogram.filters"] = aiogram_filters_module
    sys.modules["aiogram.exceptions"] = aiogram_exceptions_module