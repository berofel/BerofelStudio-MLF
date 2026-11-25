from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import wave
from unittest import TestCase
from unittest.mock import patch, Mock

from berofel.services.voice_intelligence.text_normalizer import (
    NORMALIZER_VERSION, normalize_pt_br,
)
from berofel.services.voice_intelligence.capabilities import inspect_purec_capabilities
from berofel.services.voice_intelligence.reference_selector import rank_reference_candidates
from berofel.services.voice_intelligence.quality_inspector import (
    calculate_temporal_coverage, calculate_text_error_rates,
    inspect_generated_wav_with_parakeet,
)
from berofel.services.voice_intelligence.acoustic_analyzer import analyze_pcm_f32le
from berofel.services.voice_intelligence.pronunciation_dictionary import (
    PronunciationDictionary, apply_pronunciations,
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
            self.assertFalse(manifest['http_adapter']['emotion_vectors_available'])
            self.assertEqual(manifest['build_id'], 'unknown · AVX2')


class ReferenceWindowRankingTests(TestCase):
    def test_reference_selection_revision_invalidates_conditioning_cache(self):
        from berofel.services.audio_reference import REFERENCE_PREPARATION_VERSION
        self.assertEqual(REFERENCE_PREPARATION_VERSION, 6)

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

    def test_rejects_invalid_pcm_and_parameters(self):
        with self.assertRaises(ValueError):
            analyze_pcm_f32le(b'')
        with self.assertRaises(ValueError):
            analyze_pcm_f32le(b'\x00\x00\x80\x7f')
        with self.assertRaises(ValueError):
            analyze_pcm_f32le(b'\x00\x00\x00\x00', sample_rate=0)


class ParakeetQualityInspectionTests(TestCase):
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
                Path(command[-1]).write_bytes(b'RIFF' + b'0' * 64)
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
            self.assertFalse(seen['path'].exists())
            self.assertEqual(len(stages), 2)


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
