from __future__ import annotations

import asyncio
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

from tests.aiogram_stub import ensure_aiogram_stub

ensure_aiogram_stub()

import config
from bot_app import state
from bot_app.handlers import callbacks


class DummyStatusMessage:
    def __init__(self, initial_text: str = ""):
        self.edits: list[str] = [initial_text] if initial_text else []
        self.markups: list[object | None] = []
        self.deleted = False

    async def edit_text(self, text: str, reply_markup=None):
        self.edits.append(text)
        self.markups.append(reply_markup)

    async def delete(self):
        self.deleted = True


class DummyMessage:
    def __init__(self, chat_type: str = "group", chat_id: int = 100):
        self.chat = types.SimpleNamespace(id=chat_id, type=chat_type)
        self.deleted = False
        self.status_messages: list[DummyStatusMessage] = []

    async def reply(self, text: str, **_kwargs):
        status = DummyStatusMessage(text)
        self.status_messages.append(status)
        return status

    async def delete(self):
        self.deleted = True


class DummyCallback:
    def __init__(self, token: str, message: DummyMessage | None = None, uid: int = 42):
        self.data = f"download:{token}"
        self.from_user = types.SimpleNamespace(id=uid, username="tester")
        self.message = message or DummyMessage()
        self.answers: list[dict[str, object]] = []

    async def answer(self, text: str, show_alert: bool = False):
        self.answers.append({"text": text, "show_alert": show_alert})


class FakeBot:
    def __init__(self):
        self.sent_videos = []
        self.sent_documents = []
        self.deleted_messages = []

    async def send_video(self, *args, **kwargs):
        self.sent_videos.append((args, kwargs))

    async def send_document(self, *args, **kwargs):
        self.sent_documents.append((args, kwargs))

    async def delete_message(self, chat_id: int, message_id: int):
        self.deleted_messages.append((chat_id, message_id))


class CallbackHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        state.pending_downloads.clear()
        state.user_active_downloads.clear()
        state.user_last_request_ts.clear()
        self.tempdir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.tempdir.name)
        self.temp_patch = mock.patch.object(config, "TEMP_DIR", self.temp_path)
        self.temp_patch.start()
        self.addCleanup(self.temp_patch.stop)

    async def asyncTearDown(self) -> None:
        self.tempdir.cleanup()

    async def test_callback_rejects_expired_token(self) -> None:
        token = "expired"
        state.pending_downloads[token] = {
            "url": "http://example.com",
            "ts": time.time() - state.PENDING_TOKEN_TTL - 1,
        }
        callback = DummyCallback(token)

        await callbacks.handle_download_callback(callback)

        self.assertTrue(callback.answers)
        self.assertTrue(any("истёк" in answer["text"] for answer in callback.answers))
        self.assertNotIn(token, state.pending_downloads)

    async def test_callback_processes_valid_download(self) -> None:
        token = "valid"
        callback = DummyCallback(token)
        state.pending_downloads[token] = {
            "url": "https://youtu.be/example",
            "ts": time.time(),
            "source_chat_id": callback.message.chat.id,
            "source_message_id": 555,
        }
        fake_bot = FakeBot()

        async def fake_download(url, tmpdir, timeout, cookies_file=None):  # noqa: ARG001
            file_path = Path(tmpdir) / "result.mp4"
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_bytes(b"data")
            return file_path

        fake_semaphore = asyncio.Semaphore(1)

        with mock.patch.object(callbacks, "bot", fake_bot), mock.patch(
            "bot_app.handlers.callbacks.download_video", fake_download
        ), mock.patch(
            "bot_app.handlers.callbacks.is_user_allowed", mock.AsyncMock(return_value=True)
        ), mock.patch(
            "bot_app.handlers.callbacks.capture_exception", lambda *args, **kwargs: None
        ), mock.patch.object(
            callbacks, "global_download_semaphore", fake_semaphore
        ):
            await callbacks.handle_download_callback(callback)

        self.assertFalse(state.pending_downloads)
        self.assertEqual(state.user_active_downloads.get(callback.from_user.id), 0)
        self.assertEqual(len(fake_bot.sent_videos), 1)
        self.assertTrue(callback.message.deleted)
        status_msg = callback.message.status_messages[0]
        self.assertIn("✅", status_msg.edits[-1])
        self.assertIsNotNone(status_msg.markups[-1])
        self.assertEqual(fake_bot.deleted_messages, [(callback.message.chat.id, 555)])


if __name__ == "__main__":
    unittest.main()
