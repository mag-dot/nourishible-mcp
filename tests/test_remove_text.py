import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "recipe-nourishible" / "scripts"))

try:
    import cv2
    import numpy as np
    # remove_text exits at import time when cv2 is missing, so catch
    # SystemExit as well as ImportError here.
    from remove_text import auto_boxes, inpaint_boxes
    HAS_CV2 = True
except (ImportError, SystemExit):
    HAS_CV2 = False


@unittest.skipUnless(HAS_CV2, "opencv not installed")
class AutoBoxesTests(unittest.TestCase):
    def _scene(self):
        # Dark wood background, food-coloured middle that must not produce
        # a box.
        im = np.full((720, 1280, 3), 90, np.uint8)
        im[300:600, 400:900] = (60, 140, 200)
        return im

    def test_finds_a_caption_line_in_the_top_band(self):
        im = self._scene()
        cv2.rectangle(im, (30, 25), (300, 55), (255, 255, 255), -1)
        boxes = auto_boxes(im)
        self.assertEqual(1, len(boxes))
        x0, y0, x1, y1 = boxes[0]
        self.assertLess(y0, 130)  # top band
        self.assertGreater(x1, 200)

    def test_clean_frame_finds_nothing(self):
        self.assertEqual([], auto_boxes(self._scene()))

    def test_dark_logo_box_is_filled_wholesale(self):
        im = np.full((720, 1280, 3), 220, np.uint8)  # bright wall
        cv2.rectangle(im, (1180, 20), (1260, 110), (0, 0, 0), -1)  # black logo
        cv2.rectangle(im, (1200, 40), (1240, 70), (255, 255, 255), -1)  # white figure
        out, _ = inpaint_boxes(im, [(1180, 20, 1260, 110)], 205, fill_dark=True)
        region = out[20:110, 1180:1260]
        self.assertGreater(float(region.mean()), 180)  # wall, not black

    def test_white_only_mask_leaves_a_dark_logo_behind(self):
        # The failure --auto used to have: masking just the white figure
        # leaves the black square. Documents why fill_dark exists.
        im = np.full((720, 1280, 3), 220, np.uint8)
        cv2.rectangle(im, (1180, 20), (1260, 110), (0, 0, 0), -1)
        cv2.rectangle(im, (1200, 40), (1240, 70), (255, 255, 255), -1)
        out, _ = inpaint_boxes(im, [(1180, 20, 1260, 110)], 205, fill_dark=False)
        region = out[20:110, 1180:1260]
        self.assertLess(float(region.mean()), 180)


if __name__ == "__main__":
    unittest.main()
