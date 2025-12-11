from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from services import video_cache as cache_module


class VideoCacheTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self._prev = {
            "enabled": cache_module.config.VIDEO_CACHE_ENABLED,  # type: ignore[attr-defined]
            "dir": cache_module.config.VIDEO_CACHE_DIR,  # type: ignore[attr-defined]
            "ttl": cache_module.config.VIDEO_CACHE_TTL_SECONDS,  # type: ignore[attr-defined]
            "max": cache_module.config.VIDEO_CACHE_MAX_ITEMS,  # type: ignore[attr-defined]
        }
        cache_module.reset_for_tests()
        cache_module.config.VIDEO_CACHE_ENABLED = True  # type: ignore[attr-defined]
        cache_module.config.VIDEO_CACHE_DIR = self.tmpdir.name  # type: ignore[attr-defined]
        cache_module.config.VIDEO_CACHE_TTL_SECONDS = 3600  # type: ignore[attr-defined]
        cache_module.config.VIDEO_CACHE_MAX_ITEMS = 10  # type: ignore[attr-defined]

    def tearDown(self) -> None:
        cache_module.reset_for_tests()
        cache_module.config.VIDEO_CACHE_ENABLED = self._prev["enabled"]  # type: ignore[attr-defined]
        cache_module.config.VIDEO_CACHE_DIR = self._prev["dir"]  # type: ignore[attr-defined]
        cache_module.config.VIDEO_CACHE_TTL_SECONDS = self._prev["ttl"]  # type: ignore[attr-defined]
        cache_module.config.VIDEO_CACHE_MAX_ITEMS = self._prev["max"]  # type: ignore[attr-defined]
        self.tmpdir.cleanup()

    async def test_store_and_fetch(self) -> None:
        file_dir = Path(self.tmpdir.name) / "work"
        file_dir.mkdir(parents=True, exist_ok=True)
        source = file_dir / "video.mp4"
        source.write_bytes(b"payload")

        await cache_module.store_copy("https://example.com/foo", source)

        out_dir = Path(self.tmpdir.name) / "out"
        result = await cache_module.get_cached_copy("https://example.com/foo", out_dir)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result.exists())
        self.assertEqual(result.read_bytes(), b"payload")

    async def test_expired_entry_returns_none(self) -> None:
        cache_module.config.VIDEO_CACHE_TTL_SECONDS = 0.001  # type: ignore[attr-defined]
        file_dir = Path(self.tmpdir.name) / "work2"
        file_dir.mkdir(parents=True, exist_ok=True)
        source = file_dir / "video2.mp4"
        source.write_bytes(b"payload2")

        await cache_module.store_copy("https://example.com/bar", source)
        await asyncio.sleep(0.01)
        out_dir = Path(self.tmpdir.name) / "out2"
        result = await cache_module.get_cached_copy("https://example.com/bar", out_dir)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
