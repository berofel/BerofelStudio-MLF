"""Smoke test nativo: mostra a prévia real do editor com 300 cortes sintéticos.

Gera mídia somente em diretório temporário, isola QSettings e salva a captura
no caminho informado. O volume fica zerado; o monitor e a timeline continuam
rodando pelo motor LivePreview normal do aplicativo.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QSettings, QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from berofel.core.project import Clip, Project
from berofel.services.ffmpeg import ffmpeg_path
from berofel.ui.window import MainWindow


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='docs/evidencias/previa_300_cortes_windows.png')
    parser.add_argument('--timeout', type=int, default=30)
    parser.add_argument('--width', type=int, default=1366, help='Largura lógica Qt da janela')
    parser.add_argument('--height', type=int, default=768, help='Altura lógica Qt da janela')
    args = parser.parse_args(argv)
    if sys.platform != 'win32':
        raise RuntimeError('Este smoke test precisa ser executado no Windows.')

    app = QApplication([sys.argv[0]])
    if app.platformName() != 'windows':
        raise RuntimeError(f'Plugin Qt nativo esperado; recebido: {app.platformName()}')

    output = Path(args.output)
    if not output.is_absolute():
        output = ROOT / output

    result = {'status': 'FALHOU', 'platform': app.platformName(), 'cuts': 300}
    with tempfile.TemporaryDirectory(prefix='bfs_native_preview_') as temp_dir:
        temp = Path(temp_dir)
        # MainWindow persiste o layout. Redireciona QSettings para a pasta de
        # teste e mantém intactas as preferências habituais do proprietário.
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(temp))
        source = temp / 'source_sintetica.mp4'
        subprocess.run(
            [ffmpeg_path(), '-hide_banner', '-loglevel', 'error', '-y',
             '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=30:duration=25',
             '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=25',
             '-c:v', 'libx264', '-preset', 'ultrafast', '-tune', 'zerolatency',
             '-crf', '30', '-threads', '1', '-pix_fmt', 'yuv420p',
             '-c:a', 'aac', '-shortest', str(source)],
            check=True, capture_output=True, timeout=90,
        )

        project = Project(width=320, height=180, fps=30)
        track_id = project.tracks[0].id
        project.media.append(str(source))
        project.clips = [
            Clip(str(source), index * .08, (index + 1) * .08,
                 track_id=track_id, timeline_start=index * .08,
                 kind='video', include_audio=True, source_length=25,
                 title=f'Corte {index + 1:03d}')
            for index in range(300)
        ]

        window = MainWindow()
        window.resize(max(670, args.width), max(490, args.height))
        window.project = project
        window.refresh([])
        window.timeline.set_cursor(0)
        window.transport.volume.setValue(0)
        window.show()
        app.processEvents()

        frames = []
        failures = []
        statuses = []
        audio_decoder_started = []
        def observe_frame(frame):
            points=[frame.pixelColor(x,y).getRgb()[:3]
                    for y in range(frame.height()//4,frame.height(),frame.height()//4)
                    for x in range(frame.width()//4,frame.width(),frame.width()//4)]
            brightness=[sum(pixel)/3 for pixel in points]
            frames.append({'width':frame.width(),'brightness':sum(brightness)/len(brightness),
                           'contrast':max(brightness)-min(brightness)})
        window.live.frame_ready.connect(observe_frame)
        window.live.failed.connect(failures.append)
        window.live.status_changed.connect(statuses.append)

        timer = QTimer()
        timer.setInterval(50)
        started = time.monotonic()
        captured = []

        def poll_preview():
            if failures:
                result['error'] = failures[-1]
                app.quit()
                return
            reader = window.live._audio
            if reader and reader.process is not None:
                audio_decoder_started.append(True)
            position = window.timeline.view.cursor_time
            if len(frames) >= 30 and position >= .6 and audio_decoder_started:
                app.processEvents()
                displayed=window.preview_image.pixmap
                if displayed is None or displayed.isNull():
                    result['error']='FFmpeg enviou quadros, mas o monitor não tem imagem exibida.'
                    app.quit()
                    return
                image=displayed.toImage().convertToFormat(QImage.Format.Format_RGB32)
                points=[image.pixelColor(x,y).getRgb()[:3]
                        for y in range(image.height()//4,image.height(),image.height()//4)
                        for x in range(image.width()//4,image.width(),image.width()//4)]
                brightness=[sum(pixel)/3 for pixel in points]
                visible_mean=sum(brightness)/len(brightness)
                visible_contrast=max(brightness)-min(brightness)
                if visible_mean<25 or visible_contrast<8:
                    result.update({'error':'O monitor recebeu imagem, mas os pixels exibidos estão pretos.',
                                   'frame_count':len(frames),
                                   'frame_input_mean':round(frames[-1]['brightness'],2),
                                   'monitor_mean':round(visible_mean,2),
                                   'monitor_contrast':round(visible_contrast,2)})
                    app.quit()
                    return
                output.parent.mkdir(parents=True, exist_ok=True)
                pixmap = window.grab()
                if pixmap.isNull() or not pixmap.save(str(output)):
                    result['error'] = 'Qt não conseguiu salvar a captura da janela.'
                else:
                    result.update({
                        'status': 'PASSOU',
                        'capture': str(output.resolve()),
                        'size': [pixmap.width(), pixmap.height()],
                        'logical_size': [window.width(), window.height()],
                        'device_pixel_ratio': window.devicePixelRatioF(),
                        'frames_received': len(frames),
                        'frame_input_mean':round(frames[-1]['brightness'],2),
                        'frame_input_contrast':round(frames[-1]['contrast'],2),
                        'monitor_mean':round(visible_mean,2),
                        'monitor_contrast':round(visible_contrast,2),
                        'audio_decoder_started': True,
                        'timeline_seconds': round(position, 3),
                        'live_status': statuses[-1] if statuses else '',
                    })
                    captured.append(True)
                app.quit()
                return
            if time.monotonic() - started > max(5, args.timeout):
                result.update({
                    'error': 'A prévia não produziu quadros, áudio e avanço do playhead a tempo.',
                    'frames_received': len(frames),
                    'timeline_seconds': round(position, 3),
                    'audio_decoder_started': bool(audio_decoder_started),
                    'live_status': statuses[-1] if statuses else '',
                })
                app.quit()

        timer.timeout.connect(poll_preview)
        timer.start()
        QTimer.singleShot(250, window.toggle_play)
        app.exec()
        timer.stop()
        window.stop_playback(wait_for_cleanup=True)
        window.close()
        app.processEvents()

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['status'] == 'PASSOU' else 1


if __name__ == '__main__':
    raise SystemExit(main())
