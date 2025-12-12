from __future__ import annotations

import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from utils import downloader


class DownloaderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.output_dir = Path(self._tmpdir.name)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    async def test_download_video_success_path(self) -> None:
        target_file = self.output_dir / "sample.mp4"

        async def fake_run_cmd(cmd, timeout):
            if cmd and cmd[0] == "yt-dlp" and not target_file.exists():
                target_file.write_bytes(b"video")
            return ("", "", 0)

        async def fake_ffprobe(*_args, **_kwargs):
            return {"has_audio": True, "has_video": True}

        with mock.patch("utils.downloader._run_cmd", fake_run_cmd), mock.patch(
            "utils.downloader._ffprobe_has_audio_or_video", fake_ffprobe
        ), mock.patch.object(downloader, "video_cache", None):
            result_path = await downloader.download_video(
                "https://example.com/video",
                self.output_dir,
                timeout=5,
            )

        self.assertTrue(result_path.exists())
        self.assertEqual(result_path, target_file)

    async def test_download_video_merges_when_audio_missing(self) -> None:
        video_file = self.output_dir / "video.mp4"
        audio_file = self.output_dir / "audio.m4a"
        merged_file = video_file.with_name(video_file.stem + "_merged.mp4")

        async def fake_run_cmd(cmd, timeout):
            if cmd and cmd[0] == "yt-dlp":
                format_arg = cmd[cmd.index("-f") + 1] if "-f" in cmd else ""
                if "bestvideo" in format_arg and not video_file.exists():
                    video_file.write_bytes(b"video")
                elif "bestaudio" in format_arg and not audio_file.exists():
                    audio_file.write_bytes(b"audio")
            return ("", "", 0)

        async def fake_ffprobe(*_args, **_kwargs):
            return {"has_audio": False, "has_video": True}

        async def fake_merge(v_path, a_path, out_path, timeout=120):
            self.assertEqual(v_path, video_file)
            self.assertEqual(a_path, audio_file)
            out_path.write_bytes(b"merged")
            return out_path

        with mock.patch("utils.downloader._run_cmd", fake_run_cmd), mock.patch(
            "utils.downloader._ffprobe_has_audio_or_video", fake_ffprobe
        ), mock.patch("utils.downloader._ffmpeg_merge", fake_merge), mock.patch.object(
            downloader, "video_cache", None
        ):
            result_path = await downloader.download_video(
                "https://example.com/video2",
                self.output_dir,
                timeout=5,
            )

        self.assertTrue(result_path.exists())
        self.assertEqual(result_path, merged_file)

    async def test_instagram_fallback_invoked_on_sensitive_error(self) -> None:
        fallback_file = self.output_dir / "instagram_fallback.mp4"

        async def fake_run_cmd(cmd, timeout):
            return (
                "",
                "ERROR: [Instagram] DRQSTxVDKmh: This content may be inappropriate: It's unavailable for certain audiences.",
                1,
            )

        async def fake_fallback(url, output_dir, cookies_file):
            fallback_file.write_bytes(b"fallback")
            return fallback_file

        fake_module = types.SimpleNamespace(download_sensitive_media=fake_fallback)

        with mock.patch("utils.downloader._run_cmd", fake_run_cmd), mock.patch.object(
            downloader, "video_cache", None
        ), mock.patch("utils.downloader.instagram_direct", fake_module):
            result_path = await downloader.download_video(
                "https://www.instagram.com/reel/DRQSTxVDKmh/",
                self.output_dir,
                timeout=5,
                cookies_file="tmp/instagram_cookies.txt",
            )

        self.assertTrue(fallback_file.exists())
        self.assertEqual(result_path, fallback_file)


if __name__ == "__main__":
    unittest.main()
