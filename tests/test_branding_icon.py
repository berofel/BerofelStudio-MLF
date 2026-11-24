from pathlib import Path
import unittest

from PIL import Image
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication


ROOT = Path(__file__).resolve().parents[1]


class BrandingIconTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_source_svg_and_windows_icon_load(self):
        svg = ROOT / 'assets' / 'brand' / 'berofel_studio_mark.svg'
        ico = ROOT / 'assets' / 'brand' / 'berofel_studio.ico'
        self.assertTrue(svg.is_file())
        self.assertFalse(QIcon(str(svg)).isNull())
        self.assertTrue(ico.is_file())
        icon = QIcon(str(ico))
        self.assertFalse(icon.isNull())
        self.assertIn((256, 256), {(size.width(), size.height())
                                   for size in icon.availableSizes()})

    def test_ico_contains_expected_windows_sizes(self):
        ico = ROOT / 'assets' / 'brand' / 'berofel_studio.ico'
        with Image.open(ico) as image:
            self.assertEqual(image.format, 'ICO')
            self.assertEqual(set(image.info['sizes']), {
                (16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
                (128, 128), (256, 256)})


if __name__ == '__main__':
    unittest.main()
