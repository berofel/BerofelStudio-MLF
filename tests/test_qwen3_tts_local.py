"""Testes sem download/inferência real do backend de clonagem Qwen."""
from pathlib import Path
import json
import os
import tempfile
import unittest
import wave
from unittest.mock import patch

from berofel.services.pocket_tts_service import NarrationRequest, generate_narration
from berofel.services import qwen3_tts_local as qwen


class QwenLocalCloneTests(unittest.TestCase):
    def test_narration_service_routes_only_selected_qwen_requests(self):
        request=NarrationRequest(text='teste',voice='voice.wav',consent=True,
                                 engine='qwen3-tts-local')
        expected={'path':'local.wav','duration':1.,'cache_hit':False}
        with patch('berofel.services.qwen3_tts_local.generate_local_clone',
                   return_value=expected) as backend:
            self.assertEqual(generate_narration(request),expected)
        backend.assert_called_once_with(request,progress=None,runner=None,
                                        control=None,stage=None)

    def test_ready_requires_isolated_runtime_and_complete_local_checkpoint(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);py=root/'python.exe';model=root/'model'
            model.mkdir();py.touch()
            with patch.object(qwen,'python_path',return_value=py), \
                 patch.object(qwen,'model_path',return_value=model):
                self.assertFalse(qwen.is_ready())
                for relative in qwen.REQUIRED_MODEL_FILES:
                    target=model/relative;target.parent.mkdir(parents=True,exist_ok=True);target.touch()
                self.assertTrue(qwen.is_ready())

    def test_qwen_clone_cache_reuses_generation_without_touching_reference(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);sample=root/'my_voice.wav';project=root/'project.bfs'
            with wave.open(str(sample),'wb') as output:
                output.setnchannels(1);output.setsampwidth(2);output.setframerate(24000)
                output.writeframes(b'\x00\x00'*2400)
            original=sample.read_bytes();model=root/'model';model.mkdir()
            (model/'config.json').write_text('{}',encoding='utf-8')
            request=NarrationRequest(text='Olá, teste local.',voice=str(sample),
                language='portuguese',consent=True,project_path=str(project),
                title='Teste Qwen',engine='qwen3-tts-local',reference_text='Minha voz.')
            calls=[]
            def runner(job_path,result_path):
                calls.append(1);job=json.loads(Path(job_path).read_text(encoding='utf-8'))
                with wave.open(job['output'],'wb') as output:
                    output.setnchannels(1);output.setsampwidth(2);output.setframerate(24000)
                    output.writeframes(b'\x01\x00'*2400)
                Path(result_path).write_text(json.dumps({'duration':.1}),encoding='utf-8')
            with patch.dict(os.environ,{'BEROFEL_AI_CACHE':str(root/'cache')}), \
                 patch.object(qwen,'is_ready',return_value=True), \
                 patch.object(qwen,'model_path',return_value=model):
                first=qwen.generate_local_clone(request,runner=runner)
                second=qwen.generate_local_clone(request,runner=runner)
            self.assertFalse(first['cache_hit'])
            self.assertTrue(second['cache_hit'])
            self.assertEqual(calls,[1])
            self.assertNotEqual(first['path'],second['path'])
            self.assertEqual(sample.read_bytes(),original)
            self.assertTrue(Path(first['path']).is_file())

    def test_missing_model_reports_explicit_install_step_before_any_worker(self):
        with tempfile.TemporaryDirectory() as folder:
            sample=Path(folder)/'voice.wav';sample.write_bytes(b'voice')
            request=NarrationRequest(text='teste',voice=str(sample),consent=True,
                                     engine='qwen3-tts-local')
            with patch.object(qwen,'is_ready',return_value=False):
                with self.assertRaisesRegex(RuntimeError,'INSTALAR_QWEN3_TTS_LOCAL.bat'):
                    qwen.generate_local_clone(request)

    def test_qwen_worker_uses_offline_cpu_clone_api_and_keeps_reference(self):
        import sys
        import types
        import numpy as np
        from berofel.services import qwen3_tts_worker as worker
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);sample=root/'voice.wav';sample.write_bytes(b'original')
            model=root/'model';model.mkdir();(model/'config.json').touch()
            output=root/'result.wav';result=root/'result.json'
            requests=[]
            class FakeTorch:
                float32='float32'
                @staticmethod
                def set_num_threads(count):requests.append(('threads',count))
            class FakeModel:
                @classmethod
                def from_pretrained(cls,*args,**kwargs):
                    requests.append(('load',args,kwargs));return cls()
                def generate_voice_clone(self,**kwargs):
                    requests.append(('clone',kwargs));return [np.zeros(2400,dtype=np.float32)],24000
            package=types.SimpleNamespace(Qwen3TTSModel=FakeModel)
            fake_prepare=lambda _src,_dst:(str(sample),None)
            job=root/'job.json'
            job.write_text(json.dumps({'consent':True,'model_path':str(model),
                'output':str(output),'reference':str(sample),'text':'fala',
                'language':'Portuguese','reference_text':'texto referência'}),encoding='utf-8')
            with patch.dict(sys.modules,{'torch':FakeTorch,'qwen_tts':package}), \
                 patch.object(worker,'prepare_audio_prompt',side_effect=fake_prepare):
                worker.run(str(job),str(result))
            load=next(item for item in requests if item[0]=='load')
            self.assertEqual(load[2]['device_map'],'cpu')
            self.assertTrue(load[2]['local_files_only'])
            clone=next(item for item in requests if item[0]=='clone')[1]
            self.assertEqual(clone['ref_text'],'texto referência')
            self.assertTrue(output.is_file())
            self.assertEqual(sample.read_bytes(),b'original')


if __name__=='__main__':unittest.main()
