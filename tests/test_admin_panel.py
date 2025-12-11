import types
import unittest
from unittest import mock

from tests.aiogram_stub import ensure_aiogram_stub

ensure_aiogram_stub()

import admin_panel_clean as panel


class DummyMessage:
    def __init__(self, chat_type="private", chat_id=1, title="Chat", user_id=42, username="tester"):
        self.from_user = types.SimpleNamespace(id=user_id, username=username, first_name="Test", last_name="User")
        self.chat = types.SimpleNamespace(type=chat_type, id=chat_id, title=title)
        self._replies = []

    async def reply(self, text, **kwargs):
        self._replies.append((text, kwargs))

    @property
    def replies(self):
        return self._replies


class AdminPanelTests(unittest.IsolatedAsyncioTestCase):
    async def test_cmd_stats_private(self):
        msg = DummyMessage(chat_type="private")

        with mock.patch.object(
            panel.stats_service,
            "get_summary",
            return_value={
                "total_downloads": 10,
                "successful_downloads": 8,
                "failed_downloads": 2,
                "total_bytes": 1024 * 1024,
                "unique_users": 1,
            },
        ):
            await panel.cmd_stats(msg)

        self.assertEqual(len(msg.replies), 1)
        text, kwargs = msg.replies[0]
        self.assertIn("диалога", text.lower())
        self.assertEqual(kwargs.get("parse_mode"), "HTML")

    async def test_cmd_top_users_html_escape(self):
        msg = DummyMessage(chat_type="private")

        users = [
            {
                "user_id": 7,
                "username": "evil<script>",
                "total_downloads": 5,
                "failed_count": 1,
                "total_bytes": 2 * 1024 * 1024,
            }
        ]

        with mock.patch.object(panel.stats_service, "get_top_users", return_value=users):
            await panel.cmd_top_users(msg)

        self.assertEqual(len(msg.replies), 1)
        text, _ = msg.replies[0]
        self.assertIn("&lt;script&gt;", text)
        self.assertIn("2.0 MB", text)

    async def test_cmd_stats_group_uses_group_summary(self):
        msg = DummyMessage(chat_type="group", chat_id=555, title="Группа")
        recorder = {}

        def fake_group_stats(chat_id):
            recorder["chat_id"] = chat_id
            return {
                "total_downloads": 1,
                "successful_downloads": 1,
                "failed_downloads": 0,
                "total_bytes": 0,
                "unique_users": 1,
            }

        with mock.patch.object(panel.stats_service, "get_summary", side_effect=fake_group_stats):
            await panel.cmd_stats(msg)

        self.assertEqual(recorder["chat_id"], 555)
        self.assertEqual(len(msg.replies), 1)
        text, _ = msg.replies[0]
        self.assertIn("группе", text.lower())


if __name__ == "__main__":
    unittest.main()
