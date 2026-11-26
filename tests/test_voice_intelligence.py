from __future__ import annotations

from pathlib import Path
import math
import struct
import subprocess
import tempfile
import wave
from unittest import TestCase
from unittest.mock import patch, Mock

from berofel.services.voice_intelligence.text_normalizer import (
    NORMALIZER_VERSION, normalize_pt_br,
)
from berofel.services.voice_intelligence.capabilities import (
    inspect_purec_capabilities, supports_request_seed,
)
from berofel.services.voice_intelligence.reference_selector import rank_reference_candidates
from berofel.services.voice_intelligence.speaker_fingerprint import (
    apply_emotion_direction, read_purec_emotion_direction,
)
from berofel.services.voice_intelligence.quality_inspector import (
    calculate_speech_rate, calculate_temporal_coverage, calculate_text_error_rates,
    inspect_generated_wav_with_parakeet, inspect_pcm16_wav,
)
from berofel.services.voice_intelligence.acoustic_analyzer import (
    analyze_pcm_f32le, analyze_pitch_yin_f32le, analyze_spectral_f32le,
)
from berofel.services.voice_intelligence.pronunciation_dictionary import (
    PronunciationDictionary, apply_pronunciations,
)
from berofel.services.voice_intelligence.narrative_interpreter import (
    plan_narrative_interpretation,
)
from berofel.services.narration_service import NarrationRequest, generate_narration
from berofel.services.ai_cache import file_sha256


class PortugueseSpeechNormalizerTests(TestCase):
    def test_expands_requested_brazilian_number_forms(self):
        result = normalize_pt_br(
            'R$ 1.250,50; 23/11/2026; 22h30; 3,5 GB; 15 km; 120 km/h; 45%; 1º; 2ª')
        self.assertEqual(result.spoken,
            'mil duzentos e cinquenta reais e cinquenta centavos; '
            'vinte e três de novembro de dois mil e vinte e seis; '
            'vinte e duas horas e trinta minutos; três vírgula cinco gigabytes; '
            'quinze quilômetros; cento e vinte quilômetros por hora; '
            'quarenta e cinco por cento; primeiro; segunda')
        self.assertEqual(result.version, NORMALIZER_VERSION)
        self.assertEqual(result.original,
            'R$ 1.250,50; 23/11/2026; 22h30; 3,5 GB; 15 km; 120 km/h; 45%; 1º; 2ª')
        self.assertEqual(len(result.replacements), 9)
        for item in result.replacements:
            self.assertEqual(result.original[item.source_start:item.source_end], item.original)

    def test_abbreviations_and_acronyms_are_tts_only(self):
        text = 'Dr. Silva usa IA, CPU, GPU, USB e SSD na Av. Brasil, etc.'
        result = normalize_pt_br(text)
        self.assertEqual(result.spoken,
            'doutor Silva usa i a, cê pê u, gê pê u, u ésse bê e ésse ésse dê na avenida Brasil, etcetera')
        self.assertEqual(result.original, text)

    def test_invalid_or_ambiguous_identifiers_are_preserved(self):
        text = '31/19/2026, 25h70, 127.0.0.1, 12345678901234567890, v3.5GB'
        result = normalize_pt_br(text)
        self.assertEqual(result.spoken, text)
        self.assertFalse(result.replacements)

    def test_time_forms_are_grammatical_and_invalid_dates_stay_numeric(self):
        text = normalize_pt_br('1h30, 0h30, 12h30, 31/02/2026 e 29/02/2024')
        self.assertIn('uma hora e trinta minutos', text.spoken)
        self.assertIn('meia-noite e meia', text.spoken)
        self.assertIn('meio-dia e meia', text.spoken)
        self.assertIn('31/02/2026', text.spoken)
        self.assertIn('vinte e nove de fevereiro de dois mil e vinte e quatro', text.spoken)

    def test_normalization_is_idempotent_and_keeps_regular_words(self):
        text = 'Você está falando com a gente. O ônibus chegou agora.'
        result = normalize_pt_br(text)
        self.assertEqual(result.spoken, text)
        self.assertEqual(normalize_pt_br(result.spoken).spoken, result.spoken)

    def test_zero_ordinals_and_ambiguous_three_digit_years_are_preserved(self):
        text='0º, 0ª, 23/11/123, 23/11/26, 23/11/2026'
        result=normalize_pt_br(text)
        self.assertEqual(result.spoken,
            '0º, 0ª, 23/11/123, vinte e três de novembro de vinte e seis, '
            'vinte e três de novembro de dois mil e vinte e seis')

    def test_decimal_one_uses_singular_unit(self):
        self.assertEqual(normalize_pt_br('1,00 GB e 1,01 GB').spoken,
                         'um vírgula zero zero gigabyte e um vírgula zero um gigabytes')


class DeterministicNarrativeInterpreterTests(TestCase):
    def test_detects_clear_ptbr_emotion_and_narrative_states(self):
        plan = plan_narrative_interpretation(
            'Como isso aconteceu? Finalmente conseguimos! Por fim, o projeto ficou pronto.')
        self.assertEqual(plan['method'], 'deterministic_pt_br_rules')
        self.assertEqual([item['narrative_state'] for item in plan['sentences']],
                         ['question', 'development', 'conclusion'])
        self.assertEqual(plan['sentences'][1]['emotion'], 'joy')
        self.assertGreater(plan['sentences'][1]['arousal'], .4)
        self.assertEqual(plan['prosody_application'],
                         'analysis_only_backend_capability_unverified')

    def test_negation_does_not_misclassify_happy_as_joy(self):
        plan = plan_narrative_interpretation('Eu não estava feliz com o resultado.')
        self.assertNotEqual(plan['sentences'][0]['emotion'], 'joy')
        self.assertTrue(any('negated' in item for item in plan['sentences'][0]['evidence']))

    def test_ambiguous_and_empty_text_fall_back_neutrally(self):
        self.assertEqual(plan_narrative_interpretation('A janela está aberta.')['sentences'][0]['emotion'],
                         'neutral')
        empty = plan_narrative_interpretation('  ')
        self.assertEqual(empty['sentence_count'], 0)
        self.assertEqual(empty['sentences'], [])

    def test_planner_preserves_source_character_offsets(self):
        source = 'Dr. Silva chegou.  Segunda pergunta?'
        plan = plan_narrative_interpretation(source)
        self.assertEqual(plan['sentence_count'], 2)
        for item in plan['sentences']:
            self.assertEqual(item['text'], source[item['start']:item['end']])

class StreamingFileHashTests(TestCase):
    def test_incremental_sha256_matches_standard_hash(self):
        import hashlib
        content = bytes(range(256)) * 9000
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'long-reference.wav'
            path.write_bytes(content)
            self.assertEqual(file_sha256(path, chunk_bytes=8192),
                             hashlib.sha256(content).hexdigest())

    def test_nonpositive_chunk_size_is_rejected(self):
        with self.assertRaises(ValueError):
            file_sha256('unused.wav', chunk_bytes=0)


class PronunciationDictionaryTests(TestCase):
    def test_dictionary_is_private_per_reference_content_and_atomic_json(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first = root / 'voice-a.wav'; first.write_bytes(b'authorized sample A')
            same = root / 'renamed.wav'; same.write_bytes(b'authorized sample A')
            other = root / 'voice-b.wav'; other.write_bytes(b'authorized sample B')
            dictionary = PronunciationDictionary(first, directory=root / 'dict')
            dictionary.save([{'original': 'Berofel', 'spoken_form': 'Berofél',
                              'language': 'pt-br', 'phonetic_form': '',
                              'context': '', 'case_sensitive': False, 'enabled': True}])
            self.assertEqual(dictionary.load()[0]['spoken_form'], 'Berofél')
            self.assertEqual(PronunciationDictionary(same, directory=root / 'dict').load(),
                             dictionary.load())
            self.assertEqual(PronunciationDictionary(other, directory=root / 'dict').load(), [])
            self.assertEqual(list((root / 'dict').glob('*.tmp')), [])

    def test_context_disabled_and_boundaries_are_respected_without_mutation(self):
        source = 'O Qwen instalou o QwenX; Berofel aparece no Windows.'
        entries = [
            {'original': 'Qwen', 'spoken_form': 'kuên', 'context': 'instalou',
             'enabled': True},
            {'original': 'Berofel', 'spoken_form': 'Berofél', 'context': 'Linux',
             'enabled': True},
        ]
        spoken, applied = apply_pronunciations(source, entries)
        self.assertEqual(spoken, 'O kuên instalou o QwenX; Berofel aparece no Windows.')
        self.assertEqual(applied, ('Qwen',))
        self.assertEqual(source, 'O Qwen instalou o QwenX; Berofel aparece no Windows.')

    def test_context_is_local_and_replacements_do_not_cascade(self):
        source = ('ProdutoX aparece aqui. ' + ('trecho neutro ' * 20) +
                  'contexto especial: ProdutoX.')
        entries = [
            {'original': 'ProdutoX', 'spoken_form': 'ProdutoY',
             'context': 'contexto especial', 'enabled': True},
            {'original': 'ProdutoY', 'spoken_form': 'ProdutoZ',
             'enabled': True},
        ]
        spoken, applied = apply_pronunciations(source, entries)
        self.assertEqual(spoken,
            'ProdutoX aparece aqui. ' + ('trecho neutro ' * 20) +
            'contexto especial: ProdutoY.')
        self.assertEqual(applied, ('ProdutoX',))

    def test_case_sensitive_entry_only_matches_exact_case(self):
        text, applied = apply_pronunciations('usb USB Usb', [
            {'original': 'USB', 'spoken_form': 'u ésse bê', 'case_sensitive': True}
        ])
        self.assertEqual(text, 'usb u ésse bê Usb')
        self.assertEqual(applied, ('USB',))

    def test_duplicate_terms_and_oversized_values_are_rejected(self):
        entries = [{'original': 'SSD', 'spoken_form': 'ésse', 'context': ''},
                   {'original': 'ssd', 'spoken_form': 'dê', 'context': ''}]
        with tempfile.TemporaryDirectory() as folder:
            sample = Path(folder) / 'voice.wav'; sample.write_bytes(b'x')
            with self.assertRaises(ValueError):
                PronunciationDictionary(sample, directory=Path(folder) / 'dict').save(entries)
        with self.assertRaises(ValueError):
            apply_pronunciations('a', [{'original': 'x' * 161,
                                        'spoken_form': 'y'}])


class PureCCapabilityTests(TestCase):
    def test_style_by_example_capability_is_cached_and_invalidated_by_binary_change(self):
        from berofel.services import qwen3_purec_tts as purec
        with tempfile.TemporaryDirectory() as folder:
            executable=Path(folder)/'qwen_tts.exe';executable.write_bytes(b'build one')
            manifest={'cli':{'emotion_by_example_advertised':True,
                'emotion_by_example_needs_transcript':True,
                'emotion_by_example_wav_constraints':'24khz mono'}}
            try:
                with patch.object(purec,'_layout',return_value=(executable,Path(folder),[])), \
                     patch('berofel.services.voice_intelligence.capabilities.inspect_purec_capabilities',
                           return_value=manifest) as inspect:
                    self.assertTrue(purec.supports_emotion_by_example())
                    self.assertTrue(purec.supports_emotion_by_example())
                    self.assertEqual(inspect.call_count,1)
                    manifest['cli']['emotion_by_example_advertised']=False
                    executable.write_bytes(b'build two is different')
                    self.assertFalse(purec.supports_emotion_by_example())
                    self.assertEqual(inspect.call_count,2)
            finally:
                purec._emotion_by_example_capability.cache_clear()

    def test_cli_flags_are_not_misreported_as_http_per_request_features(self):
        with tempfile.TemporaryDirectory() as folder:
            executable = Path(folder) / 'qwen_tts.exe'
            executable.write_bytes(b'fixture executable')
            def runner(command, **_kwargs):
                argument = command[-1]
                if argument == '--help':
                        return Mock(returncode=0, stdout=(
                        '--load-voice --xvector-only --icl-only --icl-frames '
                        '--quant-mixed-cpu --int8\n'
                        '--emotion <spec> (1.7B only)\n'
                        '--emotion-strength <s> (0.6B only)\n'
                        '--emo-ref <wav> EMOTION BY EXAMPLE (24kHz mono)\n'
                        '--emo-ref-text <text> required\n'
                        '--compose --max-ref-duration'),
                        stderr='')
                return Mock(returncode=0, stdout='build: unknown · AVX2', stderr='')
            manifest = inspect_purec_capabilities(executable, runner=runner)
            self.assertTrue(manifest['cli']['xvector_clone'])
            self.assertTrue(manifest['cli']['icl_reference'])
            self.assertEqual(manifest['cli']['mixed_cpu_precision'],
                             'Talker INT8 + Code Predictor INT4')
            self.assertEqual(manifest['cli']['int8_precision'],
                             'Talker INT8 + Code Predictor INT8')
            self.assertFalse(manifest['cli']['emotion_flag_is_06b'])
            self.assertTrue(manifest['cli']['emotion_by_example_advertised'])
            self.assertTrue(manifest['cli']['emotion_by_example_needs_transcript'])
            self.assertEqual(manifest['cli']['emotion_by_example_wav_constraints'], '24khz mono')
            self.assertFalse(manifest['http_adapter']['dynamic_voice_per_request'])
            self.assertFalse(manifest['http_adapter']['emotion_per_request_validated'])
            self.assertFalse(manifest['http_adapter']['emotion_by_example_per_request_validated'])
            self.assertFalse(manifest['http_adapter']['seed_per_request_validated'])
            self.assertFalse(manifest['http_adapter']['emotion_vectors_available'])
            self.assertEqual(manifest['build_id'], 'unknown · AVX2')

    def test_request_seed_capability_is_pinned_to_tested_binary_hash(self):
        from berofel.services.voice_intelligence import capabilities
        with tempfile.TemporaryDirectory() as folder:
            executable = Path(folder) / 'qwen_tts.exe'
            executable.write_bytes(b'installed build fixture')
            capabilities._seed_capability_for_file.cache_clear()
            try:
                with patch.object(capabilities, '_hash_file',
                        return_value='3a5f89d923bfdbea29327bd4111ecd651afa3ef448b2643b6ea8ad63dd907d13') as hash_file:
                    self.assertTrue(supports_request_seed(executable))
                    self.assertTrue(supports_request_seed(executable))
                    self.assertEqual(hash_file.call_count, 1)
                other = Path(folder) / 'other_qwen_tts.exe'
                other.write_bytes(b'unverified build fixture')
                with patch.object(capabilities, '_hash_file', return_value='unknown-build'):
                    self.assertFalse(supports_request_seed(other))
            finally:
                capabilities._seed_capability_for_file.cache_clear()

    def test_emotion_vectors_are_discovered_and_checked_in_runtime_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            executable = Path(folder) / 'qwen_tts.exe'
            executable.write_bytes(b'fixture executable')
            directory = Path(folder) / 'presets' / 'emovoice'
            directory.mkdir(parents=True)
            (directory / 'dir_joy.bin').write_bytes(
                struct.pack('<1024f', *([.03125] * 1024)))
            (directory / 'dir_sad.bin').write_bytes(bytes(4096))
            (directory / 'dir_unknown.bin').write_bytes(
                struct.pack('<1024f', *([.03125] * 1024)))
            (directory / 'dir_fear.bin').write_bytes(b'bad size')

            def runner(command, **_kwargs):
                if command[-1] == '--help':
                    return Mock(returncode=0, stdout='--load-voice --emotion-strength',
                                stderr='')
                return Mock(returncode=0, stdout='build: local fixture', stderr='')

            manifest = inspect_purec_capabilities(executable, runner=runner)
            self.assertTrue(manifest['http_adapter']['emotion_vectors_available'])
            self.assertEqual(manifest['cli']['emotion_direction_files'], ['dir_joy.bin'])
            self.assertEqual(set(manifest['cli']['emotion_direction_files_invalid']),
                             {'dir_sad.bin', 'dir_unknown.bin', 'dir_fear.bin'})


class PureCEmotionVectorMathTests(TestCase):
    def test_direction_asset_format_is_validated(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            good = root / 'dir_joy.bin'
            good.write_bytes(struct.pack('<1024f', *([1 / 32] * 1024)))
            self.assertEqual(len(read_purec_emotion_direction(good)), 1024)
            (root / 'dir_other.bin').write_bytes(good.read_bytes())
            with self.assertRaises(ValueError):
                read_purec_emotion_direction(root / 'dir_other.bin')
            (root / 'dir_fear.bin').write_bytes(bytes(4096))
            with self.assertRaises(ValueError):
                read_purec_emotion_direction(root / 'dir_fear.bin')
            (root / 'dir_sad.bin').write_bytes(struct.pack('<1024f', *([float('nan')] + [0.0] * 1023)))
            with self.assertRaises(ValueError):
                read_purec_emotion_direction(root / 'dir_sad.bin')

    def test_emotion_displacement_preserves_original_vector_norm(self):
        original = tuple([1.0] + [0.0] * 1023)
        direction = tuple([0.0, 1.0] + [0.0] * 1022)
        unchanged = apply_emotion_direction(original, direction, strength=0)
        shifted = apply_emotion_direction(original, direction, strength=0.25)
        self.assertEqual(unchanged, original)
        self.assertAlmostEqual(math.sqrt(sum(value * value for value in shifted)), 1.0)
        self.assertGreater(shifted[1], 0.0)
        self.assertNotEqual(shifted, original)

    def test_emotion_displacement_rejects_unbounded_or_invalid_vectors(self):
        original = tuple([1.0] + [0.0] * 1023)
        direction = tuple([0.0, 1.0] + [0.0] * 1022)
        for strength in (-0.01, 0.36, float('inf'), float('nan')):
            with self.assertRaises(ValueError):
                apply_emotion_direction(original, direction, strength=strength)
        with self.assertRaises(ValueError):
            apply_emotion_direction(original[:-1], direction)
        with self.assertRaises(ValueError):
            apply_emotion_direction(original, tuple([0.0] * 1024))


class ReferenceWindowRankingTests(TestCase):
    def test_reference_selection_revision_invalidates_conditioning_cache(self):
        from berofel.services.audio_reference import REFERENCE_PREPARATION_VERSION
        self.assertEqual(REFERENCE_PREPARATION_VERSION, 8)

    def test_partial_acoustic_scans_do_not_mix_unmeasured_candidates(self):
        from berofel.services.audio_reference import _rank_reference_shortlist
        candidates = [
            {'start': 0.0, 'duration': 3.0,
             'active_seconds': 3.0, 'active_fraction': 1.0},
            {'start': 12.0, 'duration': 6.0,
             'active_seconds': 5.0, 'active_fraction': 5.0 / 6.0},
        ]
        fallback = rank_reference_candidates(candidates)
        ranked = _rank_reference_shortlist(candidates, {
            (12.0, 6.0): {'rms_dbfs': -24.0, 'clipped_fraction': 0.0,
                          'near_silence_fraction': 0.0},
        }, fallback)
        self.assertEqual([(item.start, item.duration) for item in ranked],
                         [(12.0, 6.0)])

    def test_reference_acoustic_scan_accepts_two_second_windows(self):
        from berofel.services.audio_reference import _candidate_acoustic_metrics
        from types import SimpleNamespace
        from unittest.mock import patch
        source = Path('reference.wav')
        pcm_2s = b'\0' * (16000 * 4 * 2)
        with patch('berofel.services.audio_reference.subprocess.run',
                   return_value=SimpleNamespace(returncode=0, stdout=pcm_2s)), \
             patch('berofel.services.voice_intelligence.acoustic_analyzer.analyze_pcm_f32le',
                   return_value={'rms_dbfs': -30.0}) as analyze:
            result = _candidate_acoustic_metrics(source, 'ffmpeg', 0.0, 3.0)
        self.assertEqual(result, {'rms_dbfs': -30.0})
        analyze.assert_called_once()

    def test_clean_shorter_window_can_beat_longer_noisy_window(self):
        candidates = [
            {'start': 0, 'duration': 30, 'active_seconds': 12, 'active_fraction': .4},
            {'start': 45, 'duration': 10, 'active_seconds': 9, 'active_fraction': .9},
        ]
        acoustics = {
            (0.0, 30.0): {'rms_dbfs': -12, 'clipped_fraction': .04,
                          'near_silence_fraction': .15},
            (45.0, 10.0): {'rms_dbfs': -24, 'clipped_fraction': 0,
                           'near_silence_fraction': .03},
        }
        scores = rank_reference_candidates(candidates, acoustics)
        self.assertEqual(scores[0].start, 45.0)
        self.assertEqual(scores[0].confidence, 'heuristic')

    def test_without_acoustics_marks_score_as_limited(self):
        score = rank_reference_candidates([
            {'start': 0, 'duration': 30, 'active_seconds': 10, 'active_fraction': .8}
        ])[0]
        self.assertEqual(score.confidence, 'limited')


class VoiceReferenceReportCacheTests(TestCase):
    def test_persists_numeric_report_and_reuses_it_for_unchanged_sample(self):
        from berofel.services import audio_reference
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'voice.wav';source.write_bytes(b'private voice bytes')
            cache=root/'cache'
            computed={'duration':8.0,'selected_start':2.0,
                      'acoustic_features':{'rms_dbfs':-19.0},'warnings':[]}
            with patch.dict('os.environ',{'BEROFEL_VOICE_INSPECTION_CACHE':str(cache)}), \
                 patch.object(audio_reference,'_voice_report_dependencies',return_value={'v':1}), \
                 patch.object(audio_reference,'_inspect_voice_reference_uncached',
                              return_value=computed) as inspect:
                first=audio_reference.inspect_voice_reference(source)
                second=audio_reference.inspect_voice_reference(source)
            self.assertFalse(first['cache_hit'])
            self.assertTrue(second['cache_hit'])
            self.assertEqual(first['source_sha256'],file_sha256(source))
            self.assertEqual(second['source_sha256'],first['source_sha256'])
            self.assertEqual(inspect.call_count,1)
            payload=next(cache.rglob('*.json')).read_text(encoding='utf-8')
            self.assertNotIn(str(source),payload)
            self.assertNotIn('private voice bytes',payload)

    def test_reference_window_selection_persists_across_process_cache_clear(self):
        from berofel.services import audio_reference
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'authorized-reference.wav'
            source.write_bytes(b'private audio content')
            cache = root / 'cache'
            selected = (18.5, 24.0, .92)
            audio_reference._reference_window_for_identity.cache_clear()
            try:
                with patch.dict('os.environ', {
                        'BEROFEL_VOICE_INSPECTION_CACHE': str(cache)}), \
                     patch.object(audio_reference, '_voice_report_dependencies',
                                  return_value={'tools': 'stable-v1'}), \
                     patch.object(audio_reference, '_best_reference_window',
                                  return_value=selected) as scan:
                    first = audio_reference._reference_window(source)
                    audio_reference._reference_window_for_identity.cache_clear()
                    second = audio_reference._reference_window(source)
                self.assertEqual(first, selected)
                self.assertEqual(second, selected)
                scan.assert_called_once()
                cache_file = next((cache / 'windows').rglob('*.json'))
                payload = cache_file.read_text(encoding='utf-8')
                self.assertNotIn(str(source), payload)
                self.assertNotIn('private audio content', payload)
            finally:
                audio_reference._reference_window_for_identity.cache_clear()

    def test_reference_window_selection_cache_invalidates_on_content_or_tool_change(self):
        from berofel.services import audio_reference
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'authorized-reference.wav'
            source.write_bytes(b'audio-v1')
            cache = root / 'cache'
            dependencies = {'tools': 'v1'}
            audio_reference._reference_window_for_identity.cache_clear()
            try:
                with patch.dict('os.environ', {
                        'BEROFEL_VOICE_INSPECTION_CACHE': str(cache)}), \
                     patch.object(audio_reference, '_voice_report_dependencies',
                                  side_effect=lambda: dict(dependencies)), \
                     patch.object(audio_reference, '_best_reference_window',
                                  side_effect=[(1.0, 20.0, .8),
                                               (2.0, 20.0, .85),
                                               (3.0, 20.0, .9)]) as scan:
                    first = audio_reference._reference_window(source)
                    audio_reference._reference_window_for_identity.cache_clear()
                    dependencies['tools'] = 'v2'
                    tool_changed = audio_reference._reference_window(source)
                    audio_reference._reference_window_for_identity.cache_clear()
                    source.write_bytes(b'audio-v2')
                    media_changed = audio_reference._reference_window(source)
                self.assertEqual(first[0], 1.0)
                self.assertEqual(tool_changed[0], 2.0)
                self.assertEqual(media_changed[0], 3.0)
                self.assertEqual(scan.call_count, 3)
            finally:
                audio_reference._reference_window_for_identity.cache_clear()

    def test_invalidates_report_when_content_or_tool_identity_changes(self):
        from berofel.services import audio_reference
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'voice.wav';source.write_bytes(b'first authorized sample')
            cache=root/'cache';report={'duration':3.0,'warnings':[]}
            dependencies={'tool':'first'}
            with patch.dict('os.environ',{'BEROFEL_VOICE_INSPECTION_CACHE':str(cache)}), \
                 patch.object(audio_reference,'_voice_report_dependencies',
                              side_effect=lambda:dependencies), \
                 patch.object(audio_reference,'_inspect_voice_reference_uncached',
                              return_value=report) as inspect:
                audio_reference.inspect_voice_reference(source)
                dependencies['tool']='second'
                second=audio_reference.inspect_voice_reference(source)
                source.write_bytes(b'second sample same path')
                third=audio_reference.inspect_voice_reference(source)
            self.assertFalse(second['cache_hit'])
            self.assertFalse(third['cache_hit'])
            self.assertEqual(inspect.call_count,3)
            self.assertEqual(len(list(cache.rglob('*.json'))),1)

    def test_corrupt_cache_fails_open_and_is_replaced(self):
        from berofel.services import audio_reference
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'voice.wav';source.write_bytes(b'voice source')
            cache=root/'cache';report={'duration':4.0,'warnings':[]}
            with patch.dict('os.environ',{'BEROFEL_VOICE_INSPECTION_CACHE':str(cache)}), \
                 patch.object(audio_reference,'_voice_report_dependencies',return_value={'v':1}), \
                 patch.object(audio_reference,'_inspect_voice_reference_uncached',
                              return_value=report) as inspect:
                audio_reference.inspect_voice_reference(source)
                cache_file=next(cache.rglob('*.json'))
                cache_file.write_text('{corrupt',encoding='utf-8')
                recovered=audio_reference.inspect_voice_reference(source)
                reread=audio_reference.inspect_voice_reference(source)
            self.assertFalse(recovered['cache_hit'])
            self.assertTrue(reread['cache_hit'])
            self.assertEqual(inspect.call_count,2)


class AcousticWindowAnalysisTests(TestCase):
    def test_reports_frame_features_without_claiming_calibrated_snr(self):
        from array import array
        # Quiet lead-in followed by a clipped, voiced-like test tone.
        samples = array('f', [0.0] * 1600)
        samples.extend([1.0 if index % 2 else -1.0 for index in range(1600)])
        features = analyze_pcm_f32le(samples.tobytes())
        self.assertAlmostEqual(features['duration_seconds'], .2)
        self.assertGreater(features['crest_factor_db'], 0)
        self.assertGreater(features['clipped_fraction'], 0)
        self.assertGreater(features['zero_crossing_rate'], .4)
        self.assertIsNone(features['snr_db'])
        self.assertEqual(features['snr_confidence'], 'unavailable_without_noise_reference')

    def test_numpy_pcm_summary_matches_dependency_free_reference(self):
        from array import array
        from berofel.services.voice_intelligence.acoustic_analyzer import (
            _analyze_pcm_f32le_python,
        )
        samples = array('f')
        samples.extend([0.0] * 173)
        samples.extend([.2 * math.sin(index * .17) for index in range(16003)])
        samples.extend([1.0, -1.0, .001])
        raw = samples.tobytes()
        expected = _analyze_pcm_f32le_python(raw, sample_rate=16000, frame_ms=20)
        actual = analyze_pcm_f32le(raw, sample_rate=16000, frame_ms=20)
        self.assertEqual(actual.keys(), expected.keys())
        for key, value in expected.items():
            if isinstance(value, float):
                self.assertAlmostEqual(actual[key], value, places=8, msg=key)
            else:
                self.assertEqual(actual[key], value, key)

    def test_rejects_invalid_pcm_and_parameters(self):
        with self.assertRaises(ValueError):
            analyze_pcm_f32le(b'')
        with self.assertRaises(ValueError):
            analyze_pcm_f32le(b'\x00\x00\x80\x7f')
        with self.assertRaises(ValueError):
            analyze_pcm_f32le(b'\x00\x00\x00\x00', sample_rate=0)

    def test_yin_pitch_estimate_tracks_a_known_voiced_tone(self):
        import numpy as np
        rate = 16000
        time = np.arange(rate * 2, dtype=np.float32) / rate
        signal = .2 * np.sin(2 * np.pi * 145.0 * time)
        result = analyze_pitch_yin_f32le(signal.astype('<f4').tobytes(),
                                         sample_rate=rate)
        self.assertEqual(result['status'], 'measured')
        self.assertAlmostEqual(result['f0_median_hz'], 145.0, delta=3.0)
        self.assertGreaterEqual(result['confidence_median'], .70)
        self.assertIsNone(result['identity_score'])
        self.assertGreater(result['voiced_frame_count'], 0)

    def test_yin_does_not_report_zero_pitch_for_silence_or_invalid_pcm(self):
        import numpy as np
        silence = np.zeros(16000, dtype='<f4').tobytes()
        result = analyze_pitch_yin_f32le(silence)
        self.assertEqual(result['status'], 'unvoiced_or_low_confidence')
        self.assertIsNone(result['f0_median_hz'])
        with self.assertRaises(ValueError):
            analyze_pitch_yin_f32le(np.array([np.nan] * 1000, dtype='<f4').tobytes())

    def test_yin_requires_multiple_voiced_frames_before_reporting_summary(self):
        import numpy as np
        rate = 16000
        time = np.arange(round(rate * .1), dtype=np.float32) / rate
        signal = .2 * np.sin(2 * np.pi * 145.0 * time)
        result = analyze_pitch_yin_f32le(signal.astype('<f4').tobytes(),
                                         sample_rate=rate)
        self.assertEqual(result['status'], 'insufficient_voiced_coverage')
        self.assertIsNone(result['f0_median_hz'])
        self.assertLess(result['voiced_frame_count'], 3)


class SpectralAcousticAnalysisTests(TestCase):
    def test_tone_and_noise_have_distinct_spectral_diagnostics(self):
        import numpy as np
        rate=16000
        time=np.arange(rate*2,dtype=np.float32)/rate
        tone=(.2*np.sin(2*np.pi*220*time)).astype('<f4')
        noise=np.random.default_rng(19).normal(0,.2,rate*2).astype('<f4')
        voiced=analyze_spectral_f32le(tone.tobytes(),sample_rate=rate,max_frames=30)
        noisy=analyze_spectral_f32le(noise.tobytes(),sample_rate=rate,max_frames=30)
        self.assertEqual(voiced['status'],'measured')
        self.assertEqual(voiced['sampled_frame_count'],30)
        self.assertEqual(len(voiced['mfcc_median']),13)
        self.assertAlmostEqual(voiced['spectral_centroid_hz_p50'],220,delta=20)
        self.assertLess(voiced['spectral_flatness_p50'],noisy['spectral_flatness_p50'])
        self.assertIsNotNone(voiced['hnr_acf_proxy_db_p50'])
        self.assertGreater(voiced['hnr_acf_proxy_db_p50'],noisy['hnr_acf_proxy_db_p50'])
        self.assertIn('not calibrated',voiced['hnr_note'])

    def test_silence_is_unvoiced_and_invalid_pcm_is_rejected(self):
        import numpy as np
        silent=analyze_spectral_f32le(np.zeros(16000,dtype='<f4').tobytes())
        self.assertEqual(silent['status'],'unvoiced_or_low_energy')
        self.assertIsNone(silent['mfcc_median'])
        with self.assertRaises(ValueError):
            analyze_spectral_f32le(np.array([np.nan]*16000,dtype='<f4').tobytes())


class ParakeetQualityInspectionTests(TestCase):
    def test_speech_rate_uses_word_timestamp_union_without_double_counting(self):
        result = calculate_speech_rate([
            {'text': 'Hoje', 'start': 0.0, 'end': 0.6},
            {'text': 'vamos', 'start': 0.5, 'end': 1.0},
            {'text': 'lá', 'start': 2.0, 'end': 2.5},
        ], 4.0)
        self.assertEqual(result['word_count'], 3)
        self.assertAlmostEqual(result['active_speech_seconds'], 1.5)
        self.assertAlmostEqual(result['wpm_wall'], 45.0)
        self.assertAlmostEqual(result['wpm_active'], 120.0)
        self.assertAlmostEqual(result['active_fraction'], .375)
        self.assertEqual(result['inter_word_gap_count'], 1)
        self.assertAlmostEqual(result['inter_word_gap_p50_seconds'], 1.0)
        self.assertAlmostEqual(result['inter_word_gap_p90_seconds'], 1.0)
        self.assertEqual(result['gaps_at_least_0_5_seconds'], 1)
        self.assertEqual(result['timestamp_basis'], 'parakeet_word_timestamps')

    def test_speech_rate_skips_invalid_words_and_reports_missing_timestamps(self):
        result = calculate_speech_rate([
            {'text': 'inválida', 'start': 2.0, 'end': 1.0},
            {'text': 'fora do áudio', 'start': 8.0, 'end': 9.0},
            {'text': 'válida', 'start': .25, 'end': .75},
            {'text': 'sem tempos'},
        ], 2.0)
        self.assertEqual(result['word_count'], 1)
        self.assertAlmostEqual(result['wpm_wall'], 30.0)
        missing = calculate_speech_rate([{'text': 'somente segmento'}], 5.0)
        self.assertIsNone(missing['wpm_wall'])
        self.assertIsNone(missing['wpm_active'])
        self.assertIn('unavailable', missing['note'])

    def test_temporal_coverage_flags_long_tail_for_manual_review_only(self):
        result = calculate_temporal_coverage([
            {'start': 2.0, 'end': 3.1}, {'start': 4.0, 'end': 4.8}], 7.0)
        self.assertAlmostEqual(result['trailing_gap_seconds'], 2.2)
        self.assertTrue(result['review_ending'])
        self.assertIn('listen manually', result['note'])

    def test_temporal_coverage_does_not_invent_when_word_times_are_missing(self):
        result = calculate_temporal_coverage([], 5.0)
        self.assertIsNone(result['last_recognized_word_end_seconds'])
        self.assertIsNone(result['trailing_gap_seconds'])
        self.assertFalse(result['review_ending'])

    def test_text_rates_are_deterministic_and_accent_insensitive(self):
        rates = calculate_text_error_rates(
            'Você está falando com a gente.', 'voce esta falando com a gente')
        self.assertEqual(rates['word_error_rate'], 0)
        self.assertEqual(rates['character_error_rate'], 0)
        self.assertEqual(rates['expected_word_count'], 6)

    def test_text_rates_normalize_numeric_rendering_for_comparison_only(self):
        rates = calculate_text_error_rates(
            'O total é quarenta e cinco por cento e custa vinte e cinco reais.',
            'O total é 45% e custa R$ 25,00.')
        self.assertEqual(rates['word_error_rate'], 0)
        self.assertEqual(rates['character_error_rate'], 0)
        self.assertEqual(rates['comparison_normalization'], 'pt-br-deterministic-v2')

    def test_inspector_uses_injected_parakeet_path_and_marks_review(self):
        with tempfile.TemporaryDirectory() as folder:
            audio = Path(folder) / 'voice.wav'
            audio.write_bytes(b'RIFF' + b'0' * 64)
            seen = {}
            def ffmpeg_runner(command, **_kwargs):
                with wave.open(command[-1], 'wb') as wav:
                    wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000)
                    wav.writeframes(struct.pack('<h', 4000) * 16000)
                return Mock(returncode=0, stdout='', stderr='')
            def parakeet(path):
                seen['path'] = Path(path)
                return {'segments': [{'text': 'Hoje nós vamos demonstrar a narração.'}],
                        'model': 'parakeet-tdt-0.6b-v3-int8',
                        'backend': 'onnxruntime-cpu'}
            stages = []
            result = inspect_generated_wav_with_parakeet(audio,
                'Hoje nós vamos demonstrar a narração.', ffmpeg='ffmpeg',
                runner=ffmpeg_runner, transcriber=parakeet, stage=stages.append)
            self.assertEqual(result['word_error_rate'], 0)
            self.assertEqual(result['provider'], 'CPUExecutionProvider')
            self.assertEqual(result['asr_model'], 'Parakeet TDT v3 ONNX INT8')
            self.assertTrue(result['review_required'])
            self.assertIsNone(result['speech_rate']['wpm_active'])
            self.assertAlmostEqual(result['audio_duration_seconds'], 1.0)
            self.assertLess(result['audio_rms_dbfs'], 0)
            self.assertFalse(result['audio_digitally_silent'])
            self.assertIsNone(result['verification_skipped_reason'])
            self.assertFalse(seen['path'].exists())
            self.assertEqual(len(stages), 2)

    def test_inspector_reuses_local_parakeet_asr_by_audio_hash_but_recompares_text(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            audio = root / 'generated.wav'
            audio.write_bytes(b'RIFF' + b'unchanged synthesized audio' * 4)
            asr_cache = root / 'private-cache'

            def ffmpeg_runner(command, **_kwargs):
                with wave.open(command[-1], 'wb') as wav:
                    wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000)
                    wav.writeframes(struct.pack('<h', 4000) * 16000)
                return Mock(returncode=0, stdout='', stderr='')

            asr_result = {'text': 'voz reconhecida pelo Parakeet',
                'segments': [{'text': 'voz reconhecida pelo Parakeet'}],
                'words': [{'text': 'voz', 'start': 0.1, 'end': 0.3}],
                'backend': 'onnxruntime-cpu'}
            with patch('berofel.services.voice_intelligence.quality_inspector._parakeet_cache_identity',
                       return_value={'model': 'parakeet-tdt-v3-int8', 'threads': 4}), \
                 patch('berofel.services.parakeet_asr.transcribe_file',
                       return_value=asr_result) as parakeet:
                first = inspect_generated_wav_with_parakeet(audio,
                    'voz reconhecida pelo Parakeet', ffmpeg='ffmpeg',
                    runner=ffmpeg_runner, cache_directory=asr_cache)
                second = inspect_generated_wav_with_parakeet(audio,
                    'texto esperado diferente', ffmpeg='ffmpeg',
                    runner=Mock(side_effect=AssertionError('cache deveria evitar FFmpeg')),
                    cache_directory=asr_cache, threads=8)

            self.assertFalse(first['cache_hit'])
            self.assertTrue(second['cache_hit'])
            self.assertEqual(first['word_error_rate'], 0)
            self.assertGreater(second['word_error_rate'], 0)
            self.assertEqual(second['recognized_text'], asr_result['text'])
            self.assertEqual(second['speech_rate']['word_count'], 1)
            self.assertAlmostEqual(second['speech_rate']['wpm_active'], 300.0)
            parakeet.assert_called_once()
            payload = next(asr_cache.rglob('*.json')).read_text(encoding='utf-8')
            self.assertNotIn(str(audio), payload)
            self.assertNotIn('texto esperado diferente', payload)

    def test_inspector_invalidates_corrupt_cache_and_changed_audio(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            audio = root / 'generated.wav'
            audio.write_bytes(b'RIFF' + b'audio version one' * 5)
            cache = root / 'cache'
            def ffmpeg_runner(command, **_kwargs):
                with wave.open(command[-1], 'wb') as wav:
                    wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000)
                    wav.writeframes(struct.pack('<h', 3500) * 16000)
                return Mock(returncode=0, stdout='', stderr='')
            with patch('berofel.services.voice_intelligence.quality_inspector._parakeet_cache_identity',
                       return_value={'model': 'fixture-v1'}), \
                 patch('berofel.services.parakeet_asr.transcribe_file',
                       return_value={'text':'fala reconhecida','words':[],
                                     'backend':'onnxruntime-cpu'}) as parakeet:
                first = inspect_generated_wav_with_parakeet(audio, 'fala reconhecida',
                    ffmpeg='ffmpeg', runner=ffmpeg_runner, cache_directory=cache)
                self.assertFalse(first['cache_hit'])
                next(cache.rglob('*.json')).write_text('{corrupt', encoding='utf-8')
                recovered = inspect_generated_wav_with_parakeet(audio, 'fala reconhecida',
                    ffmpeg='ffmpeg', runner=ffmpeg_runner, cache_directory=cache)
                self.assertFalse(recovered['cache_hit'])
                audio.write_bytes(b'RIFF' + b'audio version two' * 5)
                changed = inspect_generated_wav_with_parakeet(audio, 'fala reconhecida',
                    ffmpeg='ffmpeg', runner=ffmpeg_runner, cache_directory=cache)
            self.assertFalse(changed['cache_hit'])
            self.assertEqual(parakeet.call_count, 3)

    def test_inspector_invalidates_cache_when_parakeet_runtime_identity_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            audio = root / 'generated.wav'
            audio.write_bytes(b'RIFF' + b'unchanged wav content' * 4)
            cache = root / 'cache'
            runtime = {'onnxruntime_version': 'runtime-v1'}

            def ffmpeg_runner(command, **_kwargs):
                with wave.open(command[-1], 'wb') as wav:
                    wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000)
                    wav.writeframes(struct.pack('<h', 3600) * 16000)
                return Mock(returncode=0, stdout='', stderr='')

            with patch('berofel.services.voice_intelligence.quality_inspector._parakeet_cache_identity',
                       side_effect=lambda: dict(runtime)), \
                 patch('berofel.services.parakeet_asr.transcribe_file',
                       return_value={'text':'conteúdo reconhecido','words':[],
                                     'backend':'onnxruntime-cpu'}) as parakeet:
                first = inspect_generated_wav_with_parakeet(audio, 'conteúdo reconhecido',
                    ffmpeg='ffmpeg', runner=ffmpeg_runner, cache_directory=cache)
                runtime['onnxruntime_version'] = 'runtime-v2'
                changed_runtime = inspect_generated_wav_with_parakeet(audio,
                    'conteúdo reconhecido', ffmpeg='ffmpeg', runner=ffmpeg_runner,
                    cache_directory=cache)
            self.assertFalse(first['cache_hit'])
            self.assertFalse(changed_runtime['cache_hit'])
            self.assertEqual(parakeet.call_count, 2)

    def test_silent_output_is_reported_and_skips_parakeet(self):
        with tempfile.TemporaryDirectory() as folder:
            audio = Path(folder) / 'voice.wav'
            audio.write_bytes(b'RIFF' + b'0' * 64)
            calls = []
            def ffmpeg_runner(command, **_kwargs):
                with wave.open(command[-1], 'wb') as wav:
                    wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000)
                    wav.writeframes(b'\x00\x00' * 3200)
                return Mock(returncode=0, stdout='', stderr='')
            result = inspect_generated_wav_with_parakeet(audio, 'fala esperada',
                ffmpeg='ffmpeg', runner=ffmpeg_runner,
                transcriber=lambda path: calls.append(path))
            self.assertEqual(calls, [])
            self.assertTrue(result['audio_digitally_silent'])
            self.assertIn('Parakeet não foi iniciado', result['verification_skipped_reason'])
            self.assertEqual(result['recognized_text'], '')
            self.assertIsNone(result['provider'])
            self.assertEqual(result['backend'], 'not_run')

    def test_very_quiet_nonzero_wav_is_warned_but_still_checked_by_parakeet(self):
        with tempfile.TemporaryDirectory() as folder:
            audio = Path(folder) / 'voice.wav'
            audio.write_bytes(b'RIFF' + b'0' * 64)
            calls = []
            def ffmpeg_runner(command, **_kwargs):
                with wave.open(command[-1], 'wb') as wav:
                    wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000)
                    wav.writeframes(struct.pack('<h', 2) * 1600)
                return Mock(returncode=0, stdout='', stderr='')
            def parakeet(path):
                calls.append(Path(path))
                return {'text':'voz baixa reconhecida','words':[]}
            result = inspect_generated_wav_with_parakeet(audio, 'voz baixa reconhecida',
                ffmpeg='ffmpeg', runner=ffmpeg_runner, transcriber=parakeet)
            self.assertEqual(len(calls), 1)
            self.assertFalse(result['audio_digitally_silent'])
            self.assertIsNone(result['verification_skipped_reason'])
            self.assertTrue(any('extremamente baixo' in item for item in result['audio_warnings']))

    def test_pcm16_inspector_reports_clipping_and_uses_bounded_reads(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'clip.wav'
            samples = [0, 1000, 32767, -32768, 16]
            with wave.open(str(path), 'wb') as wav:
                wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(10)
                wav.writeframes(struct.pack('<5h', *samples))
            result = inspect_pcm16_wav(path, block_seconds=.2)
            self.assertEqual(result['audio_sample_count'], 5)
            self.assertEqual(result['audio_duration_seconds'], .5)
            self.assertAlmostEqual(result['audio_clipped_fraction'], .4)
            self.assertFalse(result['audio_digitally_silent'])
            self.assertTrue(any('clipping' in warning for warning in result['audio_warnings']))


class NarrationNormalizationIntegrationTests(TestCase):
    def test_ptbr_backend_gets_spoken_text_and_result_keeps_source_text(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            reference = root / 'voice.wav'
            with wave.open(str(reference), 'wb') as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(24000)
                audio.writeframes(b'\x01\x00' * 240)
            output = root / 'result.wav'
            with wave.open(str(output), 'wb') as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(24000)
                audio.writeframes(b'\x01\x00' * 240)

            request = NarrationRequest(text='O produto custa R$ 25,00.',
                voice=str(reference), language='portuguese', consent=True,
                reference_text='fala de referência', reference_text_reviewed=True)
            captured = {}

            def backend(effective_request, **_kwargs):
                captured['text'] = effective_request.text
                return {'path': str(output), 'duration': .01, 'cache_hit': False}

            with patch('berofel.services.qwen3_tts_local.generate_local_clone', backend):
                result = generate_narration(request)

            self.assertEqual(captured['text'], 'O produto custa vinte e cinco reais.')
            self.assertEqual(result['source_text'], request.text)
            self.assertEqual(result['spoken_text'], captured['text'])
            self.assertEqual(result['text_normalizer_version'], NORMALIZER_VERSION)
            self.assertEqual(result['narrative_interpretation']['method'],
                             'deterministic_pt_br_rules')

    def test_profile_pronunciation_is_applied_only_to_tts_text(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            reference = root / 'voice.wav'
            with wave.open(str(reference), 'wb') as audio:
                audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(24000)
                audio.writeframes(b'\x01\x00' * 240)
            dictionary = PronunciationDictionary(reference, directory=root / 'pronunciations')
            dictionary.save([{'original': 'Berofel', 'spoken_form': 'Berofél',
                              'language': 'pt-br', 'context': 'editor'}])
            output = root / 'result.wav'
            with wave.open(str(output), 'wb') as audio:
                audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(24000)
                audio.writeframes(b'\x01\x00' * 240)
            request = NarrationRequest(text='O editor Berofel está pronto.',
                voice=str(reference), language='portuguese', consent=True,
                reference_text='fala autorizada', reference_text_reviewed=True)
            captured = {}
            def backend(effective_request, **_kwargs):
                captured['text'] = effective_request.text
                return {'path': str(output), 'duration': .01, 'cache_hit': False}
            with patch('berofel.services.voice_intelligence.pronunciation_dictionary._default_root',
                       return_value=root / 'pronunciations'), \
                 patch('berofel.services.qwen3_tts_local.generate_local_clone', backend):
                result = generate_narration(request)
            self.assertEqual(captured['text'], 'O editor Berofél está pronto.')
            self.assertEqual(result['source_text'], request.text)
            self.assertEqual(result['pronunciation_terms_applied'], ('Berofel',))

    def test_english_is_not_rewritten(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            reference = root / 'voice.wav'
            with wave.open(str(reference), 'wb') as audio:
                audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(24000)
                audio.writeframes(b'\x01\x00' * 240)
            output = root / 'result.wav'
            with wave.open(str(output), 'wb') as audio:
                audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(24000)
                audio.writeframes(b'\x01\x00' * 240)
            request = NarrationRequest(text='It costs R$ 25,00.', voice=str(reference),
                                      language='english', consent=True)
            captured = {}
            def backend(effective_request, **_kwargs):
                captured['text'] = effective_request.text
                return {'path': str(output), 'duration': .01, 'cache_hit': False}
            with patch('berofel.services.qwen3_tts_local.generate_local_clone', backend):
                result = generate_narration(request)
            self.assertEqual(captured['text'], request.text)
            self.assertEqual(result['source_text'], request.text)
