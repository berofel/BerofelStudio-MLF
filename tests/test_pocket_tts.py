"""Valida integração de narração sem baixar modelo ou importar PyTorch."""
from pathlib import Path
import json
import os
import tempfile
import unittest
import wave
from unittest.mock import patch
from types import SimpleNamespace

from berofel.services.pocket_tts_service import (NarrationRequest, generate_narration,
    persistent_folder, preset_voice, validate_request, VOICE_PRESETS,
    _prune_tts_cache, _tts_cache_limit_bytes)
from berofel.services.pocket_tts_worker import (create_voice_prompt_state,
    create_or_load_voice_state,load_model_for_request,prepare_audio_prompt,require_voice_cloning,
    require_local_voice_cloning_weights,
    run as run_pocket_tts_worker)


class PocketTTSOfflineTests(unittest.TestCase):
    def test_ai_workers_emit_utf8_even_when_windows_console_is_cp1252(self):
        import subprocess
        import sys
        root=Path(__file__).resolve().parents[1]
        env=os.environ.copy()
        env['PYTHONIOENCODING']='cp1252'
        for module,arguments,expected in (
            ('berofel.services.ai_worker',['extract',str(root/'não_existe_á.json'),
                                           str(root/'saida.json')],1),
            ('berofel.services.pocket_tts_worker',
             [str(root/'não_existe_á.json'),str(root/'resultado.json')],1),
        ):
            with self.subTest(module=module):
                result=subprocess.run([sys.executable,'-m',module,*arguments],
                    cwd=str(root),env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                    timeout=30,check=False)
                self.assertEqual(result.returncode,expected,result.stderr)
                error=result.stderr.decode('utf-8')
                self.assertIn('não_existe_á.json',error)
                self.assertNotIn('UnicodeEncodeError',error)

    def test_voice_authorizer_uses_the_installed_hf_cli(self):
        script=Path(__file__).resolve().parents[1]/'AUTORIZAR_POCKET_TTS.bat'
        content=script.read_text(encoding='utf-8')
        self.assertIn('set "HF_EXE=%LOCALAPPDATA%\\BFS\\venv\\Scripts\\hf.exe"',content)
        self.assertIn('set "ACTIVATION_LOG=%BFS_CLONE_ACTIVATION_LOG%"',content)
        self.assertIn('scripts\\preparar_modelo_pocket.py > "%ACTIVATION_LOG%" 2>&1',content)
        self.assertIn('"%HF_EXE%" auth login',content)
        self.assertNotIn('huggingface_hub.commands.huggingface_cli',content)

    def test_pocket_installer_does_not_claim_personal_cloning_when_weights_are_missing(self):
        script=Path(__file__).resolve().parents[1]/'scripts'/'instalar_pocket.ps1'
        content=script.read_text(encoding='utf-8')
        self.assertIn('$cloneReady=$true',content)
        self.assertIn('$cloneReady=$false',content)
        self.assertIn('Pocket TTS de catalogo instalado; clonagem de voz pessoal continua pendente.',
                      content)
        self.assertIn('Pocket TTS e clonagem de voz foram validados.',content)

    def test_authorization_probe_exercises_audio_prompt_encoder_without_user_audio(self):
        import wave
        from scripts.preparar_modelo_pocket import validate_voice_cloning_pipeline
        class CloneCapableModel:
            has_voice_cloning=True
            def get_state_for_audio_prompt(self,path,truncate=False):
                self.received=(path,truncate)
                with wave.open(path,'rb') as sample:
                    self.sample_frames=sample.getnframes()
                    self.sample_rate=sample.getframerate()
                return {'encoder':'ready'}
        model=CloneCapableModel()
        self.assertEqual(validate_voice_cloning_pipeline(model),{'encoder':'ready'})
        self.assertTrue(model.received[1])
        self.assertFalse(Path(model.received[0]).exists(),
                         'The synthetic prompt is deleted after the probe.')
        self.assertEqual(model.sample_frames,model.sample_rate)

    def test_authorization_probe_rejects_catalog_only_weights(self):
        from scripts.preparar_modelo_pocket import validate_voice_cloning_pipeline
        with self.assertRaisesRegex(RuntimeError,'somente vozes do catálogo'):
            validate_voice_cloning_pipeline(SimpleNamespace(has_voice_cloning=False))

    def test_clone_smoke_generates_only_a_short_synthetic_reference(self):
        from scipy.io import wavfile
        from scripts.testar_pocket import create_synthetic_voice_reference
        with tempfile.TemporaryDirectory(prefix='bfs_clone_smoke_') as folder:
            sample=create_synthetic_voice_reference(Path(folder)/'synthetic.wav',wavfile)
            rate,pcm=wavfile.read(str(sample))
        self.assertEqual(rate,24000)
        self.assertEqual((pcm.dtype.kind,pcm.dtype.itemsize),('i',2))
        self.assertEqual(len(pcm),28800)

    def test_clone_smoke_cli_sends_synthetic_voice_with_explicit_consent(self):
        import contextlib
        import io
        import sys
        from scripts import testar_pocket
        batch=Path(__file__).resolve().parents[1]/'TESTAR_POCKET_TTS.bat'
        self.assertIn('%*',batch.read_text(encoding='utf-8'),
                      'The BAT must forward --clone to the smoke-test script.')
        requests=[]
        generated=Path(tempfile.gettempdir())/'bfs_clone_smoke_output.wav'
        def fake_generate(request):
            requests.append(request)
            with wave.open(request.voice,'rb') as reference:
                self.assertEqual((reference.getframerate(),reference.getnchannels()),(24000,1))
                self.assertEqual(reference.getnframes(),28800)
            with wave.open(str(generated),'wb') as output:
                output.setnchannels(1);output.setsampwidth(2);output.setframerate(24000)
                output.writeframes(b'\x00\x00'*24000)
            return {'path':str(generated),'duration':1.0,'cache_hit':len(requests)>1}
        fake_pocket=SimpleNamespace(TTSModel=object())
        fake_torch=SimpleNamespace(__version__='test')
        try:
            with patch.dict(sys.modules,{'pocket_tts':fake_pocket,'torch':fake_torch}), \
                 patch.object(sys,'argv',['testar_pocket.py','--clone','--offline']), \
                 patch('berofel.services.pocket_tts_service.generate_narration',
                       side_effect=fake_generate), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(testar_pocket.main(),0)
            self.assertEqual(len(requests),2)
            self.assertTrue(all(request.consent for request in requests))
            self.assertTrue(all(Path(request.voice).name=='referencia_clone_sintetica.wav'
                                for request in requests))
            self.assertFalse(Path(requests[0].voice).exists(),
                             'The synthetic reference must be removed with the temp workspace.')
        finally:
            generated.unlink(missing_ok=True)

    def test_activation_distinguishes_missing_local_checkpoint_from_network_and_gate(self):
        from scripts.preparar_modelo_pocket import activation_failure_message
        network=activation_failure_message(OSError('[WinError 10013] socket access denied'))
        self.assertIn('estabelecer conexão',network)
        self.assertIn('WinError 10013',network)
        class LocalEntryNotFoundError(Exception):
            pass
        missing_local=activation_failure_message(
            LocalEntryNotFoundError('checkpoint absent from local cache while offline'))
        self.assertIn('não está no cache local',missing_local)
        self.assertIn('não pôde ser consultado',missing_local)
        class GatedRepoError(Exception):
            pass
        gated=activation_failure_message(GatedRepoError('access denied'))
        self.assertIn('aceite os termos',gated)

    def test_activation_distinguishes_invalid_token_and_interrupted_download(self):
        from scripts.preparar_modelo_pocket import activation_failure_message
        import huggingface_hub
        class Response:
            status_code=401
        class InvalidToken(Exception):
            response=Response()
        with patch.object(huggingface_hub,'get_token',return_value='secret-token'):
            invalid_token=activation_failure_message(InvalidToken('request contained secret-token'))
        self.assertIn('inválido ou expirado',invalid_token)
        self.assertNotIn('secret-token',invalid_token)
        self.assertIn('[redigido]',invalid_token)
        with patch.object(huggingface_hub,'get_token',return_value=None):
            unauthenticated=activation_failure_message(InvalidToken('no token'))
        self.assertIn('não há token salvo',unauthenticated)
        self.assertNotIn('secret-token',unauthenticated)
        class LocalTokenNotFoundError(Exception):
            pass
        missing_token=activation_failure_message(LocalTokenNotFoundError('no token'))
        self.assertIn('Nenhuma autenticação',missing_token)
        class IncompleteDownloadError(Exception):
            pass
        interrupted=activation_failure_message(IncompleteDownloadError('partial transfer'))
        self.assertIn('foi interrompido',interrupted)

    def test_activation_preflights_voice_clone_checkpoint_before_loading_model(self):
        from scripts.preparar_modelo_pocket import ensure_voice_cloning_weights
        import pocket_tts.utils.utils as ptu
        import pocket_tts.utils.config as ptc
        sentinel=Path('full-clone-checkpoint.safetensors')
        with (patch.object(ptc,'load_config',return_value=SimpleNamespace(
                    weights_path='hf://kyutai/pocket-tts/languages/portuguese/model.safetensors')),
              patch.object(ptu,'download_if_necessary',return_value=sentinel) as download):
            result=ensure_voice_cloning_weights('portuguese')
        self.assertEqual(result,sentinel)
        self.assertIn('kyutai/pocket-tts/languages/portuguese/model.safetensors',
                      download.call_args.args[0])
        self.assertNotIn('without-voice-cloning',download.call_args.args[0])

    def test_personal_sample_fails_before_catalog_fallback_model_is_loaded(self):
        from pocket_tts import TTSModel
        with patch('berofel.services.pocket_tts_worker.require_local_voice_cloning_weights',
                   side_effect=RuntimeError('pesos ausentes localmente')) as preflight, \
             patch.object(TTSModel,'load_model') as load_model:
            with self.assertRaisesRegex(RuntimeError,'pesos ausentes localmente'):
                load_model_for_request({'voice':'C:/voice.wav','consent':True,
                                        'language':'portuguese'})
        preflight.assert_called_once_with('portuguese')
        load_model.assert_not_called()

    def test_clone_runtime_preflight_never_downloads_missing_weights(self):
        import pocket_tts.utils.config as ptc
        import huggingface_hub
        with (patch.object(ptc,'load_config',return_value=SimpleNamespace(
                  weights_path='hf://kyutai/pocket-tts/languages/portuguese/model.safetensors@rev123')),
              patch.object(huggingface_hub,'hf_hub_download',
                           side_effect=RuntimeError('offline cache miss')) as download):
            with self.assertRaisesRegex(RuntimeError,'não estão neste PC'):
                require_local_voice_cloning_weights('portuguese')
        self.assertEqual(download.call_args.kwargs['repo_id'],'kyutai/pocket-tts')
        self.assertEqual(download.call_args.kwargs['filename'],
                         'languages/portuguese/model.safetensors')
        self.assertEqual(download.call_args.kwargs['revision'],'rev123')
        self.assertTrue(download.call_args.kwargs['local_files_only'])

    def test_personal_voice_worker_uses_normalized_reference_and_preserves_original(self):
        import numpy as np
        from scipy.io import wavfile
        with tempfile.TemporaryDirectory(prefix='bfs_personal_voice_worker_') as folder:
            root=Path(folder)
            sample_rate=48000
            source=root/'authorized_synthetic_reference.wav'
            t=np.arange(sample_rate//2,dtype=np.float64)/sample_rate
            pcm=(np.sin(2*np.pi*220*t)*10000).astype('<i2')
            wavfile.write(str(source),sample_rate,pcm)
            original=source.read_bytes()
            output=root/'narration.wav'
            request_file=root/'request.json'
            result_file=root/'worker_result.json'
            request={'voice':str(source),'text':'Teste de clonagem sintética.',
                     'language':'portuguese','consent':True,'quantize':False,
                     'output':str(output)}
            request_file.write_text(json.dumps(request),encoding='utf-8')

            class FakeAudio:
                def detach(self):return self
                def cpu(self):return self
                def numpy(self):return np.array([.1,-.1,.2,-.2],dtype=np.float32)

            class FakeCloneModel:
                sample_rate=24000
                has_voice_cloning=True
                def get_state_for_audio_prompt(self,path,truncate=False):
                    self.reference=Path(path)
                    self.truncate=truncate
                    with wave.open(str(path),'rb') as prompt:
                        self.prompt_rate=prompt.getframerate()
                        self.prompt_channels=prompt.getnchannels()
                        self.prompt_frames=prompt.getnframes()
                    return 'synthetic-voice-state'
                def generate_audio(self,state,text):
                    self.generation=(state,text)
                    return FakeAudio()

            model=FakeCloneModel()
            hub_environment={key:os.environ.get(key) for key in
                ('HF_HUB_OFFLINE','TRANSFORMERS_OFFLINE','HF_HUB_DISABLE_TELEMETRY')}
            def load_offline(_request):
                self.assertEqual(os.environ.get('HF_HUB_OFFLINE'),'1')
                self.assertEqual(os.environ.get('TRANSFORMERS_OFFLINE'),'1')
                self.assertEqual(os.environ.get('HF_HUB_DISABLE_TELEMETRY'),'1')
                return model
            with patch.dict(os.environ,{'BEROFEL_VOICE_STATE_CACHE':str(root/'voice_cache')}), \
                 patch('berofel.services.pocket_tts_worker.load_model_for_request',
                       side_effect=load_offline) as load_model:
                run_pocket_tts_worker(str(request_file),str(result_file))

            load_model.assert_called_once_with(request)
            self.assertEqual({key:os.environ.get(key) for key in hub_environment},
                             hub_environment)
            self.assertEqual(model.generation,('synthetic-voice-state',request['text']))
            self.assertTrue(model.truncate)
            self.assertEqual((model.prompt_rate,model.prompt_channels),(24000,1))
            self.assertGreater(model.prompt_frames,0)
            self.assertFalse(model.reference.exists(),
                             'Temporary conditioning audio must be deleted after encoding.')
            self.assertEqual(source.read_bytes(),original,
                             'The original authorized reference must remain unchanged.')
            self.assertTrue(output.is_file())
            rate,generated=wavfile.read(str(output))
            self.assertEqual(rate,24000)
            self.assertGreater(len(generated),0)
            self.assertTrue(result_file.is_file())

    def test_precomputed_preset_skips_personal_clone_preflight(self):
        from pocket_tts import TTSModel
        catalog_model=SimpleNamespace(has_voice_cloning=False)
        with patch('berofel.services.pocket_tts_worker.ensure_voice_cloning_weights') as preflight, \
             patch.object(TTSModel,'load_model',return_value=catalog_model) as load_model:
            result=load_model_for_request({'voice':'bill_boerst','consent':False,
                                           'language':'english'})
        self.assertIs(result,catalog_model)
        preflight.assert_not_called()
        load_model.assert_called_once_with(language='english',quantize=False)

    def test_all_cc0_presets(self):
        self.assertEqual(len(VOICE_PRESETS),4)
        for preset in VOICE_PRESETS:
            self.assertEqual(preset['license'],'CC0')
            self.assertEqual(preset_voice(preset['id']),preset['id'])

    def test_precomputed_cc0_voice_ids_work_without_audio_cloning_weights(self):
        from berofel.services.pocket_tts_worker import require_voice_cloning
        for preset in VOICE_PRESETS:
            voice=preset_voice(preset['id'])
            self.assertEqual(prepare_audio_prompt(voice,'unused.wav'),(voice,None))
            require_voice_cloning(SimpleNamespace(has_voice_cloning=False),
                                  {'voice':voice,'consent':False})

    def test_voice_installer_prepares_embedding_states_without_source_wavs(self):
        from scripts.preparar_vozes_pocket import prepare_precomputed_voice_states
        with tempfile.TemporaryDirectory(prefix='bfs_voice_state_cache_') as folder:
            calls=[]
            def resolver(language,voice_id):
                calls.append((language,voice_id))
                path=Path(folder)/f'{voice_id}.safetensors'
                path.write_bytes(b'synthetic-state' * 8)
                return path
            result=prepare_precomputed_voice_states('portuguese',resolver,lambda _message:None)
        self.assertEqual(result['cached'],[voice['id'] for voice in VOICE_PRESETS])
        self.assertEqual(result['failed'],[])
        self.assertEqual(len(calls),4)
        self.assertTrue(all(language=='portuguese' for language,_voice in calls))

    def test_voice_installer_stops_repeating_requests_after_network_failure(self):
        from scripts.preparar_vozes_pocket import prepare_precomputed_voice_states
        calls=[]
        def blocked(_language,_voice_id):
            calls.append(1)
            raise OSError('[WinError 10013] network access blocked')
        result=prepare_precomputed_voice_states('portuguese',blocked,lambda _message:None)
        self.assertEqual(len(calls),1)
        self.assertEqual(result['failed'],[voice['id'] for voice in VOICE_PRESETS])
        self.assertEqual(result['cached'],[])

    def test_custom_voice_requires_consent(self):
        with tempfile.TemporaryDirectory() as folder:
            sample=Path(folder)/'minha_voz.wav'
            sample.write_bytes(b'RIFF'+b'0'*60)
            with self.assertRaises(PermissionError):
                validate_request('Olá!',str(sample),'portuguese',False)
            validate_request('Olá!',str(sample),'portuguese',True)

    def test_custom_voice_formats_are_normalized_by_ffmpeg_without_changing_source(self):
        with tempfile.TemporaryDirectory() as folder:
            sample=Path(folder)/'minha_voz.m4a'
            sample.write_bytes(b'original user audio')
            prepared=Path(folder)/'cache'/'voice_conditioning.wav'
            def fake_ffmpeg(command, **kwargs):
                Path(command[-1]).write_bytes(b'RIFF'+b'0'*80)
                return SimpleNamespace(returncode=0,stdout='',stderr='')
            with patch('subprocess.run',side_effect=fake_ffmpeg) as run:
                voice_path,cleanup=prepare_audio_prompt(str(sample),prepared,'ffmpeg-test')
            self.assertEqual(voice_path,str(prepared))
            self.assertEqual(cleanup,prepared)
            self.assertEqual(sample.read_bytes(),b'original user audio')
            self.assertEqual(run.call_args.args[0][0],'ffmpeg-test')
            self.assertIn('-ac',run.call_args.args[0])
            self.assertIn('24000',run.call_args.args[0])

    def test_precomputed_voice_state_is_not_decoded_as_audio(self):
        voice,cleanup=prepare_audio_prompt('my_voice.safetensors','unused.wav')
        self.assertEqual(voice,'my_voice.safetensors')
        self.assertIsNone(cleanup)

    def test_personal_voice_state_is_cached_locally_and_invalidated_by_source_bytes(self):
        import sys
        from types import ModuleType
        with tempfile.TemporaryDirectory(prefix='bfs_local_voice_state_') as folder:
            root=Path(folder);sample=root/'rafael_reference.wav';sample.write_bytes(b'voice A')
            cache=root/'local_cache';encoded=[];normalized=[];saved=[]
            class Model:
                def get_state_for_audio_prompt(self,path,truncate=False):
                    if str(path).endswith('.safetensors'):
                        return ('loaded',Path(path).read_bytes())
                    encoded.append((path,truncate));return {'state':'generated'}
            fake_package=ModuleType('pocket_tts')
            def export(state,path):
                saved.append(state);Path(path).write_bytes(b'local-state')
            fake_package.export_model_state=export
            with patch.dict(os.environ,{'BEROFEL_VOICE_STATE_CACHE':str(cache)}), \
                 patch('berofel.services.pocket_tts_worker._model_voice_fingerprint',
                       return_value={'version':'fixture','weights':'local'}), \
                 patch('berofel.services.pocket_tts_worker.prepare_audio_prompt',
                       side_effect=lambda voice,target:(normalized.append((voice,target)) or (voice,None))), \
                 patch.dict(sys.modules,{'pocket_tts':fake_package}):
                model=Model()
                first=create_or_load_voice_state(model,str(sample),'portuguese')
                second=create_or_load_voice_state(model,str(sample),'portuguese')
                self.assertEqual((first,second[0]),({'state':'generated'},'loaded'))
                self.assertEqual(len(encoded),1)
                self.assertEqual(len(normalized),1)
                self.assertEqual(len(saved),1)
                sample.write_bytes(b'voice B')
                third=create_or_load_voice_state(model,str(sample),'portuguese')
                self.assertEqual(third,{'state':'generated'})
                self.assertEqual(len(encoded),2)
            self.assertEqual(sample.read_bytes(),b'voice B')
            self.assertEqual(len(list(cache.glob('*.safetensors'))),2)

    def test_safetensors_personal_voice_still_requires_clone_enabled_weights(self):
        with tempfile.TemporaryDirectory(prefix='bfs_local_voice_state_') as folder:
            profile=Path(folder)/'profile.safetensors';profile.write_bytes(b'state')
            from pocket_tts import TTSModel
            with patch('berofel.services.pocket_tts_worker.require_local_voice_cloning_weights') as preflight, \
                 patch.object(TTSModel,'load_model',return_value=SimpleNamespace(has_voice_cloning=True)):
                load_model_for_request({'voice':str(profile),'consent':True,
                                        'language':'portuguese'})
            preflight.assert_called_once_with('portuguese')

    def test_builtin_rafael_voice_id_is_not_treated_as_a_file_path(self):
        voice,cleanup=prepare_audio_prompt('rafael','unused.wav')
        self.assertEqual(voice,'rafael')
        self.assertIsNone(cleanup)

    def test_voice_prompt_embedding_caps_long_references_at_30_seconds(self):
        class Model:
            def get_state_for_audio_prompt(self,voice,truncate=False):
                self.received=(voice,truncate)
                return 'voice-state'
        model=Model()
        self.assertEqual(create_voice_prompt_state(model,'long_reference.wav'),
                         'voice-state')
        self.assertEqual(model.received,('long_reference.wav',True))

    def test_custom_voice_rejects_catalog_only_model_with_actionable_error(self):
        with self.assertRaisesRegex(RuntimeError,'AUTORIZAR_POCKET_TTS.bat'):
            require_voice_cloning(SimpleNamespace(has_voice_cloning=False),
                                  {'voice':'C:/samples/my_voice.m4a','consent':True})
        # The same model can continue using a preset voice.
        require_voice_cloning(SimpleNamespace(has_voice_cloning=False),
                              {'voice':'rafael','consent':False})

    def test_custom_voice_fails_closed_when_model_api_does_not_confirm_support(self):
        with self.assertRaisesRegex(RuntimeError,'clonagem de áudio está desativada'):
            require_voice_cloning(SimpleNamespace(),
                                  {'voice':'C:/samples/my_voice.wav','consent':True})

    def test_empty_text_rejected(self):
        with self.assertRaises(ValueError):
            validate_request('  ','rafael','portuguese')

    def test_subprocess_cache_and_durable_wav(self):
        with tempfile.TemporaryDirectory() as folder:
            old=os.environ.get('BEROFEL_AI_CACHE')
            os.environ['BEROFEL_AI_CACHE']=str(Path(folder)/'cache'/'ai')
            project=Path(folder)/'Projeto.bfs'
            project.write_text('{}')
            called=[]
            def simulated_worker(job_file,result_file):
                called.append(1)
                job=json.loads(Path(job_file).read_text(encoding='utf-8'))
                wav=Path(job['output'])
                with wave.open(str(wav),'wb') as audio:
                    audio.setnchannels(1)
                    audio.setsampwidth(2)
                    audio.setframerate(16000)
                    audio.writeframes(b'\x00\x00' * 16000)
                Path(result_file).write_text(json.dumps({'duration':1., 'sample_rate':16000}),encoding='utf-8')
            try:
                request=NarrationRequest(text='Bom dia.',voice='rafael',project_path=str(project),title='Teste')
                a=generate_narration(request,runner=simulated_worker)
                b=generate_narration(request,runner=simulated_worker)
                self.assertEqual(len(called),1)
                self.assertFalse(a['cache_hit'])
                self.assertTrue(b['cache_hit'])
                self.assertNotEqual(a['path'],b['path'])
                self.assertTrue(Path(a['path']).exists())
                self.assertEqual(Path(a['path']).parent,persistent_folder(str(project)))
                c=generate_narration(NarrationRequest(text='Boa noite.',voice='rafael',project_path=str(project)),runner=simulated_worker)
                self.assertEqual(len(called),2)
                self.assertTrue(Path(c['path']).is_file())
                cache_root=Path(os.environ['BEROFEL_AI_CACHE']).parent/'pocket_tts'
                entry=next(cache_root.rglob('audio.wav')).parent
                self.assertFalse((entry/'request.json').exists())
                self.assertFalse((entry/'worker_result.json').exists())
            finally:
                if old is None:os.environ.pop('BEROFEL_AI_CACHE',None)
                else:os.environ['BEROFEL_AI_CACHE']=old

    def test_tts_cache_lru_preserves_active_current_and_unknown_files(self):
        with tempfile.TemporaryDirectory(prefix='bfs_tts_prune_') as folder:
            root=Path(folder)/'pocket_tts';entries=[]
            for index in range(3):
                key=f'{index:032x}';entry=root/key[:2]/key
                entry.mkdir(parents=True)
                (entry/'audio.wav').write_bytes(bytes([index])*10)
                metadata=entry/'result.json';metadata.write_text(
                    json.dumps({'key':key,'engine':'pocket-tts','duration':1.}))
                stamp=1_700_000_000_000_000_000+index*1_000_000
                os.utime(metadata,ns=(stamp,stamp))
                entries.append(entry)
            (entries[0]/'request.json').write_text('{}')
            stale=entries[0]/'abandoned.part.wav';stale.write_bytes(b'orphan')
            os.utime(stale,ns=(1_700_000_000_000_000_000,)*2)
            unknown=root/'user-data';unknown.mkdir()
            preserve=unknown/'keep.bin';preserve.write_bytes(b'user data')
            unmarked_key='f'*32
            unmarked=root/unmarked_key[:2]/unmarked_key
            unmarked.mkdir(parents=True)
            unmarked_file=unmarked/'unknown.bin';unmarked_file.write_bytes(b'keep')
            remaining=_prune_tts_cache(root,protected=entries[2],max_bytes=1)
            self.assertTrue(entries[0].exists(),'An active cache entry must survive pruning.')
            self.assertFalse(stale.exists(),'A stale partial output should be cleaned.')
            self.assertFalse(entries[1].exists(),'The oldest eligible entry should be evicted.')
            self.assertTrue(entries[2].exists(),'The cache entry used by this request is protected.')
            protected_total=sum(file.stat().st_size for entry in (entries[0],entries[2])
                                for file in entry.rglob('*') if file.is_file())
            self.assertEqual(remaining,protected_total)
            self.assertEqual(preserve.read_bytes(),b'user data')
            self.assertEqual(unmarked_file.read_bytes(),b'keep',
                             'Unmarked hash-shaped directories are not owned cache entries.')

    def test_tts_cache_limit_is_configurable_in_megabytes(self):
        with patch.dict(os.environ,{'BEROFEL_TTS_CACHE_MAX_MB':'64'}):
            self.assertEqual(_tts_cache_limit_bytes(),64*1024*1024)
        with patch.dict(os.environ,{'BEROFEL_TTS_CACHE_MAX_MB':'invalid'}):
            self.assertEqual(_tts_cache_limit_bytes(),2*1024*1024*1024)

    def test_tts_cache_budget_evicts_old_audio_but_keeps_durable_project_wavs(self):
        with tempfile.TemporaryDirectory(prefix='bfs_tts_budget_') as folder:
            old_cache=os.environ.get('BEROFEL_AI_CACHE')
            old_limit=os.environ.get('BEROFEL_TTS_CACHE_MAX_MB')
            os.environ['BEROFEL_AI_CACHE']=str(Path(folder)/'cache'/'ai')
            os.environ['BEROFEL_TTS_CACHE_MAX_MB']='0'
            project=Path(folder)/'Projeto.bfs';project.write_text('{}')
            called=[]
            def simulated_worker(job_file,result_file):
                called.append(1)
                job=json.loads(Path(job_file).read_text(encoding='utf-8'))
                with wave.open(job['output'],'wb') as audio:
                    audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(16000)
                    audio.writeframes(b'\x00\x00'*16000)
                Path(result_file).write_text(json.dumps(
                    {'duration':1.,'sample_rate':16000}),encoding='utf-8')
            try:
                first=generate_narration(NarrationRequest(text='Primeiro',voice='rafael',
                    project_path=str(project)),runner=simulated_worker)
                second=generate_narration(NarrationRequest(text='Segundo',voice='rafael',
                    project_path=str(project)),runner=simulated_worker)
                self.assertTrue(Path(first['path']).is_file())
                self.assertTrue(Path(second['path']).is_file())
                root=Path(os.environ['BEROFEL_AI_CACHE']).parent/'pocket_tts'
                self.assertEqual(len(list(root.rglob('audio.wav'))),1)
                again=generate_narration(NarrationRequest(text='Primeiro',voice='rafael',
                    project_path=str(project)),runner=simulated_worker)
                self.assertFalse(again['cache_hit'])
                self.assertEqual(len(called),3)
                self.assertTrue(Path(first['path']).is_file(),
                                'Cache eviction must not remove user-facing project media.')
            finally:
                if old_cache is None:os.environ.pop('BEROFEL_AI_CACHE',None)
                else:os.environ['BEROFEL_AI_CACHE']=old_cache
                if old_limit is None:os.environ.pop('BEROFEL_TTS_CACHE_MAX_MB',None)
                else:os.environ['BEROFEL_TTS_CACHE_MAX_MB']=old_limit

    def test_tts_cache_invalidates_when_installed_model_version_changes(self):
        with tempfile.TemporaryDirectory(prefix='bfs_tts_version_cache_') as folder:
            old=os.environ.get('BEROFEL_AI_CACHE')
            os.environ['BEROFEL_AI_CACHE']=str(Path(folder)/'cache'/'ai')
            project=Path(folder)/'Projeto.bfs';project.write_text('{}')
            called=[]
            def simulated_worker(job_file,result_file):
                called.append(1)
                job=json.loads(Path(job_file).read_text(encoding='utf-8'))
                with wave.open(job['output'],'wb') as audio:
                    audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(16000)
                    audio.writeframes(b'\x00\x00'*16000)
                Path(result_file).write_text(json.dumps(
                    {'duration':1.,'sample_rate':16000}),encoding='utf-8')
            request=NarrationRequest(text='Teste de versão.',voice='rafael',
                                     project_path=str(project))
            try:
                with patch('berofel.services.pocket_tts_service.package_version',
                           side_effect=['4.0.1','4.0.1','4.0.2']):
                    first=generate_narration(request,runner=simulated_worker)
                    cached=generate_narration(request,runner=simulated_worker)
                    changed=generate_narration(request,runner=simulated_worker)
                self.assertFalse(first['cache_hit'])
                self.assertTrue(cached['cache_hit'])
                self.assertFalse(changed['cache_hit'])
                self.assertEqual(len(called),2)
            finally:
                if old is None:os.environ.pop('BEROFEL_AI_CACHE',None)
                else:os.environ['BEROFEL_AI_CACHE']=old

    def test_voice_cache_uses_audio_content_when_size_and_mtime_are_unchanged(self):
        with tempfile.TemporaryDirectory(prefix='bfs_voice_content_cache_') as folder:
            old=os.environ.get('BEROFEL_AI_CACHE')
            os.environ['BEROFEL_AI_CACHE']=str(Path(folder)/'cache'/'ai')
            project=Path(folder)/'Projeto.bfs';project.write_text('{}')
            sample=Path(folder)/'voice.wav';sample.write_bytes(b'AAAA')
            stamp=sample.stat()
            called=[]
            def simulated_worker(job_file,result_file):
                called.append(1)
                job=json.loads(Path(job_file).read_text(encoding='utf-8'))
                with wave.open(job['output'],'wb') as audio:
                    audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(16000)
                    audio.writeframes(b'\x00\x00'*16000)
                Path(result_file).write_text(json.dumps(
                    {'duration':1.,'sample_rate':16000}),encoding='utf-8')
            request=NarrationRequest(text='Teste de voz.',voice=str(sample),consent=True,
                                     project_path=str(project))
            try:
                first=generate_narration(request,runner=simulated_worker)
                sample.write_bytes(b'BBBB')
                os.utime(sample,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
                changed=generate_narration(request,runner=simulated_worker)
                self.assertFalse(first['cache_hit'])
                self.assertFalse(changed['cache_hit'])
                self.assertEqual(len(called),2)
            finally:
                if old is None:os.environ.pop('BEROFEL_AI_CACHE',None)
                else:os.environ['BEROFEL_AI_CACHE']=old

if __name__ == '__main__': unittest.main()
