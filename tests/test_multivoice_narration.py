import json
import tempfile
import unittest
import wave
from pathlib import Path

from berofel.services.multivoice_narration import (
    DEFAULT_PAUSE_MS, MultiVoiceScript, ScriptValidationError,
    create_script, group_lines_by_voice, group_script_lines_by_profile, parse_berofel_script,
    generate_script_audio, reorder_lines, split_dialogue_text, synthesis_cache_key,
    update_line_text,
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

            def fake_generate(request, **_kwargs):
                output = root / 'generated.wav'
                _wav(output)
                return {'path': str(output), 'duration': .1}

            generated = generate_script_audio(script, {'p1': active},
                str(root / 'project.berofel.json'), generator=fake_generate)
            self.assertEqual(generated.lines[0].status, 'generated')
            self.assertIn('V2', generated.voices)

    def test_cache_key_invalidates_only_text_voice_engine_threads_or_version(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); sample = root / 'voice.wav'; _wav(sample)
            profile = {'id': 'p1', 'sample_path': str(sample), 'reference_text': 'fala',
                       'authorized': True}
            line = parse_berofel_script('[001 | V1]\nUma frase')[0]
            original = synthesis_cache_key(line, profile, 'qwen3-tts-purec-int8', 6, 'engine-a')
            self.assertEqual(original, synthesis_cache_key(line, profile,
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
                        'cache_hit':False}
            project_path=root/'episode.berofel.json'
            result=generate_script_audio(script,profiles,str(project_path),
                                         generator=fake_generate)
            self.assertEqual([item[0] for item in calls],
                             [str(ref1)]*3+[str(ref2)]*3)
            self.assertEqual({item[2:] for item in calls},
                             {('qwen3-tts-purec-int8',6)})
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
