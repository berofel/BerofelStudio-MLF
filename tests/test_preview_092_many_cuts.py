"""Stress de prévia para centenas de cortes sequenciais (regressão WinError 206).

Executar com ``python -m unittest discover -s tests -p
test_preview_092_many_cuts.py -v``. Toda a mídia é sintética e temporária.
"""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from berofel.core.project import Clip, Project
from berofel.services.ffmpeg import ffmpeg_path, media_info
from berofel.services.export_multitrack import export_project
from berofel.ui.live_preview import LivePreview, _PipeReader
from berofel.services.preview_pipeline import (
    PREVIEW_MAX_CMD_CHARS,
    PREVIEW_MAX_CLIPS,
    _overlapping_clips,
    prepare_commands,
)


class PreviewManyCutsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_live_preview_advances_to_prefetched_window(self):
        with tempfile.TemporaryDirectory(prefix='bfs_live_switch_') as folder:
            root = Path(folder)
            still = root / 'still.png'
            from PIL import Image
            Image.new('RGB', (160, 90), 'steelblue').save(still)
            project = Project(width=160, height=90, fps=12)
            project.add_clip(Clip(str(still), 0, 1, track_id=project.tracks[0].id,
                                  kind='image'))

            first_tmp = tempfile.TemporaryDirectory(prefix='bfs_live_first_')
            first = prepare_commands(project, 0, first_tmp.name, 160, 12, window=.5)
            live = LivePreview()
            # Keep this integration test independent from the host audio device;
            # FFmpeg still produces and the reader still drains the PCM pipe.
            def start_without_device():
                live._ready = True
                live._time0 = time.monotonic()
                live._paused_total = 0.0
                live._audio_clock_offset = 0.0
            live._start_clock = start_without_device

            loop = QEventLoop()
            timeout = QTimer()
            timeout.setSingleShot(True)
            expired = []
            timeout.timeout.connect(lambda: (expired.append(True), loop.quit()))
            failures = []
            frames = []
            positions = []
            prefetched = []
            live.failed.connect(failures.append)
            live.frame_ready.connect(lambda _frame: frames.append(True))
            live.position_changed.connect(positions.append)
            live.reached_end.connect(loop.quit)

            def prepare_next(at):
                temporary = tempfile.TemporaryDirectory(prefix='bfs_live_next_')
                prefetched.append(temporary)
                commands = prepare_commands(project, at, temporary.name, 160, 12,
                                            window=.5)
                live.prefetch(commands, temporary)

            live.next_requested.connect(prepare_next)
            try:
                live.start(first, first_tmp, project_end=project.duration)
                timeout.start(5000)
                loop.exec()
                self.assertFalse(expired, 'A prévia não chegou ao fim em duas janelas.')
                self.assertFalse(failures, '; '.join(failures))
                self.assertFalse(live.active)
                self.assertTrue(prefetched, 'A segunda janela não foi solicitada.')
                self.assertGreaterEqual(len(frames), 8)
                self.assertTrue(any(position > .5 for position in positions),
                                'A prévia não avançou para o tempo da segunda janela.')
                self.assertEqual(positions, sorted(positions),
                                 'A posição apresentada recuou na troca de janela.')
            finally:
                timeout.stop()
                live.stop()
                first_tmp.cleanup()
                for temporary in prefetched:
                    temporary.cleanup()

    def test_ffmpeg_stderr_is_drained_and_retained_when_large(self):
        script = (
            "import sys; "
            "sys.stderr.buffer.write(b'x' * 200000 + b'preview-reader-error'); "
            "sys.stderr.flush(); "
            "sys.stdout.buffer.write(b'1234'); sys.stdout.flush(); sys.exit(7)"
        )
        reader = _PipeReader([sys.executable, '-c', script], 4, 2)
        reader.start()
        reader.join(timeout=10)

        self.assertFalse(reader.is_alive(), 'A leitura de stderr deixou o worker preso.')
        self.assertIn('preview-reader-error', reader.message)
        self.assertEqual(reader.output.get_nowait(), b'1234')

    def test_cancel_stops_process_and_stderr_reader(self):
        script = (
            "import sys, time\n"
            "while True:\n"
            "    sys.stderr.buffer.write(b'x' * 4096)\n"
            "    sys.stderr.flush()\n"
            "    time.sleep(.001)\n"
        )
        reader = _PipeReader([sys.executable, '-c', script], 4, 2)
        reader.start()
        deadline = time.monotonic() + 5
        while reader.process is None and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertIsNotNone(reader.process, 'O processo de teste não iniciou.')
        reader.stop()
        reader.join(timeout=5)

        self.assertFalse(reader.is_alive(), 'O worker permaneceu ativo após cancelar.')
        self.assertTrue(reader.ended.is_set())
        self.assertFalse(
            reader._stderr_thread and reader._stderr_thread.is_alive(),
            'A thread de stderr permaneceu ativa após cancelar.',
        )

    def test_300_sequential_cuts_prepare_bounded_video_and_audio(self):
        with tempfile.TemporaryDirectory(prefix='bfs_preview_300_') as folder:
            root = Path(folder)
            source = root / 'synthetic.mp4'
            subprocess.run(
                [ffmpeg_path(), '-hide_banner', '-loglevel', 'error', '-y',
                 '-f', 'lavfi', '-i', 'testsrc=size=160x90:rate=12:duration=1',
                 '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1',
                 '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac',
                 '-shortest', str(source)],
                check=True, capture_output=True, timeout=30,
            )

            project = Project(width=160, height=90, fps=12)
            track_id = project.tracks[0].id
            project.clips = [
                Clip(str(source), 0, .1, track_id=track_id,
                     kind='video', timeline_start=index * .1)
                for index in range(300)
            ]

            commands = prepare_commands(project, 0, root / 'live', 160, 12)

            self.assertLessEqual(
                len(_overlapping_clips(project, 0, commands.duration)),
                PREVIEW_MAX_CLIPS,
            )
            self.assertLessEqual(
                max(len(subprocess.list2cmdline(command))
                    for command in (commands.video, commands.audio)),
                PREVIEW_MAX_CMD_CHARS,
            )

            video = subprocess.run(
                commands.video, capture_output=True, timeout=30,
            )
            audio = subprocess.run(
                commands.audio, capture_output=True, timeout=30,
            )
            self.assertEqual(video.returncode, 0,
                             video.stderr.decode(errors='replace'))
            self.assertEqual(audio.returncode, 0,
                             audio.stderr.decode(errors='replace'))
            frame_bytes = commands.width * commands.height * 4
            self.assertGreater(len(video.stdout), frame_bytes * 8)
            self.assertGreater(len(audio.stdout), int(48000 * 4 * commands.duration * .8))

            destination = root / 'export_300_cortes.mp4'
            export_project(project, str(destination))
            duration, has_video, has_audio = media_info(str(destination))
            self.assertTrue(has_video)
            self.assertTrue(has_audio)
            self.assertAlmostEqual(duration, project.duration, delta=.25)

    def test_500_sequential_cuts_keep_windows_commands_and_pipes_bounded(self):
        with tempfile.TemporaryDirectory(prefix='bfs_preview_500_') as folder:
            root=Path(folder);source=root/'synthetic.mp4'
            subprocess.run(
                [ffmpeg_path(),'-hide_banner','-loglevel','error','-y',
                 '-f','lavfi','-i','testsrc=size=160x90:rate=12:duration=1',
                 '-f','lavfi','-i','sine=frequency=660:duration=1',
                 '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(source)],
                check=True,capture_output=True,timeout=30)
            project=Project(width=160,height=90,fps=12)
            track_id=project.tracks[0].id
            project.clips=[Clip(str(source),0,.1,track_id=track_id,kind='video',
                                timeline_start=index*.1) for index in range(500)]
            commands=prepare_commands(project,0,root/'preview',160,12)
            self.assertLessEqual(len(_overlapping_clips(project,0,commands.duration)),
                                 PREVIEW_MAX_CLIPS)
            self.assertLessEqual(max(len(subprocess.list2cmdline(command))
                                     for command in (commands.video,commands.audio)),
                                 PREVIEW_MAX_CMD_CHARS)
            video=subprocess.run(commands.video,capture_output=True,timeout=30)
            audio=subprocess.run(commands.audio,capture_output=True,timeout=30)
            self.assertEqual(video.returncode,0,video.stderr.decode(errors='replace'))
            self.assertEqual(audio.returncode,0,audio.stderr.decode(errors='replace'))
            frame_bytes=commands.width*commands.height*4
            self.assertGreater(len(video.stdout),frame_bytes*8)
            self.assertGreater(len(audio.stdout),int(48000*4*commands.duration*.8))

    def test_80_minute_timeline_with_800_cuts_seeks_across_all_regions(self):
        """Exercise long absolute timestamps without needing an 80-minute source file."""
        with tempfile.TemporaryDirectory(prefix='bfs_preview_80min_') as folder:
            root=Path(folder);source=root/'synthetic.mp4';still=root/'background.png'
            from PIL import Image
            Image.new('RGB',(160,90),'midnightblue').save(still)
            subprocess.run(
                [ffmpeg_path(),'-hide_banner','-loglevel','error','-y',
                 '-f','lavfi','-i','testsrc=size=160x90:rate=12:duration=1',
                 '-f','lavfi','-i','sine=frequency=440:duration=1',
                 '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(source)],
                check=True,capture_output=True,timeout=30)
            project=Project(width=160,height=90,fps=12)
            project.add_clip(Clip(str(still),0,4800,track_id=project.tracks[1].id,
                                  kind='image',title='Fundo de oitenta minutos'))
            project.clips.extend(
                Clip(str(source),0,1,track_id=project.tracks[0].id,kind='video',
                     timeline_start=index*6,source_length=1,title=f'Corte {index+1}')
                for index in range(800))
            self.assertAlmostEqual(project.duration,4800.)

            # Seek preparation is sampled every ~160 s; every command remains
            # limited even though the project owns 800 cuts and spans 80 min.
            for index in range(30):
                at=index*160.+.1
                commands=prepare_commands(project,at,root/'seek_prepare',160,12,window=.25)
                self.assertAlmostEqual(commands.source_time,at)
                self.assertLessEqual(len(_overlapping_clips(project,at,at+commands.duration)),
                                     PREVIEW_MAX_CLIPS)
                self.assertLessEqual(max(len(subprocess.list2cmdline(command))
                                         for command in (commands.video,commands.audio)),
                                     PREVIEW_MAX_CMD_CHARS)

            # Decode real video+audio pipes at the start, middle and final minute.
            for at in (.1,2400.1,4740.1):
                with self.subTest(seek=at):
                    commands=prepare_commands(project,at,root/f'decode_{int(at)}',
                                              160,12,window=.5)
                    video=subprocess.run(commands.video,capture_output=True,timeout=30)
                    audio=subprocess.run(commands.audio,capture_output=True,timeout=30)
                    self.assertEqual(video.returncode,0,video.stderr.decode(errors='replace'))
                    self.assertEqual(audio.returncode,0,audio.stderr.decode(errors='replace'))
                    self.assertGreater(len(video.stdout),commands.width*commands.height*4)
                    self.assertGreater(len(audio.stdout),int(48000*4*commands.duration*.8))


if __name__ == '__main__':
    unittest.main()
