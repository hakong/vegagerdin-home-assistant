"""Tests for locally bundled Home Assistant brand images."""

from __future__ import annotations

import struct
import unittest
from pathlib import Path

BRAND_DIR = (
    Path(__file__).parents[1] / "custom_components" / "vegagerdin" / "brand"
)
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _png_header(path: Path) -> tuple[int, int, int, int, int]:
    """Return dimensions and relevant encoding fields from a PNG."""
    with path.open("rb") as image:
        if image.read(8) != PNG_SIGNATURE:
            raise AssertionError(f"{path.name} is not a PNG")
        length = struct.unpack(">I", image.read(4))[0]
        if image.read(4) != b"IHDR" or length != 13:
            raise AssertionError(f"{path.name} has an invalid IHDR")
        width, height, bit_depth, color_type, _, _, interlace = struct.unpack(
            ">IIBBBBB", image.read(13)
        )
    return width, height, bit_depth, color_type, interlace


class TestBrandAssets(unittest.TestCase):
    """Validate the Home Assistant local-brand contract."""

    def test_expected_brand_files(self) -> None:
        """Only supported light, dark, and hDPI filenames are bundled."""
        self.assertEqual(
            {path.name for path in BRAND_DIR.iterdir()},
            {
                "icon.png",
                "icon@2x.png",
                "logo.png",
                "logo@2x.png",
                "dark_logo.png",
                "dark_logo@2x.png",
            },
        )

    def test_brand_dimensions_and_encoding(self) -> None:
        """Images have required dimensions, alpha, and progressive encoding."""
        expected_heights = {
            "icon.png": 256,
            "icon@2x.png": 512,
            "logo.png": 256,
            "logo@2x.png": 512,
            "dark_logo.png": 256,
            "dark_logo@2x.png": 512,
        }
        for filename, expected_height in expected_heights.items():
            with self.subTest(filename=filename):
                width, height, bit_depth, color_type, interlace = _png_header(
                    BRAND_DIR / filename
                )
                self.assertEqual(height, expected_height)
                if filename.startswith("icon"):
                    self.assertEqual(width, height)
                else:
                    self.assertGreater(width, height)
                self.assertEqual(bit_depth, 8)
                self.assertIn(color_type, (4, 6), "PNG must include alpha")
                self.assertEqual(interlace, 1, "PNG must be progressive")


if __name__ == "__main__":
    unittest.main()
