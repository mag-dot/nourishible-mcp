#!/usr/bin/env python3
"""Setup / preflight for /watch.

Modes:
  setup.py --check      Silent preflight. Exit 0 if ready, 2/3/4 on failure.
  setup.py --json       Machine-readable status for Claude to parse.
  setup.py              Installer. Auto-installs deps, scaffolds .env, marks SETUP_COMPLETE.
  setup.py --check-capture   Silent preflight for the Instagram capture profile (tier 1 only).
  setup.py --json-capture    Machine-readable capture-profile status.
  setup.py --install-capture Installer for the capture profile (see CAPTURE_BINARIES below).

Design:
- Silent on success: --check exits 0 with no output when everything's ready so
  that /watch doesn't spam "setup is complete" on every turn.
- Idempotent: re-running the installer is safe — it never clobbers existing
  keys and only appends missing ones.
- SETUP_COMPLETE=true in ~/.config/watch/.env tells us the user has been
  through a successful installer run at least once.
- Never sudo. On macOS, auto-install via brew. Elsewhere, print exact commands.
- Never write an API key to disk automatically — only scaffold placeholders.

The capture profile (Instagram, via recipe-extract — see
PRODUCT-STRATEGY.md §3.11/§4.3) is deliberately a SEPARATE, opt-in preflight
from the one above rather than folded into it: a user who only ever extracts
YouTube links should never be asked to install Whisper, compile Swift, or
grant a macOS permission they don't need. Tier 1 only (no BlackHole/Multi-
Output Device) — that needs sudo and Audio MIDI Setup, neither of which this
script can do, and BlackHole is optional besides (capture.sh degrades to the
microphone gracefully, and a recipe reel's ingredients live in on-screen
text/OCR far more reliably than in narration).
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from config import get_config  # noqa: E402


REQUIRED_BINARIES = ["ffmpeg", "ffprobe", "yt-dlp"]
CONFIG_DIR = Path.home() / ".config" / "watch"
CONFIG_FILE = CONFIG_DIR / ".env"
ENV_TEMPLATE = """# /watch API configuration
#
# Whisper transcription fallback — used only when yt-dlp cannot get captions
# (or when you point /watch at a local file with no subtitles).
#
# Groq is preferred: it runs whisper-large-v3 at a fraction of OpenAI's price
# and is faster in practice. OpenAI is the compatible fallback.
#
# Get a Groq key:  https://console.groq.com/keys
# Get an OpenAI key:  https://platform.openai.com/api-keys
#
# Leave both blank to disable Whisper — /watch will still work, but videos
# without native captions will come back frames-only.

GROQ_API_KEY=
OPENAI_API_KEY=

# Default watch behavior (the /watch first-run wizard sets this for you).
# Allowed values: transcript | efficient | balanced | token-burner
# Keep the value on its own line with no trailing comment.
# WATCH_DETAIL=balanced

# Cookies for login-sensitive YouTube requests (anonymous requests are
# sometimes bot-gated). Set ONE of these:
#
# Read cookies straight from an installed, logged-in browser (simplest —
# just stay logged into that browser):
# WATCH_COOKIES_FROM_BROWSER=chrome
#
# Or point at an exported Netscape-format cookies.txt (takes precedence):
# WATCH_COOKIES_FILE=/path/to/cookies.txt
#
# YouTube video CDN failures (SSL/TLS to googlevideo.com) often clear up
# with browser cookies + an up-to-date yt-dlp. Run setup.py to install
# curl_cffi into the Homebrew yt-dlp environment.
#
# NOTE: this does NOT apply to Instagram. yt-dlp's Instagram extractor
# returns HTTP 400 even with valid, cookie-authenticated requests (tested
# 15 Aug 2026 — upstream breakage, not a config gap). Instagram is handled
# by scripts/capture/ instead — a local screen capture, not an API request —
# see the recipe-extract skill and CAPTURE_BINARIES below.
"""

# --- Instagram capture profile (recipe-extract skill) -----------------------
#
# Tier 1 only. whisper-cli/node/swiftc are checked but a missing one only
# degrades that specific feature (no transcript, no re-catalog step) rather
# than blocking capture outright — capture.sh's own OCR-only fallback is
# already the point, not a failure mode to avoid.
CAPTURE_BINARIES = ["whisper-cli", "node", "swiftc"]
WHISPER_MODEL_DIR = Path.home() / ".whisper-models"
WHISPER_MODEL_PATH = WHISPER_MODEL_DIR / "ggml-base.en.bin"
WHISPER_MODEL_URL = (
    "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin"
)
# ~141MB — base.en, not large-v3-turbo (1.6GB): good enough for recipe
# narration, and the smaller download matters more here than it does for
# ig-saved's own setup, since this runs unattended as part of a skill
# install rather than a person choosing to wait for it.
OCR_BIN_DIR = Path.home() / ".local" / "bin"
OCR_BIN_PATH = OCR_BIN_DIR / "ocr"
OCR_SOURCE = SCRIPT_DIR / "capture" / "ocr.swift"


def _which(name: str) -> str | None:
    return shutil.which(name)


def _check_binaries() -> list[str]:
    return [b for b in REQUIRED_BINARIES if not _which(b)]


_PERM_WARNED: set[str] = set()


def _check_file_permissions(path: Path) -> None:
    """Warn to stderr (once per path per process) if a secrets file is
    world/group readable."""
    key = str(path)
    if key in _PERM_WARNED:
        return
    try:
        mode = path.stat().st_mode
        if mode & 0o044:
            _PERM_WARNED.add(key)
            sys.stderr.write(
                f"[watch] WARNING: {path} is readable by other users. "
                f"Run: chmod 600 {path}\n"
            )
            sys.stderr.flush()
    except OSError:
        pass


def _read_env_key(name: str) -> str | None:
    value = os.environ.get(name)
    if value and value.strip():
        return value.strip()
    if not CONFIG_FILE.exists():
        return None
    _check_file_permissions(CONFIG_FILE)
    try:
        for line in CONFIG_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, raw = line.partition("=")
            if key.strip() != name:
                continue
            raw = raw.strip()
            if len(raw) >= 2 and raw[0] in ('"', "'") and raw[-1] == raw[0]:
                raw = raw[1:-1]
            return raw or None
    except OSError:
        return None
    return None


def _have_api_key() -> tuple[bool, str | None]:
    if _read_env_key("GROQ_API_KEY"):
        return True, "groq"
    if _read_env_key("OPENAI_API_KEY"):
        return True, "openai"
    return False, None


def is_first_run() -> bool:
    """True if the installer hasn't completed successfully yet."""
    return _read_env_key("SETUP_COMPLETE") != "true"


def _scaffold_env() -> bool:
    """Create ~/.config/watch/.env with placeholders if missing."""
    if CONFIG_FILE.exists():
        return False
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(ENV_TEMPLATE, encoding="utf-8")
    try:
        CONFIG_FILE.chmod(0o600)
    except OSError:
        pass
    return True


def _write_setup_complete() -> None:
    """Idempotently append SETUP_COMPLETE=true to .env.

    Used only after a fully successful install (deps + key). Future sessions
    detect this marker to skip wizard-style UI and stay silent.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    existing = ""
    if CONFIG_FILE.exists():
        existing = CONFIG_FILE.read_text(encoding="utf-8")
        for line in existing.splitlines():
            if line.strip().startswith("SETUP_COMPLETE="):
                return
        if existing and not existing.endswith("\n"):
            existing += "\n"
        CONFIG_FILE.write_text(existing + "SETUP_COMPLETE=true\n", encoding="utf-8")
    else:
        CONFIG_FILE.write_text(ENV_TEMPLATE + "\nSETUP_COMPLETE=true\n", encoding="utf-8")
    try:
        CONFIG_FILE.chmod(0o600)
    except OSError:
        pass


def _brew_pkg(missing: list[str]) -> list[str]:
    pkgs: list[str] = []
    for bin_name in missing:
        if bin_name in ("ffmpeg", "ffprobe"):
            if "ffmpeg" not in pkgs:
                pkgs.append("ffmpeg")
        elif bin_name == "yt-dlp":
            if "yt-dlp" not in pkgs:
                pkgs.append("yt-dlp")
        else:
            pkgs.append(bin_name)
    return pkgs


def _install_macos(missing: list[str]) -> tuple[bool, str]:
    if _which("brew") is None:
        return False, (
            "Homebrew is not installed. Install it from https://brew.sh, then re-run setup. "
            "Or install manually: `brew install " + " ".join(_brew_pkg(missing)) + "`"
        )
    pkgs = _brew_pkg(missing)
    if not pkgs:
        return True, "nothing to install"
    cmd = ["brew", "install", *pkgs]
    print(f"[setup] running: {' '.join(cmd)}", file=sys.stderr)
    result = subprocess.run(cmd)
    if result.returncode != 0:
        return False, f"brew install failed with exit code {result.returncode}"
    return True, f"installed via brew: {', '.join(pkgs)}"


def _yt_dlp_python() -> Path | None:
    """Return the Python interpreter used by the yt-dlp on PATH, if known."""
    yt = _which("yt-dlp")
    if not yt:
        return None
    try:
        first = Path(yt).read_text(encoding="utf-8", errors="ignore").splitlines()[0]
    except OSError:
        return None
    if not first.startswith("#!"):
        return None
    interp = first[2:].strip()
    if interp.startswith("/"):
        return Path(interp) if Path(interp).is_file() else None
    resolved = _which(interp)
    return Path(resolved) if resolved else None


def _yt_dlp_has_curl_cffi() -> bool:
    py = _yt_dlp_python()
    if py is None:
        return False
    result = subprocess.run(
        [str(py), "-c", "import curl_cffi"],
        capture_output=True,
    )
    return result.returncode == 0


def _install_yt_dlp_extras() -> tuple[bool, str]:
    """Install curl_cffi into Homebrew yt-dlp's venv (macOS) for TLS impersonation."""
    py = _yt_dlp_python()
    if py is None:
        return False, "yt-dlp python interpreter not found — skip curl_cffi install"
    if _yt_dlp_has_curl_cffi():
        return True, "curl_cffi already available to yt-dlp"
    cmd = [str(py), "-m", "pip", "install", "-U", "curl_cffi>=0.10,<0.16"]
    print(f"[setup] running: {' '.join(cmd)}", file=sys.stderr)
    result = subprocess.run(cmd)
    if result.returncode != 0:
        return False, f"curl_cffi install failed (exit {result.returncode})"
    return True, "installed curl_cffi for yt-dlp (better YouTube TLS/impersonation)"


def _install_hint_linux(missing: list[str]) -> str:
    pkgs = _brew_pkg(missing)
    hints = []
    if "ffmpeg" in pkgs:
        hints.append("apt: `sudo apt install ffmpeg` or dnf: `sudo dnf install ffmpeg`")
    if "yt-dlp" in pkgs:
        hints.append("`pipx install yt-dlp` (recommended) or `pip install --user yt-dlp`")
    return "\n  ".join(hints) if hints else "nothing to install"


def _install_hint_windows(missing: list[str]) -> str:
    pkgs = _brew_pkg(missing)
    hints = []
    if "ffmpeg" in pkgs:
        hints.append("winget: `winget install Gyan.FFmpeg`")
    if "yt-dlp" in pkgs:
        hints.append("winget: `winget install yt-dlp.yt-dlp` or pip: `pip install --user yt-dlp`")
    return "\n  ".join(hints) if hints else "nothing to install"


# --- capture profile ---------------------------------------------------------


def _check_capture_binaries() -> list[str]:
    return [b for b in CAPTURE_BINARIES if not _which(b)]


def _capture_model_present() -> bool:
    return WHISPER_MODEL_PATH.exists() and WHISPER_MODEL_PATH.stat().st_size > 0


def _capture_ocr_present() -> bool:
    return OCR_BIN_PATH.exists() and os.access(OCR_BIN_PATH, os.X_OK)


def _screen_recording_status() -> str:
    """'granted' | 'denied' | 'unknown'.

    macOS's TCC.db (where this permission actually lives) is SIP-protected —
    even reading it as the logged-in user fails, so there is no direct query.
    The only reliable signal is trying a real 1-frame capture: a permitted
    process gets real pixel data back, a denied one gets a black/empty frame
    or an avfoundation error. 'unknown' covers everything that isn't macOS,
    a machine with no screen-capture device found, or a probe that itself
    failed to run for an unrelated reason — this function must never claim
    'denied' when it genuinely doesn't know, since that would send a user to
    System Settings for a permission they may already have.

    The device index is NOT hardcoded: avfoundation's video device list is
    machine-specific (a laptop webcam, an external "Desk View" camera, etc.
    can all sit at lower indices than the actual screen), and a fixed index
    probed the wrong device outright on a real machine during testing —
    same "capture screen" match capture.sh itself already uses.
    """
    if platform.system() != "Darwin":
        return "unknown"

    try:
        devices = subprocess.run(
            ["ffmpeg", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
            capture_output=True,
            text=True,
            timeout=10,
        ).stderr  # avfoundation always exits non-zero for -list_devices; stderr has the list regardless.
    except (subprocess.SubprocessError, OSError):
        return "unknown"

    screen_idx = None
    for line in devices.splitlines():
        if "capture screen" in line.lower():
            match = re.search(r"\[(\d+)\]", line)
            if match:
                screen_idx = match.group(1)
                break
    if screen_idx is None:
        return "unknown"

    probe = Path(os.environ.get("TMPDIR", "/tmp")) / f"watch-screencap-probe-{os.getpid()}.jpg"
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "avfoundation", "-framerate", "30", "-capture_cursor", "0",
                "-i", f"{screen_idx}:none", "-frames:v", "1", str(probe),
            ],
            capture_output=True,
            timeout=10,
        )
        if result.returncode == 0 and probe.exists() and probe.stat().st_size > 0:
            return "granted"
        return "denied"
    except (subprocess.SubprocessError, OSError):
        return "unknown"
    finally:
        probe.unlink(missing_ok=True)


def _open_screen_recording_settings() -> None:
    subprocess.run(
        ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"],
        check=False,
    )


def _download_whisper_model() -> tuple[bool, str]:
    WHISPER_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = WHISPER_MODEL_PATH.with_suffix(".part")
    try:
        import urllib.request

        print(f"[setup] downloading Whisper model (~141MB) to {WHISPER_MODEL_PATH}", file=sys.stderr)
        urllib.request.urlretrieve(WHISPER_MODEL_URL, tmp_path)  # noqa: S310 — fixed, HTTPS, hardcoded URL
        if tmp_path.stat().st_size < 1_000_000:
            tmp_path.unlink(missing_ok=True)
            return False, "downloaded file was suspiciously small — network issue or a changed URL upstream"
        tmp_path.rename(WHISPER_MODEL_PATH)
        return True, f"downloaded to {WHISPER_MODEL_PATH}"
    except OSError as err:
        tmp_path.unlink(missing_ok=True)
        return False, f"download failed: {err}"


def _compile_ocr_binary() -> tuple[bool, str]:
    if not OCR_SOURCE.exists():
        return False, f"ocr.swift not found at {OCR_SOURCE} — is scripts/capture/ present?"
    OCR_BIN_DIR.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["swiftc", "-O", "-o", str(OCR_BIN_PATH), str(OCR_SOURCE)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False, f"swiftc failed: {result.stderr.strip()[-500:]}"
    return True, f"compiled to {OCR_BIN_PATH}"


def _capture_status() -> dict:
    missing_bin = _check_capture_binaries()
    has_model = _capture_model_present()
    has_ocr = _capture_ocr_present()
    screen_recording = _screen_recording_status()

    # capture.sh itself already degrades to the microphone when no virtual
    # audio device is installed, and OCR-only extraction is a documented,
    # working path (confirmed against a real capture — see YEA-352). So
    # ready-for-tier-1 means "the binaries/model/OCR exist and macOS will
    # let ffmpeg touch the screen", not "every optional extra is present".
    ready = (
        not missing_bin
        and has_model
        and has_ocr
        and screen_recording in ("granted", "unknown")
    )

    return {
        "ready": ready,
        "missing_binaries": missing_bin,
        "whisper_model_present": has_model,
        "ocr_binary_present": has_ocr,
        "ocr_binary_path": str(OCR_BIN_PATH),
        "screen_recording": screen_recording,
        "platform": platform.system(),
    }


def cmd_check_capture() -> int:
    """Silent-on-success preflight for the capture profile. Same exit-code
    shape as cmd_check: 0 ready, non-zero with one actionable stderr line."""
    s = _capture_status()
    if s["ready"]:
        return 0

    parts = []
    if s["missing_binaries"]:
        parts.append(f"missing: {', '.join(s['missing_binaries'])}")
    if not s["whisper_model_present"]:
        parts.append("no Whisper model")
    if not s["ocr_binary_present"]:
        parts.append("OCR binary not compiled")
    if s["screen_recording"] == "denied":
        parts.append("Screen Recording permission not granted")
    installer = Path(__file__).resolve()
    sys.stderr.write(
        f"[watch] Instagram capture setup incomplete ({'; '.join(parts)}). "
        f"Run: python3 {installer} --install-capture\n"
    )
    sys.stderr.flush()
    return 2


def cmd_json_capture() -> int:
    json.dump(_capture_status(), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def cmd_install_capture() -> int:
    if platform.system() != "Darwin":
        print(
            "[setup] Instagram capture (screen recording + Vision OCR) is macOS-only. "
            "On this platform, Instagram links aren't supported by recipe-extract — "
            "YouTube still works normally.",
            file=sys.stderr,
        )
        return 2

    missing_bin = _check_capture_binaries()
    if missing_bin:
        ok, msg = _install_macos(missing_bin)
        print(f"[setup] {msg}", file=sys.stderr)
        if not ok:
            return 2
        still_missing = _check_capture_binaries()
        if still_missing:
            # whisper-cli/node come from brew; swiftc ships with Xcode
            # Command Line Tools, which brew cannot install — hint at it
            # explicitly rather than reporting a bare "still missing".
            if "swiftc" in still_missing:
                print(
                    "[setup] swiftc still missing — install Xcode Command Line Tools: "
                    "xcode-select --install",
                    file=sys.stderr,
                )
            other = [b for b in still_missing if b != "swiftc"]
            if other:
                print(f"[setup] still missing after brew: {', '.join(other)}", file=sys.stderr)
            return 2

    if not _capture_model_present():
        ok, msg = _download_whisper_model()
        print(f"[setup] {msg}", file=sys.stderr)
        if not ok:
            return 2
    else:
        print(f"[setup] Whisper model already present: {WHISPER_MODEL_PATH}")

    if not _capture_ocr_present():
        ok, msg = _compile_ocr_binary()
        print(f"[setup] {msg}", file=sys.stderr)
        if not ok:
            return 2
    else:
        print(f"[setup] OCR binary already present: {OCR_BIN_PATH}")

    screen_recording = _screen_recording_status()
    if screen_recording == "denied":
        print(
            "[setup] Screen Recording permission is needed for Instagram capture. "
            "Opening System Settings — grant it to your terminal app, then re-run "
            "this command.",
            file=sys.stderr,
        )
        _open_screen_recording_settings()
        return 3
    elif screen_recording == "unknown":
        print(
            "[setup] Could not verify Screen Recording permission automatically — "
            "the first real capture will tell you if it's missing.",
            file=sys.stderr,
        )

    print("[setup] Instagram capture profile ready.")
    return 0


def _status() -> dict:
    """Structured preflight snapshot.

    `status` describes the *ideal* state (a Whisper key is encouraged), so a
    keyless install still reports `needs_key` on the very first run — that's
    the agent's cue to encourage adding one.

    `can_proceed` is the operational gate: /watch can run as long as the
    binaries are present AND the user has either set a key or already finished
    setup (consciously opting out of Whisper). A keyless user who completed
    setup is NOT nagged on every call.
    """
    missing = _check_binaries()
    has_key, backend = _have_api_key()
    setup_complete = not is_first_run()

    if not missing and has_key:
        status = "ready"
    elif missing and not has_key:
        status = "needs_install_and_key"
    elif missing:
        status = "needs_install"
    else:
        status = "needs_key"

    can_proceed = (not missing) and (has_key or setup_complete)

    cfg = get_config()
    return {
        "status": status,
        "can_proceed": can_proceed,
        "first_run": not setup_complete,
        "setup_complete": setup_complete,
        "missing_binaries": missing,
        "whisper_backend": backend,
        "has_api_key": has_key,
        "config_file": str(CONFIG_FILE),
        "watch_detail": cfg["detail"],
        "platform": platform.system(),
    }


def cmd_check() -> int:
    """Silent-on-success preflight.

    Exit 0 with no output when /watch can run. A keyless user who already
    finished setup (SETUP_COMPLETE=true) counts as ready — Whisper is
    encouraged, not required — so they are never nagged on follow-up calls.

    On a state that blocks /watch, print one actionable line to stderr:
      2 → binaries missing
      3 → genuine first run with no API key (encourage one)
      4 → both missing
    """
    s = _status()
    if s["can_proceed"]:
        return 0

    parts = []
    if s["missing_binaries"]:
        parts.append(f"missing binaries: {', '.join(s['missing_binaries'])}")
    if not s["has_api_key"] and not s["setup_complete"]:
        parts.append("no Whisper API key (GROQ_API_KEY or OPENAI_API_KEY)")
    installer = Path(__file__).resolve()
    sys.stderr.write(
        f"[watch] setup incomplete ({'; '.join(parts)}). "
        f"Run: python3 {installer}\n"
    )
    sys.stderr.flush()

    if s["missing_binaries"] and not s["has_api_key"]:
        return 4
    if s["missing_binaries"]:
        return 2
    return 3


def cmd_json() -> int:
    json.dump(_status(), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def cmd_install() -> int:
    missing = _check_binaries()
    installed_deps = False
    if missing:
        system = platform.system()
        if system == "Darwin":
            ok, msg = _install_macos(missing)
            print(f"[setup] {msg}", file=sys.stderr)
            if not ok:
                return 2
            still_missing = _check_binaries()
            if still_missing:
                print(f"[setup] still missing after install: {', '.join(still_missing)}", file=sys.stderr)
                return 2
            installed_deps = True
        elif system == "Linux":
            print("[setup] dependencies missing on Linux — please install:", file=sys.stderr)
            print("  " + _install_hint_linux(missing), file=sys.stderr)
            return 2
        elif system == "Windows":
            print("[setup] dependencies missing on Windows — please install:", file=sys.stderr)
            print("  " + _install_hint_windows(missing), file=sys.stderr)
            return 2
        else:
            print(f"[setup] unsupported platform ({system}) for auto-install. Install manually:", file=sys.stderr)
            print(f"  missing: {', '.join(missing)}", file=sys.stderr)
            return 2

    if _which("yt-dlp"):
        ok, msg = _install_yt_dlp_extras()
        print(f"[setup] {msg}", file=sys.stderr)

    created = _scaffold_env()
    if created:
        print(f"[setup] created config: {CONFIG_FILE}")
    else:
        print(f"[setup] config exists: {CONFIG_FILE}")

    has_key, backend = _have_api_key()
    if has_key:
        _write_setup_complete()
        print(f"[setup] ready. whisper backend: {backend}")
        if installed_deps:
            print("[setup] installed dependencies; /watch is fully set up.")
        return 0

    print("")
    print("[setup] one step left: add a Whisper API key.")
    print("")
    print(f"  Edit {CONFIG_FILE} and set either:")
    print("    GROQ_API_KEY=...    (preferred — cheaper, faster; get one at console.groq.com/keys)")
    print("    OPENAI_API_KEY=...  (fallback; get one at platform.openai.com/api-keys)")
    print("")
    print("  Without a key, /watch still works but videos without captions come back frames-only.")
    return 3


def main() -> int:
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg == "--check":
            return cmd_check()
        if arg == "--json":
            return cmd_json()
        if arg == "--check-capture":
            return cmd_check_capture()
        if arg == "--json-capture":
            return cmd_json_capture()
        if arg == "--install-capture":
            return cmd_install_capture()
    return cmd_install()


if __name__ == "__main__":
    raise SystemExit(main())
