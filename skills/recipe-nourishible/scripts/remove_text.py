#!/usr/bin/env python3
"""Remove burned-in text (a title card, caption, "gf / df" label) from a thumbnail.

Thumbnails must carry no text. When the best frame has on-screen text laid over the
food, run this on the full-resolution `thumb_*.jpg` before uploading it.

    python3 remove_text.py IN.jpg OUT.jpg --box x0,y0,x1,y1 [--min-channel 205]
    python3 remove_text.py IN.jpg OUT.jpg --auto

`--box` is a pixel rectangle around the text, in the image's own coordinates; read it off
the frame you are looking at, with a little margin. `--auto` finds the boxes itself
(see auto_boxes): captions and watermarks live on the top or bottom edge, so it only
looks there, and only at light lettering — the same white-text mask the manual path
uses. Try `--auto` first; measure a box by hand only if it misses text or masks food.

Inside each box, near-white low-saturation pixels (white lettering) are masked, grown
slightly to cover anti-aliased edges, and inpainted from the surrounding food. Pixels
outside the boxes are untouched, so salt flakes and highlights elsewhere in the frame
survive. Coloured text: lower --min-channel is no use; pick a frame without it instead.

Always open OUT.jpg afterwards and check only the dish remains. Needs
`pip install opencv-python-headless` (use a venv if the system Python is locked).
"""
import argparse
import sys

try:
    import cv2
    import numpy as np
except ImportError:
    sys.exit("remove_text.py needs opencv: pip install opencv-python-headless")

# Captions and watermarks sit on an edge, not over the food: look only in the
# top 18% and bottom 12% of the frame. Anything taller than a caption line is
# not text; anything narrower than a short word is a speck, not a line.
AUTO_TOP_FRAC = 0.18
AUTO_BOTTOM_FRAC = 0.12
AUTO_MIN_LINE_HEIGHT = 8
AUTO_MAX_LINE_HEIGHT = 60
AUTO_MIN_LINE_WIDTH = 30


def white_mask(im: np.ndarray, min_channel: int) -> np.ndarray:
    """Near-white, low-saturation pixels — white lettering, not food."""
    b, g, r = (im[:, :, i].astype(int) for i in range(3))
    white = ((np.minimum(np.minimum(b, g), r) > min_channel) & (np.abs(r - b) < 45)).astype(np.uint8) * 255
    return white


def auto_boxes(
    im: np.ndarray, min_channel: int = 205,
    top_frac: float = AUTO_TOP_FRAC, bottom_frac: float = AUTO_BOTTOM_FRAC,
) -> list[tuple[int, int, int, int]]:
    """Find burned-in caption/logo boxes without a hand-measured rectangle.

    Takes the white-text mask, keeps only the top and bottom bands, joins
    letters into lines with a wide horizontal close, and keeps the
    line-shaped components. Food in the middle of the frame is never
    touched, and scattered bright specks (salt, highlights) don't form a
    line, so they don't become a box either. Returns (x0, y0, x1, y1) boxes
    with a little margin for anti-aliased edges.
    """
    h, w = im.shape[:2]
    mask = white_mask(im, min_channel)
    band = np.zeros_like(mask)
    top_h = int(h * top_frac)
    bot_h = int(h * bottom_frac)
    band[:top_h, :] = mask[:top_h, :]
    if bot_h:
        band[h - bot_h:, :] = mask[h - bot_h:, :]
    closed = cv2.morphologyEx(
        band, cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (25, 3)),
    )
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes: list[tuple[int, int, int, int]] = []
    for cnt in contours:
        x, y, bw, bh = cv2.boundingRect(cnt)
        if AUTO_MIN_LINE_HEIGHT <= bh <= AUTO_MAX_LINE_HEIGHT and bw >= AUTO_MIN_LINE_WIDTH:
            boxes.append((
                max(0, x - 4), max(0, y - 4),
                min(w, x + bw + 4), min(h, y + bh + 4),
            ))
    # One caption line can split into two components; merge boxes that
    # overlap or nearly touch on the same band.
    boxes = sorted(boxes)
    merged: list[list[int]] = []
    for box in boxes:
        if (
            merged
            and box[0] <= merged[-1][2] + 12
            and box[1] <= merged[-1][3]
            and box[3] >= merged[-1][1]
        ):
            m = merged[-1]
            m[0] = min(m[0], box[0])
            m[1] = min(m[1], box[1])
            m[2] = max(m[2], box[2])
            m[3] = max(m[3], box[3])
        else:
            merged.append(list(box))
    return [tuple(b) for b in merged]


def inpaint_boxes(
    im: np.ndarray, boxes: list[tuple[int, int, int, int]], min_channel: int,
    fill_dark: bool = False,
) -> tuple[np.ndarray, int]:
    """Inpaint the lettering inside `boxes`; return (image, masked px).

    Normally only the white lettering inside a box is masked, so the
    background behind it survives. But a dark logo (white figure on a black
    square) defeats that: masking just the white figure leaves the black
    square behind. With `fill_dark`, a box whose contents are mostly dark
    gets filled wholesale instead — the whole box is logo, not background.
    """
    gray = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    white = white_mask(im, min_channel)
    mask = np.zeros(im.shape[:2], np.uint8)
    for x0, y0, x1, y1 in boxes:
        x0, y0 = max(x0, 0), max(y0, 0)
        region = np.zeros(im.shape[:2], np.uint8)
        region[y0:y1, x0:x1] = 255
        box_gray = gray[y0:y1, x0:x1]
        # A box that is mostly dark is a logo (white figure on a black
        # square), not background with lettering — fill it wholesale. 150
        # sits below bright food and plate (170+) and above dark logos and
        # dark-caption backgrounds, so a box over food keeps the
        # white-only mask.
        if fill_dark and box_gray.size and box_gray.mean() < 150:
            mask = cv2.bitwise_or(mask, region)
        else:
            mask = cv2.bitwise_or(mask, cv2.bitwise_and(white, region))
    mask = cv2.dilate(mask, np.ones((5, 5), np.uint8), iterations=2)
    return cv2.inpaint(im, mask, 5, cv2.INPAINT_TELEA), int((mask > 0).sum())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--box", help="x0,y0,x1,y1 around the text")
    ap.add_argument("--auto", action="store_true", help="detect caption/logo text in the top/bottom bands automatically")
    ap.add_argument("--min-channel", type=int, default=205, help="lowest B/G/R value counted as white text")
    args = ap.parse_args()

    if bool(args.box) == bool(args.auto):
        ap.error("--box and --auto are alternatives; pass exactly one")

    im = cv2.imread(args.src)
    if im is None:
        sys.exit(f"cannot read {args.src}")

    if args.auto:
        boxes = auto_boxes(im, args.min_channel)
        if not boxes:
            print("no text found in the top/bottom bands — nothing changed, no file written")
            return
        print(f"auto-detected boxes: {boxes}")
    else:
        x0, y0, x1, y1 = (int(v) for v in args.box.split(","))
        boxes = [(x0, y0, x1, y1)]

    out, masked = inpaint_boxes(im, boxes, args.min_channel, fill_dark=args.auto)
    cv2.imwrite(args.dst, out, [cv2.IMWRITE_JPEG_QUALITY, 92])
    print(f"masked {masked} px -> {args.dst}")


if __name__ == "__main__":
    main()
