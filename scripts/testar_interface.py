"""Teste OPCIONAL de janela + prévia simultânea no Windows do usuário.

Abre uma janela Qt temporária, reproduz dois vídeos gerados localmente,
verifica que aparecem pelo menos 3 frames no widget. Fecha sozinho.
Não requer câmera, modelos de ASR ou nenhum arquivo pessoal.
"""
from __future__ import annotations
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from berofel.core.project import Clip,Project
from berofel.services.ffmpeg import ffmpeg_path
from PySide6.QtCore import QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
from berofel.ui.window import MainWindow


def sample(root, name, color, freq):
    dest=root/(name+'.mp4')
    ffmpeg=ffmpeg_path()
    p=subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-nostdin','-y',
        '-f','lavfi','-i',f'color=c={color}:s=160x90:r=24:d=2.0',
        '-f','lavfi','-i',f'sine=frequency={freq}:duration=2.0',
        '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',
        '-shortest',str(dest)],capture_output=True,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if p.returncode:
        raise RuntimeError(p.stderr.decode('utf-8','replace')[-800:])
    return str(dest)


def main():
    with tempfile.TemporaryDirectory(prefix='bfs_gui_smoke_') as folder:
        root=Path(folder)
        red=sample(root,'red','red',440)
        blue=sample(root,'blue','blue',880)
        app=QApplication(sys.argv)
        win=MainWindow()
        project=Project(width=160,height=90,fps=24)
        project.add_clip(Clip(red,0,2,kind='video',track_id=project.tracks[-1].id))
        project.add_clip(Clip(blue,0,2,kind='video',track_id=project.tracks[0].id))
        win.project=project
        win.refresh()
        win.show()
        state={'count':0,'error':None,'frame_mean':None,'monitor_mean':None}
        def image_mean(img):
            points=[img.pixelColor(x,y).getRgb()[:3]
                    for y in range(img.height()//4,img.height(),img.height()//4)
                    for x in range(img.width()//4,img.width(),img.width()//4)]
            return sum(sum(pixel)/3 for pixel in points)/len(points)
        def on_frame(img):
            if not img.isNull():
                state['count']+=1
                state['frame_mean']=image_mean(img)
        def on_error(txt):
            state['error']=txt
            app.quit()
        win.live.frame_ready.connect(on_frame)
        win.live.failed.connect(on_error)
        QTimer.singleShot(300,win.toggle_play)
        def complete():
            pixmap=win.preview_image.pixmap
            if pixmap is None or pixmap.isNull():
                state['error']='O FFmpeg enviou quadros, mas o monitor não recebeu uma imagem.'
            else:
                state['monitor_mean']=image_mean(
                    pixmap.toImage().convertToFormat(QImage.Format.Format_RGB32))
            win.stop_playback()
            app.quit()
        QTimer.singleShot(15000,complete)
        app.exec()
        win.stop_playback()
        if state['error']:
            print('[ERRO] Playback Qt: '+state['error'])
            return 1
        if state['count']<3:
            print('[ERRO] A janela não exibiu pelo menos 3 frames compostos.')
            return 1
        if state['error'] or state['frame_mean'] is None or state['frame_mean']<25 or \
                state['monitor_mean'] is None or state['monitor_mean']<25:
            print('[ERRO] A prévia recebeu sinal preto ou não exibiu pixels visíveis: '
                  +str(state))
            return 1
        print(f'[OK] Preview integrado à GUI: {state["count"]} quadros; '
              f'brilho da entrada {state["frame_mean"]:.1f}, '
              f'monitor {state["monitor_mean"]:.1f}.')
        return 0


if __name__=='__main__':
    try: sys.exit(main())
    except Exception as exc:
        import traceback
        traceback.print_exc()
        sys.exit(1)
