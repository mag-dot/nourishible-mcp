#!/usr/bin/env python3
"""Build a labelled contact sheet of the frames considered for a thumbnail, and keep it.

The extraction working directory is deleted in Step 7, which throws away the evidence for
why a frame was picked. This writes one small sheet plus the picks to a durable folder so a
bad thumbnail can be revisited without re-downloading the video.

    python3 frame_sheet.py WORK_DIR --slug SLUG [--picked thumb_0001.jpg] [--dest DIR]

Every frame_*.jpg / cue_*.jpg / thumb_*.jpg under WORK_DIR is tiled, labelled with its file
name, and the --picked frame is outlined. Output goes to
~/.nourishible/frame-sheets/SLUG/ (override with --dest): sheet.jpg, the picked file, and
picks.txt. Needs Pillow.
"""
import argparse
import shutil
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:
    sys.exit("frame_sheet.py needs Pillow: pip install pillow")

TILE_W, COLS, MAX_FRAMES = 240, 6, 60


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("work_dir")
    ap.add_argument("--slug", required=True)
    ap.add_argument("--picked", help="file name of the frame used as the thumbnail")
    ap.add_argument("--dest")
    args = ap.parse_args()

    work = Path(args.work_dir).expanduser()
    frames = sorted(p for pat in ("frame_*.jpg", "cue_*.jpg", "thumb_*.jpg") for p in work.glob(pat))
    if not frames:
        sys.exit(f"no frames found in {work}")
    if len(frames) > MAX_FRAMES:
        step = len(frames) / MAX_FRAMES
        frames = [frames[int(i * step)] for i in range(MAX_FRAMES)]
        if args.picked and not any(p.name == args.picked for p in frames):
            frames.append(work / args.picked)

    tiles = []
    for p in frames:
        im = Image.open(p).convert("RGB")
        im = im.resize((TILE_W, round(im.height * TILE_W / im.width)))
        d = ImageDraw.Draw(im)
        d.rectangle((0, 0, TILE_W, 14), fill=(0, 0, 0))
        d.text((3, 1), p.name, fill=(255, 255, 255))
        if p.name == args.picked:
            d.rectangle((0, 0, im.width - 1, im.height - 1), outline=(255, 0, 0), width=4)
        tiles.append(im)

    rows = [tiles[i:i + COLS] for i in range(0, len(tiles), COLS)]
    row_h = [max(t.height for t in r) for r in rows]
    sheet = Image.new("RGB", (COLS * TILE_W, sum(row_h)), (30, 30, 30))
    y = 0
    for r, h in zip(rows, row_h):
        for i, t in enumerate(r):
            sheet.paste(t, (i * TILE_W, y))
        y += h

    dest = Path(args.dest).expanduser() if args.dest else Path.home() / ".nourishible" / "frame-sheets" / args.slug
    dest.mkdir(parents=True, exist_ok=True)
    sheet.save(dest / "sheet.jpg", quality=80)
    if args.picked and (work / args.picked).exists():
        shutil.copy2(work / args.picked, dest / args.picked)
    (dest / "picks.txt").write_text(f"picked: {args.picked or '(none recorded)'}\nframes on sheet: {len(frames)}\n")
    print(dest / "sheet.jpg")


if __name__ == "__main__":
    main()
