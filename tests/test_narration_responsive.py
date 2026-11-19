"""Regressão: painel de narração se adapta ao estreitamento da janela."""
from __future__ import annotations

import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')

try:
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QApplication, QWidget
    from berofel.ui.window import MainWindow
except ImportError:
    QApplication=None


@unittest.skipUnless(QApplication is not None,'PySide6 indisponível neste ambiente')
class NarrationResponsiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def test_narrow_sidebar_reflows_controls_without_horizontal_overflow(self):
        window=MainWindow()
        window.resize(800,620)
        window.show()
        window.side_tabs.setCurrentWidget(window.narration_panel)
        window.horizontal.setSizes([160,400,150])
        self.app.processEvents()

        panel=window.narration_panel
        page=panel.widget()
        self.assertTrue(panel._compact)
        self.assertLessEqual(page.width(),panel.viewport().width()+2)
        outside=[]
        for child in page.findChildren(QWidget):
            if not child.isVisible():
                continue
            x=child.mapTo(page,QPoint(0,0)).x()
            if x<0 or x+child.width()>page.width()+2:
                outside.append((type(child).__name__,x,child.width()))
        self.assertEqual(outside,[])
        self.assertLessEqual(window.minimumWidth(),630)
        window.close()
        self.app.processEvents()


if __name__=='__main__':
    unittest.main()
