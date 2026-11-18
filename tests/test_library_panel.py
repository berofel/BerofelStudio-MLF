"""Teste do reflow compacto da Biblioteca em janelas estreitas."""
import os
import unittest

try:
    from PySide6.QtWidgets import QApplication
    from berofel.ui.library_panel import LibraryDock
except ImportError:
    QApplication=None


@unittest.skipUnless(QApplication is not None,'PySide6 indisponível neste ambiente')
class LibraryPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        cls.app=QApplication.instance() or QApplication([])

    def test_library_shortens_labels_below_245_pixels_and_restores_them(self):
        panel=LibraryDock()
        panel.resize(210,600)
        panel.show();self.app.processEvents()
        self.assertEqual(panel.heading.text(),'BIBLIOTECA')
        self.assertEqual(panel.import_button.text(),'+ Importar')
        self.assertEqual(panel.relink_button.text(),'↪ Relink mídia')
        self.assertEqual(panel.marker_heading.text(),'MARCADORES')
        self.assertEqual(panel.import_button.toolTip(),'Importar arquivos de mídia')
        panel.resize(270,600);self.app.processEvents()
        self.assertEqual(panel.heading.text(),'BIBLIOTECA DE MÍDIA')
        self.assertEqual(panel.import_button.text(),'+ Importar arquivos')
        self.assertEqual(panel.relink_button.text(),'↪ Relink mídia selecionada')
        self.assertEqual(panel.marker_heading.text(),'MARCADORES DA TIMELINE')
        panel.close()

    def test_library_actions_remain_reachable_in_short_windows(self):
        panel=LibraryDock()
        panel.resize(280,250)
        panel.show();self.app.processEvents()
        self.assertGreater(panel.media_scroll.verticalScrollBar().maximum(),0)
        panel.media_scroll.verticalScrollBar().setValue(
            panel.media_scroll.verticalScrollBar().maximum())
        self.app.processEvents()
        self.assertTrue(panel.import_button.isVisible())
        self.assertTrue(panel.relink_button.isVisible())
        panel.close()


if __name__=='__main__':
    unittest.main()
