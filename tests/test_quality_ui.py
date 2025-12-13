from __future__ import annotations

import unittest

from aiogram.types import InlineKeyboardMarkup

from bot_app.ui import quality
from bot_app.ui.i18n import translate


class QualityUITests(unittest.TestCase):
    def test_get_preset_returns_known_value(self) -> None:
        preset = quality.get_preset("720p")
        self.assertEqual(preset.slug, "720p")
        self.assertTrue(preset.expect_video)
        self.assertTrue(preset.expect_audio)

    def test_get_preset_falls_back_to_default(self) -> None:
        preset = quality.get_preset("does-not-exist")
        self.assertIs(preset, quality.DEFAULT_PRESET)

    def test_build_keyboard_contains_expected_rows(self) -> None:
        token = "abc123"
        kb = quality.build_keyboard(token, locale="ru")
        self.assertIsInstance(kb, InlineKeyboardMarkup)
        rows = kb.inline_keyboard
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(rows[0]), 2)
        self.assertEqual(len(rows[1]), 2)

        expected_slugs = ["auto", "720p", "480p", "audio"]
        actual_slugs = []
        actual_labels = []
        for row in rows:
            for button in row:
                actual_slugs.append(button.callback_data.split(":")[-1])
                actual_labels.append(button.text)
                self.assertTrue(button.callback_data.startswith(f"quality:{token}:"))
        self.assertEqual(actual_slugs, expected_slugs)

        translated_labels = [translate(f"quality.option.{slug}", "ru") for slug in expected_slugs]
        self.assertEqual(actual_labels, translated_labels)


if __name__ == "__main__":
    unittest.main()
