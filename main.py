"""Executar com .venv/Scripts/python main.py ou ABRIR_BEROFELSTUDIO.bat."""
import sys
from pathlib import Path
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication
from berofel.ui.window import MainWindow


def application_icon_path() -> Path:
    """Prefer the generated multi-resolution Windows icon for shell/taskbar."""
    brand_dir = Path(__file__).resolve().parent / 'assets' / 'brand'
    for name in ('berofel_studio.ico', 'berofel_studio_mark.svg'):
        candidate = brand_dir / name
        if candidate.is_file():
            return candidate
    return brand_dir / 'berofel_studio_mark.svg'


def main():
    app = QApplication(sys.argv)
    app.setApplicationName('BerofelStudio')
    app.setOrganizationName('Berofel')
    icon = application_icon_path()
    if icon.is_file():
        app.setWindowIcon(QIcon(str(icon)))
    window = MainWindow()
    if icon.is_file():
        window.setWindowIcon(QIcon(str(icon)))
    window.show()
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
