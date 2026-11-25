"""Regressoes de ASR local ONNX: lote com um modelo e nenhum fallback."""
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from berofel.services import ai_worker


class ParakeetWorkerTests(unittest.TestCase):
    def test_single_worker_loads_model_separately_then_passes_loaded_instance(self):
        model=object()
        expected={'words':[],'segments':[]}
        with patch('berofel.services.parakeet_asr.load_model',return_value=model) as load, \
             patch('berofel.services.parakeet_asr.transcribe_file',return_value=expected) as transcribe:
            result=ai_worker._parakeet({'audio_path':'input.wav','model_path':'local',
                                        'speech_spans':[],'threads':4})
        self.assertIs(result,expected)
        load.assert_called_once_with(model_path='local',threads=4)
        transcribe.assert_called_once_with('input.wav',model=model,speech_spans=[],threads=4)

    def test_parakeet_batch_loads_one_model_and_reuses_for_all_chunks(self):
        calls=[]
        class FakeModel:
            pass
        def fake_transcribe(payload,*,model):
            calls.append((payload['audio_path'],model))
            return {'words':[],'segments':[],'model':'parakeet-tdt-0.6b-v3-int8'}
        with tempfile.TemporaryDirectory() as folder:
            jobs=[{'payload':{'audio_path':f'chunk-{i}.wav','model_path':'local-model',
                              'threads':6},'output':str(Path(folder)/f'{i}.json')}
                  for i in range(3)]
            with patch('berofel.services.parakeet_asr.load_model',return_value=FakeModel()) as load, \
                 patch.object(ai_worker,'_parakeet',side_effect=fake_transcribe):
                result=ai_worker._parakeet_batch({'jobs':jobs})
            self.assertEqual(result,{'completed':3})
            load.assert_called_once()
            self.assertEqual(len({id(model) for _,model in calls}),1)
            self.assertTrue(all(Path(job['output']).is_file() for job in jobs))

    def test_worker_has_no_whisper_handler(self):
        self.assertIn('parakeet',ai_worker.HANDLERS)
        self.assertIn('parakeet_batch',ai_worker.HANDLERS)
        self.assertNotIn('whisper',ai_worker.HANDLERS)
        self.assertNotIn('whisper_batch',ai_worker.HANDLERS)


if __name__=='__main__': unittest.main()
