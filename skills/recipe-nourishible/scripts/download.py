#!/usr/bin/env python3
"""Download a video via yt-dlp, or resolve a local file path.

Also fetches subtitles (manual first, then auto-generated) in VTT format so
transcribe.py can parse them without needing Whisper.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlparse


VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi", ".flv", ".wmv"}

# Hosts that routinely rate-limit or block anonymous yt-dlp requests unless a
# logged-in session is provided. Instagram in particular returns "login
# required" / 401s for many Reels and most Stories without cookies.
LOGIN_SENSITIVE_HOSTS = ("instagram.com", "www.instagram.com")

# Xiaohongshu (XHS/RED/小红书) — served either from the full domain or a short
# link (xhslink.cn) that 302s to it. yt-dlp ships a real extractor for this
# (unlike Instagram/TikTok), but a large fraction of XHS content is a photo
# carousel ("图文" note) with no video at all — that shape needs its own path,
# see download_xhs_images() below.
XIAOHONGSHU_HOSTS = ("xiaohongshu.com", "www.xiaohongshu.com", "xhslink.cn")


def _cookie_args(cookies_from_browser: str | None, cookies_file: str | None) -> list[str]:
    """Build the yt-dlp cookie flags, preferring an explicit cookies file."""
    if cookies_file:
        return ["--cookies", cookies_file]
    if cookies_from_browser:
        return ["--cookies-from-browser", cookies_from_browser]
    return []


def is_login_sensitive(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return any(host == h or host.endswith("." + h) for h in LOGIN_SENSITIVE_HOSTS)


def is_xiaohongshu(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return any(host == h or host.endswith("." + h) for h in XIAOHONGSHU_HOSTS)


def probe_xhs_note(url: str) -> dict:
    """Fetch a Xiaohongshu note's metadata via yt-dlp without downloading.

    Distinguishes a video note (has playable ``formats``) from a photo/图文
    note (image carousel, ``formats`` always empty — yt-dlp's XiaoHongShu
    extractor only ever populates formats from the note's video stream, which
    photo notes simply don't have). ``--ignore-no-formats-error`` is required
    or yt-dlp raises instead of returning the metadata for a photo note.
    """
    if shutil.which("yt-dlp") is None:
        raise SystemExit("yt-dlp is not installed. Install with: brew install yt-dlp")

    cmd = ["yt-dlp", "--ignore-no-formats-error", "-j", "--", url]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not result.stdout.strip():
        raise SystemExit(
            f"yt-dlp could not read this Xiaohongshu note (exit {result.returncode}): "
            f"{result.stderr.strip()}"
        )
    # -j prints one JSON object per line; a single note is always exactly one line.
    return json.loads(result.stdout.splitlines()[0])


def download_xhs_images(url: str, out_dir: Path) -> dict:
    """Download every image in a Xiaohongshu photo/图文 note (no video — a
    captioned image carousel). Returns image paths plus title/description/
    uploader/canonical-url, shaped like the ``info`` dict callers already get
    from the video path so watch.py's report-building code doesn't need two
    separate schemas.
    """
    info = probe_xhs_note(url)
    thumbnails = info.get("thumbnails") or []
    if not thumbnails:
        raise SystemExit("No images or video found in this Xiaohongshu note.")

    # Each image in the note appears twice in `thumbnails` — a lower-res
    # "...!nd_prv_..." preview and a "...!nd_dft_..." fuller version, sharing
    # the same `id`. Dedup by id, keeping whichever has the larger pixel area.
    best_by_id: dict[str, dict] = {}
    for thumb in thumbnails:
        tid = str(thumb.get("id"))
        area = (thumb.get("width") or 0) * (thumb.get("height") or 0)
        cur = best_by_id.get(tid)
        if cur is None or area > (cur.get("width") or 0) * (cur.get("height") or 0):
            best_by_id[tid] = thumb
    ordered = [
        best_by_id[k] for k in sorted(best_by_id, key=lambda k: int(k) if k.isdigit() else 0)
    ]

    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []
    for i, thumb in enumerate(ordered):
        img_url = thumb.get("url")
        if not img_url:
            continue
        dest = out_dir / f"image_{i:04d}.jpg"
        try:
            req = urllib.request.Request(img_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as resp, open(dest, "wb") as f:
                shutil.copyfileobj(resp, f)
            paths.append(str(dest))
        except Exception as exc:
            print(f"[watch] failed to download image {i}: {exc}", file=sys.stderr)

    if not paths:
        raise SystemExit("Failed to download any images from this Xiaohongshu note.")

    return {
        "image_paths": paths,
        "info": {
            "title": info.get("title"),
            "uploader": info.get("uploader_id"),
            "description": info.get("description"),
            # webpage_url is the resolved xiaohongshu.com/... URL, not the
            # xhslink.cn short link — use this as sourceUrl so dedup can key
            # off the stable note id instead of a rotating share token.
            "url": info.get("webpage_url") or url,
        },
    }


def is_url(source: str) -> bool:
    if source.startswith("-"):
        return False
    parsed = urlparse(source)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def resolve_local(path: str) -> dict:
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise SystemExit(f"File not found: {p}")
    if p.suffix.lower() not in VIDEO_EXTS:
        print(
            f"[watch] warning: {p.suffix} is not a known video extension, proceeding anyway",
            file=sys.stderr,
        )
    return {
        "video_path": str(p),
        "subtitle_path": None,
        "info": {"title": p.name, "url": str(p)},
        "downloaded": False,
    }


def _pick_subtitle(out_dir: Path) -> Path | None:
    candidates = sorted(out_dir.glob("video*.vtt"))
    if not candidates:
        return None
    preferred = [
        c for c in candidates
        if any(marker in c.name for marker in (".en.", ".en-US.", ".en-GB.", ".en-orig."))
    ]
    return preferred[0] if preferred else candidates[0]


def _pick_video(out_dir: Path) -> Path | None:
    for ext in (".mp4", ".mkv", ".webm", ".mov", ".m4a", ".mp3", ".opus"):
        for candidate in out_dir.glob(f"video*{ext}"):
            return candidate
    for candidate in out_dir.glob("video.*"):
        if candidate.suffix.lower() in VIDEO_EXTS:
            return candidate
    return None


def fetch_captions(
    url: str,
    out_dir: Path,
    cookies_from_browser: str | None = None,
    cookies_file: str | None = None,
) -> dict:
    """Fetch metadata and best available VTT captions without downloading video."""
    if shutil.which("yt-dlp") is None:
        raise SystemExit("yt-dlp is not installed. Install with: brew install yt-dlp")

    out_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(out_dir / "video.%(ext)s")
    cmd = [
        "yt-dlp",
        "--skip-download",
        "--write-info-json",
        "--write-subs",
        "--write-auto-subs",
        "--sub-langs", "en.*",
        "--sub-format", "vtt",
        "--convert-subs", "vtt",
        "--no-playlist",
        "--ignore-errors",
        *_cookie_args(cookies_from_browser, cookies_file),
        "-o", output_template,
        "--",
        url,
    ]
    result = subprocess.run(cmd, stdout=sys.stderr, stderr=sys.stderr)
    subtitle = _pick_subtitle(out_dir)
    info = _read_info(out_dir / "video.info.json", url)
    if (
        result.returncode != 0
        and not subtitle
        and is_login_sensitive(url)
        and not (cookies_from_browser or cookies_file)
    ):
        print(
            "[watch] this looks like Instagram — many Reels/Stories require a logged-in "
            "session. Set WATCH_COOKIES_FROM_BROWSER=chrome (or firefox/safari/edge) in "
            "~/.config/watch/.env, or pass --cookies-from-browser.",
            file=sys.stderr,
        )
    return {
        "video_path": None,
        "subtitle_path": str(subtitle) if subtitle else None,
        "info": info or {"url": url},
        "downloaded": False,
    }


def _read_info(info_path: Path, url: str) -> dict:
    info: dict = {}
    if info_path.exists():
        try:
            raw = json.loads(info_path.read_text(encoding="utf-8"))
            info = {
                "title": raw.get("title"),
                "uploader": raw.get("uploader") or raw.get("channel"),
                "duration": raw.get("duration"),
                "url": raw.get("webpage_url") or url,
            }
        except Exception as exc:
            print(f"[watch] info.json parse failed: {exc}", file=sys.stderr)
            info = {"url": url}
    return info


def download_url(
    url: str,
    out_dir: Path,
    audio_only: bool = False,
    cookies_from_browser: str | None = None,
    cookies_file: str | None = None,
) -> dict:
    if shutil.which("yt-dlp") is None:
        raise SystemExit("yt-dlp is not installed. Install with: brew install yt-dlp")

    out_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(out_dir / "video.%(ext)s")

    fmt = "ba/bestaudio" if audio_only else "bv*[height<=720]+ba/b[height<=720]/bv+ba/b"
    cmd = [
        "yt-dlp",
        "-N", "8",
        "-f", fmt,
        "--merge-output-format", "mp4",
        "--write-info-json",
        "--write-subs",
        "--write-auto-subs",
        "--sub-langs", "en.*",
        "--sub-format", "vtt",
        "--convert-subs", "vtt",
        "--no-playlist",
        "--ignore-errors",
        *_cookie_args(cookies_from_browser, cookies_file),
        "-o", output_template,
        "--",
        url,
    ]

    # yt-dlp may exit non-zero if a subtitle variant fails (e.g. 429) even when
    # the video itself downloaded fine. Treat "video file present" as success.
    result = subprocess.run(cmd, stdout=sys.stderr, stderr=sys.stderr)
    video = _pick_video(out_dir)
    if video is None:
        hint = ""
        if is_login_sensitive(url) and not (cookies_from_browser or cookies_file):
            hint = (
                " — this looks like Instagram; many Reels/Stories require a logged-in "
                "session. Set WATCH_COOKIES_FROM_BROWSER=chrome in ~/.config/watch/.env "
                "(or firefox/safari/edge), or pass --cookies-from-browser."
            )
        raise SystemExit(
            f"yt-dlp did not produce a video file in {out_dir} (exit {result.returncode}){hint}"
        )

    subtitle = _pick_subtitle(out_dir)
    info = _read_info(out_dir / "video.info.json", url)

    return {
        "video_path": str(video),
        "subtitle_path": str(subtitle) if subtitle else None,
        "info": info or {"url": url},
        "downloaded": True,
    }


def download(
    source: str,
    out_dir: Path,
    audio_only: bool = False,
    cookies_from_browser: str | None = None,
    cookies_file: str | None = None,
) -> dict:
    if is_url(source):
        return download_url(
            source,
            out_dir,
            audio_only=audio_only,
            cookies_from_browser=cookies_from_browser,
            cookies_file=cookies_file,
        )
    return resolve_local(source)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: download.py <url-or-path> <out-dir>", file=sys.stderr)
        raise SystemExit(2)
    result = download(sys.argv[1], Path(sys.argv[2]))
    print(json.dumps(result, indent=2))
