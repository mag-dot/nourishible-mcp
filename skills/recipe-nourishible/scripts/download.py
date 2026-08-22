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

YOUTUBE_HOSTS = ("youtube.com", "www.youtube.com", "youtu.be", "m.youtube.com")

# Extra yt-dlp flags tried in order when a YouTube video stream fails (SSL 403,
# SABR, PO-token gaps, …). Metadata/captions are fetched separately first.
YOUTUBE_DOWNLOAD_STRATEGIES: list[list[str]] = [
    [],
    ["--extractor-args", "youtube:player_client=android,web"],
    ["-N", "1"],
    ["--extractor-args", "youtube:player_client=tv_embedded,web"],
    ["--legacy-server-connect"],
]

_SSL_MARKERS = (
    "UNEXPECTED_EOF_WHILE_READING",
    "SSL_ERROR_SYSCALL",
    "SSL routines",
    "TLS connect error",
    "SSLEOFError",
)


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


def is_youtube(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    if host == "youtu.be":
        return True
    return any(host == h or host.endswith("." + h) for h in YOUTUBE_HOSTS)


def _looks_like_ssl_error(text: str) -> bool:
    upper = text.upper()
    return any(marker.upper() in upper for marker in _SSL_MARKERS)


def _brew_curl_bin() -> str | None:
    for candidate in (
        "/opt/homebrew/opt/curl/bin/curl",
        "/usr/local/opt/curl/bin/curl",
    ):
        if Path(candidate).is_file():
            return candidate
    return None


def _curl_downloader_args() -> list[str]:
    """Prefer Homebrew curl (OpenSSL) over macOS /usr/bin/curl (LibreSSL)."""
    curl_bin = _brew_curl_bin() or shutil.which("curl")
    if not curl_bin:
        return []
    return [
        "--downloader", "curl",
        "--downloader-args", f"curl:{curl_bin} -L --retry 5 --retry-all-errors --compressed",
    ]


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


def _base_download_cmd(
    url: str,
    out_dir: Path,
    audio_only: bool,
    cookies_from_browser: str | None,
    cookies_file: str | None,
) -> list[str]:
    output_template = str(out_dir / "video.%(ext)s")
    fmt = "ba/bestaudio" if audio_only else "bv*[height<=720]+ba/b[height<=720]/bv+ba/b"
    return [
        "yt-dlp",
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


def _run_yt_dlp(cmd: list[str]) -> tuple[int, str]:
    result = subprocess.run(cmd, stdout=sys.stderr, stderr=subprocess.PIPE, text=True)
    err = (result.stderr or "").strip()
    return result.returncode, err


def _youtube_strategy_list() -> list[list[str]]:
    strategies = [list(s) for s in YOUTUBE_DOWNLOAD_STRATEGIES]
    curl_args = _curl_downloader_args()
    if curl_args:
        strategies.append(curl_args)
        strategies.append(["-N", "1", *curl_args])
    return strategies


def download_youtube_thumbnail(
    url: str,
    out_dir: Path,
    cookies_from_browser: str | None = None,
    cookies_file: str | None = None,
) -> str | None:
    """Best-effort YouTube still when the video stream cannot be downloaded."""
    if shutil.which("yt-dlp") is None:
        return None

    out_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(out_dir / "thumb")
    cmd = [
        "yt-dlp",
        "--skip-download",
        "--write-thumbnail",
        "--convert-thumbnails", "jpg",
        "--no-playlist",
        *_cookie_args(cookies_from_browser, cookies_file),
        "-o", output_template,
        "--",
        url,
    ]
    subprocess.run(cmd, stdout=sys.stderr, stderr=sys.stderr)
    for candidate in sorted(out_dir.glob("thumb*.jpg")):
        return str(candidate)
    for candidate in sorted(out_dir.glob("thumb*")):
        if candidate.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
            return str(candidate)
    return None


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
    base_cmd = _base_download_cmd(
        url, out_dir, audio_only, cookies_from_browser, cookies_file,
    )

    strategies: list[list[str]] = [[]]
    if is_youtube(url):
        strategies = _youtube_strategy_list()

    last_error = ""
    for idx, extra in enumerate(strategies):
        if idx:
            label = " ".join(extra[:4])
            print(f"[watch] retrying download ({idx + 1}/{len(strategies)}): {label}…", file=sys.stderr)
        cmd = [*base_cmd[:1], *extra, *base_cmd[1:]]
        code, err = _run_yt_dlp(cmd)
        last_error = err
        video = _pick_video(out_dir)
        if video is not None:
            subtitle = _pick_subtitle(out_dir)
            info = _read_info(out_dir / "video.info.json", url)
            return {
                "video_path": str(video),
                "subtitle_path": str(subtitle) if subtitle else None,
                "info": info or {"url": url},
                "downloaded": True,
            }

    hint = ""
    if is_login_sensitive(url) and not (cookies_from_browser or cookies_file):
        hint = (
            " — this looks like Instagram; many Reels/Stories require a logged-in "
            "session. Set WATCH_COOKIES_FROM_BROWSER=chrome in ~/.config/watch/.env "
            "(or firefox/safari/edge), or pass --cookies-from-browser."
        )
    elif is_youtube(url) and _looks_like_ssl_error(last_error):
        hint = (
            " — YouTube's video CDN rejected the connection (SSL/TLS). Captions/metadata "
            "may still be available. Try: `brew upgrade yt-dlp`, run "
            "`python3 skills/recipe-nourishible/scripts/setup.py` to install curl_cffi, "
            "set WATCH_COOKIES_FROM_BROWSER=chrome, or use a different network/VPN. "
            "watch.py will fall back to the official thumbnail when the stream fails."
        )
    raise SystemExit(
        f"yt-dlp did not produce a video file in {out_dir} (exit {code}){hint}"
    )


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
