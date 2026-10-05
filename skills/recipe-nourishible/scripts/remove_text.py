#!/usr/bin/env python3
"""Remove burned-in text (a title card, caption, "gf / df" label) from a thumbnail.

Thumbnails must carry no text. When the best frame has on-screen text laid over the
food, run this on the full-resolution `thumb_*.jpg` before uploading it.

    python3 remove_text.py IN.jpg OUT.jpg --box x0,y0,x1,y1 [--min-channel 205]

`--box` is a pixel rectangle around the text, in the image's own coordinates; read it off
the frame you are looking at, with a little margin. Inside it, near-white low-saturation
pixels (white lettering) are masked, grown slightly to cover anti-aliased edges, and
inpainted from the surrounding food. Pixels outside the box are untouched, so salt flakes
and highlights elsewhere in the frame survive. Coloured text: lower --min-channel is
no use; pick a frame without it instead.

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


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--box", required=True, help="x0,y0,x1,y1 around the text")
    ap.add_argument("--min-channel", type=int, default=205, help="lowest B/G/R value counted as white text")
    args = ap.parse_args()

    im = cv2.imread(args.src)
    if im is None:
        sys.exit(f"cannot read {args.src}")
    x0, y0, x1, y1 = (int(v) for v in args.box.split(","))

    roi = np.zeros(im.shape[:2], np.uint8)
    roi[max(y0, 0):y1, max(x0, 0):x1] = 255
    b, g, r = (im[:, :, i].astype(int) for i in range(3))
    white = ((np.minimum(np.minimum(b, g), r) > args.min_channel) & (np.abs(r - b) < 45)).astype(np.uint8) * 255
    mask = cv2.dilate(cv2.bitwise_and(white, roi), np.ones((5, 5), np.uint8), iterations=2)
    cv2.imwrite(args.dst, cv2.inpaint(im, mask, 5, cv2.INPAINT_TELEA), [cv2.IMWRITE_JPEG_QUALITY, 92])
    print(f"masked {int((mask > 0).sum())} px -> {args.dst}")


if __name__ == "__main__":
    main()
