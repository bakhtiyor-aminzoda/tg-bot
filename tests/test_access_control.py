import types
import unittest

from tests.aiogram_stub import ensure_aiogram_stub

ensure_aiogram_stub()

import config
from utils import access_control


class DummyBot:
    def __init__(self, status_map=None):
        self.status_map = status_map or {}

    async def get_chat_member(self, chat_id, user_id):
        status = self.status_map.get((chat_id, user_id), "member")
        return types.SimpleNamespace(status=status)


class DummyMessage:
    def __init__(self, user_id=1, chat_type="private", chat_id=100, username="user", bot=None):
        self.from_user = types.SimpleNamespace(id=user_id, username=username)
        self.chat = types.SimpleNamespace(type=chat_type, id=chat_id)
        self.bot = bot or DummyBot()


class AccessControlTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._orig_whitelist = config.WHITELIST_MODE
        self._orig_admin_only = config.ADMIN_ONLY
        self._orig_allowed = set(config.ALLOWED_USER_IDS)
        self._orig_admins = set(config.ADMIN_USER_IDS)

    def tearDown(self):
        config.WHITELIST_MODE = self._orig_whitelist
        config.ADMIN_ONLY = self._orig_admin_only
        config.ALLOWED_USER_IDS = set(self._orig_allowed)
        config.ADMIN_USER_IDS = set(self._orig_admins)

    async def test_without_restrictions_allows_everyone(self):
        config.WHITELIST_MODE = False
        config.ADMIN_ONLY = False
        msg = DummyMessage()
        self.assertTrue(await access_control.is_user_allowed(msg))

    async def test_whitelist_blocks_unknown_user(self):
        config.WHITELIST_MODE = True
        config.ADMIN_ONLY = False
        config.ALLOWED_USER_IDS = set()

        msg = DummyMessage(user_id=99)
        self.assertFalse(await access_control.is_user_allowed(msg))

        config.ALLOWED_USER_IDS = {99}
        self.assertTrue(await access_control.is_user_allowed(msg))

    async def test_admin_only_checks_chat_admins(self):
        config.WHITELIST_MODE = False
        config.ADMIN_ONLY = True
        config.ADMIN_USER_IDS = set()

        bot = DummyBot(status_map={(200, 5): "administrator"})
        group_message = DummyMessage(user_id=5, chat_type="group", chat_id=200, bot=bot)
        self.assertTrue(await access_control.is_user_allowed(group_message))

        non_admin_msg = DummyMessage(user_id=6, chat_type="group", chat_id=200, bot=bot)
        self.assertFalse(await access_control.is_user_allowed(non_admin_msg))

        config.ADMIN_USER_IDS = {6}
        self.assertTrue(await access_control.is_user_allowed(non_admin_msg))


if __name__ == "__main__":
    unittest.main()
