"""Round-trip test for hot EQ changes in a live FFmpeg preview process."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
import wave

import numpy as np

from berofel.core.project import Clip,Project
from berofel.services.ffmpeg import ffmpeg_path,supports_filter
from berofel.services.preview_pipeline import prepare_commands
from berofel.services.voice_preview_controller import (AsyncVoicePreviewController,
    VoicePreviewController)


class VoicePreviewControllerTests(unittest.TestCase):
    def test_async_controller_keeps_ui_nonblocking_and_coalesces_slider_updates(self):
        calls=[]
        class SlowController:
            def __init__(self,*args,**kwargs):pass
            def set_eq(self,clip_id,values,bypass=False):
                time.sleep(.08)
                calls.append((clip_id,dict(values),bypass))
                return True
            def close(self):pass
        ready=threading.Event()
        def factory(*args,**kwargs):
            ready.set()
            return SlowController()
        from unittest.mock import patch
        with patch('berofel.services.voice_preview_controller.VoicePreviewController',
                   side_effect=factory):
            controller=AsyncVoicePreviewController('tcp://127.0.0.1:12345',
                {'clip':{'bass_db':'bass'}},timeout_ms=100)
            try:
                self.assertTrue(ready.wait(1.))
                started=time.perf_counter()
                for value in range(20):
                    self.assertTrue(controller.set_eq('clip',{'bass_db':value}))
                self.assertLess(time.perf_counter()-started,.05)
                self.assertTrue(controller.flush(timeout=1.))
                self.assertEqual(len(calls),1)
                self.assertEqual(calls[0][1]['bass_db'],19)
            finally:controller.close()

    def test_live_eq_command_updates_running_ffmpeg_without_restart(self):
        if not importlib.util.find_spec('zmq') or not supports_filter('azmq'):
            self.skipTest('PyZMQ/FFmpeg azmq indisponível neste ambiente.')
        with tempfile.TemporaryDirectory(prefix='bfs_live_voice_eq_') as folder:
            root=Path(folder);source=root/'voice.wav';rate=48000
            tone=(.1*np.sin(2*np.pi*440*np.arange(rate*4)/rate)*32767).astype('<i2')
            with wave.open(str(source),'wb') as wav:
                wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(rate)
                wav.writeframes(tone.tobytes())
            project=Project(width=160,height=90,fps=12)
            clip=project.add_clip(Clip(str(source),0,4,kind='audio',
                track_id=project.tracks[-1].id))
            commands=prepare_commands(project,0,root/'preview',preview_width=160,
                                      fps=12,window=4,voice_control_clip_id=clip.id)
            self.assertIn(clip.id,commands.voice_eq_targets)
            audio_command=list(commands.audio)
            input_start=audio_command.index('-ss')
            audio_command.insert(input_start,'-re')
            process=subprocess.Popen(audio_command,stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            captured=[]
            reader=threading.Thread(target=lambda:captured.append(process.stdout.read()),
                                     daemon=True)
            reader.start()
            controller=None
            try:
                controller=VoicePreviewController(commands.voice_control_address,
                    commands.voice_eq_targets,commands.voice_eq_initial,timeout_ms=750)
                time.sleep(.7)
                pitch_target=commands.voice_eq_targets[clip.id].get('pitch_semitones')
                live_pitch=bool(supports_filter('rubberband') and pitch_target and
                                pitch_target.startswith('rubberband@'))
                started=time.perf_counter()
                values={'bass_db':5.,'mids_db':-1.5,'treble_db':2.}
                if live_pitch:values['pitch_semitones']=-1.
                self.assertTrue(controller.set_eq(clip.id,values))
                elapsed=time.perf_counter()-started
                self.assertLess(elapsed,1.5)
                self.assertIsNone(process.poll(),'EQ command should not restart FFmpeg')
                if live_pitch:
                    time.sleep(1.1)
                    self.assertTrue(controller.set_eq(clip.id,{
                        'bass_db':0.,'mids_db':0.,'treble_db':0.,
                        'pitch_semitones':0.},bypass=True))
                    self.assertIsNone(process.poll(),
                        'Pitch bypass should update the running FFmpeg process')
                process.wait(timeout=8)
                reader.join(timeout=2)
                if live_pitch and captured:
                    samples=np.frombuffer(captured[0],dtype='<i2').reshape(-1,2)[:,0]
                    def dominant_frequency(start_s):
                        segment=samples[int(start_s*rate):int((start_s+.5)*rate)]
                        segment=segment.astype(np.float64)
                        segment-=segment.mean()
                        spectrum=np.abs(np.fft.rfft(segment*np.hanning(len(segment))))
                        bins=np.fft.rfftfreq(len(segment),1/rate)
                        region=(bins>=350)&(bins<=480)
                        return float(bins[region][np.argmax(spectrum[region])])
                    self.assertLess(abs(dominant_frequency(.1)-440.),4.)
                    self.assertLess(abs(dominant_frequency(1.5)-415.3),7.)
                    self.assertLess(abs(dominant_frequency(3.)-440.),7.)
            finally:
                if controller:controller.close()
                if process.poll() is None:process.terminate()
                try:process.wait(timeout=3)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=3)
                reader.join(timeout=2)
                if process.stdout:process.stdout.close()
                if process.stderr:process.stderr.close()

    def test_async_eq_reaches_running_ffmpeg_without_blocking_or_restart(self):
        if not importlib.util.find_spec('zmq') or not supports_filter('azmq'):
            self.skipTest('PyZMQ/FFmpeg azmq indisponível neste ambiente.')
        with tempfile.TemporaryDirectory(prefix='bfs_async_live_eq_') as folder:
            root=Path(folder);source=root/'voice.wav';rate=48000
            tone=(.1*np.sin(2*np.pi*440*np.arange(rate*3)/rate)*32767).astype('<i2')
            with wave.open(str(source),'wb') as wav:
                wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(rate)
                wav.writeframes(tone.tobytes())
            project=Project(width=160,height=90,fps=12)
            clip=project.add_clip(Clip(str(source),0,3,kind='audio',
                track_id=project.tracks[-1].id))
            commands=prepare_commands(project,0,root/'preview',preview_width=160,
                fps=12,window=3,voice_control_clip_id=clip.id)
            audio_command=list(commands.audio)
            audio_command.insert(audio_command.index('-ss'),'-re')
            process=subprocess.Popen(audio_command,stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            controller=None
            try:
                controller=AsyncVoicePreviewController(commands.voice_control_address,
                    commands.voice_eq_targets,commands.voice_eq_initial,timeout_ms=750)
                time.sleep(.3)
                started=time.perf_counter()
                self.assertTrue(controller.set_eq(clip.id,{
                    'bass_db':4.,'mids_db':-1.,'treble_db':2.}))
                self.assertLess(time.perf_counter()-started,.1)
                self.assertTrue(controller.flush(timeout=2.))
                self.assertIsNone(process.poll(),
                    'Async EQ must update the existing FFmpeg process, not restart it')
            finally:
                if controller:controller.close()
                if process.poll() is None:process.terminate()
                try:process.wait(timeout=3)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=3)
                if process.stderr:process.stderr.close()


if __name__=='__main__':unittest.main()
