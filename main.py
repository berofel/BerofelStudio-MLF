"""Executar com .venv/Scripts/python main.py ou ABRIR_BEROFELSTUDIO.bat."""
import sys
from pathlib import Path
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication
from berofel.ui.window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName('BerofelStudio')
    app.setOrganizationName('Berofel')
    icon = Path(__file__).resolve().parent / 'assets' / 'brand' / 'berofel_studio_mark.svg'
    if icon.is_file():
        app.setWindowIcon(QIcon(str(icon)))
    window = MainWindow()
    if icon.is_file():
        window.setWindowIcon(QIcon(str(icon)))
    window.show()
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
