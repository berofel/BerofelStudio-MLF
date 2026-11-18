"""Integração: prova que preview gera vídeo E áudio da mesma timeline composta.

Executar: python -m unittest discover -s tests -v
Usa mídias sintéticas minúsculas; não depende de arquivos pessoais.
"""
from __future__ import annotations

from dataclasses import replace
import math
from pathlib import Path
import subprocess
import tempfile
import unittest
import wave

import numpy as np
from PIL import Image

from berofel.core.project import Clip, Project
from berofel.services.ffmpeg import ffmpeg_path
from berofel.services.preview_pipeline import crop_project, prepare_commands


class PreviewTests(unittest.TestCase):
    def test_solo_track_filters_preview_audio(self):
        with tempfile.TemporaryDirectory(prefix='bfs_preview_solo_') as folder:
            root=Path(folder); rate=48000
            sources=[]
            for frequency in (440,880):
                samples=(.5*32767*np.sin(2*np.pi*frequency*np.arange(rate//2)/rate)).astype('<i2')
                source=root/f'{frequency}.wav'
                with wave.open(str(source),'wb') as stream:
                    stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(rate)
                    stream.writeframes(samples.tobytes())
                sources.append(source)
            p=Project(width=160,height=90,fps=12)
            p.add_clip(Clip(str(sources[0]),0,.5,track_id=p.tracks[0].id,kind='audio'))
            p.add_clip(Clip(str(sources[1]),0,.5,track_id=p.tracks[1].id,kind='audio'))
            p.tracks[0].solo=True
            cmd=prepare_commands(p,0,root/'live',160,12)
            result=subprocess.run(cmd.audio,capture_output=True,timeout=25)
            self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
            audio=np.frombuffer(result.stdout,dtype='<i2').reshape((-1,2))
            samples=audio[:rate//2,0].astype(float)
            spectrum=np.abs(np.fft.rfft(samples))
            self.assertGreater(spectrum[220],1e5)
            self.assertLess(spectrum[440],spectrum[220]*.03)
            from berofel.services.export_multitrack import export_project
            destination=root/'solo.mp4'
            export_project(p,destination)
            decoded=subprocess.run([ffmpeg_path(),'-hide_banner','-loglevel','error','-i',
                str(destination),'-vn','-f','s16le','-acodec','pcm_s16le','-ac','2','-ar',
                str(rate),'-'],capture_output=True,check=True,timeout=30)
            exported=np.frombuffer(decoded.stdout,dtype='<i2').reshape((-1,2))
            exported_samples=exported[rate//10:rate//2,0].astype(float)
            spectrum=np.abs(np.fft.rfft(exported_samples))
            self.assertGreater(spectrum[176],1e5)
            self.assertLess(spectrum[352],spectrum[176]*.05)

    def create_media(self, folder: Path):
        ffmpeg=ffmpeg_path()
        red = folder/'red.mp4'; blue = folder/'blue.mp4'; tone=folder/'tone.wav'
        for file,color,frequency in [(red,'red','330'),(blue,'blue','740')]:
            subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-y',
                '-f','lavfi','-i',f'color=c={color}:s=160x90:r=24:d=1.5',
                '-f','lavfi','-i',f'sine=frequency={frequency}:duration=1.5',
                '-c:v','libx264','-pix_fmt','yuv420p', '-c:a','aac','-shortest',str(file)],check=True)
        subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-y',
            '-f','lavfi','-i','sine=frequency=1200:duration=1.5',str(tone)],check=True)
        return red,blue,tone

    def test_window_preserves_source_times(self):
        p=Project()
        tid=p.tracks[0].id
        c=Clip(source='video.mp4',start=10,end=18,track_id=tid,
               timeline_start=25,kind='video')
        p.clips=[c]
        clipped,duration=crop_project(p,28,3,preview_width=640)
        self.assertAlmostEqual(duration,3)
        self.assertEqual(len(clipped.clips),1)
        r=clipped.clips[0]
        self.assertAlmostEqual(r.start,13)
        self.assertAlmostEqual(r.end,16)
        self.assertAlmostEqual(r.timeline_start,0)
        self.assertEqual(r.track_id,tid)

    def test_same_time_audio_video_and_z_order(self):
        with tempfile.TemporaryDirectory(prefix='bfs_preview_test_') as folder:
            root=Path(folder)
            red,blue,tone=self.create_media(root)
            p=Project()
            p.width=160;p.height=90;p.fps=24
            # Topo azul cobre fundo vermelho. Ambos tocam áudio junto.
            p.add_clip(Clip(str(red),0,1.5,track_id=p.tracks[-1].id,
                            kind='video',timeline_start=0))
            blueclip=p.add_clip(Clip(str(blue),0,1.5,track_id=p.tracks[0].id,
                            kind='video',timeline_start=0))
            p.add_clip(Clip(str(tone),0,1.5,track_id=p.tracks[2].id,
                            kind='audio',timeline_start=0,include_audio=True))
            cmd=prepare_commands(p,0,root/'live',160,12)
            v=subprocess.run(cmd.video,capture_output=True,timeout=25)
            a=subprocess.run(cmd.audio,capture_output=True,timeout=25)
            self.assertEqual(v.returncode,0,v.stderr.decode(errors='replace'))
            self.assertEqual(a.returncode,0,a.stderr.decode(errors='replace'))
            framebytes=cmd.width*cmd.height*4
            self.assertGreater(len(v.stdout),framebytes*14)
            self.assertGreater(len(a.stdout),48000*4*1.3)
            # BGRA, pixel central: azul dominante
            frame=np.frombuffer(v.stdout[:framebytes],dtype=np.uint8).reshape((cmd.height,cmd.width,4))
            self.assertGreater(int(frame[45,80,0]),int(frame[45,80,2])+70)
            audio=np.frombuffer(a.stdout,dtype='<i2').reshape((-1,2))
            spectrum=np.abs(np.fft.rfft(audio[:48000,0].astype(float)))
            for freq in (330,740,1200):
                self.assertGreater(spectrum[freq],1e5,f'frequência {freq}Hz não encontrada na mixagem')
            # Ao colocar a camada azul atrás, a imagem fica vermelha.
            p.move_track(p.tracks[0].id,1)
            p.move_track(p.tracks[1].id,1)
            # Melhor prova: camada do vermelho trazida para frente.
            redtrack=p.clips[0].track_id
            while p.tracks[0].id!=redtrack:
                p.move_track(redtrack,-1)
            cmd2=prepare_commands(p,0,root/'live2',160,12)
            v2=subprocess.run(cmd2.video,capture_output=True,timeout=25)
            self.assertEqual(v2.returncode,0,v2.stderr.decode(errors='replace'))
            frame2=np.frombuffer(v2.stdout[:framebytes],dtype=np.uint8).reshape((90,160,4))
            self.assertGreater(int(frame2[45,80,2]),int(frame2[45,80,0])+70)

    def test_seek_and_silent_timeline(self):
        with tempfile.TemporaryDirectory(prefix='bfs_preview_seek_') as folder:
            root=Path(folder)
            red,blue,tone=self.create_media(root)
            p=Project(width=160,height=90,fps=24)
            p.add_clip(Clip(str(red),start=.15,end=1.35,track_id=p.tracks[0].id,
                            kind='video',timeline_start=.5))
            cmd=prepare_commands(p,1.0,root/'live',160,12)
            self.assertAlmostEqual(cmd.duration,.7,places=3)
            v=subprocess.run(cmd.video,capture_output=True,timeout=25)
            a=subprocess.run(cmd.audio,capture_output=True,timeout=25)
            self.assertEqual(v.returncode,0,v.stderr.decode(errors='replace'))
            self.assertEqual(a.returncode,0,a.stderr.decode(errors='replace'))
            self.assertGreater(len(v.stdout),160*90*4*7)
            self.assertGreater(len(a.stdout),40000)

    def test_audio_seek_after_speed_uses_matching_source_time(self):
        """A janela em seek deve reproduzir o mesmo ponto do áudio acelerado."""
        with tempfile.TemporaryDirectory(prefix='bfs_preview_speed_audio_') as folder:
            root=Path(folder)
            rate=48000
            pieces=[]
            for frequency in (440,880,1320):
                t=np.arange(rate//2,dtype=np.float64)/rate
                pieces.append((0.7*32767*np.sin(2*np.pi*frequency*t)).astype('<i2'))
            source=root/'segmented_tones.wav'
            with wave.open(str(source),'wb') as stream:
                stream.setnchannels(1)
                stream.setsampwidth(2)
                stream.setframerate(rate)
                stream.writeframes(np.concatenate(pieces).tobytes())

            project=Project(width=160,height=90,fps=12)
            clip=Clip(str(source),0,1.5,track_id=project.tracks[0].id,
                      kind='audio',timeline_start=.2,speed=2.0)
            project.add_clip(clip)

            def dominant_frequency(pcm,start):
                samples=np.frombuffer(pcm,dtype='<i2').reshape((-1,2))
                begin=round(start*rate)
                mono=samples[begin:begin+rate//20,0].astype(np.float64)
                mono-=mono.mean()
                spectrum=np.abs(np.fft.rfft(mono*np.hanning(len(mono))))
                bins=np.fft.rfftfreq(len(mono),1/rate)
                return bins[int(np.argmax(spectrum[1:])+1)]

            whole=prepare_commands(project,0,root/'whole',160,12)
            window=prepare_commands(project,.50,root/'window',160,12)
            full_pcm=subprocess.run(whole.audio,capture_output=True,check=True,
                                    timeout=25).stdout
            window_pcm=subprocess.run(window.audio,capture_output=True,check=True,
                                      timeout=25).stdout
            # 0.58 s on the full timeline and 0.08 s into the .50 s seek are
            # the same timeline point; speed=2 maps both into source 0.76 s.
            self.assertAlmostEqual(dominant_frequency(full_pcm,.58),880,delta=25)
            self.assertAlmostEqual(dominant_frequency(window_pcm,.08),880,delta=25)
            self.assertAlmostEqual(window.source_time,.50,places=3)

    def test_track_gain_and_pan_are_applied_to_preview_mix(self):
        with tempfile.TemporaryDirectory(prefix='bfs_track_mix_') as folder:
            root=Path(folder)
            rate=48000
            t=np.arange(rate//2,dtype=np.float64)/rate
            signal=(.25*32767*np.sin(2*np.pi*440*t)).astype('<i2')
            source=root/'tone.wav'
            with wave.open(str(source),'wb') as stream:
                stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(rate)
                stream.writeframes(signal.tobytes())
            project=Project(width=160,height=90,fps=12)
            track=project.tracks[0]
            track.volume=.5;track.pan=1.
            project.add_clip(Clip(str(source),0,.5,track_id=track.id,kind='audio'))
            commands=prepare_commands(project,0,root/'preview',160,12)
            result=subprocess.run(commands.audio,capture_output=True,check=True,timeout=20)
            stereo=np.frombuffer(result.stdout,dtype='<i2').reshape((-1,2)).astype(np.float64)
            left=float(np.sqrt(np.mean(stereo[:,0]**2)))
            right=float(np.sqrt(np.mean(stereo[:,1]**2)))
            self.assertGreater(right,1500,'A faixa panoramizada à direita ficou sem sinal.')
            self.assertLess(left,80,'O balanço totalmente à direita vazou para a esquerda.')
            from berofel.services.export_multitrack import export_project
            rendered=root/'track_mix.mp4'
            export_project(project,str(rendered))
            decoded=root/'track_mix.wav'
            subprocess.run([ffmpeg_path(),'-hide_banner','-loglevel','error','-y',
                            '-i',str(rendered),'-map','0:a:0','-c:a','pcm_s16le',
                            str(decoded)],check=True,capture_output=True,timeout=25)
            with wave.open(str(decoded),'rb') as stream:
                output=np.frombuffer(stream.readframes(stream.getnframes()),
                                     dtype='<i2').reshape((-1,stream.getnchannels()))
            export_left=float(np.sqrt(np.mean(output[:,0].astype(float)**2)))
            export_right=float(np.sqrt(np.mean(output[:,1].astype(float)**2)))
            self.assertGreater(export_right,1000)
            self.assertLess(export_left,export_right*.08,
                            'A exportação não preservou o balanço para a direita.')

if __name__ == '__main__':
    unittest.main()

class VideoOnlyPreviewTests(unittest.TestCase):
    def test_image_without_audio_has_silent_pcm(self):
        with tempfile.TemporaryDirectory(prefix='bfs_silence_test_') as folder:
            root=Path(folder)
            img=root/'still.png'
            Image.new('RGB',(160,90),'green').save(img)
            p=Project(width=160,height=90,fps=12)
            p.add_clip(Clip(str(img),0,.5,track_id=p.tracks[-1].id,kind='image'))
            cmd=prepare_commands(p,0,root/'live',160,12)
            v=subprocess.run(cmd.video,capture_output=True,timeout=25)
            a=subprocess.run(cmd.audio,capture_output=True,timeout=25)
            self.assertEqual(v.returncode,0,v.stderr.decode(errors='replace'))
            self.assertEqual(a.returncode,0,a.stderr.decode(errors='replace'))
            self.assertGreater(len(v.stdout),160*90*4*4)
            self.assertGreater(len(a.stdout),80000)
            self.assertEqual(max(a.stdout),0,'A saída silenciosa contém áudio espúrio.')

    def test_hidden_image_no_longer_covers_video(self):
        with tempfile.TemporaryDirectory(prefix='bfs_hidden_test_') as folder:
            root=Path(folder)
            red=root/'red.png';blue=root/'blue.png'
            Image.new('RGB',(160,90),'red').save(red)
            Image.new('RGB',(160,90),'blue').save(blue)
            p=Project(width=160,height=90,fps=12)
            p.add_clip(Clip(str(red),0,.5,track_id=p.tracks[-1].id,kind='image'))
            p.add_clip(Clip(str(blue),0,.5,track_id=p.tracks[0].id,kind='image'))
            p.tracks[0].hidden=True
            cmd=prepare_commands(p,0,root/'live',160,12)
            v=subprocess.run(cmd.video,capture_output=True,timeout=25)
            self.assertEqual(v.returncode,0,v.stderr.decode(errors='replace'))
            mid=(45*160+80)*4
            b,g,r,a=v.stdout[mid:mid+4]
            self.assertGreater(r,b+90)
