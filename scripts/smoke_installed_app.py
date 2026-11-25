"""Create and close the real Qt editor window in a clean/offscreen install."""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication

from berofel import __version__
from berofel.ui.window import MainWindow


def main() -> int:
    app = QApplication.instance() or QApplication(["BerofelStudio-install-smoke"])
    app.setApplicationName("BerofelStudio")
    app.setOrganizationName("Berofel")
    window = MainWindow()
    window.show()
    app.processEvents()
    if not window.isVisible():
        raise RuntimeError("A janela principal não ficou visível na sessão Qt de teste.")
    if __version__ not in window.windowTitle():
        raise RuntimeError("A janela abriu com uma versão diferente do pacote instalado.")
    window.close()
    app.processEvents()
    print(f"[OK] Janela Qt do BerofelStudio {__version__} abriu e encerrou.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
