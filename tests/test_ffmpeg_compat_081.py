"""Regressões FFmpeg 9+: prévia, quadro e exportação com graph em arquivo."""
from pathlib import Path
from unittest import TestCase, mock
import subprocess
import tempfile
from PIL import Image
from berofel.core.project import Project, Clip
from berofel.services.ffmpeg import (
    _supports_legacy_filter_script, filter_complex_file_args, ffmpeg_path,
)
from berofel.services.preview_pipeline import prepare_commands
from berofel.services.export_multitrack import export_project, render_frame


class FfmpegFilterCompatTests(TestCase):
    def tearDown(self):
        _supports_legacy_filter_script.cache_clear()

    def test_modern_build_chooses_modern_file_option(self):
        with mock.patch('berofel.services.ffmpeg.subprocess.run') as run:
            run.return_value.returncode = 0
            run.return_value.stdout = ' -filter_complex <graph>\n -/filter_complex <file>\n'
            args = filter_complex_file_args('grafico.txt', 'ffmpeg-modern.exe')
        self.assertEqual(args, ['-/filter_complex','grafico.txt'])

    def test_older_build_chooses_legacy_file_option(self):
        with mock.patch('berofel.services.ffmpeg.subprocess.run') as run:
            run.return_value.returncode = 0
            run.return_value.stdout = ' -filter_complex_script <filename>\n'
            args = filter_complex_file_args('grafico.txt', 'ffmpeg-legacy.exe')
        self.assertEqual(args, ['-filter_complex_script','grafico.txt'])

    def test_help_probed_only_once(self):
        with mock.patch('berofel.services.ffmpeg.subprocess.run') as run:
            run.return_value.returncode = 0
            run.return_value.stdout = ''
            filter_complex_file_args('a.txt','ffmpeg-same.exe')
            filter_complex_file_args('b.txt','ffmpeg-same.exe')
        self.assertEqual(run.call_count,1)

    def test_modern_option_renders_video_audio_frame_and_mp4(self):
        # Executa com o binário REAL disponível; simula versão moderna na escolha
        # da opção. FFmpeg 7.x aceita as duas, e FFmpeg 9 usará a moderna.
        with tempfile.TemporaryDirectory(prefix='bfs_filter_compat_') as folder:
            root=Path(folder)
            img=root/'still.png'; Image.new('RGB',(160,90),'blue').save(img)
            p=Project(width=160,height=90,fps=12)
            p.add_clip(Clip(str(img),0,0.6,track_id=p.tracks[0].id,kind='image'))
            with mock.patch('berofel.services.ffmpeg._supports_legacy_filter_script',return_value=False):
                commands=prepare_commands(p,0,root/'preview',160,12)
                self.assertIn('-/filter_complex',commands.video)
                self.assertIn('-/filter_complex',commands.audio)
                v=subprocess.run(commands.video,capture_output=True,timeout=30)
                a=subprocess.run(commands.audio,capture_output=True,timeout=30)
                self.assertEqual(v.returncode,0,v.stderr.decode(errors='replace')[-1500:])
                self.assertEqual(a.returncode,0,a.stderr.decode(errors='replace')[-1500:])
                self.assertGreater(len(v.stdout),160*90*4*5)
                self.assertGreater(len(a.stdout),48000*4*.4)
                frame=root/'quadro.png'; render_frame(p,.2,str(frame))
                self.assertGreater(frame.stat().st_size,100)
                movie=root/'saida.mp4'; export_project(p,str(movie))
                self.assertGreater(movie.stat().st_size,1000)
