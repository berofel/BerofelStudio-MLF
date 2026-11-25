"""Tests deterministicos do adaptador ONNX Parakeet TDT v3 INT8/CPU."""
from __future__ import annotations

from array import array
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
import wave
from unittest.mock import patch

from berofel.services.parakeet_asr import (
    _word_groups, detect_speech, load_model, read_pcm16_mono_16k,
    transcribe_file, transcribe_samples,
)


class FakeModel:
    def __init__(self): self.calls=[]
    def recognize(self, samples, sample_rate):
        self.calls.append((len(samples),sample_rate))
        return SimpleNamespace(text=' Olá mundo',tokens=[' Olá',' mundo'],
                               timestamps=[.1,.5])


class FakeVad:
    def segment_batch(self, batch, lengths, sample_rate, **kwargs):
        self.call=(batch.shape,tuple(lengths),sample_rate,kwargs)
        return [[(1600,8000)]]


class ParakeetAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.model_dir=Path(self.temp.name)/'model'
        self.model_dir.mkdir()
        (self.model_dir/'encoder.int8.onnx').write_bytes(b'fixture')
        self.wav=Path(self.temp.name)/'tone.wav'
        with wave.open(str(self.wav),'wb') as f:
            f.setnchannels(1);f.setsampwidth(2);f.setframerate(16000)
            f.writeframes(array('h',[0,16384,-16384,32767]+[0]*31996).tobytes())

    def test_pcm_reader_validates_format_and_duration(self):
        pcm,duration=read_pcm16_mono_16k(self.wav)
        self.assertEqual(list(pcm[:4]),[0,16384,-16384,32767])
        self.assertEqual(duration,2.0)
        stereo=Path(self.temp.name)/'stereo.wav'
        with wave.open(str(stereo),'wb') as f:
            f.setnchannels(2);f.setsampwidth(2);f.setframerate(16000);f.writeframes(b'\0'*4)
        with self.assertRaisesRegex(ValueError,'mono'):
            read_pcm16_mono_16k(stereo)

    def test_sentencepiece_tokens_group_into_words_with_source_offset(self):
        words=_word_groups([' Olá',' mundo'],[.1,.5],12.0,2.0)
        self.assertEqual([w['text'] for w in words],['Olá','mundo'])
        self.assertEqual([(w['start'],w['end']) for w in words],[(12.1,12.5),(12.5,14.0)])

    def test_vad_returns_padded_seconds_and_caps_speech_windows(self):
        import numpy as np
        vad=FakeVad()
        spans=detect_speech(np.zeros(16000,dtype=np.float32),vad=vad,
                            speech_pad_ms=100,max_speech_seconds=20)
        self.assertEqual(spans,[{'start':.1,'end':.5}])
        self.assertEqual(vad.call[2],16000)

    def test_inference_reuses_one_model_for_regions_and_maps_original_times(self):
        import numpy as np
        model=FakeModel()
        audio=np.zeros(16000*4,dtype=np.float32)
        result=transcribe_samples(audio,4.,model=model,
            speech_spans=[{'start':1.,'end':2.},{'start':3.,'end':4.}],threads=6)
        self.assertEqual(model.calls,[(16000,16000),(16000,16000)])
        self.assertEqual([w['text'] for w in result['words']],['Olá','mundo','Olá','mundo'])
        self.assertEqual(result['words'][0]['start'],1.1)
        self.assertEqual(result['words'][2]['start'],3.1)
        self.assertEqual(result['backend'],'onnxruntime-cpu')
        self.assertEqual(result['model'],'parakeet-tdt-0.6b-v3-int8')
        self.assertEqual(result['language'],'multilingual-auto')
        self.assertIsNone(result['words'][0]['probability'])

    def test_model_loader_requires_local_int8_and_forces_cpu_provider(self):
        with patch('berofel.services.model_paths.parakeet_tdt_model_dir',
                   return_value=self.model_dir), \
             patch('berofel.services.parakeet_asr.make_session_options',return_value='options'), \
             patch.dict('sys.modules',{'onnx_asr':SimpleNamespace(load_model=lambda *a,**kw:
                 SimpleNamespace(with_timestamps=lambda:'loaded'))}) as modules:
            self.assertEqual(load_model(threads=6),'loaded')
        missing=Path(self.temp.name)/'missing'
        with patch('berofel.services.model_paths.parakeet_tdt_model_dir',return_value=missing):
            with self.assertRaisesRegex(FileNotFoundError,'TDT v3 INT8'):
                load_model()

    def test_file_transcription_uses_supplied_precomputed_spans(self):
        model=FakeModel()
        result=transcribe_file(self.wav,model=model,
            speech_spans=[{'start':0.,'end':1.}],threads=6)
        self.assertTrue(result['words'])
        self.assertEqual(model.calls,[(16000,16000)])


if __name__=='__main__': unittest.main()
