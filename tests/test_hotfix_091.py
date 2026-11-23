"""Regressão dos dois erros reportados em 13/11/2026."""
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
import wave

from berofel.services.ai_worker import _whisper


class WhisperCompatTest(unittest.TestCase):
    def test_whisper_uses_pcm_array_instead_of_pyav_path(self):
        class FakeWhisper:
            def __init__(self): self.called = False
            def transcribe(self, audio, **kwargs):
                self.kwargs=kwargs
                import numpy as np
                self.called = True
                self.assert_array = isinstance(audio, np.ndarray) and audio.dtype == np.dtype('float32')
                self.assert_shape = audio.shape
                word = SimpleNamespace(start=0.05,end=0.30,word='Olá',probability=0.9)
                segment = SimpleNamespace(start=0.0,end=0.5,text=' Olá',words=[word])
                return iter([segment]), SimpleNamespace(language='pt',duration=0.5)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'audio.wav'
            with wave.open(str(path),'wb') as wav:
                wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000)
                wav.writeframes(b'\0\0'*8000)
            fake=FakeWhisper()
            result=_whisper({'audio_path':str(path),'model':'base','language':'pt'},model=fake)
            self.assertTrue(fake.called)
            self.assertTrue(fake.assert_array)
            self.assertEqual(fake.assert_shape,(8000,))
            self.assertEqual(result['words'][0]['text'],'Olá')
            self.assertEqual(result['words'][0]['start'],0.05)
            self.assertEqual(result['language'],'pt')
            self.assertNotIn('hotwords',fake.kwargs)

    def test_optional_hotwords_are_passed_to_whisper_without_changing_word_timing_path(self):
        class FakeWhisper:
            def transcribe(self, audio, **kwargs):
                import numpy as np
                self.audio=audio;self.kwargs=kwargs
                word=SimpleNamespace(start=.05,end=.3,word='Berofel Studio',probability=.9)
                segment=SimpleNamespace(start=0.,end=.5,text=' Berofel Studio',words=[word])
                return iter([segment]),SimpleNamespace(language='pt',duration=.5)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'audio.wav'
            with wave.open(str(path),'wb') as wav:
                wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000)
                wav.writeframes(b'\0\0'*8000)
            fake=FakeWhisper()
            result=_whisper({'audio_path':str(path),'model':'base','language':'pt',
                             'hotwords':'Berofel Studio, timeline'},model=fake)
            self.assertEqual(fake.kwargs['hotwords'],'Berofel Studio, timeline')
            self.assertTrue(fake.kwargs['word_timestamps'])
            self.assertFalse(fake.kwargs['vad_filter'])
            self.assertEqual(result['words'][0]['text'],'Berofel Studio')

    def test_installer_searches_releases_and_fallback(self):
        path=Path(__file__).resolve().parents[1]/'scripts'/'instalar_qwen.ps1'
        text=path.read_text(encoding='utf-8')
        self.assertIn('releases?per_page=30',text)
        self.assertIn('releases/tags/v0.9.0',text)
        self.assertIn('bin-win-cpu-x64',text)
        self.assertIn('sha256:',text)
        self.assertIn('Qwen3-1.7B-Q4_K_M.gguf',text)

    def test_whisper_batch_reuses_one_model(self):
        from unittest.mock import patch
        from berofel.services import ai_worker
        class FakeModel: pass
        paths=[]
        with tempfile.TemporaryDirectory() as folder:
            jobs=[{'payload':{'audio_path':'any'},'output':str(Path(folder)/f'w_{i}.json')} for i in range(3)]
            with patch.object(ai_worker,'_load_whisper',return_value=FakeModel()) as loader, \
                 patch.object(ai_worker,'_whisper',return_value={'words':[], 'segments':[]}) as trans:
                result=ai_worker._whisper_batch({'jobs':jobs})
                self.assertEqual(result['completed'],3)
                loader.assert_called_once()
                self.assertEqual(trans.call_count,3)
                for j in jobs:self.assertTrue(Path(j['output']).is_file())


if __name__ == '__main__': unittest.main()
