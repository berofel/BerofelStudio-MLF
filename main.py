"""Executar com .venv/Scripts/python main.py ou ABRIR_BEROFELSTUDIO.bat."""
import sys
from PySide6.QtWidgets import QApplication
from berofel.ui.window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName('BerofelStudio')
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
