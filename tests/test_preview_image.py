"""Fluxo inicial da prévia usa a referência visual do Studio 3.x."""
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from berofel.ui.window import PreviewImage
except ImportError:
    QApplication=None


@unittest.skipUnless(QApplication is not None,'PySide6 indisponível neste ambiente')
class PreviewWelcomeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def test_welcome_cta_emits_import_request_only_when_clicked(self):
        preview=PreviewImage()
        preview.resize(640,360)
        requests=[]
        preview.import_requested.connect(lambda:requests.append(True))
        preview.show();self.app.processEvents()

        rect=preview._welcome_button_rect()
        QTest.mouseClick(preview,Qt.MouseButton.LeftButton,
                         pos=rect.center())
        self.assertEqual(requests,[True])
        QTest.mouseClick(preview,Qt.MouseButton.LeftButton,
                         pos=preview.rect().topLeft()+type(rect.center())(4,4))
        self.assertEqual(requests,[True])
        preview.setFocus()
        QTest.keyClick(preview,Qt.Key.Key_Return)
        self.assertEqual(requests,[True,True])
        self.assertEqual(preview.accessibleName(),'Importar vídeo')
        preview.close()

    def test_compact_welcome_button_stays_inside_short_preview(self):
        preview=PreviewImage()
        preview.resize(640,100)
        rect=preview._welcome_button_rect()
        self.assertEqual(rect.height(),30)
        self.assertGreaterEqual(rect.top(),0)
        self.assertLessEqual(rect.bottom()+1,preview.height())
        preview.close()


if __name__=='__main__':
    unittest.main()
