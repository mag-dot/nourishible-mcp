import tempfile
import unittest
from pathlib import Path

from nourishible_worker.manifest import (
    MAX_FRAME_BYTES,
    MAX_FRAMES,
    MAX_OCR_CHARS,
    MAX_TRANSCRIPT_CHARS,
    ManifestError,
    build_manifest,
)


def jpeg():
    return b"\xff\xd8\xff" + b"image" + b"\xff\xd9"


class ManifestTests(unittest.TestCase):
    def test_builds_bounded_manifest_from_capture_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "frame_0001.jpg").write_bytes(jpeg())
            (root / "frame_0002.jpg").write_bytes(jpeg())
            (root / "caption.txt").write_text("caption")
            (root / "onscreen.clean.txt").write_text("ingredients")
            result = build_manifest(temp, "https://instagram.com/reel/abc")
            self.assertEqual(2, len(result.files))
            self.assertEqual("caption", result.caption_text)
            self.assertEqual("operator_screen_capture", result.capture_method)

    def test_requires_at_least_one_frame(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ManifestError):
                build_manifest(temp, "https://instagram.com/reel/abc")

    def test_rejects_too_many_frames(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for index in range(MAX_FRAMES + 1):
                (root / ("frame_%04d.jpg" % index)).write_bytes(jpeg())
            with self.assertRaisesRegex(ManifestError, "maximum is %d" % MAX_FRAMES):
                build_manifest(temp, "https://instagram.com/reel/abc")

    def test_rejects_oversized_frame(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "frame_0001.jpg").write_bytes(b"x" * (MAX_FRAME_BYTES + 1))
            with self.assertRaisesRegex(ManifestError, "outside the frame size limit"):
                build_manifest(temp, "https://instagram.com/reel/abc")

    def test_rejects_transcript_and_ocr_overflows(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "frame_0001.jpg").write_bytes(jpeg())
            (root / "transcript.clean.txt").write_text("t" * (MAX_TRANSCRIPT_CHARS + 1))
            with self.assertRaisesRegex(ManifestError, "transcript.clean.txt"):
                build_manifest(temp, "https://instagram.com/reel/abc")

            (root / "transcript.clean.txt").write_text("")
            (root / "onscreen.clean.txt").write_text("o" * (MAX_OCR_CHARS + 1))
            with self.assertRaisesRegex(ManifestError, "onscreen.clean.txt"):
                build_manifest(temp, "https://instagram.com/reel/abc")
