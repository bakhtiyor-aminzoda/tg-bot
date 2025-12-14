from __future__ import annotations

import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from tests.aiogram_stub import ensure_aiogram_stub

ensure_aiogram_stub()

import config
from bot_app import state
from bot_app.handlers import downloads


class DummyStatusMessage:
    def __init__(self, initial_text: str = ""):
        self.deleted = False
        self.edits: list[str] = [initial_text] if initial_text else []
        self.markups: list[object | None] = []

    async def edit_text(self, text: str, reply_markup=None):
        self.edits.append(text)
        self.markups.append(reply_markup)

    async def delete(self):
        self.deleted = True


class DummyMessage:
    def __init__(self, text: str, chat_type: str = "private", chat_id: int = 1, user_id: int = 100):
        self.text = text
        self.caption = None
        self.reply_to_message = None
        self.from_user = types.SimpleNamespace(id=user_id, username="tester")
        self.chat = types.SimpleNamespace(id=chat_id, type=chat_type)
        self._status_messages: list[DummyStatusMessage] = []
        self.deleted = False

    async def reply(self, text: str, **_kwargs):
        status = DummyStatusMessage(text)
        self._status_messages.append(status)
        return status

    async def delete(self):
        self.deleted = True

    @property
    def status_messages(self):
        return self._status_messages


class FakeBot:
    def __init__(self):
        self.sent_videos = []

    async def send_video(self, *args, **kwargs):
        self.sent_videos.append((args, kwargs))


class SmokeFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        state.pending_downloads.clear()
        state.user_active_downloads.clear()
        state.user_last_request_ts.clear()
        self.tempdir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.tempdir.name)
        self.temp_patch = mock.patch.object(config, "TEMP_DIR", self.temp_path)
        self.enable_history_patch = mock.patch.object(config, "ENABLE_HISTORY", False)
        self.temp_patch.start()
        self.enable_history_patch.start()
        self.addCleanup(self.temp_patch.stop)
        self.addCleanup(self.enable_history_patch.stop)

    async def asyncTearDown(self) -> None:
        self.tempdir.cleanup()

    async def test_private_message_triggers_download_flow(self) -> None:
        message = DummyMessage("https://youtube.com/watch?v=test")
        fake_bot = FakeBot()

        async def fake_download(url, tmpdir, timeout, cookies_file=None, **_kwargs):  # noqa: ARG001
            file_path = Path(tmpdir) / "result.mp4"
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_bytes(b"data")
            return file_path

        with mock.patch.object(downloads, "bot", fake_bot), mock.patch(
            "bot_app.handlers.downloads.download_video", fake_download
        ), mock.patch(
            "bot_app.handlers.downloads.is_user_allowed", mock.AsyncMock(return_value=True)
        ), mock.patch(
            "bot_app.handlers.downloads.capture_exception", lambda *args, **kwargs: None
        ):
            await downloads.universal_handler(message)

        self.assertEqual(state.user_active_downloads.get(message.from_user.id), 0)
        self.assertEqual(len(fake_bot.sent_videos), 1)
        self.assertTrue(message.status_messages)
        self.assertIn("✅", message.status_messages[0].edits[-1])
        self.assertIsNotNone(message.status_messages[0].markups[-1])
        self.assertTrue(message.deleted)


if __name__ == "__main__":
    unittest.main()
