from __future__ import annotations

import asyncio
import tempfile
import time
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, mock

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup

from bot_app.handlers import downloads
from bot_app import state
from bot_app.runtime import logger as runtime_logger


class DummyStatusMessage:
    def __init__(self, text: str = "") -> None:
        self.edit_calls: list[str] = [text]
        self.deleted = False

    async def edit_text(self, text: str, **kwargs):
        self.edit_calls.append(text)
        return self

    async def delete(self):
        self.deleted = True


class DummyMessage:
    def __init__(self, user_id: int, chat_type: str = "private", text: str = "") -> None:
        self.chat = SimpleNamespace(id=chat_type == "group" and -1000 or 1234, type=chat_type)
        self.from_user = SimpleNamespace(id=user_id, language_code="ru", first_name="Tester")
        self.text = text
        self.caption = None
        self.reply_to_message = None
        self.replies: list[dict] = []
        self.deleted = False

    async def reply(self, text: str, **kwargs):
        status = DummyStatusMessage(text)
        self.replies.append({"text": text, "kwargs": kwargs, "status": status})
        return status

    async def delete(self):
        self.deleted = True
        return True


class DummyCallback:
    def __init__(self, token: str, slug: str, user_id: int = 1, data_prefix: str = "quality") -> None:
        self.data = f"{data_prefix}:{token}:{slug}"
        self.from_user = SimpleNamespace(id=user_id, language_code="ru")
        self.message = DummyStatusMessage()
        self.answers: list[dict] = []

    async def answer(self, text: str, show_alert: bool = False):
        self.answers.append({"text": text, "show_alert": show_alert})


class DownloadsHandlerTests(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        state.user_active_downloads.clear()
        state.user_last_request_ts.clear()
        state.pending_quality_requests.clear()
        state.pending_downloads.clear()
        state.chat_last_callback_ts.clear()
        state.global_callback_events.clear()
        self._history_patch = mock.patch.object(downloads.config, "ENABLE_HISTORY", False)
        self._history_patch.start()
        self._runtime_log_level = runtime_logger.level
        runtime_logger.setLevel(logging.ERROR)

    def tearDown(self) -> None:
        self._history_patch.stop()
        runtime_logger.setLevel(self._runtime_log_level)
        self.tmpdir.cleanup()

    async def test_audio_preset_uses_send_audio(self) -> None:
        message = DummyMessage(user_id=42, text="/download https://youtu.be/demo")
        audio_path = Path(self.tmpdir.name) / "audio.m4a"
        audio_path.write_bytes(b"audio-bytes")

        dummy_bot = SimpleNamespace(
            send_video=mock.AsyncMock(),
            send_audio=mock.AsyncMock(),
            send_document=mock.AsyncMock(),
        )

        async def fake_download(*args, **kwargs):
            return audio_path

        with (
            mock.patch.object(downloads, "bot", dummy_bot),
            mock.patch.object(downloads, "is_user_allowed", new=mock.AsyncMock(return_value=True)),
            mock.patch.object(downloads, "ensure_safe_public_url", return_value=None),
            mock.patch.object(downloads, "ensure_file_is_safe", new=mock.AsyncMock()),
            mock.patch.object(downloads, "download_video", new=mock.AsyncMock(side_effect=fake_download)),
            mock.patch.object(downloads, "global_download_semaphore", asyncio.Semaphore(1)),
            mock.patch.object(downloads.config, "ENABLE_HISTORY", False),
        ):
            await downloads._process_download_flow(
                message,
                "https://youtu.be/demo",
                locale="ru",
                quality_slug="audio",
                request_id="test-audio",
                skip_quality_prompt=True,
            )

        dummy_bot.send_audio.assert_awaited_once()
        dummy_bot.send_video.assert_not_awaited()

    async def test_quality_callback_invokes_process_flow_with_slug(self) -> None:
        token = "tok123"
        restored_message = DummyMessage(user_id=7, text="https://youtu.be/demo")
        dummy_bot = SimpleNamespace()
        restored_message.bot = dummy_bot
        callback = DummyCallback(token=token, slug="audio", user_id=7)

        state.pending_quality_requests[token] = {
            "ts": time.time(),
            "user_id": 7,
            "url": "https://youtu.be/demo",
            "locale": "ru",
            "request_id": "req-1",
            "message_dump": {"dummy": True},
        }

        with (
            mock.patch.object(downloads, "bot", dummy_bot),
            mock.patch.object(downloads, "_process_download_flow", new=mock.AsyncMock()) as process_mock,
            mock.patch(
                "bot_app.handlers.downloads.types.Message.model_validate",
                return_value=restored_message,
            ),
        ):
            await downloads.handle_quality_choice_callback(callback)

        process_mock.assert_awaited_once()
        kwargs = process_mock.await_args.kwargs
        self.assertEqual(kwargs.get("quality_slug"), "audio")
        self.assertTrue(kwargs.get("skip_quality_prompt"))

    async def test_cooldown_path_returns_message_and_skips_download(self) -> None:
        message = DummyMessage(user_id=99, text="/download https://youtu.be/demo")
        url = "https://youtu.be/demo"
        state.user_last_request_ts[99] = time.time()

        with (
            mock.patch.object(downloads, "is_user_allowed", new=mock.AsyncMock(return_value=True)),
            mock.patch.object(downloads, "ensure_safe_public_url", return_value=None),
            mock.patch.object(downloads, "download_video", new=mock.AsyncMock()) as download_mock,
            mock.patch.object(downloads.config, "ENABLE_HISTORY", False),
        ):
            await downloads._process_download_flow(
                message,
                url,
                locale="ru",
                quality_slug="auto",
                request_id="cooldown",
                skip_quality_prompt=True,
            )

        download_mock.assert_not_awaited()
        self.assertTrue(message.replies)
        self.assertIn("Слишком часто", message.replies[0]["text"])

    async def test_group_message_creates_pending_token_and_keyboard(self) -> None:
        message = DummyMessage(user_id=10, chat_type="group", text="https://youtu.be/demo")

        with (
            mock.patch.object(downloads, "is_user_allowed", new=mock.AsyncMock(return_value=True)),
            mock.patch.object(downloads, "ensure_safe_public_url", return_value=None),
            mock.patch.object(downloads, "update_pending_tokens_gauge"),
        ):
            await downloads._process_download_flow(message, message.text, locale="ru")

        self.assertEqual(len(state.pending_downloads), 1)
        payload = next(iter(state.pending_downloads.values()))
        self.assertEqual(payload["url"], message.text)
        self.assertTrue(message.replies)
        markup = message.replies[0]["kwargs"].get("reply_markup")
        self.assertIsInstance(markup, InlineKeyboardMarkup)

    async def test_max_active_downloads_show_limit_message(self) -> None:
        message = DummyMessage(user_id=55, text="/download https://youtu.be/demo")
        state.user_active_downloads[55] = 1

        with (
            mock.patch.object(downloads, "is_user_allowed", new=mock.AsyncMock(return_value=True)),
            mock.patch.object(downloads, "ensure_safe_public_url", return_value=None),
            mock.patch.object(downloads, "download_video", new=mock.AsyncMock()) as download_mock,
            mock.patch.object(downloads.config, "MAX_CONCURRENT_PER_USER", 1),
            mock.patch.object(downloads.config, "ENABLE_HISTORY", False),
        ):
            await downloads._process_download_flow(
                message,
                "https://youtu.be/demo",
                locale="ru",
                quality_slug="auto",
                request_id="limit",
                skip_quality_prompt=True,
            )

        download_mock.assert_not_awaited()
        self.assertTrue(message.replies)
        self.assertIn("активных", message.replies[0]["text"])

    async def test_send_document_fallback_on_video_error(self) -> None:
        message = DummyMessage(user_id=77, text="/download https://youtu.be/demo")
        video_path = Path(self.tmpdir.name) / "video.mp4"
        video_path.write_bytes(b"video")

        dummy_bot = SimpleNamespace(
            send_video=mock.AsyncMock(side_effect=TelegramBadRequest(method="sendVideo", message="fail")),
            send_audio=mock.AsyncMock(),
            send_document=mock.AsyncMock(),
        )

        with (
            mock.patch.object(downloads, "bot", dummy_bot),
            mock.patch.object(downloads, "is_user_allowed", new=mock.AsyncMock(return_value=True)),
            mock.patch.object(downloads, "ensure_safe_public_url", return_value=None),
            mock.patch.object(downloads, "ensure_file_is_safe", new=mock.AsyncMock()),
            mock.patch.object(downloads, "download_video", new=mock.AsyncMock(return_value=video_path)),
            mock.patch.object(downloads, "global_download_semaphore", asyncio.Semaphore(1)),
            mock.patch.object(downloads, "capture_exception"),
        ):
            await downloads._process_download_flow(
                message,
                "https://youtu.be/demo",
                locale="ru",
                quality_slug="auto",
                request_id="fallback",
                skip_quality_prompt=True,
            )

        dummy_bot.send_video.assert_awaited_once()
        dummy_bot.send_document.assert_awaited_once()


if __name__ == "__main__":
    import unittest

    unittest.main()
