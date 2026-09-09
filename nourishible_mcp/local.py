from __future__ import annotations
import json
import os
import re
import subprocess
import sysconfig
import tempfile
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse


DETAILS = {"transcript", "efficient", "balanced", "token-burner"}
SUPPORTED_HOSTS = {
    "youtube.com": "youtube",
    "www.youtube.com": "youtube",
    "m.youtube.com": "youtube",
    "youtu.be": "youtube",
    "xiaohongshu.com": "xiaohongshu",
    "www.xiaohongshu.com": "xiaohongshu",
    "xhslink.cn": "xiaohongshu",
    "www.xhslink.cn": "xiaohongshu",
    "instagram.com": "instagram",
    "www.instagram.com": "instagram",
}


class LocalToolError(RuntimeError):
    pass


def skill_dir() -> Path:
    override = os.environ.get("NOURISHIBLE_SKILL_DIR")
    candidates = []
    if override:
        candidates.append(Path(override).expanduser())
    candidates.extend(
        [
            Path(__file__).resolve().parents[1] / "skills" / "recipe-nourishible",
            Path(sysconfig.get_path("data")) / "share" / "nourishible" / "recipe-nourishible",
        ]
    )
    for candidate in candidates:
        if (candidate / "SKILL.md").is_file() and (candidate / "scripts" / "watch.py").is_file():
            return candidate.resolve()
    raise LocalToolError(
        "Bundled recipe skill was not found. Reinstall nourishible-mcp-local or set "
        "NOURISHIBLE_SKILL_DIR to the recipe-nourishible directory."
    )


def workflow_text() -> str:
    return (skill_dir() / "SKILL.md").read_text(encoding="utf-8")


def platform_for(source_url: str) -> str:
    parsed = urlparse(source_url)
    if parsed.scheme not in {"http", "https"}:
        raise LocalToolError("source_url must be an http or https URL")
    host = (parsed.hostname or "").lower()
    platform = SUPPORTED_HOSTS.get(host)
    if not platform:
        raise LocalToolError("Supported sources are YouTube, Xiaohongshu, and Instagram")
    return platform


def _run(args: list[str], timeout_seconds: int) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            args,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise LocalToolError(f"Local command timed out after {timeout_seconds} seconds") from exc


def setup_status(profile: str = "standard") -> dict[str, Any]:
    if profile not in {"standard", "instagram"}:
        raise LocalToolError("profile must be 'standard' or 'instagram'")
    setup_script = skill_dir() / "scripts" / "setup.py"
    flag = "--json" if profile == "standard" else "--json-capture"
    result = _run(["python3", str(setup_script), flag], 30)
    if result.returncode != 0:
        raise LocalToolError(result.stderr.strip() or result.stdout.strip() or "Setup check failed")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise LocalToolError("Setup check returned invalid JSON") from exc
    payload["profile"] = profile
    payload["skillDir"] = str(skill_dir())
    return payload


def install_dependencies(profile: str = "standard") -> dict[str, Any]:
    if profile not in {"standard", "instagram"}:
        raise LocalToolError("profile must be 'standard' or 'instagram'")
    setup_script = skill_dir() / "scripts" / "setup.py"
    args = ["python3", str(setup_script)]
    if profile == "instagram":
        args.append("--install-capture")
    result = _run(args, 900)
    return {
        "ok": result.returncode == 0,
        "exitCode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "profile": profile,
    }


def extract_evidence(
    source_url: str,
    detail: str = "balanced",
    resolution: int = 1024,
    max_frames: Optional[int] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    section: Optional[str] = None,
    timestamps: Optional[str] = None,
    out_dir: Optional[str] = None,
    no_whisper: bool = False,
) -> dict[str, Any]:
    platform = platform_for(source_url)
    if platform == "instagram":
        raise LocalToolError(
            "Instagram requires human-confirmed screen capture. Call instagram_capture_instructions "
            "and run the returned command in a terminal after opening the post in Chrome."
        )
    if detail not in DETAILS:
        raise LocalToolError("detail must be transcript, efficient, balanced, or token-burner")
    if not 256 <= resolution <= 4096:
        raise LocalToolError("resolution must be between 256 and 4096 pixels")
    if max_frames is not None and not 1 <= max_frames <= 1000:
        raise LocalToolError("max_frames must be between 1 and 1000")

    work = Path(out_dir).expanduser().resolve() if out_dir else Path(tempfile.mkdtemp(prefix="nourishible-"))
    work.mkdir(parents=True, exist_ok=True)
    watch = skill_dir() / "scripts" / "watch.py"
    args = [
        "python3", str(watch), source_url, "--detail", detail,
        "--resolution", str(resolution), "--out-dir", str(work),
    ]
    optional = {
        "--max-frames": max_frames,
        "--start": start,
        "--end": end,
        "--section": section,
        "--timestamps": timestamps,
    }
    for flag, value in optional.items():
        if value is not None:
            args.extend([flag, str(value)])
    if no_whisper:
        args.append("--no-whisper")

    result = _run(args, 1800)
    if result.returncode != 0:
        raise LocalToolError(result.stderr.strip() or result.stdout.strip() or "Evidence extraction failed")
    frames = sorted(str(path.resolve()) for path in (work / "frames").glob("*.jpg"))
    return {
        "ok": True,
        "platform": platform,
        "workDir": str(work),
        "framePaths": frames,
        "report": result.stdout,
        "diagnostics": result.stderr,
        "next": (
            "Read every framePath and reconcile the frames, transcript, and description using the "
            "nourishible://recipe-workflow resource. Then save through the hosted Nourishible tools."
        ),
    }


def instagram_capture_instructions(source_url: str, seconds: int = 45, out_dir: Optional[str] = None) -> dict[str, Any]:
    if platform_for(source_url) != "instagram":
        raise LocalToolError("source_url must be an Instagram post or Reel")
    if not 5 <= seconds <= 600:
        raise LocalToolError("seconds must be between 5 and 600")
    work = Path(out_dir).expanduser().resolve() if out_dir else Path(tempfile.mkdtemp(prefix="nourishible-instagram-"))
    capture = skill_dir() / "scripts" / "capture" / "capture-only.sh"
    quoted_capture = _shell_quote(str(capture))
    quoted_work = _shell_quote(str(work))
    return {
        "sourceUrl": source_url,
        "workDir": str(work),
        "command": f"{quoted_capture} {seconds} {quoted_work}",
        "instructions": (
            "Open this exact post in Google Chrome and start playback yourself. Run the command in "
            "a terminal and confirm that its preview shows only the post. The MCP server intentionally "
            "does not automate navigation, playback, or the privacy preview."
        ),
    }


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"
