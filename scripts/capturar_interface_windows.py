"""Captura a janela vazia do editor pelo plugin Qt nativo do Windows."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from berofel.ui.window import MainWindow
from berofel.services.process_control import ProcessControl


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='docs/evidencias/interface_windows_nativa.png')
    parser.add_argument('--width',type=int,default=1366)
    parser.add_argument('--height',type=int,default=768)
    parser.add_argument('--qwen-progress',action='store_true',
                        help='Captura o cabeçalho com progresso Qwen simulado; não inicia IA.')
    args=parser.parse_args(argv)
    app=QApplication([sys.argv[0]])
    platform=app.platformName()
    if sys.platform!='win32' or platform!='windows':
        raise RuntimeError(f'Captura requer plugin Windows nativo; recebido {sys.platform}/{platform}.')
    window=MainWindow()
    window.resize(max(670,args.width),max(490,args.height))
    if args.qwen_progress:
        window.process_panel.begin('Edição completa · Qwen',ProcessControl())
        window.process_panel.set_stage('Qwen • bloco 2/40 · 284 palavras · cache por trecho')
        window.process_panel.set_progress(37,100)
    window.show()
    app.processEvents()
    output=Path(args.output)
    if not output.is_absolute():
        output=ROOT/output

    def capture():
        app.processEvents()
        output.parent.mkdir(parents=True,exist_ok=True)
        pixmap=window.grab()
        if pixmap.isNull() or not pixmap.save(str(output)):
            print('Falha ao capturar a janela nativa do editor.',file=sys.stderr)
            app.exit(1)
            return
        screen=window.screen()
        ratio=screen.devicePixelRatio() if screen else 0
        print(f'{output.resolve()} | {pixmap.width()}x{pixmap.height()} | '
              f'DPI ratio={ratio} | Qt platform={platform}',flush=True)
        window.hide()
        app.quit()

    QTimer.singleShot(900,capture)
    return app.exec()


if __name__=='__main__':
    raise SystemExit(main())
