"""Comportamento dos grupos dobráveis do inspector de propriedades."""
import os
import unittest

try:
    from PySide6.QtWidgets import QApplication, QLabel
    from berofel.ui.window import InspectorGroup
except ImportError:
    QApplication = None


@unittest.skipUnless(QApplication is not None, 'PySide6 não instalado neste ambiente')
class PropertyInspectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        cls.app = QApplication.instance() or QApplication([])

    def test_group_collapses_and_expands_without_removing_controls(self):
        group = InspectorGroup('Movimento e velocidade')
        control = QLabel('Velocidade')
        group.body_layout.addWidget(control)
        group.show()
        self.app.processEvents()

        self.assertTrue(group.body.isVisible())
        group.toggle.click()
        self.assertFalse(group.body.isVisible())
        self.assertIs(group.body_layout.itemAt(0).widget(), control)
        group.toggle.click()
        self.assertTrue(group.body.isVisible())
        self.assertIs(group.body_layout.itemAt(0).widget(), control)
        group.close()


if __name__ == '__main__':
    unittest.main()
