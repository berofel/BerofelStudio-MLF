"""Render the source SVG brand mark into a multi-size Windows ICO."""
from __future__ import annotations

from pathlib import Path
import os
import tempfile

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'assets' / 'brand' / 'berofel_studio_mark.svg'
OUTPUT = ROOT / 'assets' / 'brand' / 'berofel_studio.ico'
SIZES = (16, 24, 32, 48, 64, 128, 256)


def main() -> None:
    app = QGuiApplication.instance() or QGuiApplication([])
    renderer = QSvgRenderer(str(SOURCE))
    if not renderer.isValid():
        raise SystemExit(f'Não foi possível abrir o SVG da marca: {SOURCE}')
    frames = {}
    with tempfile.TemporaryDirectory(prefix='bfs-icon-') as directory:
        for size in SIZES:
            image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(Qt.GlobalColor.transparent)
            painter = QPainter(image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            renderer.render(painter)
            painter.end()
            png = Path(directory) / f'icon-{size}.png'
            if not image.save(str(png), 'PNG'):
                raise SystemExit(f'Falha ao renderizar ícone em {size}px.')
            with Image.open(png) as frame:
                frames[size] = frame.convert('RGBA').copy()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    frames[256].save(OUTPUT, format='ICO', sizes=[(n, n) for n in SIZES])
    with Image.open(OUTPUT) as check:
        if check.format != 'ICO' or check.size != (256, 256):
            raise SystemExit('O arquivo ICO final não passou na verificação.')
    print(f'Ícone Windows criado: {OUTPUT} ({OUTPUT.stat().st_size:,} bytes)')


if __name__ == '__main__':
    main()
