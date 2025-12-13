import time
import unittest

from bot_app import admin_runtime, state


class AdminRuntimeTests(unittest.TestCase):
    def setUp(self):
        state.user_active_downloads.clear()
        state.user_last_request_ts.clear()
        state.pending_downloads.clear()

    def tearDown(self):
        state.user_active_downloads.clear()
        state.user_last_request_ts.clear()
        state.pending_downloads.clear()

    def test_snapshot_includes_active_and_pending(self):
        state.user_active_downloads[123] = 2
        state.user_last_request_ts[123] = time.time() - 30
        state.pending_downloads["tok-1"] = {
            "ts": time.time() - 5,
            "initiator_id": 999,
            "source_chat_id": -1001,
        }

        snapshot = admin_runtime.get_runtime_snapshot(pending_limit=5, active_limit=5)

        self.assertEqual(snapshot["active_total"], 2)
        self.assertEqual(len(snapshot["active_rows"]), 1)
        self.assertEqual(snapshot["active_rows"][0]["user_id"], 123)
        self.assertEqual(snapshot["pending_total"], 1)
        self.assertEqual(snapshot["pending_rows"][0]["token"], "tok-1")

    def test_cancel_user_downloads(self):
        state.user_active_downloads[1] = 3
        state.user_last_request_ts[1] = time.time()
        self.assertTrue(admin_runtime.cancel_user_downloads(1))
        self.assertEqual(state.user_active_downloads[1], 0)
        self.assertFalse(admin_runtime.cancel_user_downloads(999))

    def test_flush_pending_tokens(self):
        state.pending_downloads["a"] = {"ts": time.time()}
        state.pending_downloads["b"] = {"ts": time.time()}
        cleared = admin_runtime.flush_pending_tokens()
        self.assertEqual(cleared, 2)
        self.assertEqual(state.pending_downloads, {})


if __name__ == "__main__":
    unittest.main()
