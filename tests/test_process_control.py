"""Testes reais de suspensão e cancelamento, sem baixar modelos de IA."""
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import wave
from pathlib import Path

from berofel.services.process_control import ProcessControl, ProcessCancelled, psutil
from berofel.services.ai_pipeline import Pipeline, AIOptions, StageRunner
from berofel.services.ai_cache import CacheStore, CACHE_SCHEMA, write_json, read_json
from berofel.services.tasks import Task
from berofel.core.project import Clip


class ControlTests(unittest.TestCase):
    def test_task_does_not_deliver_audio_chunks_unless_explicitly_enabled(self):
        def synthesize(audio_chunk=None):
            if audio_chunk is not None:
                audio_chunk(b'pcm')
            return audio_chunk is not None

        default_chunks = []
        default_task = Task(synthesize)
        default_task.signals.audio_chunk.connect(default_chunks.append)
        default_task.run()
        self.assertEqual(default_chunks, [])

        streamed_chunks = []
        streamed_task = Task(synthesize, stream_audio=True)
        streamed_task.signals.audio_chunk.connect(streamed_chunks.append)
        streamed_task.run()
        self.assertEqual(streamed_chunks, [b'pcm'])

    def test_cancel_after_task_result_cleans_nested_temporary_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            task_ref={}
            created=[]
            cancelled=[]
            def work():
                tempdir=tempfile.TemporaryDirectory(prefix='bfs_task_test_',dir=folder)
                created.append(Path(tempdir.name))
                task_ref['task'].control.cancel()
                return {'preview':('commands',tempdir)}
            task=Task(work)
            task_ref['task']=task
            task.signals.cancelled.connect(lambda:cancelled.append(True))
            task.run()
            self.assertEqual(cancelled,[True])
            self.assertEqual(len(created),1)
            self.assertFalse(created[0].exists(),
                             'Resultado temporário cancelado precisa ser limpo explicitamente.')

    def test_pause_resume_without_progress_or_elapsed_spike(self):
        control = ProcessControl()
        with tempfile.TemporaryDirectory() as folder:
            counter = Path(folder) / 'counter.txt'
            code = ("import pathlib,time,sys; p=pathlib.Path(sys.argv[1]); "
                    "[(p.write_text(str(i)),time.sleep(.06)) for i in range(100)]")
            proc = control.popen([sys.executable, '-u', '-c', code, str(counter)])
            try:
                deadline = time.monotonic() + 3
                while not counter.exists() and time.monotonic() < deadline:
                    time.sleep(.03)
                self.assertTrue(counter.exists())
                time.sleep(.14)
                self.assertTrue(control.pause())
                before = counter.read_text()
                elapsed = control.elapsed()
                time.sleep(.35)
                self.assertEqual(counter.read_text(), before, 'O processo continuou executando durante a pausa')
                self.assertLess(control.elapsed()-elapsed, .12, 'Pausa não deve ser contada no tempo ativo')
                self.assertTrue(control.resume())
                deadline = time.monotonic()+2
                while counter.read_text() == before and time.monotonic() < deadline:
                    time.sleep(.04)
                self.assertNotEqual(counter.read_text(), before)
            finally:
                control.cancel()
                proc.wait(timeout=4)
                control.release(proc)

    def test_run_invokes_nonblocking_poll_callback_while_child_is_active(self):
        control=ProcessControl();events=[]
        result=control.run([sys.executable,'-c','import time; time.sleep(.45)'],
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=3,
            on_poll=lambda:events.append(time.monotonic()))
        self.assertEqual(result.returncode,0)
        self.assertGreaterEqual(len(events),1)

    def test_real_stage_runner_extracts_audio_in_tracked_subprocess(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder)
            source=folder/'source.wav'
            with wave.open(str(source),'wb') as f:
                f.setnchannels(1)
                f.setsampwidth(2)
                f.setframerate(16000)
                f.writeframes(b'\0\0'*16000)
            result=StageRunner()('extract',{'source':str(source),'start':0.,
                        'duration':.8,'audio_path':str(folder/'result.wav')},
                        folder/'stage.json',control=ProcessControl())
            self.assertGreater(Path(result['audio_path']).stat().st_size,44)
            self.assertEqual(read_json(folder/'stage.json')['stage'],'extract')

    def test_cancel_kills_running_process_and_reports_cancellation(self):
        control = ProcessControl()
        result = []
        def worker():
            try:
                control.run([sys.executable, '-c', 'import time; time.sleep(30)'],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            except ProcessCancelled:
                result.append('cancelled')
            except Exception as error:
                result.append(type(error).__name__)
        thread = threading.Thread(target=worker)
        thread.start()
        time.sleep(.3)
        self.assertTrue(control.cancel())
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive(), 'O cancelamento deixou o processo preso')
        self.assertEqual(result, ['cancelled'])

    def test_cache_survives_cancel_and_resumes_later(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'media.mp4'
            source.write_bytes(b'fake-media')
            clip = Clip(source=str(source),start=0,end=5,kind='video')
            control = ProcessControl()
            calls = []
            def fake(stage,payload,output,**kwargs):
                calls.append(stage)
                if stage == 'extract':
                    wav = Path(payload['audio_path'])
                    wav.write_bytes(b'RIFF' + b'0'*80)
                    result = {'audio_path':str(wav),'duration':5}
                elif stage == 'vad':
                    result = {'speech':[{'start':0,'end':5}], 'duration':5}
                elif stage == 'whisper':
                    result = {'words':[], 'segments':[], 'duration':5}
                else:
                    raise AssertionError(stage)
                write_json(Path(output),{'schema':CACHE_SCHEMA,'stage':stage,'result':result})
                return result
            cache = CacheStore(Path(folder)/'cache')
            def stop_after_first(done,total):
                if done == 1:
                    control.cancel()
            with self.assertRaises(ProcessCancelled):
                Pipeline(cache,fake,control=control).analyze([clip],AIOptions(),progress=stop_after_first)
            self.assertEqual(calls,['extract'])
            result = Pipeline(cache,fake,control=ProcessControl()).analyze([clip],AIOptions())
            self.assertEqual(calls,['extract','vad','whisper'])
            self.assertEqual(result['cache_hits'],1)
            self.assertEqual(result['cache_misses'],2)


if __name__ == '__main__':
    unittest.main()
