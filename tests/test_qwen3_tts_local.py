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
    def test_canonical_service_rejects_unreviewed_ptbr_transcript_before_backend(self):
        request=NarrationRequest(text='frase nova',voice='voice.wav',consent=True,
            engine='qwen3-tts-local',language='portuguese',
            reference_text='rascunho do Whisper',reference_text_reviewed=False)
        with patch('berofel.services.qwen3_tts_local.generate_local_clone') as backend:
            with self.assertRaisesRegex(ValueError,'ainda não foi confirmada'):
                generate_narration(request)
        backend.assert_not_called()

    def test_stopping_worker_closes_all_subprocess_pipes(self):
        import io
        from unittest.mock import Mock
        process=Mock()
        process.poll.return_value=0
        process.stdin=io.StringIO()
        process.stdout=io.StringIO()
        process.stderr=io.StringIO()
        with patch.object(qwen,'_WORKER_PROCESS',process), \
             patch.object(qwen,'_WORKER_MODEL_KEY','cached-model'), \
             patch.object(qwen,'_WORKER_LOAD_SECONDS',2.0):
            qwen.stop_local_worker()
        self.assertTrue(process.stdin.closed)
        self.assertTrue(process.stdout.closed)
        self.assertTrue(process.stderr.closed)

    def test_worker_reader_reports_startup_progress_and_continues_to_ready(self):
        import io
        class FakeProcess:
            stdout=io.StringIO('{"progress":"Importando Qwen3-TTS…"}\n{"ready":true}\n')
            def poll(self):return None
        stages=[]
        response=qwen._read_worker_line(FakeProcess(),timeout=2,stage=stages.append)
        self.assertTrue(response['ready'])
        self.assertEqual(stages,['Qwen3-TTS Base • Importando Qwen3-TTS…'])

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
            request=NarrationRequest(text='teste',voice=str(sample),consent=True,
                                     reference_text='fala exata da referência',
                                     reference_text_reviewed=True)
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
                title='Teste Qwen',engine='qwen3-tts-local',reference_text='Minha voz.',
                reference_text_reviewed=True)
            calls=[]
            def runner(job_path,result_path):
                calls.append(1);job=json.loads(Path(job_path).read_text(encoding='utf-8'))
                with wave.open(job['output'],'wb') as output:
                    output.setnchannels(1);output.setsampwidth(2);output.setframerate(24000)
                    output.writeframes(b'\x01\x00'*2400)
                Path(result_path).write_text(json.dumps({'duration':.1,
                    'conditioning_mode':'audio+transcript','conditioning_verified':True,
                    'icl_mode':True,'x_vector_only_mode':False}),encoding='utf-8')
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
                                     reference_text='fala exata da referência',
                                     reference_text_reviewed=True)
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
            class PromptItem:
                ref_code=np.asarray([1,2,3],dtype=np.int64)
                ref_spk_embedding=np.asarray([.2,.4,.3],dtype=np.float32)
                x_vector_only_mode=False
                icl_mode=True
                ref_text='texto referência'
            class FakeModel:
                @classmethod
                def from_pretrained(cls,*args,**kwargs):
                    requests.append(('load',args,kwargs));return cls()
                def generate_voice_clone(self,**kwargs):
                    requests.append(('clone',kwargs));return [np.zeros(2400,dtype=np.float32)],24000
                def create_voice_clone_prompt(self,**kwargs):
                    requests.append(('prompt',kwargs));return [PromptItem()]
            package=types.SimpleNamespace(Qwen3TTSModel=FakeModel,
                                          VoiceClonePromptItem=object)
            prepare_calls=[]
            fake_prepare=lambda _src,_dst,**kwargs:(prepare_calls.append(kwargs) or (str(sample),None))
            job=root/'job.json'
            job.write_text(json.dumps({'consent':True,'model_path':str(model),
                'output':str(output),'reference':str(sample),'text':'fala',
                'language':'Portuguese','reference_text':'texto referência',
                'reference_window_start':42.0,'reference_window_duration':18.0}),encoding='utf-8')
            with patch.dict(sys.modules,{'torch':FakeTorch,'qwen_tts':package}), \
                 patch.object(worker,'prepare_audio_prompt',side_effect=fake_prepare):
                worker.run(str(job),str(result))
            load=next(item for item in requests if item[0]=='load')
            self.assertEqual(load[2]['device_map'],'cpu')
            self.assertTrue(load[2]['local_files_only'])
            clone=next(item for item in requests if item[0]=='clone')[1]
            self.assertIsInstance(clone['voice_clone_prompt'][0],PromptItem)
            self.assertEqual(clone['max_new_tokens'],96)
            prompt_args=next(item for item in requests if item[0]=='prompt')[1]
            self.assertEqual(prompt_args['ref_audio'],str(sample))
            self.assertEqual(prompt_args['ref_text'],'texto referência')
            self.assertFalse(prompt_args['x_vector_only_mode'])
            self.assertTrue(output.is_file())
            self.assertEqual(sample.read_bytes(),b'original')
            self.assertEqual(prepare_calls,[{'start_seconds':42.0,'duration_seconds':18.0,
                                             'trim_outer_silence':True}])
            result_data=json.loads(result.read_text(encoding='utf-8'))
            self.assertEqual(result_data['reference_window'],{'start':42.0,'duration':18.0})
            self.assertEqual(result_data['conditioning_mode'],'audio+transcript')
            self.assertTrue(result_data['conditioning_verified'])
            self.assertTrue(result_data['icl_mode'])
            self.assertFalse(result_data['x_vector_only_mode'])
            self.assertEqual(result_data['reference_text_word_count'],2)

    def test_warm_worker_loads_model_once_and_reuses_voice_prompt(self):
        import io
        import sys
        import types
        import numpy as np
        from berofel.services import qwen3_tts_worker as worker
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);sample=root/'reference.wav';sample.write_bytes(b'authorized sample')
            requests=[]
            class FakeModel:
                def create_voice_clone_prompt(self,**kwargs):
                    requests.append(('prompt',kwargs))
                    return [types.SimpleNamespace(ref_code=np.asarray([1,2]),
                        ref_spk_embedding=np.asarray([.1,.2]),
                        x_vector_only_mode=False,icl_mode=True,ref_text='texto exato')]
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
            self.assertTrue(responses[0]['ready'])
            self.assertGreaterEqual(responses[0]['model_load_seconds'],0.0)
            self.assertFalse(responses[1]['result']['prompt_cache_hit'])
            self.assertTrue(responses[2]['result']['prompt_cache_hit'])
            for response in responses[1:3]:
                self.assertGreaterEqual(response['result']['model_load_seconds'],0.0)
                self.assertGreaterEqual(response['result']['profile_prepare_seconds'],0.0)
                self.assertGreaterEqual(response['result']['generation_seconds'],0.0)
            self.assertTrue(responses[3]['shutdown'])
            self.assertTrue((root/'out0.wav').is_file())
            self.assertTrue((root/'out1.wav').is_file())

    def test_text_conditioned_clone_fails_closed_without_reference_codes(self):
        import numpy as np
        from types import SimpleNamespace
        from berofel.services import qwen3_tts_worker as worker
        item=SimpleNamespace(ref_code=None,ref_spk_embedding=np.asarray([.1,.2]),
            x_vector_only_mode=True,icl_mode=False,ref_text=None)
        with self.assertRaisesRegex(RuntimeError,'áudio, transcrição e vetor vocal'):
            worker._verify_clone_conditioning([item],'transcrição conferida')

    def test_text_conditioned_clone_fails_closed_when_reference_text_changed(self):
        import numpy as np
        from types import SimpleNamespace
        from berofel.services import qwen3_tts_worker as worker
        item=SimpleNamespace(ref_code=np.asarray([1,2]),ref_spk_embedding=np.asarray([.1,.2]),
            x_vector_only_mode=False,icl_mode=True,ref_text='texto diferente')
        with self.assertRaisesRegex(RuntimeError,'áudio, transcrição e vetor vocal'):
            worker._verify_clone_conditioning([item],'transcrição conferida')

    def test_worker_model_loader_reports_real_startup_phases(self):
        import sys
        import types
        from berofel.services import qwen3_tts_worker as worker
        class FakeTorch:
            float32='float32'
            @staticmethod
            def set_num_threads(_count):pass
            @staticmethod
            def set_num_interop_threads(_count):pass
        class FakeModel:
            @classmethod
            def from_pretrained(cls,*_args,**_kwargs):return cls()
        model=types.SimpleNamespace(Qwen3TTSModel=FakeModel)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'config.json').touch();stages=[]
            with patch.dict(sys.modules,{'torch':FakeTorch,'qwen_tts':model}), \
                 patch.object(worker.os,'cpu_count',return_value=8), \
                 patch.object(worker,'install_librosa_compat') as install_compat:
                loaded=worker._load_model(root,progress=stages.append)
        install_compat.assert_called_once()
        self.assertIsInstance(loaded,FakeModel)
        self.assertEqual(stages,[
            'Importando PyTorch para CPU…',
            'Importando Qwen3-TTS…',
            'Lendo os pesos locais do Qwen3-TTS 0.6B…',
            'Pesos carregados; preparando a sessão de narração…'])

    def test_qwen_audio_compat_loads_local_audio_and_resamples_without_librosa(self):
        import numpy as np
        import sys
        import types
        from scipy.io import wavfile
        from scipy.fft import rfft, rfftfreq
        from berofel.services import qwen3_audio_compat as audio
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);sample=root/'stereo.wav';rate=24000
            time_axis=np.arange(rate,dtype=np.float32)/rate
            left=.3*np.sin(2*np.pi*440*time_axis)
            right=.3*np.sin(2*np.pi*440*time_axis)
            wavfile.write(sample,rate,(np.column_stack((left,right))*32767).astype(np.int16))
            class FakeSoundFile:
                def __init__(self,path):
                    self.rate,self.data=wavfile.read(path);self.position=0
                    self.samplerate=self.rate
                def __enter__(self):return self
                def __exit__(self,*_args):return False
                def __len__(self):return len(self.data)
                def seek(self,position):self.position=position
                def read(self,frames=-1,dtype='float32',always_2d=True):
                    end=len(self.data) if frames<0 else self.position+frames
                    data=self.data[self.position:end].astype(np.float32)/32768.0
                    return data if data.ndim>1 or not always_2d else data[:,None]
            fake_soundfile=types.SimpleNamespace(SoundFile=FakeSoundFile)
            with patch.dict(sys.modules,{'soundfile':fake_soundfile}):
                mono,source_rate=audio.load(sample,sr=None,mono=True)
        converted=audio.resample(mono,source_rate,16000)
        spectrum=np.abs(rfft(converted))
        peak_frequency=rfftfreq(converted.size,1/16000)[int(np.argmax(spectrum[1:])+1)]
        self.assertEqual(source_rate,24000)
        self.assertEqual(mono.shape,(24000,))
        self.assertEqual(converted.shape,(16000,))
        self.assertAlmostEqual(peak_frequency,440,delta=2)
        self.assertLess(float(np.max(np.abs(converted))),.32)

    def test_qwen_audio_compat_installs_audio_and_mel_apis_used_by_qwen(self):
        import sys
        from berofel.services import qwen3_audio_compat as audio
        original=sys.modules.pop('librosa',None)
        original_filters=sys.modules.pop('librosa.filters',None)
        try:
            audio.install_librosa_compat()
            module=sys.modules['librosa']
            self.assertEqual(module.__version__,'0.10.2')
            self.assertIs(module.load,audio.load)
            self.assertIs(module.resample,audio.resample)
            self.assertTrue(hasattr(module,'filters'))
            self.assertIs(module.filters.mel,audio.mel)
            for sample_rate,fft_size,bands in ((24000,1024,80),(16000,400,128)):
                matrix=module.filters.mel(sr=sample_rate,n_fft=fft_size,n_mels=bands)
                self.assertEqual(matrix.shape,(bands,1+fft_size//2))
                self.assertTrue((matrix>=0).all())
                self.assertTrue((matrix.sum(axis=1)>0).all())
                self.assertTrue(__import__('numpy').isfinite(matrix).all())
        finally:
            sys.modules.pop('librosa',None)
            sys.modules.pop('librosa.filters',None)
            if original is not None:
                sys.modules['librosa']=original
            if original_filters is not None:
                sys.modules['librosa.filters']=original_filters

    def test_worker_transmits_startup_error_before_exiting(self):
        import io
        import sys
        from contextlib import redirect_stdout, redirect_stderr
        from berofel.services import qwen3_tts_worker as worker
        outgoing=io.StringIO()
        with patch.object(worker,'_load_model',side_effect=RuntimeError('checkpoint inválido')), \
             patch.object(sys,'stdin',io.StringIO('')), \
             patch.object(sys,'stdout',outgoing), \
             redirect_stdout(outgoing),redirect_stderr(io.StringIO()), \
             self.assertRaisesRegex(RuntimeError,'checkpoint inválido'):
            worker.serve('model')
        response=json.loads(outgoing.getvalue().splitlines()[0])
        self.assertEqual(response['startup_error'],'RuntimeError')
        self.assertIn('checkpoint inválido',response['error'])

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
                return_value=(str(normalized),None)), \
                 patch.object(audio_reference,'_reference_window',return_value=(0.0,3.0,1.0)), \
                 patch('berofel.services.ffmpeg.media_info',return_value=(3.0,False,True)):
                report=audio_reference.inspect_voice_reference(source)
            self.assertAlmostEqual(report['duration'],3.0,places=2)
            self.assertAlmostEqual(report['audible_signal_seconds'],3.0,delta=.05)
            self.assertGreater(report['rms_dbfs'],-15)
            self.assertEqual(source.read_bytes(),original)

    def test_reference_quality_warns_when_more_than_half_is_silent(self):
        import numpy as np
        from scipy.io import wavfile
        from berofel.services import audio_reference
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source.wav';normalized=root/'normalized.wav'
            rate=24000;frames=rate*4;signal=np.zeros(frames,dtype=np.int16)
            active=int(frames*.449)
            signal[:active]=(np.sin(np.arange(active)*2*np.pi*220/rate)*12000).astype(np.int16)
            wavfile.write(str(normalized),rate,signal)
            source.write_bytes(b'authorized source bytes')
            with patch.object(audio_reference,'prepare_audio_prompt',
                return_value=(str(normalized),None)), \
                 patch.object(audio_reference,'_reference_window',return_value=(0.0,4.0,.45)), \
                 patch('berofel.services.ffmpeg.media_info',return_value=(4.0,False,True)):
                report=audio_reference.inspect_voice_reference(source)
            self.assertGreater(report['silence_fraction'],.50)
            self.assertTrue(any('Mais de 50%' in warning for warning in report['warnings']))

    def test_voice_reference_guidance_also_covers_moderate_silence(self):
        from berofel.services.audio_reference import voice_reference_warnings
        warnings=voice_reference_warnings({'warnings':[],'silence_fraction':.35})
        self.assertEqual(len(warnings),1)
        self.assertIn('quase silenciosa',warnings[0])

    def test_voice_reference_guidance_does_not_duplicate_silence_warning(self):
        from berofel.services.audio_reference import voice_reference_warnings
        warnings=voice_reference_warnings({'warnings':['Mais de 50% está quase silencioso.'],
                                           'silence_fraction':.65})
        self.assertEqual(len(warnings),1)

    def test_reference_window_selection_avoids_leading_silence_and_searches_full_file(self):
        from berofel.services.audio_reference import _best_reference_window
        # 1 h source: first 40 s silent; later speech regions are eligible.
        source='long-reference.wav'
        silence_log='''
[silencedetect] silence_start: 0
[silencedetect] silence_end: 40.0 | silence_duration: 40.0
[silencedetect] silence_start: 70.0
[silencedetect] silence_end: 3540.0 | silence_duration: 3470.0
'''
        with patch('berofel.services.ffmpeg.ffmpeg_path',return_value='ffmpeg'), \
             patch('berofel.services.ffmpeg.media_info',return_value=(3600.0,False,True)), \
             patch('berofel.services.audio_reference.subprocess.run',return_value=type(
                 'Result',(),{'returncode':0,'stderr':silence_log})()) as run:
            start,length,active= _best_reference_window(source,123,456)
        self.assertEqual(length,30.0)
        self.assertGreaterEqual(start,40.0)
        self.assertAlmostEqual(start,40.0)
        self.assertEqual(active,1.0)
        self.assertTrue(any('silencedetect' in arg
                            for call in run.call_args_list
                            for arg in call.args[0]))

    def test_real_ffmpeg_scan_selects_later_voice_activity_without_changing_source(self):
        import numpy as np
        from scipy.io import wavfile
        from berofel.services.audio_reference import inspect_voice_reference,prepare_audio_prompt
        from berofel.services.ffmpeg import ffmpeg_path
        with tempfile.TemporaryDirectory(prefix='bfs_full_reference_scan_') as folder:
            root=Path(folder);source=root/'long.wav'
            rate=24000;lead=np.zeros(rate*35,dtype=np.int16)
            t=np.arange(rate*8)/rate
            voice=(np.sin(2*np.pi*180*t)*11000).astype(np.int16)
            original=np.concatenate((lead,voice,lead))
            wavfile.write(source,rate,original)
            before=source.read_bytes()
            report=inspect_voice_reference(source)
            self.assertGreater(report['source_duration'],70.0)
            self.assertGreaterEqual(report['selected_start'],30.0)
            self.assertLess(report['selected_start'],45.0)
            self.assertLessEqual(report['duration'],15.0)
            self.assertGreater(report['active_fraction'],.5)
            crop=root/'same-window.wav'
            prepare_audio_prompt(str(source),crop,ffmpeg=ffmpeg_path(),
                start_seconds=report['selected_start'],duration_seconds=report['duration'])
            crop_rate,crop_pcm=wavfile.read(crop)
            self.assertAlmostEqual(len(crop_pcm)/crop_rate,report['duration'],delta=.1)
            self.assertEqual(source.read_bytes(),before)

    def test_qwen_prompt_edge_trim_preserves_internal_speech_after_pause(self):
        import numpy as np
        from scipy.io import wavfile
        from berofel.services.audio_reference import prepare_audio_prompt
        from berofel.services.ffmpeg import ffmpeg_path
        with tempfile.TemporaryDirectory(prefix='bfs_voice_prompt_edges_') as folder:
            root=Path(folder);source=root/'reference.wav';cropped=root/'prompt.wav'
            rate=24000
            def tone(seconds,frequency=180):
                t=np.arange(round(rate*seconds))/rate
                return (np.sin(2*np.pi*frequency*t)*9000).astype(np.int16)
            silence=lambda seconds:np.zeros(round(rate*seconds),dtype=np.int16)
            # Quiet lead-in and tail surround two utterances with a real pause.
            original=np.concatenate((silence(1.0),tone(.6),silence(1.1),
                                     tone(.7,205),silence(1.0)))
            wavfile.write(source,rate,original);before=source.read_bytes()
            prepare_audio_prompt(str(source),cropped,ffmpeg=ffmpeg_path(),
                start_seconds=0.0,duration_seconds=len(original)/rate,
                trim_outer_silence=True)
            crop_rate,crop=wavfile.read(cropped)
            crop=np.asarray(crop,dtype=np.float64)/32768.0
            self.assertEqual(crop_rate,rate)
            self.assertGreater(len(crop)/rate,2.45)
            self.assertLess(len(crop)/rate,2.8)
            self.assertGreater(np.sqrt(np.mean(crop[:int(.4*rate)]**2)),.08)
            # The internal pause is retained, and the second utterance survives.
            self.assertLess(np.sqrt(np.mean(crop[int(.8*rate):int(1.2*rate)]**2)),.02)
            self.assertGreater(np.sqrt(np.mean(crop[-int(.4*rate):]**2)),.08)
            self.assertEqual(source.read_bytes(),before)

    def test_full_file_reference_report_explains_qwen_uses_short_selected_window(self):
        from berofel.services.audio_reference import voice_reference_warnings
        report={'warnings':[], 'source_duration':3600.0,'duration':30.0,
                'selected_start':1800.0,'active_fraction':.98,'silence_fraction':.02}
        self.assertEqual(voice_reference_warnings(report),[])
        self.assertGreater(report['source_duration'],report['duration'])

    def test_prepare_voice_prompt_supports_official_xvector_only_mode(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);sample=root/'reference.wav';sample.write_bytes(b'RIFF'+b'x'*200)
            model=root/'model';model.mkdir()
            with patch.dict(os.environ,{'BEROFEL_QWEN3_TTS_MODEL':str(model),
                    'BEROFEL_QWEN3_PROMPT_CACHE':str(root/'prompts')}), \
                 patch.object(qwen,'is_ready',return_value=True), \
                 patch('berofel.services.audio_reference._reference_window',return_value=(0.0,30.0,1.0)), \
                 patch.object(qwen,'_runtime_request',return_value={
                     'ok':True,'prompt_cache_hit':False,'worker_pid':123,
                     'model_load_count':1,'model_load_seconds':1.0,
                     'profile_prepare_seconds':.2,'operation_seconds':.2}) as runtime:
                result=qwen.prepare_local_voice_prompt(str(sample),'')
            self.assertFalse(result['prompt_cache_hit'])
            self.assertEqual(runtime.call_args.args[0]['reference_text'],'')

    def test_correcting_profile_transcript_invalidates_only_the_old_prompt_cache_key(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);sample=root/'reference.wav';sample.write_bytes(b'RIFF'+b'x'*200)
            model=root/'model';model.mkdir()
            with patch.object(qwen,'_model_fingerprint',return_value={'model':'fixture'}):
                old=qwen._prompt_cache_file(sample,'texto salvo incorreto',model)
                corrected=qwen._prompt_cache_file(sample,'transcrição corrigida',model)
                repeated=qwen._prompt_cache_file(sample,'texto salvo incorreto',model)
                other_window=qwen._prompt_cache_file(sample,'texto salvo incorreto',model,(18.0,12.0))
            self.assertNotEqual(old,corrected)
            self.assertEqual(old,repeated)
            self.assertNotEqual(old,other_window)

    def test_reference_transcript_guard_rejects_full_audio_text_for_short_crop(self):
        from berofel.services.audio_reference import validate_reference_transcript
        with self.assertRaisesRegex(ValueError,'janela escolhida'):
            validate_reference_transcript('fala '*100,10.0)
        validate_reference_transcript('fala de referência curta',10.0)


if __name__=='__main__':unittest.main()
