import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "recipe-nourishible" / "scripts"


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
class FindPlatingTests(unittest.TestCase):
    def _make_clip(self, path, duration=10):
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i",
            f"testsrc=duration={duration}:size=320x240:rate=10",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ], check=True)

    def test_scores_the_last_fifth(self):
        with tempfile.TemporaryDirectory() as temp:
            video = Path(temp) / "clip.mp4"
            self._make_clip(video)
            result = subprocess.run([
                "python3", str(SCRIPTS / "frames.py"), str(video), temp,
                "--find-plating",
            ], capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual("last 20% of the video", payload["window"])
        self.assertAlmostEqual(8.0, payload["start_seconds"], places=1)
        self.assertAlmostEqual(10.0, payload["end_seconds"], places=1)
        self.assertTrue(payload["candidates"])
        for cand in payload["candidates"]:
            self.assertGreaterEqual(cand["timestamp_seconds"], 8.0)

    def test_explicit_window_overrides_the_default(self):
        with tempfile.TemporaryDirectory() as temp:
            video = Path(temp) / "clip.mp4"
            self._make_clip(video)
            result = subprocess.run([
                "python3", str(SCRIPTS / "frames.py"), str(video), temp,
                "--find-plating", "--start", "2", "--end", "5",
            ], capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual("explicit --start/--end window", payload["window"])
        self.assertAlmostEqual(2.0, payload["start_seconds"], places=1)
        self.assertAlmostEqual(5.0, payload["end_seconds"], places=1)


if __name__ == "__main__":
    unittest.main()
