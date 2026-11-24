"""Teste de integracao de render; gera arquivos temporarios minusculos."""
import tempfile
import unittest
import subprocess
import wave
from pathlib import Path

from berofel.core.project import Project, Clip
from berofel.services.ffmpeg import ffmpeg_path, media_info
from berofel.services.export_multitrack import export_project, render_frame


class ExportTests(unittest.TestCase):
    def test_caption_background_and_weight_render_to_rgba_overlay(self):
        from PIL import Image
        from berofel.services.export_multitrack import _make_title_png
        with tempfile.TemporaryDirectory(prefix='bfs_caption_style_') as folder:
            target=Path(folder)/'caption.png'
            clip=Clip('',0,1,kind='text',text='Teste de estilo',font_family='Arial',
                      font_size=32,font_weight='normal',background_color='#000000',
                      background_opacity=.8)
            _make_title_png(clip,target,320,180)
            with Image.open(target) as image:
                self.assertEqual(image.mode,'RGBA')
                alphas=set(image.tobytes()[3::4]) - {0}
                self.assertIn(204,alphas,'O fundo configurado deve aparecer no overlay renderizado.')

    def test_mix_with_overlays(self):
        from PIL import Image
        ffmpeg=ffmpeg_path()
        with tempfile.TemporaryDirectory(prefix='bfs_test_') as folder:
            base=Path(folder)
            vid=base/'v.mp4'
            wav=base/'n.wav'
            png=base/'i.png'
            Image.new('RGB',(80,45),(0,0,255)).save(png)
            subprocess.run([ffmpeg,'-loglevel','error','-y',
                '-f','lavfi','-i','color=c=red:s=160x90:r=30:d=1',
                '-f','lavfi','-i','sine=frequency=440:duration=1',
                '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',
                '-shortest',str(vid)],check=True)
            subprocess.run([ffmpeg,'-loglevel','error','-y',
                '-f','lavfi','-i','sine=frequency=880:duration=1',
                str(wav)],check=True)
            p=Project()
            p.clips.append(Clip(str(vid),0,1,track_id=p.tracks[-1].id,kind='video'))
            p.add_clip(Clip(str(png),0,1,track_id=p.tracks[1].id,kind='image',opacity=.5))
            p.add_clip(Clip(str(wav),0,1,track_id=p.tracks[1].id,kind='audio'))
            p.add_clip(Clip('',0,1,track_id=p.tracks[0].id,kind='text',text='Teste'))
            result=str(base/'result.mp4')
            export_project(p,result)
            duration,video,audio=media_info(result)
            self.assertTrue(video and audio)
            self.assertGreater(duration,.9)
            img=str(base/'result.png')
            render_frame(p,.3,img)
            with Image.open(img) as frame:
                self.assertEqual(frame.size,(1280,720))
            self.assertGreater(Path(img).stat().st_size,1000)


    def test_cannot_overwrite_original(self):
        with tempfile.TemporaryDirectory(prefix='bfs_safety_') as folder:
            from PIL import Image
            original=str(Path(folder)/'original.png')
            Image.new('RGB',(80,45),'green').save(original)
            original_hash=Path(original).read_bytes()
            p=Project()
            p.add_clip(Clip(original,0,1,kind='image',track_id=p.tracks[0].id))
            with self.assertRaisesRegex(ValueError,'preservar o arquivo original'):
                export_project(p,original)
            self.assertEqual(Path(original).read_bytes(),original_hash)

    def test_cancel_export_does_not_commit_partial_mp4(self):
        from PIL import Image
        from berofel.services.process_control import ProcessControl, ProcessCancelled
        with tempfile.TemporaryDirectory(prefix='bfs_cancel_export_') as folder:
            png=str(Path(folder)/'sample.png')
            Image.new('RGB',(100,50),'cyan').save(png)
            project=Project(width=160,height=90,fps=12)
            project.add_clip(Clip(png,0,4,kind='image',track_id=project.tracks[0].id))
            dest=str(Path(folder)/'cancelled.mp4')
            control=ProcessControl()
            def stop(at,total):
                if at > 0:
                    control.cancel()
            # A tarefa pode exportar rápido; se chegar ao final sem callbacks
            # intermediários, cancela desde o início para validar atomicidade.
            with self.assertRaises(ProcessCancelled):
                export_project(project,dest,control=control,
                               on_progress=lambda at,total: control.cancel() if at == 0 else None)
            self.assertFalse(Path(dest).exists())
            self.assertFalse(list(Path(folder).glob('.*.bfs_*.mp4')))

    def test_export_emits_progress_and_no_leftover(self):
        with tempfile.TemporaryDirectory(prefix='bfs_progress_') as folder:
            from PIL import Image
            img=str(Path(folder)/'picture.png')
            Image.new('RGB',(120,68),'purple').save(img)
            p=Project(width=160,height=90,fps=12)
            p.add_clip(Clip(img,0,.65,kind='image',track_id=p.tracks[0].id))
            dest=str(Path(folder)/'finished.mp4')
            events=[]
            export_project(p,dest,lambda cur,total:events.append((cur,total)))
            self.assertTrue(Path(dest).is_file())
            self.assertGreaterEqual(len(events),2)
            self.assertEqual(events[-1][0],events[-1][1])
            self.assertFalse(list(Path(folder).glob('.*.bfs_*.mp4')))

    def test_pitch_preservation_matches_preview_and_export_at_2x(self):
        import numpy as np
        from berofel.services.preview_pipeline import prepare_commands
        with tempfile.TemporaryDirectory(prefix='bfs_pitch_preserve_') as folder:
            root=Path(folder);tone=root/'tone.wav'
            subprocess.run([ffmpeg_path(),'-hide_banner','-loglevel','error','-y',
                '-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=1',
                '-c:a','pcm_s16le',str(tone)],check=True,capture_output=True,timeout=20)
            project=Project(width=160,height=90,fps=12)
            audio=project.add_clip(Clip(str(tone),0,1,kind='audio',speed=2,
                preserve_pitch=True,track_id=project.tracks[1].id))

            def dominant_frequency(samples):
                mono=samples.reshape((-1,2)).astype(np.float64).mean(axis=1)
                mono=mono[int(len(mono)*.1):int(len(mono)*.9)]
                spectrum=np.abs(np.fft.rfft(mono*np.hanning(len(mono))))
                frequencies=np.fft.rfftfreq(len(mono),1/48000)
                band=(frequencies>200)&(frequencies<1200)
                return float(frequencies[band][int(np.argmax(spectrum[band]))])

            commands=prepare_commands(project,0,root/'preview',preview_width=160,fps=12,
                                     window=audio.duration)
            preview=subprocess.run(commands.audio,capture_output=True,timeout=30)
            self.assertEqual(preview.returncode,0,preview.stderr.decode(errors='replace'))
            preview_hz=dominant_frequency(np.frombuffer(preview.stdout,dtype='<i2'))
            self.assertAlmostEqual(preview_hz,440.,delta=25.)

            output=root/'pitch_preserved.mp4'
            export_project(project,str(output))
            decoded=root/'decoded.wav'
            subprocess.run([ffmpeg_path(),'-hide_banner','-loglevel','error','-y',
                '-i',str(output),'-map','0:a:0','-ac','2','-ar','48000',
                '-c:a','pcm_s16le',str(decoded)],check=True,capture_output=True,timeout=30)
            with wave.open(str(decoded),'rb') as stream:
                exported=np.frombuffer(stream.readframes(stream.getnframes()),dtype='<i2')
            export_hz=dominant_frequency(exported)
            self.assertAlmostEqual(export_hz,440.,delta=30.)

    def test_fragmented_export_keeps_audio_level_and_duration_at_join(self):
        """Stressa a emenda AAC criada quando o projeto vira várias janelas."""
        import numpy as np
        from PIL import Image
        with tempfile.TemporaryDirectory(prefix='bfs_aac_join_') as folder:
            root=Path(folder)
            still=root/'still.png'
            Image.new('RGB',(160,90),'blue').save(still)
            rate=48000
            t=np.arange(rate,dtype=np.float64)/rate
            samples=(.25*32767*np.sin(2*np.pi*440*t)).astype('<i2')
            tone=root/'tone.wav'
            with wave.open(str(tone),'wb') as stream:
                stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(rate)
                stream.writeframes(samples.tobytes())

            project=Project(width=160,height=90,fps=12)
            project.add_clip(Clip(str(still),0,20,track_id=project.tracks[0].id,
                                  kind='image'))
            audio_track=project.tracks[1].id
            project.clips.extend(Clip(str(tone),0,.5,track_id=audio_track,
                                      kind='audio',timeline_start=i*.5)
                                 for i in range(40))
            destination=root/'fragmented.mp4'
            export_project(project,str(destination))

            duration,has_video,has_audio=media_info(str(destination))
            self.assertTrue(has_video and has_audio)
            self.assertAlmostEqual(duration,20.,delta=.06)
            decoded=root/'decoded.wav'
            subprocess.run([ffmpeg_path(),'-hide_banner','-loglevel','error','-y',
                            '-i',str(destination),'-map','0:a:0','-c:a','pcm_s16le',
                            str(decoded)],check=True,capture_output=True,timeout=30)
            with wave.open(str(decoded),'rb') as stream:
                channels=stream.getnchannels()
                pcm=np.frombuffer(stream.readframes(stream.getnframes()),dtype='<i2')
            pcm=pcm.reshape((-1,channels)).astype(np.float64).mean(axis=1)
            levels=[]
            for at in (9.90,9.95,10.00,10.05,10.10):
                segment=pcm[round(at*rate):round((at+.04)*rate)]
                levels.append(float(np.sqrt(np.mean(segment*segment))))
            self.assertGreater(min(levels),max(levels)*.5,
                               f'Queda de áudio na emenda AAC: {levels}')

if __name__=='__main__':
    unittest.main()
