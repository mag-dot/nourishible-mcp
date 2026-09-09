import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from nourishible_mcp import local


class Result:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class LocalToolsTests(unittest.TestCase):
    def test_finds_repo_skill(self):
        self.assertTrue((local.skill_dir() / "scripts" / "watch.py").is_file())

    def test_rejects_unsupported_source(self):
        with self.assertRaisesRegex(local.LocalToolError, "Supported sources"):
            local.platform_for("https://example.com/video")

    def test_setup_status_parses_script_json(self):
        with patch.object(local, "_run", return_value=Result(stdout=json.dumps({"can_proceed": True}))):
            result = local.setup_status()
        self.assertTrue(result["can_proceed"])
        self.assertEqual("standard", result["profile"])

    def test_extract_returns_absolute_frame_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            frames = Path(temp) / "frames"
            frames.mkdir()
            (frames / "frame_0001.jpg").write_bytes(b"jpeg")
            with patch.object(local, "_run", return_value=Result(stdout="# report")):
                result = local.extract_evidence("https://youtu.be/abc", out_dir=temp, no_whisper=True)
        self.assertEqual("youtube", result["platform"])
        self.assertTrue(Path(result["framePaths"][0]).is_absolute())
        self.assertEqual("# report", result["report"])

    def test_instagram_returns_human_confirmed_command(self):
        result = local.instagram_capture_instructions("https://www.instagram.com/reel/abc")
        self.assertIn("capture-only.sh", result["command"])
        self.assertIn("confirm", result["instructions"])


if __name__ == "__main__":
    unittest.main()
