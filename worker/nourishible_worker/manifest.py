"""Build a bounded, checksummed evidence manifest from existing capture output."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from .types import EvidenceFile, EvidenceManifest

MAX_FRAMES = 24
MAX_FRAME_BYTES = 2 * 1024 * 1024
MAX_TRANSCRIPT_CHARS = 40_000
MAX_OCR_CHARS = 48_000


class ManifestError(ValueError):
    pass


def _read(path: Path, limit: int) -> str:
    if not path.exists():
        return ""
    value = path.read_text(encoding="utf-8", errors="replace")
    if len(value) > limit:
        raise ManifestError("%s exceeds its evidence limit" % path.name)
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _frame_timestamp(path: Path, index: int) -> float:
    # capture-only output is sequential, not timestamped. Preserve order without claiming
    # a precise playback time. The server can treat this as ordinal evidence.
    match = re.search(r"(\d+)$", path.stem)
    return float(int(match.group(1)) if match else index)


def build_manifest(capture_dir: str, source_url: str, human_action_at: str | None = None) -> EvidenceManifest:
    root = Path(capture_dir).resolve()
    if not root.is_dir():
        raise ManifestError("capture directory does not exist")
    frames = sorted(root.glob("frame_*.jpg"))
    if not frames:
        raise ManifestError("capture has no JPEG frames")
    if len(frames) > MAX_FRAMES:
        raise ManifestError("capture has %d frames; maximum is %d" % (len(frames), MAX_FRAMES))

    files: List[EvidenceFile] = []
    for index, frame in enumerate(frames):
        size = frame.stat().st_size
        if size <= 0 or size > MAX_FRAME_BYTES:
            raise ManifestError("%s is outside the frame size limit" % frame.name)
        files.append(EvidenceFile(kind="frame", path=str(frame), sha256=_sha256(frame), bytes=size,
                                  timestamp_seconds=_frame_timestamp(frame, index)))

    return EvidenceManifest(
        source_url=source_url,
        capture_method="operator_screen_capture",
        policy_version="instagram-human-capture-v1",
        human_action_at=human_action_at or datetime.now(timezone.utc).isoformat(),
        files=files,
        transcript_text=_read(root / "transcript.clean.txt", MAX_TRANSCRIPT_CHARS),
        onscreen_text=_read(root / "onscreen.clean.txt", MAX_OCR_CHARS),
        caption_text=_read(root / "caption.txt", MAX_OCR_CHARS),
    )
