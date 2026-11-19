"""Testes sem download/inferência real do backend de clonagem Qwen."""
from pathlib import Path
import json
import os
import tempfile
import unittest
import wave
from unittest.mock import patch

from berofel.services.narration_service import NarrationRequest, generate_narration
from berofel.services import qwen3_tts_local as qwen


class QwenLocalCloneTests(unittest.TestCase):
    def test_standard_installation_has_no_pocket_tts_backend_or_installer(self):
        root=Path(__file__).resolve().parents[1]
        for name in ('requirements.txt','requirements-core.txt','requirements-ai.txt'):
            self.assertNotIn('pocket-tts',(root/name).read_text(encoding='utf-8').casefold())
        for relative in ('INSTALAR_POCKET_TTS.bat','AUTORIZAR_POCKET_TTS.bat',
                         'scripts/instalar_pocket.ps1',
                         'berofel/services/pocket_tts_worker.py'):
            self.assertFalse((root/relative).exists(),relative)

    def test_qwen_installer_provisions_ffmpeg_module_for_isolated_worker(self):
        script=Path(__file__).resolve().parents[1]/'scripts'/'instalar_qwen3_tts_local.ps1'
        source=script.read_text(encoding='utf-8')
        self.assertIn('imageio-ffmpeg',source)
        self.assertIn('imageio_ffmpeg',source)

    def test_narration_service_routes_qwen_and_rejects_other_engines(self):
        with tempfile.TemporaryDirectory() as folder:
            sample=Path(folder)/'voice.wav'
            with wave.open(str(sample),'wb') as output:
                output.setnchannels(1);output.setsampwidth(2);output.setframerate(24000)
                output.writeframes(b'\x01\x00'*2400)
            request=NarrationRequest(text='teste',voice=str(sample),consent=True)
            expected={'path':'local.wav','duration':1.,'cache_hit':False}
            with patch('berofel.services.qwen3_tts_local.generate_local_clone',
                       return_value=expected) as backend:
                self.assertEqual(generate_narration(request),expected)
            backend.assert_called_once_with(request,progress=None,runner=None,
                                            control=None,stage=None)
            with self.assertRaisesRegex(ValueError,'exclusivamente Qwen3-TTS Base'):
                generate_narration(NarrationRequest(text='teste',voice=str(sample),
                    consent=True,engine='pocket-tts'))

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
            request=NarrationRequest(text='teste',voice=str(sample),consent=True)
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
                @staticmethod
                def set_num_interop_threads(count):requests.append(('interop_threads',count))
            class FakeModel:
                @classmethod
                def from_pretrained(cls,*args,**kwargs):
                    requests.append(('load',args,kwargs));return cls()
                def generate_voice_clone(self,**kwargs):
                    requests.append(('clone',kwargs));return [np.zeros(2400,dtype=np.float32)],24000
                def create_voice_clone_prompt(self,**kwargs):
                    requests.append(('prompt',kwargs));return ['prepared prompt']
            package=types.SimpleNamespace(Qwen3TTSModel=FakeModel,
                                          VoiceClonePromptItem=object)
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
            self.assertEqual(clone['voice_clone_prompt'],['prepared prompt'])
            self.assertEqual(clone['max_new_tokens'],96)
            self.assertTrue(output.is_file())
            self.assertEqual(sample.read_bytes(),b'original')

    def test_warm_worker_loads_model_once_and_reuses_voice_prompt(self):
        import io
        import sys
        import numpy as np
        from berofel.services import qwen3_tts_worker as worker
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);sample=root/'reference.wav';sample.write_bytes(b'authorized sample')
            requests=[]
            class FakeModel:
                def create_voice_clone_prompt(self,**kwargs):
                    requests.append(('prompt',kwargs));return ['prepared']
                def generate_voice_clone(self,**kwargs):
                    requests.append(('generate',kwargs))
                    return [np.ones(2400,dtype=np.float32)*.1],24000
            model=FakeModel();jobs=[]
            for index in range(2):
                jobs.append(json.dumps({'text':f'fala {index}','reference':str(sample),
                    'reference_text':'texto exato','language':'Portuguese','consent':True,
                    'output':str(root/f'out{index}.wav'),'model_fingerprint':'fingerprint'}))
            jobs.append(json.dumps({'operation':'shutdown'}))
            incoming=io.StringIO('\n'.join(jobs)+'\n');outgoing=io.StringIO()
            with patch.object(worker,'_load_model',return_value=model) as loader, \
                 patch.object(worker,'prepare_audio_prompt',return_value=(str(sample),None)), \
                 patch.object(sys,'stdin',incoming),patch.object(sys,'stdout',outgoing):
                worker.serve(str(root/'unused-model'))
            loader.assert_called_once()
            self.assertEqual(sum(item[0]=='prompt' for item in requests),1,outgoing.getvalue())
            self.assertEqual(sum(item[0]=='generate' for item in requests),2)
            responses=[json.loads(line) for line in outgoing.getvalue().splitlines()]
            self.assertFalse(responses[1]['result']['prompt_cache_hit'])
            self.assertTrue(responses[2]['result']['prompt_cache_hit'])
            self.assertTrue(responses[3]['shutdown'])
            self.assertTrue((root/'out0.wav').is_file())
            self.assertTrue((root/'out1.wav').is_file())

    def test_voice_prompt_cache_persists_safely_across_worker_restarts(self):
        import sys
        import types
        import numpy as np
        from berofel.services import qwen3_tts_worker as worker
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);sample=root/'reference.wav';sample.write_bytes(b'authorized local reference')
            request={'reference':str(sample),'reference_text':'texto conferido',
                     'model_fingerprint':'model-fingerprint',
                     'prompt_cache_path':str(root/'cache'/'voice.npz')}
            class Tensor:
                def __init__(self,array):self.array=np.asarray(array)
                def detach(self):return self
                def cpu(self):return self
                def numpy(self):return self.array
            class Item:
                def __init__(self,**kwargs):self.__dict__.update(kwargs)
            fake_torch=types.SimpleNamespace(from_numpy=lambda value:np.asarray(value))
            fake_qwen=types.SimpleNamespace(VoiceClonePromptItem=Item)
            with patch.dict(os.environ,{'BEROFEL_QWEN3_PROMPT_CACHE':str(root/'cache')}), \
                 patch.dict(sys.modules,{'torch':fake_torch,'qwen_tts':fake_qwen}):
                key=worker._prompt_key(request)
                original=[Item(ref_code=Tensor(np.asarray([3,4],dtype=np.int64)),
                    ref_spk_embedding=Tensor(np.asarray([.1,.2],dtype=np.float32)),
                    x_vector_only_mode=False,icl_mode=True,ref_text='texto conferido')]
                worker._save_cached_prompt(original,request,key)
                loaded=worker._load_cached_prompt(object(),request,key)
            self.assertEqual(len(loaded),1)
            self.assertEqual(loaded[0].ref_text,'texto conferido')
            self.assertEqual(loaded[0].ref_code.tolist(),[3,4])
            self.assertTrue(np.allclose(loaded[0].ref_spk_embedding,[.1,.2]))
            cached=next((root/'cache').glob('*.npz'))
            with np.load(cached,allow_pickle=False) as data:
                self.assertIn('metadata',data.files)
                self.assertEqual(str(data['metadata'].item()).find('model-fingerprint')>=0,True)

    def test_reference_quality_report_measures_pcm_without_changing_source(self):
        import numpy as np
        from scipy.io import wavfile
        from berofel.services import audio_reference
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'source.wav';normalized=Path(folder)/'normalized.wav'
            wavfile.write(str(normalized),24000,
                (np.sin(np.arange(72000)*2*np.pi*220/24000)*12000).astype(np.int16))
            source.write_bytes(b'authorized source bytes')
            original=source.read_bytes()
            with patch.object(audio_reference,'prepare_audio_prompt',
                return_value=(str(normalized),None)):
                report=audio_reference.inspect_voice_reference(source)
            self.assertAlmostEqual(report['duration'],3.0,places=2)
            self.assertGreater(report['rms_dbfs'],-15)
            self.assertEqual(source.read_bytes(),original)


if __name__=='__main__':unittest.main()
