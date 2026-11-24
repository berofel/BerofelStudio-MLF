import hashlib
import json
import os
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from berofel.services.multivoice_narration import (
    DEFAULT_PAUSE_MS, MultiVoiceScript, ScriptValidationError,
    create_script, group_lines_by_voice, group_script_lines_by_profile, parse_berofel_script,
    generate_script_audio, profile_ids_used_by_script, reorder_lines, split_dialogue_text,
    synthesis_cache_key, script_generation_fingerprint, load_script_checkpoint,
    save_script_checkpoint, update_line_text,
)
from berofel.services.narration_service import persistent_folder


def _wav(path: Path, frames: int = 2400):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), 'wb') as output:
        output.setnchannels(1); output.setsampwidth(2); output.setframerate(24000)
        output.writeframes(b'\x20\x01' * frames)


class MultiVoiceScriptTests(unittest.TestCase):
    def test_parser_preserves_punctuation_multiline_and_optional_voice_name(self):
        parsed = parse_berofel_script(
            'Berofel Script V1\n\n[001 | V1 | João]\nOlá, José!\nTudo bem?\n\n[002 | V10]\nSim...'
        )
        self.assertEqual([(line.number, line.voice_id) for line in parsed], [(1, 'V1'), (2, 'V10')])
        self.assertEqual(parsed[0].character_name, 'João')
        self.assertEqual(parsed[0].text, 'Olá, José!\nTudo bem?')
        self.assertEqual(parsed[1].text, 'Sim...')
        self.assertNotEqual(parsed[0].id, parsed[1].id)

    def test_parser_rejects_duplicate_numbers_even_with_different_zero_padding(self):
        with self.assertRaisesRegex(ScriptValidationError, 'duplicado'):
            parse_berofel_script('[001 | V1]\nUm\n[1 | V2]\nDois')

    def test_parser_rejects_bad_headers_empty_lines_and_orphan_text(self):
        cases = ('antes\n[001 | V1]\ntexto', '[001 | V11]\ntexto',
                 '[001 | V1]\n[002 | V2]\ntexto', '[001 | V1]\n')
        for text in cases:
            with self.subTest(text=text), self.assertRaises(ScriptValidationError):
                parse_berofel_script(text)

    def test_parser_supports_100k_characters_1000_lines_and_all_ten_voices(self):
        text = '\n'.join(f'[{i:03d} | V{(i - 1) % 10 + 1}]\n' + ('fala ' * 18)
                          for i in range(1, 1001))
        parsed = parse_berofel_script(text)
        self.assertGreaterEqual(len(text), 100_000)
        self.assertEqual(len(parsed), 1000)
        self.assertEqual({line.voice_id for line in parsed}, {f'V{i}' for i in range(1, 11)})
        groups = group_lines_by_voice(parsed)
        self.assertEqual([voice for voice, _ in groups], [f'V{i}' for i in range(1, 11)])
        self.assertEqual([line.number for line in groups[0][1]], list(range(1, 1001, 10)))

    def test_oversized_dialogue_splits_on_word_boundaries_and_keeps_punctuation(self):
        text = ('Primeira frase, com pontuação. ' * 80).strip()
        parts = split_dialogue_text(text, max_chars=120)
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(len(part) <= 120 for part in parts))
        self.assertTrue(all(part and not part.startswith(' ') and not part.endswith(' ')
                            for part in parts))
        self.assertEqual(' '.join(parts), text)

    def test_assignment_validation_requires_every_used_saved_profile(self):
        with self.assertRaisesRegex(ScriptValidationError, 'Associe'):
            create_script('[001 | V1]\nOlá', {}, 'qwen3-tts-purec-int8')
        with self.assertRaisesRegex(ScriptValidationError, 'V1 a V10'):
            create_script('[001 | V1]\nOlá', {'V11': {'profile_id': 'p'}}, 'bad')

    def test_ids_survive_reorder_and_edit_keeps_previous_audio_until_replacement(self):
        script = create_script('[001 | V1]\nPrimeira\n[002 | V1]\nSegunda',
                               {'V1': {'profile_id': 'voice-1'}}, 'engine')
        first, second = script.lines
        first.status = 'generated'; first.audio_path = 'old.wav'; first.duration = 1.25
        first.cache_key = 'old-key'; first.clip_id = 'clip-1'
        reorder_lines(script, [second.id, first.id])
        self.assertEqual([line.number for line in script.lines], [1, 2])
        self.assertEqual(script.lines[1].id, first.id)
        update_line_text(script, first.id, 'Texto corrigido!')
        self.assertEqual(first.status, 'pending')
        self.assertEqual(first.audio_path, 'old.wav')
        self.assertEqual(first.duration, 1.25)
        self.assertEqual(first.clip_id, 'clip-1')
        self.assertEqual(first.text, 'Texto corrigido!')

    def test_json_schema_roundtrip_keeps_voice_mapping_and_line_ids(self):
        script = create_script('[001 | V2]\nOi\n[002 | V1]\nTchau',
            {'V1': {'profile_id': 'p1', 'display_name': 'Ana'},
             'V2': {'profile_id': 'p2', 'display_name': 'Bia'}},
            'qwen3-tts-purec-int8', pause_ms=425)
        restored = MultiVoiceScript.from_dict(json.loads(json.dumps(script.to_dict())))
        self.assertEqual(restored.to_dict(), script.to_dict())
        self.assertEqual(restored.pause_ms, 425)
        self.assertEqual(DEFAULT_PAUSE_MS, 200)

    def test_generation_fingerprint_ignores_runtime_state_but_detects_script_edits(self):
        script = create_script('[001 | V1]\nOriginal',
                               {'V1': {'profile_id': 'p1'},
                                'V2': {'profile_id': 'unused'}},
                               'qwen3-tts-purec-int8')
        initial = script_generation_fingerprint(script)
        script.lines[0].status = 'generated'
        script.lines[0].audio_path = 'cached.wav'
        script.total_seconds = 8.0
        script.timeline_start = 12.0
        script.voices['V2']['profile_id'] = 'changed-unused-profile'
        self.assertEqual(initial, script_generation_fingerprint(script))
        script.lines[0].text = 'Editado'
        self.assertNotEqual(initial, script_generation_fingerprint(script))

    def test_stale_run_checkpoint_cannot_replace_manual_script_edits_on_restore(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            reference = root / 'voice.wav'
            _wav(reference)
            profile = {'id': 'p1', 'sample_path': str(reference),
                       'reference_text': 'fala', 'language': 'portuguese',
                       'authorized': True}
            project_path = root / 'episode.berofel.json'
            script = create_script('[001 | V1]\nTexto original.',
                {'V1': {'profile_id': 'p1'}, 'V2': {'profile_id': 'unused-1'}},
                'qwen3-tts-purec-int8')
            script.timeline_start = 2.0
            canonical_path = save_script_checkpoint(script, str(project_path))
            run_script = MultiVoiceScript.from_dict(script.to_dict())
            run_script.timeline_start = 8.0
            run_path = (persistent_folder(str(project_path)) / 'roteiros' / script.id /
                        'runs' / 'test-run.json')

            def fake_generate(_request, **_kwargs):
                output = root / 'generated.wav'
                _wav(output)
                return {'path': str(output), 'duration': .1, 'cache_hit': False}

            generated = generate_script_audio(run_script, {'p1': profile}, str(project_path),
                generator=fake_generate, checkpoint_path=str(run_path))
            self.assertEqual(Path(generated.checkpoint_path), run_path)
            self.assertEqual(load_script_checkpoint(str(project_path), script.id).lines[0].status,
                             'pending')

            # Force the timestamp tie possible on a Windows volume. The newer
            # run checkpoint contains the valid audio and must win this tie.
            tied_mtime = 1_800_000_000
            os.utime(canonical_path, (tied_mtime, tied_mtime))
            os.utime(run_path, (tied_mtime, tied_mtime))

            restored = load_script_checkpoint(str(project_path), script.id,
                                               expected_script=script)
            self.assertEqual(restored.lines[0].status, 'generated')
            self.assertEqual(restored.timeline_start, 2.0)
            self.assertEqual(restored.voices['V2']['profile_id'], 'unused-1')

            edited = MultiVoiceScript.from_dict(script.to_dict())
            update_line_text(edited, edited.lines[0].id, 'Texto corrigido durante a IA.')
            edited.voices['V2']['profile_id'] = 'unused-2'
            save_script_checkpoint(edited, str(project_path))
            restored_after_edit = load_script_checkpoint(str(project_path), script.id,
                                                          expected_script=edited)
            self.assertEqual(restored_after_edit.lines[0].text,
                             'Texto corrigido durante a IA.')
            self.assertEqual(restored_after_edit.lines[0].status, 'pending')
            self.assertEqual(restored_after_edit.voices['V2']['profile_id'], 'unused-2')

    def test_restore_does_not_mark_missing_or_silent_checkpoint_wav_as_generated(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            project_path = root / 'episode.berofel.json'
            for wav_state in ('missing', 'silent'):
                with self.subTest(wav_state=wav_state):
                    script = create_script('[001 | V1]\nTexto preservado.',
                        {'V1': {'profile_id': 'p1'}}, 'qwen3-tts-purec-int8')
                    audio = root / f'{wav_state}.wav'
                    if wav_state == 'silent':
                        audio.parent.mkdir(parents=True, exist_ok=True)
                        with wave.open(str(audio), 'wb') as output:
                            output.setnchannels(1); output.setsampwidth(2)
                            output.setframerate(24000); output.writeframes(bytes(4800))
                    line = script.lines[0]
                    line.status = 'generated'; line.audio_path = str(audio)
                    line.duration = 0.1; line.clip_id = 'existing-clip'
                    save_script_checkpoint(script, str(project_path))
                    expected = MultiVoiceScript.from_dict(script.to_dict())
                    restored = load_script_checkpoint(str(project_path), script.id,
                                                       expected_script=expected)
                    self.assertEqual(restored.lines[0].status, 'pending')
                    self.assertEqual(restored.lines[0].audio_path, '')
                    self.assertIn('WAV salvo', restored.lines[0].error)

    def test_restore_sanitizes_project_without_checkpoint_and_keeps_approved_audio(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            project_path = root / 'episode.berofel.json'
            script = create_script('[001 | V1]\nTexto salvo.',
                {'V1': {'profile_id': 'p1'}}, 'qwen3-tts-purec-int8')
            missing = root / 'removed.wav'
            line = script.lines[0]
            line.status = 'generated'; line.audio_path = str(missing); line.duration = .2
            restored = load_script_checkpoint(str(project_path), script.id,
                                               expected_script=script)
            self.assertEqual(restored.lines[0].status, 'pending')
            self.assertEqual(restored.lines[0].audio_path, '')

            approved = root / 'approved.wav'
            _wav(approved)
            expected = MultiVoiceScript.from_dict(script.to_dict())
            expected.lines[0].status = 'pending'
            expected.lines[0].audio_path = str(approved)
            expected.lines[0].duration = .1
            interrupted = MultiVoiceScript.from_dict(expected.to_dict())
            interrupted.lines[0].status = 'generated'
            interrupted.lines[0].audio_path = str(missing)
            interrupted.lines[0].duration = .2
            save_script_checkpoint(interrupted, str(project_path))
            restored = load_script_checkpoint(str(project_path), script.id,
                                               expected_script=expected)
            self.assertEqual(restored.lines[0].status, 'pending')
            self.assertEqual(restored.lines[0].audio_path, str(approved))

    def test_interrupted_generating_checkpoint_restores_as_pending(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            project_path = root / 'episode.berofel.json'
            script = create_script('[001 | V1]\nTexto salvo.',
                {'V1': {'profile_id': 'p1'}}, 'qwen3-tts-purec-int8')
            interrupted = MultiVoiceScript.from_dict(script.to_dict())
            interrupted.lines[0].status = 'generating'
            save_script_checkpoint(interrupted, str(project_path))
            restored = load_script_checkpoint(str(project_path), script.id,
                                               expected_script=script)
            self.assertEqual(restored.lines[0].status, 'pending')
            self.assertIn('interrompida', restored.lines[0].error)

    def test_grouping_merges_character_slots_that_share_the_same_saved_profile(self):
        script = create_script('[001 | V1]\nA\n[002 | V2]\nB\n[003 | V3]\nC\n[004 | V2]\nD',
            {'V1': {'profile_id': 'p1'}, 'V2': {'profile_id': 'p1'},
             'V3': {'profile_id': 'p2'}}, 'qwen3-tts-purec-int8')
        groups = group_script_lines_by_profile(script)
        self.assertEqual([profile for profile, _ in groups], ['p1', 'p2'])
        self.assertEqual([line.number for line in groups[0][1]], [1, 2, 4])

    def test_unused_configured_voice_does_not_block_generation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            reference = root / 'voice.wav'
            _wav(reference)
            active = {'id': 'p1', 'sample_path': str(reference),
                      'reference_text': 'fala', 'authorized': True}
            script = create_script('[001 | V1]\nFala ativa.',
                {'V1': {'profile_id': 'p1'}, 'V2': {'profile_id': 'deleted-unused-profile'}},
                'qwen3-tts-purec-int8')
            self.assertEqual(profile_ids_used_by_script(script), {'p1'})

            def fake_generate(request, **_kwargs):
                output = root / 'generated.wav'
                _wav(output)
                return {'path': str(output), 'duration': .1}

            generated = generate_script_audio(script, {'p1': active},
                str(root / 'project.berofel.json'), generator=fake_generate)
            self.assertEqual(generated.lines[0].status, 'generated')
            self.assertIn('V2', generated.voices)

    def test_ptbr_original_multivoice_requires_reviewed_profile_before_queue(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);reference=root/'voice.wav';_wav(reference)
            profile={'id':'p1','sample_path':str(reference),
                     'reference_text':'rascunho de referência',
                     'language':'portuguese','authorized':True,
                     'reference_text_reviewed':False}
            script=create_script('[001 | V1]\nUma frase nova.',
                {'V1':{'profile_id':'p1'}},'qwen3-tts-local')
            called=[]
            with self.assertRaisesRegex(ValueError,'ainda não foi confirmada'):
                generate_script_audio(script,{'p1':profile},
                    str(root/'project.berofel.json'),
                    generator=lambda request,**kwargs:called.append(request))
            self.assertEqual(called,[])

    def test_cache_key_invalidates_only_text_voice_engine_threads_or_version(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); sample = root / 'voice.wav'; _wav(sample)
            profile = {'id': 'p1', 'sample_path': str(sample), 'reference_text': 'fala',
                       'authorized': True}
            line = parse_berofel_script('[001 | V1]\nUma frase')[0]
            other_voice = parse_berofel_script('[001 | V2]\nUma frase')[0]
            original = synthesis_cache_key(line, profile, 'qwen3-tts-purec-int8', 6, 'engine-a')
            self.assertEqual(original, synthesis_cache_key(line, profile,
                'qwen3-tts-purec-int8', 6, 'engine-a'))
            self.assertEqual(original, synthesis_cache_key(other_voice, profile,
                'qwen3-tts-purec-int8', 6, 'engine-a'))
            line.text = 'Outra frase'
            self.assertNotEqual(original, synthesis_cache_key(line, profile,
                'qwen3-tts-purec-int8', 6, 'engine-a'))
            line.text = 'Uma frase'
            self.assertNotEqual(original, synthesis_cache_key(line, profile,
                'qwen3-tts-purec-mixed', 6, 'engine-a'))
            self.assertNotEqual(original, synthesis_cache_key(line, profile,
                'qwen3-tts-purec-int8', 4, 'engine-a'))
            self.assertNotEqual(original, synthesis_cache_key(line, profile,
                'qwen3-tts-purec-int8', 6, 'engine-b'))

    def test_shared_profile_and_text_reuse_audio_but_keep_one_wav_per_line(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            reference = root / 'voice.wav'
            _wav(reference)
            profile = {'id': 'p1', 'sample_path': str(reference),
                       'reference_text': 'fala', 'language': 'portuguese',
                       'authorized': True}
            script = create_script('[001 | V1]\nTexto repetido.\n'
                                   '[002 | V2]\nTexto repetido.',
                {'V1': {'profile_id': 'p1'}, 'V2': {'profile_id': 'p1'}},
                'qwen3-tts-purec-int8')
            calls = []

            def fake_generate(_request, **_kwargs):
                calls.append(1)
                output = root / 'backend.wav'
                _wav(output, frames=3600)
                return {'path': str(output), 'duration': .15, 'cache_hit': False}

            result = generate_script_audio(script, {'p1': profile},
                str(root / 'episode.berofel.json'), generator=fake_generate)
            self.assertEqual(len(calls), 1)
            self.assertFalse(result.lines[0].cache_hit)
            self.assertTrue(result.lines[1].cache_hit)
            self.assertNotEqual(result.lines[0].audio_path, result.lines[1].audio_path)
            self.assertTrue(all(Path(line.audio_path).is_file() for line in result.lines))
            self.assertEqual(Path(result.lines[0].audio_path).read_bytes(),
                             Path(result.lines[1].audio_path).read_bytes())

    def test_native_multivoice_prepares_all_profiles_before_first_synthesis(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            references=[]
            profiles={}
            assignments={}
            for index,voice in enumerate(('V1','V2'),1):
                reference=root/f'voice{index}.wav';_wav(reference)
                profile_id=f'p{index}'
                references.append(reference)
                profiles[profile_id]={'id':profile_id,'sample_path':str(reference),
                    'reference_text':f'referência {index}','language':'portuguese',
                    'authorized':True}
                assignments[voice]={'profile_id':profile_id}
            script=create_script(
                '[001 | V2]\nSegunda personagem.\n[002 | V1]\nPrimeira personagem.',
                assignments,'qwen3-tts-native-q4')
            order=[]
            def prepare(selected,**kwargs):
                order.append(('prepare',[item['id'] for item in selected]))
                return {'prepared':True,'profile_count':2,'embedding_cache_hits':0,
                        'profile_prepare_seconds':7.6,'model_load_seconds':0.8,
                        'engine':'qwen3-tts-native-q4','threads':6}
            def synthesize(request,**kwargs):
                order.append(('synthesize',request.voice))
                output=root/'generated.wav';_wav(output,frames=2400)
                return {'path':str(output),'duration':.1,'cache_hit':False,
                        'generation_seconds':.2,'model_load_seconds':0.0,
                        'profile_prepare_seconds':0.0}
            with patch('berofel.services.qwen3_native_tts.prepare_native_voice_profiles',
                       side_effect=prepare) as preparation:
                result=generate_script_audio(script,profiles,
                    str(root/'episode.berofel.json'),generator=synthesize,
                    engine_fingerprint='native-q4-fixture')
            self.assertEqual(order[0],('prepare',['p1','p2']))
            self.assertEqual([item[0] for item in order],
                             ['prepare','synthesize','synthesize'])
            self.assertEqual([item[1] for item in order[1:]],
                             [str(references[0]),str(references[1])])
            self.assertEqual(preparation.call_count,1)
            self.assertEqual(result.profile_preparation_seconds,7.6)
            self.assertEqual(result.model_load_seconds,.8)
            restored=MultiVoiceScript.from_dict(result.to_dict())
            self.assertEqual(restored.profile_preparation_seconds,7.6)
            self.assertEqual(restored.model_load_seconds,.8)

    def test_batch_generates_by_voice_then_restores_script_order_and_regenerates_one_line(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            ref1=root/'voice1.wav';ref2=root/'voice2.wav'
            _wav(ref1);_wav(ref2)
            profiles={
                'p1':{'id':'p1','sample_path':str(ref1),'reference_text':'um',
                      'language':'portuguese','authorized':True},
                'p2':{'id':'p2','sample_path':str(ref2),'reference_text':'dois',
                      'language':'portuguese','authorized':True},
            }
            script=create_script(
                '\n'.join(f'[{i:03d} | {voice}]\nFala de teste número {i}.'
                          for i,voice in enumerate(('V2','V1','V2','V1','V1','V2'),1)),
                {'V1':{'profile_id':'p1'},'V2':{'profile_id':'p2'}},
                'qwen3-tts-purec-int8')
            calls=[]
            def fake_generate(request,**_kwargs):
                calls.append((request.voice,request.text,request.engine,request.thread_count))
                out=root/'backend-output'/f'{len(calls)}.wav'
                _wav(out,frames=1200+len(calls))
                return {'path':str(out),'duration':(1200+len(calls))/24000,
                        'cache_hit':False,
                        'model_load_seconds':.8 if len(calls) in (1,4) else 0.0,
                        'profile_prepare_seconds':.5 if len(calls) in (1,4) else 0.0}
            project_path=root/'episode.berofel.json'
            result=generate_script_audio(script,profiles,str(project_path),
                                         generator=fake_generate)
            self.assertEqual([item[0] for item in calls],
                             [str(ref1)]*3+[str(ref2)]*3)
            self.assertEqual({item[2:] for item in calls},
                             {('qwen3-tts-purec-int8',6)})
            self.assertEqual(result.model_load_seconds, 1.6)
            self.assertEqual(result.profile_preparation_seconds, 1.0)
            self.assertEqual([line.number for line in result.lines],list(range(1,7)))
            self.assertTrue(all(line.status=='generated' and Path(line.audio_path).is_file()
                                for line in result.lines))
            self.assertEqual(len(list((persistent_folder(str(project_path))
                                      /'roteiros'/result.id).glob('*.wav'))),6)
            checkpoint = Path(result.checkpoint_path)
            self.assertTrue(checkpoint.is_file())
            restored = MultiVoiceScript.from_dict(json.loads(checkpoint.read_text(encoding='utf-8')))
            self.assertEqual([line.status for line in restored.lines], ['generated'] * 6)

            prior_paths={line.id:line.audio_path for line in result.lines}
            generate_script_audio(result,profiles,str(project_path),generator=fake_generate)
            self.assertEqual(len(calls),6,'cache deve evitar nova síntese')
            target=result.lines[2]
            update_line_text(result,target.id,'Somente esta fala mudou.')
            generate_script_audio(result,profiles,str(project_path),generator=fake_generate)
            self.assertEqual(len(calls),7,'somente a fala alterada deve sintetizar')
            self.assertEqual(calls[-1][1],'Somente esta fala mudou.')
            self.assertTrue(all(line.audio_path==prior_paths[line.id]
                                for line in result.lines if line.id!=target.id))
            self.assertNotEqual(target.audio_path,prior_paths[target.id])

    def test_100_line_queue_groups_70_20_10_and_regenerates_only_line_047(self):
        """Exercise large queue/timeline persistence with a synthetic WAV backend.

        This validates orchestration and file isolation, not Qwen audio quality.
        The real two-speaker acceptance run is covered by the opt-in offline
        integration script once a second authorized voice profile exists.
        """
        with tempfile.TemporaryDirectory(prefix='bfs_multivoice_100_') as folder:
            root = Path(folder)
            references = [root / f'voice{i}.wav' for i in range(1, 4)]
            for reference in references:
                _wav(reference)
            profiles = {
                f'p{i}': {'id': f'p{i}', 'sample_path': str(references[i - 1]),
                          'reference_text': f'referência {i}', 'language': 'portuguese',
                          'authorized': True}
                for i in range(1, 4)
            }
            voice_cycle = ('V1', 'V1', 'V1', 'V2', 'V1',
                           'V1', 'V3', 'V1', 'V2', 'V1')
            ordered_voices = [voice_cycle[index % len(voice_cycle)] for index in range(100)]
            script_text = '\n'.join(
                f'[{index:03d} | {voice}]\nFala sintética de validação {index}.'
                for index, voice in enumerate(ordered_voices, 1))
            script = create_script(
                script_text,
                {f'V{i}': {'profile_id': f'p{i}'} for i in range(1, 4)},
                'qwen3-tts-purec-int8', title='Fila multivozes 100 falas')
            calls = []

            def synthetic_generator(request, **_kwargs):
                calls.append(request.voice)
                output = root / 'backend' / f'{len(calls):04d}.wav'
                _wav(output, frames=1200 + len(calls))
                return {'path': str(output), 'duration': (1200 + len(calls)) / 24000,
                        'cache_hit': False, 'generation_seconds': .001}

            project = str(root / 'episode.berofel.json')
            result = generate_script_audio(
                script, profiles, project, generator=synthetic_generator,
                engine_fingerprint='synthetic-test')
            grouped_paths = ([str(references[0])] * 70 +
                             [str(references[1])] * 20 +
                             [str(references[2])] * 10)
            self.assertEqual(calls, grouped_paths)
            self.assertEqual(len(result.lines), 100)
            self.assertEqual(len({line.audio_path for line in result.lines}), 100)
            self.assertEqual([line.number for line in result.lines], list(range(1, 101)))
            self.assertTrue(all(line.status == 'generated' and
                                Path(line.audio_path).is_file() for line in result.lines))
            prior_audio = {line.id: hashlib.sha256(
                Path(line.audio_path).read_bytes()).hexdigest() for line in result.lines}

            target = next(line for line in result.lines if line.number == 47)
            update_line_text(result, target.id, 'Somente a fala 047 foi corrigida.')
            before_regeneration = len(calls)
            result = generate_script_audio(
                result, profiles, project, generator=synthetic_generator,
                engine_fingerprint='synthetic-test')
            self.assertEqual(len(calls) - before_regeneration, 1)
            unchanged = [line for line in result.lines if line.id != target.id]
            self.assertTrue(all(hashlib.sha256(Path(line.audio_path).read_bytes()).hexdigest()
                                == prior_audio[line.id] for line in unchanged))
            self.assertNotEqual(hashlib.sha256(Path(target.audio_path).read_bytes()).hexdigest(),
                                prior_audio[target.id])
            self.assertTrue(Path(result.checkpoint_path).is_file())

    def test_cancel_during_single_line_regeneration_preserves_approved_audio_and_checkpoint(self):
        from berofel.services.process_control import ProcessCancelled

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            reference = root / 'voice.wav'
            _wav(reference)
            profile = {'id': 'p1', 'sample_path': str(reference),
                       'reference_text': 'fala', 'language': 'portuguese',
                       'authorized': True}
            script = create_script('[001 | V1]\nTexto original.',
                {'V1': {'profile_id': 'p1'}}, 'qwen3-tts-purec-int8')
            line = script.lines[0]
            approved = root / 'approved.wav'
            _wav(approved, frames=2400)
            line.status = 'generated'
            line.audio_path = str(approved)
            line.duration = 0.1
            old_audio = approved.read_bytes()
            update_line_text(script, line.id, 'Texto novo para regenerar.')

            class CancelAfterSynthesisStarts:
                cancelled = False

                def checkpoint(self):
                    return None

            control = CancelAfterSynthesisStarts()

            def cancel_during_generation(_request, **_kwargs):
                control.cancelled = True
                raise ProcessCancelled('Cancelado pelo usuário.')

            with self.assertRaises(ProcessCancelled):
                generate_script_audio(script, {'p1': profile},
                    str(root / 'episode.berofel.json'), control=control,
                    generator=cancel_during_generation)

            self.assertEqual(line.status, 'pending')
            self.assertEqual(line.audio_path, str(approved))
            self.assertEqual(approved.read_bytes(), old_audio)
            checkpoint = MultiVoiceScript.from_dict(
                json.loads(Path(script.checkpoint_path).read_text(encoding='utf-8')))
            restored = checkpoint.lines[0]
            self.assertEqual(restored.status, 'pending')
            self.assertEqual(restored.audio_path, str(approved))
            self.assertEqual(approved.read_bytes(), old_audio)

    def test_long_dialogue_is_generated_as_safe_chunks_and_merged_to_one_wav(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            reference = root / 'voice.wav'
            _wav(reference)
            profile = {'id': 'p1', 'sample_path': str(reference),
                       'reference_text': 'fala', 'language': 'portuguese',
                       'authorized': True}
            long_text = 'Frase longa com palavras preservadas. ' * 35
            long_text = long_text.strip()
            script = create_script(f'[001 | V1]\n{long_text}',
                {'V1': {'profile_id': 'p1'}}, 'qwen3-tts-purec-int8')
            calls = []

            def fake_generate(request, **_kwargs):
                calls.append(request.text)
                result_path = root / f'backend-{len(calls)}.wav'
                _wav(result_path, frames=2400)
                return {'path': str(result_path), 'duration': .1,
                        'generation_seconds': .01}

            result = generate_script_audio(script, {'p1': profile},
                str(root / 'project.berofel.json'), generator=fake_generate)
            line = result.lines[0]
            self.assertGreater(len(calls), 1)
            self.assertTrue(all(len(part) <= 800 for part in calls))
            self.assertEqual(' '.join(calls), long_text)
            self.assertEqual(line.status, 'generated')
            self.assertTrue(Path(line.audio_path).is_file())
            self.assertGreater(line.duration, sum(.1 for _ in calls))
            with wave.open(line.audio_path, 'rb') as audio:
                self.assertGreater(audio.getnframes(), 2 * 2400)


if __name__ == '__main__':
    unittest.main()
