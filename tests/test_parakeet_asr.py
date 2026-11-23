"""Small deterministic tests for the optional Parakeet ASR adapter."""
from __future__ import annotations

from array import array
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
import wave
from unittest.mock import patch

from berofel.services.parakeet_asr import read_pcm16_mono_16k, transcribe_file


class _FakeSession:
    def __enter__(self): return self
    def __exit__(self,*_args): return None
    def run(self,pcm,**kwargs):
        self.pcm=pcm
        self.kwargs=kwargs
        return SimpleNamespace(
            words=(SimpleNamespace(text='Olá,',t0_ms=120,t1_ms=420,seg_index=0),
                   SimpleNamespace(text=' mundo!',t0_ms=450,t1_ms=870,seg_index=0)),
            segments=(SimpleNamespace(text='Olá, mundo!',t0_ms=120,t1_ms=870,
                                      first_word=0,n_words=2),),
            language='pt',timestamp_kind='word')


class _FakeModel:
    def __init__(self,*_args,**kwargs): self.kwargs=kwargs;self.closed=False
    def __enter__(self): return self
    def __exit__(self,*_args): self.close()
    def session(self,**kwargs): self.session_options=kwargs;return _FakeSession()
    def close(self): self.closed=True


class _FakeBinding:
    Model=_FakeModel
    @staticmethod
    def native_version(): return '0.4.2-test'


class ParakeetAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.model=Path(self.temp.name)/'fake.gguf'
        self.model.write_bytes(b'not loaded in these tests')
        self.wav=Path(self.temp.name)/'tone.wav'
        with wave.open(str(self.wav),'wb') as f:
            f.setnchannels(1);f.setsampwidth(2);f.setframerate(16000)
            f.writeframes(array('h',[0,16384,-16384,32767]+[0]*31996).tobytes())

    def test_pcm_reader_validates_format_and_normalizes_duration(self):
        pcm,duration=read_pcm16_mono_16k(self.wav)
        self.assertEqual(list(pcm[:4]),[0.0,.5,-.5,32767/32768])
        self.assertEqual(duration,2.0)
        stereo=Path(self.temp.name)/'stereo.wav'
        with wave.open(str(stereo),'wb') as f:
            f.setnchannels(2);f.setsampwidth(2);f.setframerate(16000);f.writeframes(b'\0'*4)
        with self.assertRaisesRegex(ValueError,'mono'):
            read_pcm16_mono_16k(stereo)

    def test_result_word_times_are_seconds_and_segment_links_are_stable(self):
        with patch('berofel.services.parakeet_asr.load_binding',return_value=_FakeBinding):
            result=transcribe_file(self.wav,model_path=self.model,backend='vulkan',threads=6)
        self.assertEqual(result['timestamp_kind'],'word')
        self.assertEqual([w['text'] for w in result['words']],['Olá,','mundo!'])
        self.assertEqual([(w['start'],w['end']) for w in result['words']],[(.12,.42),(.45,.87)])
        self.assertEqual(result['segments'][0]['word_ids'],['p0_0','p0_1'])
        self.assertEqual(result['backend'],'vulkan')
        self.assertEqual(result['language'],'pt')

    def test_clamps_word_end_to_chunk_duration(self):
        class LateSession(_FakeSession):
            def run(self,pcm,**kwargs):
                return SimpleNamespace(words=(SimpleNamespace(text='fim',t0_ms=1900,t1_ms=3000,
                    seg_index=0),),segments=(),language='',timestamp_kind='word')
        class LateModel(_FakeModel):
            def session(self,**kwargs):return LateSession()
        class LateBinding(_FakeBinding):Model=LateModel
        with patch('berofel.services.parakeet_asr.load_binding',return_value=LateBinding):
            result=transcribe_file(self.wav,model_path=self.model)
        self.assertEqual(result['words'][0]['end'],2.0)


if __name__=='__main__':
    unittest.main()
