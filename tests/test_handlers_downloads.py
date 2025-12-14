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
from bot_app.ui.i18n import translate


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



class DownloadsHandlerTests(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        state.user_active_downloads.clear()
        state.user_last_request_ts.clear()
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
                request_id="cooldown",
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
                request_id="limit",
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
                request_id="fallback",
            )

        dummy_bot.send_video.assert_awaited_once()
        dummy_bot.send_document.assert_awaited_once()

    async def test_photo_flow_uses_send_photo_and_caption(self) -> None:
        message = DummyMessage(user_id=88, text="/download https://instagram.com/p/demo")
        photo_path = Path(self.tmpdir.name) / "media.jpg"
        photo_path.write_bytes(b"img")

        dummy_bot = SimpleNamespace(
            send_photo=mock.AsyncMock(),
            send_video=mock.AsyncMock(),
            send_document=mock.AsyncMock(),
        )

        with (
            mock.patch.object(downloads, "bot", dummy_bot),
            mock.patch.object(downloads, "detect_platform", return_value="instagram"),
            mock.patch.object(downloads, "is_user_allowed", new=mock.AsyncMock(return_value=True)),
            mock.patch.object(downloads, "ensure_safe_public_url", return_value=None),
            mock.patch.object(downloads, "ensure_file_is_safe", new=mock.AsyncMock()),
            mock.patch.object(downloads, "download_video", new=mock.AsyncMock(return_value=photo_path)),
            mock.patch.object(downloads, "global_download_semaphore", asyncio.Semaphore(1)),
        ):
            await downloads._process_download_flow(
                message,
                "https://instagram.com/p/demo",
                locale="ru",
                request_id="photo",
            )

        dummy_bot.send_photo.assert_awaited_once()
        dummy_bot.send_video.assert_not_called()
        caption = dummy_bot.send_photo.await_args.kwargs["caption"]
        expected_caption = translate("download.caption.photo", "ru", platform="Instagram")
        self.assertEqual(caption, expected_caption)

    async def test_photo_flow_document_fallback_uses_localized_caption(self) -> None:
        message = DummyMessage(user_id=89, text="/download https://instagram.com/p/demo2")
        photo_path = Path(self.tmpdir.name) / "media2.jpg"
        photo_path.write_bytes(b"img")

        dummy_bot = SimpleNamespace(
            send_photo=mock.AsyncMock(side_effect=TelegramBadRequest(method="sendPhoto", message="fail")),
            send_video=mock.AsyncMock(),
            send_document=mock.AsyncMock(),
        )

        with (
            mock.patch.object(downloads, "bot", dummy_bot),
            mock.patch.object(downloads, "detect_platform", return_value="instagram"),
            mock.patch.object(downloads, "is_user_allowed", new=mock.AsyncMock(return_value=True)),
            mock.patch.object(downloads, "ensure_safe_public_url", return_value=None),
            mock.patch.object(downloads, "ensure_file_is_safe", new=mock.AsyncMock()),
            mock.patch.object(downloads, "download_video", new=mock.AsyncMock(return_value=photo_path)),
            mock.patch.object(downloads, "global_download_semaphore", asyncio.Semaphore(1)),
            mock.patch.object(downloads, "capture_exception"),
        ):
            await downloads._process_download_flow(
                message,
                "https://instagram.com/p/demo2",
                locale="ru",
                request_id="photo-fallback",
            )

        dummy_bot.send_photo.assert_awaited_once()
        dummy_bot.send_document.assert_awaited_once()
        doc_caption = dummy_bot.send_document.await_args.kwargs["caption"]
        expected_doc_caption = translate(
            "download.document_caption.photo",
            "ru",
            platform="Instagram",
        )
        self.assertEqual(doc_caption, expected_doc_caption)


if __name__ == "__main__":
    import unittest

    unittest.main()
