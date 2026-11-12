import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "recipe-nourishible" / "scripts"))

from download import _pick_subtitles, _read_info, native_caption_codes, sub_langs


class ReadInfoTests(unittest.TestCase):
    def test_keeps_description_and_language(self):
        with tempfile.TemporaryDirectory() as temp:
            info_path = Path(temp) / "video.info.json"
            info_path.write_text(json.dumps({
                "title": "T", "uploader": "U", "duration": 60,
                "webpage_url": "https://youtu.be/x",
                "description": "ingredients: ...",
                "language": "yue",
            }), encoding="utf-8")
            info = _read_info(info_path, "https://youtu.be/x")
        self.assertEqual("ingredients: ...", info["description"])
        self.assertEqual("yue", info["language"])

    def test_missing_description_and_language_are_none(self):
        with tempfile.TemporaryDirectory() as temp:
            info_path = Path(temp) / "video.info.json"
            info_path.write_text(json.dumps({"title": "T"}), encoding="utf-8")
            info = _read_info(info_path, "https://youtu.be/x")
        self.assertIsNone(info["description"])
        self.assertIsNone(info["language"])


class NativeCaptionCodesTests(unittest.TestCase):
    def test_yue_maps_to_written_chinese(self):
        self.assertEqual(
            ["yue", "zh-HK", "zh-Hant", "zh-TW", "zh"],
            native_caption_codes("yue"),
        )

    def test_plain_language_passes_through(self):
        self.assertEqual(["ja"], native_caption_codes("ja"))
        self.assertEqual([], native_caption_codes(None))

    def test_sub_langs_stays_english_only_for_english(self):
        self.assertEqual("en,en-US,en-GB,en-orig", sub_langs("en"))
        self.assertEqual("en,en-US,en-GB,en-orig", sub_langs(None))

    def test_sub_langs_adds_native_codes(self):
        self.assertEqual(
            "en,en-US,en-GB,en-orig,yue,zh-HK,zh-Hant,zh-TW,zh",
            sub_langs("yue"),
        )


class PickSubtitlesTests(unittest.TestCase):
    def _write(self, out_dir, names):
        for name in names:
            (out_dir / name).write_text("WEBVTT\n\n", encoding="utf-8")

    def test_picks_english_and_native(self):
        with tempfile.TemporaryDirectory() as temp:
            out_dir = Path(temp)
            self._write(out_dir, ["video.en.vtt", "video.zh-HK.vtt"])
            english, native = _pick_subtitles(out_dir, "yue")
        self.assertEqual("video.en.vtt", english.name)
        self.assertEqual("video.zh-HK.vtt", native.name)

    def test_native_falls_back_to_any_non_english_track(self):
        with tempfile.TemporaryDirectory() as temp:
            out_dir = Path(temp)
            self._write(out_dir, ["video.en.vtt", "video.fr.vtt"])
            _, native = _pick_subtitles(out_dir, "ja")
        self.assertEqual("video.fr.vtt", native.name)

    def test_english_only_means_no_native(self):
        with tempfile.TemporaryDirectory() as temp:
            out_dir = Path(temp)
            self._write(out_dir, ["video.en.vtt"])
            english, native = _pick_subtitles(out_dir, "yue")
        self.assertEqual("video.en.vtt", english.name)
        self.assertIsNone(native)


if __name__ == "__main__":
    unittest.main()
