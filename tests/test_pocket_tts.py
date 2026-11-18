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
    load_model_for_request,prepare_audio_prompt,require_voice_cloning)


class PocketTTSOfflineTests(unittest.TestCase):
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

    def test_activation_distinguishes_network_block_from_huggingface_gate(self):
        from scripts.preparar_modelo_pocket import activation_failure_message
        network=activation_failure_message(OSError('[WinError 10013] socket access denied'))
        self.assertIn('pela rede',network)
        self.assertIn('WinError 10013',network)
        class LocalEntryNotFoundError(Exception):
            pass
        missing_local=activation_failure_message(
            LocalEntryNotFoundError('checkpoint absent from local cache while offline'))
        self.assertIn('pela rede',missing_local)
        self.assertIn('não ativa clonagem',missing_local)
        class GatedRepoError(Exception):
            pass
        gated=activation_failure_message(GatedRepoError('access denied'))
        self.assertIn('aceite os termos',gated)

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
        with patch('berofel.services.pocket_tts_worker.ensure_voice_cloning_weights',
                   side_effect=RuntimeError('rede indisponível')) as preflight, \
             patch.object(TTSModel,'load_model') as load_model:
            with self.assertRaisesRegex(RuntimeError,'rede indisponível'):
                load_model_for_request({'voice':'C:/voice.wav','consent':True,
                                        'language':'portuguese'})
        preflight.assert_called_once_with('portuguese')
        load_model.assert_not_called()

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
