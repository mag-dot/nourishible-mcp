#!/usr/bin/env python3
"""Probe video metadata and extract frames at an auto-scaled fps.

Auto-fps targets a frame budget, not a fixed rate. Token cost scales with frame
count, so budget-by-duration keeps short videos dense and long videos capped.
When a user-specified range is passed, focused-mode budgets denser (they are
zooming in for detail).
"""
from __future__ import annotations

import json
import re
import bisect
import shutil
import subprocess
import sys
from pathlib import Path


MAX_FPS = 2.0
SCENE_THRESHOLD = 0.20
# Keep scene-detection results once we have at least this many distinct shots.
# Below this the video is effectively static (screen recording, talking head),
# so we fall back to uniform sampling. Matching the reference fork's behaviour,
# this is a low floor — NOT the frame budget — so normal videos with cuts use
# the (single-pass) scene engine instead of paying for a wasted second decode.
SCENE_MIN_FRAMES = 8
# Below this many decoded keyframes a clip is too sparse for keyframe coverage
# (very short or oddly encoded), so the cheap tier falls back to uniform.
KEYFRAME_MIN = 4
MAX_READ_DIMENSION = 1998
# Per-frame pixel budget for reading frames. `--resolution` caps *width* only,
# so before this existed a portrait 9:16 reel cost 3.2x what a landscape 16:9
# video did at the same setting (1024x1820 = 2485 image tokens vs 1024x576 =
# 786) purely because of orientation. Image tokens scale with area, so the
# budget is expressed as area. 0.8 MP sits just above what a 1024-wide 16:9
# frame already used (0.59 MP), so landscape output is unchanged and portrait
# output drops from 2485 to ~1067 tokens a frame.
#
# The floor is set by legibility, not by cost: burned-in recipe text was tested
# down to ~1.1% of frame height, thin and low-contrast over busy food. At 0.6 MP
# (581px wide portrait) that smallest line was only marginally readable; at
# 0.8 MP (671px) it is clearly readable. Don't lower this without re-running
# that check — unreadable ingredient text costs far more than it saves.
MAX_READ_PIXELS = 800_000
# Resolution for a frame grabbed to *be* the recipe thumbnail, as opposed to
# one grabbed for the agent to read. Reading frames are deliberately small
# (token cost scales with pixels); a thumbnail is the full-size card/OG image
# everyone sees, so it wants every pixel the source actually has. _scale_filter
# uses min(resolution, iw), so this is a ceiling, never an upscale — asking for
# 1440 on a 1080-wide reel yields the native 1080.
THUMBNAIL_RESOLUTION = 1440
# JPEG -q:v for thumbnail grabs (lower is better). Reading frames use 4, which
# is fine at 512-1024px but visibly lossy once the frame is the card image.
THUMBNAIL_QUALITY = 2
# Width for thumbnail-*candidate* grabs (--timestamps), which exist only to be
# looked at and ranked, then thrown away. Deliberately far below the reading
# resolution: judging "is this the finished dish, and is it well composed" needs
# a fraction of the detail that reading a burned-in ingredient line does. At 384
# a portrait candidate is 384x682 = ~350 image tokens, so a 12-frame shortlist
# costs ~4.2k rather than the ~33k that re-grabbing 12 frames at full thumbnail
# resolution would. The winner is re-grabbed at full resolution afterwards with
# --thumbnail-at, so nothing about the final card image depends on this number.
CANDIDATE_READ_RESOLUTION = 384
# Frame-delta dedup: downscale each frame to a DEDUP_THUMB x DEDUP_THUMB
# grayscale thumbnail and treat two frames as near-identical only when BOTH the
# mean per-pixel difference is at or below DEDUP_THRESHOLD and the largest
# single-cell difference is at or below DEDUP_MAX_DELTA (both 0-255).
#
# The max test is load-bearing, not a refinement. Mean alone cannot see a small
# burned-in text overlay changing over an otherwise static shot — the single
# most common way a recipe reel states its ingredients. Measured on two
# 1080x1920 frames identical but for a 46px ingredient line (2.4% of frame
# height), the mean delta was 0.102 against a 2.0 threshold: dropped as a
# near-duplicate, taking the ingredient with it. No threshold fixes that (0.05
# would dedup nothing); the 16x16 mean simply destroys the signal. The same
# pair separates cleanly on max — 22 for the text change against 0 for a true
# duplicate — so that is what the second test reads.
#
# Still conservative on both axes: only frames that are the same shot AND have
# no localised change anywhere collapse, so a code diff / scrolling terminal /
# slide-gaining-a-bullet survives for the same reason the ingredient line now
# does. Unlike a within-frame perceptual hash, this distinguishes flat frames
# (solid slides, fades) by luma.
#
# 32x32 rather than 16x16: at 16x16 a single cell spans 67x120 source pixels on
# a portrait reel, so a one-line overlay is averaged down into ~10 of max even
# where it is plainly visible. 32x32 lifts that same change to 22 and costs
# nothing measurable (4x256 bytes a frame, one ffmpeg pass either way).
DEDUP_THUMB = 32
DEDUP_THRESHOLD = 2.0
DEDUP_MAX_DELTA = 12.0
SHOWINFO_TS_RE = re.compile(r"pts_time:([0-9.]+)")
# Buffer for the two-stage seek in _two_stage_seek(). Kept short: it's paid as
# extra decode time on every timestamp-anchored grab.
SEEK_BUFFER_SECONDS = 2.0


def _two_stage_seek(target: float | None) -> tuple[list[str], list[str]]:
    """Split a seek into a fast keyframe-snap seek before ``-i`` plus a short
    accurate residual seek after ``-i``.

    A bare ``-ss`` before ``-i`` snaps to the nearest keyframe and hands
    decoding off from there — fine when what follows is a normal sequential
    decode, but a single ``-frames:v 1`` grab (or a scene-detect pass that
    starts mid-GOP) can then emit a frame whose backward P/B references
    haven't fully resolved. On affected sources that surfaces as a visibly
    corrupted/ghosted frame — this is what produced the "Homebrew Kombucha"
    thumbnail glitch (a fast-seek grab landing mid-transition in the source
    video). Decoding forward through ``SEEK_BUFFER_SECONDS`` of buffer before
    the frame we keep resolves that reference chain, at the cost of a couple
    extra seconds of decode instead of a bare jump.

    Returns ``(pre_i_args, post_i_args)`` — args to splice before and after
    ``-i`` respectively. ``target=None`` (no seek requested) returns
    ``([], [])``.
    """
    if target is None:
        return [], []
    rough = max(0.0, target - SEEK_BUFFER_SECONDS)
    residual = target - rough
    pre = ["-ss", f"{rough:.3f}"] if rough > 0 else []
    post = ["-ss", f"{residual:.3f}"] if residual > 0 else []
    return pre, post


def _scale_filter(resolution: int, max_pixels: int | None = MAX_READ_PIXELS) -> str:
    """Downscale filter honouring three independent ceilings, never upscaling.

    Width <= ``resolution``, height <= ``MAX_READ_DIMENSION``, and total area
    <= ``max_pixels``. Solving for the output width directly (rather than
    letting force_original_aspect_ratio pick it) is what lets the area cap
    apply: for a uniform scale ``s``, area <= P means ``s <= sqrt(P/(iw*ih))``,
    so ``w = iw*s = sqrt(P*iw/ih)``. Height follows from ``h=-2`` (aspect
    preserved, rounded to an even number).

    ``max_pixels=None`` restores pure width/height capping — used for thumbnail
    grabs, which are written to disk rather than read into a context window and
    so should keep every pixel the source has.
    """
    caps = [f"min(iw,{resolution})", f"iw*{MAX_READ_DIMENSION}/ih"]
    if max_pixels is not None:
        caps.append(f"sqrt({max_pixels}*iw/ih)")
    expr = caps[0]
    for c in caps[1:]:
        expr = f"min({expr},{c})"
    return f"scale=w='trunc(({expr})/2)*2':h=-2"


def _clamp_fps(fps: float, duration_seconds: float, max_frames: int) -> tuple[float, int]:
    fps = min(fps, MAX_FPS)
    target = min(max_frames, max(1, int(round(fps * duration_seconds))))
    return fps, target


def parse_time(value: str | float | int | None) -> float | None:
    """Parse SS, MM:SS, or HH:MM:SS (with optional .ms) into seconds."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    parts = s.split(":")
    try:
        if len(parts) == 1:
            return float(parts[0])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    except ValueError:
        pass
    raise SystemExit(f"Cannot parse time value: {value!r} (expected SS, MM:SS, or HH:MM:SS)")


def format_time(seconds: float) -> str:
    total = int(round(seconds))
    hours, rem = divmod(total, 3600)
    minutes, sec = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{sec:02d}"
    return f"{minutes:02d}:{sec:02d}"


def get_metadata(video_path: str) -> dict:
    if shutil.which("ffprobe") is None:
        raise SystemExit("ffprobe is not installed. Install with: brew install ffmpeg")

    result = subprocess.run(
        [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            str(Path(video_path).resolve()),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"ffprobe failed: {result.stderr.strip()}")

    data = json.loads(result.stdout or "{}")
    streams = data.get("streams", [])
    fmt = data.get("format", {})
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    duration = float(fmt.get("duration") or video_stream.get("duration") or 0)
    return {
        "duration_seconds": duration,
        "width": video_stream.get("width"),
        "height": video_stream.get("height"),
        "codec": video_stream.get("codec_name"),
        "size_bytes": int(fmt.get("size") or 0),
        "has_audio": audio_stream is not None,
    }


def auto_fps(duration_seconds: float, max_frames: int = 100) -> tuple[float, int]:
    """Pick fps that targets a sensible frame budget for full-video scans."""
    if duration_seconds <= 0:
        return 1.0, 1

    if duration_seconds <= 30:
        target = min(max_frames, max(12, int(round(duration_seconds))))
    elif duration_seconds <= 60:
        target = min(max_frames, 40)
    elif duration_seconds <= 180:  # 3 min
        target = min(max_frames, 60)
    elif duration_seconds <= 600:  # 10 min
        target = min(max_frames, 80)
    else:
        target = max_frames

    return _clamp_fps(target / duration_seconds, duration_seconds, max_frames)


def auto_fps_focus(duration_seconds: float, max_frames: int = 100) -> tuple[float, int]:
    """Denser budget for user-specified ranges — they are zooming in for detail."""
    if duration_seconds <= 0:
        return min(MAX_FPS, 2.0), 2

    if duration_seconds <= 5:
        target = min(max_frames, max(10, int(round(duration_seconds * 6))))
    elif duration_seconds <= 15:
        target = min(max_frames, max(30, int(round(duration_seconds * 4))))
    elif duration_seconds <= 30:
        target = min(max_frames, 60)
    elif duration_seconds <= 60:
        target = min(max_frames, 80)
    elif duration_seconds <= 180:
        target = max_frames
    else:
        target = max_frames

    return _clamp_fps(target / duration_seconds, duration_seconds, max_frames)


def extract(
    video_path: str,
    out_dir: Path,
    fps: float,
    resolution: int = 512,
    max_frames: int = 100,
    start_seconds: float | None = None,
    end_seconds: float | None = None,
) -> list[dict]:
    if shutil.which("ffmpeg") is None:
        raise SystemExit("ffmpeg is not installed. Install with: brew install ffmpeg")

    out_dir.mkdir(parents=True, exist_ok=True)
    for existing in out_dir.glob("frame_*.jpg"):
        existing.unlink()

    output_pattern = str(out_dir / "frame_%04d.jpg")
    cmd: list[str] = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",
        "-y",
    ]

    # -ss before -i = fast seek (keyframe-snap, good enough for preview frames).
    if start_seconds is not None:
        cmd += ["-ss", f"{start_seconds:.3f}"]
    if end_seconds is not None:
        cmd += ["-to", f"{end_seconds:.3f}"]

    cmd += [
        "-i", str(Path(video_path).resolve()),
        "-vf", f"fps={fps},{_scale_filter(resolution)}",
        "-frames:v", str(max_frames),
        "-q:v", "4",
        output_pattern,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"ffmpeg frame extraction failed: {result.stderr.strip()}")

    offset = start_seconds or 0.0
    frames = sorted(out_dir.glob("frame_*.jpg"))
    return [
        {
            "index": i,
            "timestamp_seconds": round(offset + (i / fps if fps > 0 else 0.0), 2),
            "path": str(p),
            "reason": "uniform",
        }
        for i, p in enumerate(frames)
    ]


def extract_scene_candidates(
    video_path: str,
    out_dir: Path,
    resolution: int = 512,
    max_frames: int | None = 100,
    start_seconds: float | None = None,
    end_seconds: float | None = None,
    threshold: float = SCENE_THRESHOLD,
) -> list[dict]:
    """Extract first frame plus ffmpeg scene-change frames.

    When ``max_frames`` is set, ``-frames:v`` lets ffmpeg stop decoding once it
    has emitted that many frames (early exit) and avoids writing extras that we
    would only delete afterwards. ``None`` (uncapped "complete" detail) keeps
    every detected shot, as the user explicitly opted in.
    """
    if shutil.which("ffmpeg") is None:
        raise SystemExit("ffmpeg is not installed. Install with: brew install ffmpeg")

    out_dir.mkdir(parents=True, exist_ok=True)
    for existing in out_dir.glob("frame_*.jpg"):
        existing.unlink()

    output_pattern = str(out_dir / "frame_%04d.jpg")
    pre_seek, post_seek = _two_stage_seek(start_seconds)
    cmd: list[str] = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "info",
        "-y",
        *pre_seek,
    ]
    # -to is an absolute input-side timestamp, so it isn't shifted by the
    # accurate residual seek (post_seek) applied after -i below.
    if end_seconds is not None:
        cmd += ["-to", f"{end_seconds:.3f}"]

    vf = f"select='eq(n\\,0)+gt(scene\\,{threshold})',{_scale_filter(resolution)},showinfo"
    cmd += [
        "-i", str(Path(video_path).resolve()),
        *post_seek,
        "-vf", vf,
        "-vsync", "vfr",
    ]
    if max_frames is not None:
        cmd += ["-frames:v", str(max_frames)]
    cmd += [
        "-q:v", "4",
        output_pattern,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"ffmpeg scene extraction failed: {result.stderr.strip()}")

    offset = start_seconds or 0.0
    timestamps = [round(offset + float(match.group(1)), 2) for match in SHOWINFO_TS_RE.finditer(result.stderr)]
    frames = sorted(out_dir.glob("frame_*.jpg"))
    out: list[dict] = []
    for i, path in enumerate(frames):
        ts = timestamps[i] if i < len(timestamps) else offset
        out.append({
            "index": i,
            "timestamp_seconds": ts,
            "path": str(path),
            "reason": "first-frame" if i == 0 else "scene-change",
        })
    return out


def _even_indices(count: int, n: int) -> list[int]:
    """Indices of ``n`` evenly-spaced items out of ``count`` (first + last kept).

    ``n >= count`` returns every index; ``n == 1`` returns just the first.
    """
    if n >= count:
        return list(range(count))
    if n <= 1:
        return [0]
    return [round(i * (count - 1) / (n - 1)) for i in range(n)]


def parse_timestamps(value: str | None) -> list[float]:
    """Parse a comma-separated list of times (SS, MM:SS, HH:MM:SS) into a
    sorted, de-duplicated list of seconds. Empty/blank tokens are skipped;
    an unparseable token raises (via :func:`parse_time`)."""
    if not value:
        return []
    out: list[float] = []
    for token in value.split(","):
        token = token.strip()
        if not token:
            continue
        seconds = parse_time(token)
        if seconds is not None:
            out.append(float(seconds))
    return sorted(set(out))


def merge_frames(primary: list[dict], pinned: list[dict]) -> list[dict]:
    """Combine two frame lists into one chronological list and reindex 0..n-1.

    ``pinned`` frames (transcript cues) are never dropped — this is a plain
    union, so the cap is enforced upstream by reserving budget for the cues.
    """
    merged = sorted([*primary, *pinned], key=lambda f: f["timestamp_seconds"])
    for i, frame in enumerate(merged):
        frame["index"] = i
    return merged


def extract_at_timestamps(
    video_path: str,
    out_dir: Path,
    timestamps: list[float],
    resolution: int = 512,
    max_frames: int | None = None,
    start_seconds: float | None = None,
    end_seconds: float | None = None,
    prefix: str = "cue",
    quality: int = 4,
    reason: str = "transcript-cue",
    max_pixels: int | None = MAX_READ_PIXELS,
) -> tuple[list[dict], dict]:
    """Grab exactly one frame at each requested timestamp (transcript cues).

    Timestamps are absolute source seconds. Any falling outside an active
    ``[start, end]`` focus window are dropped. Files use a ``<prefix>_*.jpg``
    name so they sit alongside detail-engine ``frame_*.jpg`` output without
    either clobbering the other. When more cues than ``max_frames`` survive,
    they are even-sampled (first + last kept) before extraction.

    ``prefix`` also scopes the clear-before-write: only files matching this
    prefix are removed, so a ``--thumbnail-at`` grab (prefix ``thumb``) leaves
    the transcript-cue frames from an earlier pass intact.
    """
    if shutil.which("ffmpeg") is None:
        raise SystemExit("ffmpeg is not installed. Install with: brew install ffmpeg")

    out_dir.mkdir(parents=True, exist_ok=True)
    for existing in out_dir.glob(f"{prefix}_*.jpg"):
        existing.unlink()

    lo = start_seconds or 0.0
    hi = end_seconds if end_seconds is not None else float("inf")
    requested = sorted(set(round(float(t), 2) for t in timestamps))
    in_window = [t for t in requested if lo <= t <= hi]
    dropped = len(requested) - len(in_window)

    if max_frames is not None and len(in_window) > max_frames:
        points = [in_window[i] for i in _even_indices(len(in_window), max_frames)]
    else:
        points = in_window

    out: list[dict] = []
    for t in points:
        path = out_dir / f"{prefix}_{len(out):04d}.jpg"
        pre_seek, post_seek = _two_stage_seek(t)
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "error",
            "-y",
            *pre_seek,
            "-i", str(Path(video_path).resolve()),
            *post_seek,
            "-frames:v", "1",
            "-vf", _scale_filter(resolution, max_pixels),
            "-q:v", str(quality),
            str(path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0 and path.exists():
            out.append({
                "index": len(out),
                "timestamp_seconds": t,
                "path": str(path),
                "reason": reason,
            })

    meta = {
        "engine": "timestamps",
        "candidate_count": len(requested),
        "selected_count": len(out),
        "dropped_out_of_window": dropped,
        "fallback": False,
    }
    return out, meta


def _even_sample(candidates: list[dict], n: int) -> list[dict]:
    """Pick ``n`` evenly-spaced candidates (always including first and last),
    delete the JPEGs we drop, and reindex the survivors 0..len-1.

    Shared by every capped engine so all detail modes sample the same way:
    detect all candidates across the full range, then thin down to the cap.
    ``n >= len(candidates)`` keeps everything (the uncapped / under-cap case).
    """
    selected = [candidates[i] for i in _even_indices(len(candidates), n)]

    keep_paths = {sel["path"] for sel in selected}
    for cand in candidates:
        if cand["path"] not in keep_paths:
            try:
                Path(cand["path"]).unlink()
            except OSError:
                pass
    for i, frame in enumerate(selected):
        frame["index"] = i
    return selected


def _frame_delta(a: bytes, b: bytes) -> tuple[float, float]:
    """Mean and max absolute per-pixel difference (0-255) between two grayscale
    thumbnails. Mismatched lengths are treated as maximally different so a
    decode hiccup never collapses distinct frames.

    Both are returned because they answer different questions: the mean says
    "is this the same shot", the max says "did anything change anywhere in it".
    A small text overlay only moves the second (see DEDUP_MAX_DELTA)."""
    if not a or len(a) != len(b):
        return float("inf"), float("inf")
    diffs = [abs(x - y) for x, y in zip(a, b)]
    return sum(diffs) / len(diffs), float(max(diffs))


def _thumb_frames(paths: list[Path]) -> list[bytes]:
    """Decode every frame in ``paths`` to a small grayscale thumbnail via one
    ffmpeg pass over the JPEG sequence.

    ffmpeg does the pixel decode (keeps us pure-stdlib); we slice the raw
    grayscale stream into one ``DEDUP_THUMB``-square thumbnail per frame.
    Fail-open: any ffmpeg error, an unrecognized name, or a byte-count mismatch
    returns ``[]`` so the caller skips dedup rather than breaking extraction.
    """
    if not paths:
        return []
    paths = [Path(p) for p in paths]
    m = re.match(r"(.*?)(\d+)(\.[A-Za-z0-9]+)$", paths[0].name)
    if m is None:
        return []
    prefix, digits, ext = m.group(1), m.group(2), m.group(3)
    pattern = str(paths[0].parent / f"{prefix}%0{len(digits)}d{ext}")

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",
        "-start_number", str(int(digits)),
        "-i", pattern,
        "-vf", f"scale={DEDUP_THUMB}:{DEDUP_THUMB},format=gray",
        "-f", "rawvideo",
        "-",
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        return []

    chunk = DEDUP_THUMB * DEDUP_THUMB
    data = result.stdout
    if len(data) != chunk * len(paths):
        return []
    return [data[i * chunk:(i + 1) * chunk] for i in range(len(paths))]


def dedupe_perceptual(
    candidates: list[dict],
    threshold: float = DEDUP_THRESHOLD,
    max_delta: float = DEDUP_MAX_DELTA,
) -> tuple[list[dict], int]:
    """Drop near-identical frames from a chronological candidate list.

    Thumbnails the extracted JPEGs and greedily removes frames that are within
    ``threshold`` mean *and* ``max_delta`` max per-pixel difference of the last
    kept one. Returns ``(survivors, dropped_count)``; a no-op (unchanged list)
    when thumbnails are unavailable or there are fewer than two candidates.
    """
    if len(candidates) <= 1:
        return candidates, 0
    thumbs = _thumb_frames([Path(c["path"]) for c in candidates])
    return _dedupe_by_deltas(candidates, thumbs, threshold, max_delta)


def _dedupe_by_deltas(
    candidates: list[dict],
    thumbs: list[bytes],
    threshold: float = DEDUP_THRESHOLD,
    max_delta: float = DEDUP_MAX_DELTA,
) -> tuple[list[dict], int]:
    """Greedily drop frames within ``threshold`` mean *and* ``max_delta`` max
    per-pixel difference of the last *kept* frame. Requiring both is what keeps
    a frame whose only change is a small burned-in ingredient overlay, which
    moves max but barely moves mean (see DEDUP_MAX_DELTA). Deletes dropped JPEGs
    and reindexes survivors 0..n-1 (same cleanup contract as
    :func:`_even_sample`). Fail-open: if ``thumbs`` does not line up 1:1 with
    ``candidates``, return them unchanged.
    """
    if len(thumbs) != len(candidates) or len(candidates) <= 1:
        return candidates, 0

    kept = [candidates[0]]
    last = thumbs[0]
    dropped: list[dict] = []
    for cand, thumb in zip(candidates[1:], thumbs[1:]):
        mean_d, max_d = _frame_delta(thumb, last)
        if mean_d <= threshold and max_d <= max_delta:
            dropped.append(cand)
        else:
            kept.append(cand)
            last = thumb

    for cand in dropped:
        try:
            Path(cand["path"]).unlink()
        except OSError:
            pass
    for i, frame in enumerate(kept):
        frame["index"] = i
    return kept, len(dropped)


def extract_scene_or_uniform(
    video_path: str,
    out_dir: Path,
    fps: float,
    target_frames: int,
    resolution: int = 512,
    max_frames: int | None = 100,
    start_seconds: float | None = None,
    end_seconds: float | None = None,
    dedup: bool = True,
) -> tuple[list[dict], dict]:
    """Prefer scene selection, falling back to uniform only when the video is
    effectively static (fewer than ``SCENE_MIN_FRAMES`` detected shots).

    Scene cuts are detected across the *whole* range (uncapped), near-identical
    frames are dropped (:func:`dedupe_perceptual`, unless ``dedup`` is False),
    and the survivors are even-sampled down to ``max_frames`` via
    :func:`_even_sample`, exactly like the keyframe engine. This costs a full
    decode, but it guarantees coverage spans the entire clip — capping detection
    with ``-frames:v`` instead would keep only the first ``max_frames`` cuts and
    drop the tail of long videos (and could even fall below ``SCENE_MIN_FRAMES``
    and misfire the uniform fallback on a cut-heavy clip).
    """
    scene_frames = extract_scene_candidates(
        video_path,
        out_dir,
        resolution=resolution,
        max_frames=None,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
    )
    scene_count = len(scene_frames)
    if scene_count >= SCENE_MIN_FRAMES:
        deduped, n_dropped = dedupe_perceptual(scene_frames) if dedup else (scene_frames, 0)
        cap = len(deduped) if max_frames is None else max_frames
        selected = _even_sample(deduped, cap)
        return selected, {
            "engine": "scene",
            "candidate_count": scene_count,
            "deduped_count": n_dropped,
            "selected_count": len(selected),
            "fallback": False,
        }

    fallback_cap = target_frames if max_frames is None else min(max_frames, target_frames)
    frames = extract(
        video_path,
        out_dir,
        fps=fps,
        resolution=resolution,
        max_frames=fallback_cap,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
    )
    n_dropped = 0
    if dedup:
        frames, n_dropped = dedupe_perceptual(frames)
    return frames, {
        "engine": "uniform",
        "candidate_count": scene_count,
        "deduped_count": n_dropped,
        "selected_count": len(frames),
        "fallback": True,
    }


# ---------------------------------------------------------------------------
# Thumbnail candidate ranking
#
# Scores every sampled frame with ffmpeg's own analysis filters (blurdetect +
# signalstats) and returns a shortlist of timestamps worth *looking* at. One
# decode pass, no new dependencies, no image tokens: 353 frames of a 6-minute
# video scored in 5.7s.
#
# What this deliberately does NOT do is pick the thumbnail. Measured on a real
# recipe video, pixel statistics cannot tell a finished dish from raw
# ingredients — the raw tray scored *higher* on both sharpness and saturation
# than the plated result (raw potatoes are uniformly vivid; the cooked dish is
# browner and softer), and satspread/huespread ranges overlapped completely.
# A ranker built on these signals picks confidently wrong. "Is this the
# finished dish" is semantic, so the shortlist goes to a model to decide.
#
# The shortlist is bucketed across the whole timeline rather than biased late.
# The finished dish is often near the end, but a large share of recipe reels
# open with it as a hook in the first seconds — a late-only gate would miss
# exactly the most common format.
# ---------------------------------------------------------------------------

CANDIDATE_RANK_FPS = 1.0
CANDIDATE_SCALE_WIDTH = 320
DEFAULT_CANDIDATE_COUNT = 12
_METRIC_RE = re.compile(r"lavfi\.(?:signalstats\.)?(\w+)=(-?[0-9.]+)")
_FRAME_TS_RE = re.compile(r"frame:\d+\s+pts:\S+\s+pts_time:([0-9.]+)")


def _parse_metrics(text: str) -> list[dict]:
    """Parse ffmpeg ``metadata=print`` output into one dict per frame."""
    rows: list[dict] = []
    cur: dict | None = None
    for line in text.splitlines():
        line = line.strip()
        ts = _FRAME_TS_RE.match(line)
        if ts:
            if cur:
                rows.append(cur)
            cur = {"t": float(ts.group(1))}
            continue
        m = _METRIC_RE.match(line)
        if m and cur is not None:
            try:
                cur[m.group(1)] = float(m.group(2))
            except ValueError:
                pass
    if cur:
        rows.append(cur)
    return [r for r in rows if "blur" in r and "YAVG" in r]


def score_candidate_frames(
    video_path: str,
    rank_fps: float = CANDIDATE_RANK_FPS,
    start_seconds: float | None = None,
    end_seconds: float | None = None,
) -> list[dict]:
    """Run one analysis pass and return per-frame technical metrics."""
    if shutil.which("ffmpeg") is None:
        raise SystemExit("ffmpeg is not installed. Install with: brew install ffmpeg")

    pre_seek = ["-ss", f"{start_seconds:.3f}"] if start_seconds else []
    duration = ["-t", f"{end_seconds - (start_seconds or 0):.3f}"] if end_seconds else []
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        *pre_seek,
        "-i", str(Path(video_path).resolve()),
        *duration,
        "-vf",
        f"fps={rank_fps},scale={CANDIDATE_SCALE_WIDTH}:-2,"
        "blurdetect=block_pct=80,signalstats,metadata=print:file=-",
        "-an", "-f", "null", "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    rows = _parse_metrics(result.stdout)
    # Timestamps are relative to the seek point; report them absolute.
    if start_seconds:
        for r in rows:
            r["t"] += start_seconds
    return rows


# A bucket whose sharpest frame is still softer than this fraction of the
# video's own frames has nothing worth looking at, and its slot is dropped.
# Expressed as a percentile of *this* video rather than an absolute blurdetect
# number, because that number is content-dependent — a soft-lit food video and
# a crisp studio one occupy different ranges, and an absolute cutoff would
# empty the shortlist on one and never fire on the other.
CANDIDATE_MIN_SHARPNESS = 0.50


def rank_thumbnail_candidates(
    rows: list[dict],
    count: int = DEFAULT_CANDIDATE_COUNT,
    min_sharpness: float = CANDIDATE_MIN_SHARPNESS,
) -> list[dict]:
    """Shortlist ``count`` technically-usable frames spread across the timeline.

    Buckets the timeline into ``count`` equal spans and returns the best-quality
    frame in each. Bucketing rather than global top-N is what guarantees the
    shortlist covers both ends of the video — a global ranking clusters on
    whichever single well-lit sequence happens to score highest, which on a
    recipe video is usually one long mid-process shot.

    Blur is disqualifying *here* and nowhere else. A motion-blurred frame is
    often the most informative one for the recipe itself — hands pouring,
    stirring, adding — so the reading pass keeps it. It can never be a good
    card image, so the candidate pool drops it: bucket-best already excludes
    blurry frames wherever a sharp one exists nearby, and ``min_sharpness``
    additionally drops a bucket whose *best* frame is still soft, rather than
    spending a candidate slot on the least-bad frame of a blurry stretch.
    """
    usable = [r for r in rows if 60.0 <= r.get("YAVG", 0.0) <= 200.0]
    if not usable:
        usable = list(rows)
    if not usable:
        return []

    # Sharpness as a percentile of this video: 1.0 = sharpest frame in it.
    blurs = sorted(r["blur"] for r in usable)
    span_b = max(len(blurs) - 1, 1)

    def sharpness(blur: float) -> float:
        return 1.0 - bisect.bisect_left(blurs, blur) / span_b

    lo = min(r["t"] for r in usable)
    hi = max(r["t"] for r in usable)
    span = max(hi - lo, 1e-6)
    buckets: dict[int, list[dict]] = {}
    for r in usable:
        i = min(count - 1, int((r["t"] - lo) / span * count))
        buckets.setdefault(i, []).append(r)

    out: list[dict] = []
    for i in sorted(buckets):
        # Lower blurdetect score = sharper. Saturation breaks ties only; it is
        # not trustworthy as a primary signal (see the module comment above).
        best = min(buckets[i], key=lambda r: (r["blur"], -r.get("SATAVG", 0.0)))
        sharp = sharpness(best["blur"])
        if sharp < min_sharpness and len(buckets) > 1:
            continue
        out.append({
            "timestamp_seconds": round(best["t"], 2),
            "sharpness": round(sharp, 3),
            "blur": round(best["blur"], 3),
            "saturation": round(best.get("SATAVG", 0.0), 1),
            "brightness": round(best.get("YAVG", 0.0), 1),
            "bucket": i,
        })
    return out


def extract_keyframes(
    video_path: str,
    out_dir: Path,
    resolution: int = 512,
    max_frames: int | None = 50,
    start_seconds: float | None = None,
    end_seconds: float | None = None,
    dedup: bool = True,
) -> tuple[list[dict], dict]:
    """Decode only keyframes (I-frames) — the cheap, near-instant tier.

    ``-skip_frame nokey`` makes ffmpeg reconstruct only keyframes, skipping all
    P/B frames. Encoders emit keyframes at scene cuts, so these already
    approximate "distinct moments". Near-identical frames are dropped
    (:func:`dedupe_perceptual`, unless ``dedup`` is False); over-cap →
    even-sample first→last; too few keyframes → uniform fallback.
    """
    if shutil.which("ffmpeg") is None:
        raise SystemExit("ffmpeg is not installed. Install with: brew install ffmpeg")

    out_dir.mkdir(parents=True, exist_ok=True)
    for existing in out_dir.glob("frame_*.jpg"):
        existing.unlink()

    output_pattern = str(out_dir / "frame_%04d.jpg")
    cmd: list[str] = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "info",
        "-y",
    ]
    if start_seconds is not None:
        cmd += ["-ss", f"{start_seconds:.3f}"]
    if end_seconds is not None:
        cmd += ["-to", f"{end_seconds:.3f}"]
    cmd += [
        "-skip_frame", "nokey",
        "-i", str(Path(video_path).resolve()),
        "-vf", f"{_scale_filter(resolution)},showinfo",
        "-vsync", "vfr",
        "-q:v", "4",
        output_pattern,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"ffmpeg keyframe extraction failed: {result.stderr.strip()}")

    offset = start_seconds or 0.0
    timestamps = [round(offset + float(m.group(1)), 2) for m in SHOWINFO_TS_RE.finditer(result.stderr)]
    files = sorted(out_dir.glob("frame_*.jpg"))
    candidates: list[dict] = []
    for i, path in enumerate(files):
        ts = timestamps[i] if i < len(timestamps) else offset
        candidates.append({
            "index": i,
            "timestamp_seconds": ts,
            "path": str(path),
            "reason": "keyframe",
        })

    # Too few keyframes → uniform fallback over the same range.
    if len(candidates) < KEYFRAME_MIN:
        for cand in candidates:
            try:
                Path(cand["path"]).unlink()
            except OSError:
                pass
        meta = get_metadata(video_path)
        full_duration = meta["duration_seconds"]
        eff_start = start_seconds or 0.0
        eff_end = end_seconds if end_seconds is not None else full_duration
        eff_duration = max(0.0, eff_end - eff_start)
        budget = max_frames if max_frames is not None else 100
        fps, _ = auto_fps(eff_duration, max_frames=budget)
        frames_out = extract(
            video_path,
            out_dir,
            fps=fps,
            resolution=resolution,
            max_frames=budget,
            start_seconds=start_seconds,
            end_seconds=end_seconds,
        )
        n_dropped = 0
        if dedup:
            frames_out, n_dropped = dedupe_perceptual(frames_out)
        return frames_out, {
            "engine": "uniform",
            "candidate_count": len(candidates),
            "deduped_count": n_dropped,
            "selected_count": len(frames_out),
            "fallback": True,
        }

    # Detect-all, drop near-duplicates, then even-sample down to the cap (first +
    # last always kept). ``max_frames is None`` (uncapped) keeps every keyframe.
    candidate_count = len(candidates)
    deduped, n_dropped = dedupe_perceptual(candidates) if dedup else (candidates, 0)
    cap = len(deduped) if max_frames is None else max_frames
    selected = _even_sample(deduped, cap)
    return selected, {
        "engine": "keyframe",
        "candidate_count": candidate_count,
        "deduped_count": n_dropped,
        "selected_count": len(selected),
        "fallback": False,
    }


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(
            "usage: frames.py <video-path> <out-dir> [--fps F] [--resolution W] "
            "[--max-frames N] [--start T] [--end T] [--no-dedup] "
            "[--thumbnail-at T] [--thumbnail-resolution W] "
            "[--rank-candidates] [--candidates N] [--rank-fps F] "
            "[--timestamps T1,T2,...] [--candidate-resolution W]",
            file=sys.stderr,
        )
        raise SystemExit(2)

    video = sys.argv[1]
    out = Path(sys.argv[2])
    args = sys.argv[3:]

    fps_override = None
    resolution = 512
    max_frames = 100
    start_arg = None
    end_arg = None
    dedup = True
    thumbnail_at_arg: str | None = None
    thumbnail_resolution: int | None = None
    rank_candidates = False
    candidate_count = DEFAULT_CANDIDATE_COUNT
    rank_fps = CANDIDATE_RANK_FPS
    timestamps_arg: str | None = None
    candidate_resolution = CANDIDATE_READ_RESOLUTION
    i = 0
    while i < len(args):
        if args[i] == "--fps":
            fps_override = float(args[i + 1]); i += 2
        elif args[i] == "--resolution":
            resolution = int(args[i + 1]); i += 2
        elif args[i] == "--max-frames":
            max_frames = int(args[i + 1]); i += 2
        elif args[i] == "--start":
            start_arg = args[i + 1]; i += 2
        elif args[i] == "--end":
            end_arg = args[i + 1]; i += 2
        elif args[i] == "--no-dedup":
            dedup = False; i += 1
        elif args[i] == "--thumbnail-at":
            thumbnail_at_arg = args[i + 1]; i += 2
        elif args[i] == "--thumbnail-resolution":
            thumbnail_resolution = int(args[i + 1]); i += 2
        elif args[i] == "--rank-candidates":
            rank_candidates = True; i += 1
        elif args[i] == "--candidates":
            candidate_count = int(args[i + 1]); i += 2
        elif args[i] == "--rank-fps":
            rank_fps = float(args[i + 1]); i += 2
        elif args[i] == "--timestamps":
            timestamps_arg = args[i + 1]; i += 2
        elif args[i] == "--candidate-resolution":
            candidate_resolution = int(args[i + 1]); i += 2
        else:
            # A typo is not a request for the defaults. Silently ignoring it
            # meant `--resolutionn 1024` extracted at the 512 default and still
            # printed success JSON — a quiet halving of the legibility the
            # caller explicitly asked for.
            print(f"unknown option {args[i]!r}", file=sys.stderr)
            raise SystemExit(2)

    # Shortlist thumbnail candidates without spending a single image token.
    # Emits timestamps only — re-grab the ones you want with --thumbnail-at.
    if rank_candidates:
        start_sec = parse_time(start_arg)
        end_sec = parse_time(end_arg)
        scored = score_candidate_frames(
            video, rank_fps=rank_fps, start_seconds=start_sec, end_seconds=end_sec,
        )
        shortlist = rank_thumbnail_candidates(scored, count=candidate_count)
        print(json.dumps({
            "scored_frames": len(scored),
            "candidates": shortlist,
            "note": (
                "Technical quality only — these are frames worth looking at, not a "
                "ranked pick. Pixel statistics cannot distinguish a finished dish from "
                "raw ingredients; read the shortlist and choose, then re-grab your pick "
                "at full resolution with --thumbnail-at."
            ),
        }, indent=2))
        raise SystemExit(0)

    # Batch-grab the shortlist from --rank-candidates so it can be looked at.
    # These are reading frames, not thumbnails: area-capped, low resolution,
    # written under their own `cand_` prefix so they clobber neither the
    # detail-engine frames nor a `thumb_` grab. One call, because
    # --thumbnail-at clears its own prefix on entry and so keeps only the last
    # timestamp when called in a loop.
    if timestamps_arg is not None:
        points = [parse_time(t.strip()) for t in timestamps_arg.split(",") if t.strip()]
        points = [t for t in points if t is not None]
        frames_out, meta_out = extract_at_timestamps(
            video, out, points,
            resolution=candidate_resolution,
            prefix="cand",
            quality=4,
            reason="thumbnail-candidate",
        )
        print(json.dumps({
            "requested": points,
            "resolution": candidate_resolution,
            "frames": frames_out,
            "meta": meta_out,
        }, indent=2))
        raise SystemExit(0)

    # Grab exactly one frame to *be* the thumbnail — either re-grabbing the
    # timestamp of the #1 pick at full resolution (the normal path; the reading
    # frames are deliberately downscaled and make a soft card image), or a
    # manual override that skips the Step 5.5 ranking entirely.
    #
    # Uses the same two-stage seek as every other timestamp-anchored grab (see
    # _two_stage_seek's docstring for why that matters for a clean frame), but
    # at THUMBNAIL_RESOLUTION / THUMBNAIL_QUALITY rather than the reading
    # settings, and under a `thumb_` prefix so it doesn't clear cue frames.
    if thumbnail_at_arg is not None:
        t = parse_time(thumbnail_at_arg)
        target_res = thumbnail_resolution or max(resolution, THUMBNAIL_RESOLUTION)
        frames_out, meta_out = extract_at_timestamps(
            video, out, [t],
            resolution=target_res,
            prefix="thumb",
            quality=THUMBNAIL_QUALITY,
            reason="thumbnail",
            # No area cap: this frame is written to disk to be cropped and
            # uploaded, never read into a context window.
            max_pixels=None,
        )
        print(json.dumps(
            {
                "thumbnail_at": t,
                "requested_resolution": target_res,
                "frames": frames_out,
                "meta": meta_out,
            },
            indent=2,
        ))
        raise SystemExit(0)

    meta = get_metadata(video)
    start_sec = parse_time(start_arg)
    end_sec = parse_time(end_arg)
    full_duration = meta["duration_seconds"]

    effective_start = start_sec if start_sec is not None else 0.0
    effective_end = end_sec if end_sec is not None else full_duration
    effective_duration = max(0.0, effective_end - effective_start)

    focused = start_sec is not None or end_sec is not None
    if focused:
        fps, target = auto_fps_focus(effective_duration, max_frames=max_frames)
    else:
        fps, target = auto_fps(effective_duration, max_frames=max_frames)
    if fps_override is not None:
        fps = fps_override
        target = max(1, int(round(fps * effective_duration)))

    frames = extract(
        video, out,
        fps=fps,
        resolution=resolution,
        max_frames=max_frames,
        start_seconds=start_sec,
        end_seconds=end_sec,
    )
    deduped_count = 0
    if dedup:
        frames, deduped_count = dedupe_perceptual(frames)
    print(json.dumps(
        {
            "meta": meta, "fps": fps, "target": target, "focused": focused,
            "deduped_count": deduped_count, "frames": frames,
        },
        indent=2,
    ))
