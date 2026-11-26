import hashlib
import json
import tempfile
import wave
import types
import sys
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from berofel.services.narration_service import (
    NarrationRequest, _split_narration_text, generate_narration,
    load_narration_segment_manifest, regenerate_narration_segment,
    qwen_output_token_budget,
)


class LongNarrationTests(TestCase):
    def test_qwen_budget_scales_above_the_old_2048_token_ceiling(self):
        self.assertGreater(qwen_output_token_budget('palavra ' * 250), 2048)
        self.assertLessEqual(qwen_output_token_budget('palavra ' * 10000), 8192)

    def test_sentence_and_word_boundary_split_is_lossless(self):
        text = ('Primeira frase com conteúdo. ' * 100) + ('palavra ' * 700)
        chunks = _split_narration_text(text, 700)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(part) <= 700 for part in chunks))
        self.assertEqual(' '.join(chunks).replace(' .', '.'), text.strip())

    def test_long_text_split_does_not_separate_known_titles_from_names(self):
        text=('A Dra. Ana revisa o caso com bastante cuidado. '
              'O Prof. Silva explica o resultado com clareza. ')*30
        chunks=_split_narration_text(text,120)
        self.assertGreater(len(chunks),1)
        self.assertTrue(all(not chunk.rstrip().endswith(('Dra.','Prof.'))
                            for chunk in chunks),chunks)
        self.assertTrue(all(len(chunk)<=120 for chunk in chunks))
        self.assertEqual(' '.join(chunks),text.strip())

    def test_1700_character_local_text_remains_one_request(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            reference = root / 'voice.wav'
            self._write_wav(reference, frames=240)
            request = NarrationRequest(text='palavra ' * 212 + 'final',
                voice=str(reference), language='english', consent=True,
                project_path=str(root / 'project.bfs'))
            calls = []

            def fake_backend(req, **_kwargs):
                calls.append(req.text)
                out = root / 'single.wav'
                self._write_wav(out, frames=24000)
                return {'path': str(out), 'duration': 1.0, 'cache_hit': False,
                        'prompt_cache_hit': False, 'generation_seconds': 1.0}

            with patch('berofel.services.qwen3_tts_local.generate_local_clone', fake_backend):
                result = generate_narration(request)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0], request.text)
            self.assertEqual(result['duration'], 1.0)

    def test_purec_long_text_becomes_one_gapless_wav(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            reference = root / 'voice.wav'
            self._write_wav(reference, frames=240)
            text = ('Uma fala longa em português. ' * 90).strip()
            request = NarrationRequest(text=text, voice=str(reference),
                language='english', consent=True, engine='qwen3-tts-purec-int8',
                project_path=str(root / 'project.bfs'))
            calls = []

            def fake_backend(req, **_kwargs):
                calls.append(req.text)
                out = Path(req.project_path).parent / f'{len(calls)}.wav'
                self._write_wav(out, frames=24000)
                return {'path': str(out), 'duration': 1.0, 'cache_hit': False,
                        'prompt_cache_hit': False, 'generation_seconds': 0.5,
                        'conditioning_mode': 'speaker-embedding-only'}

            purec = types.ModuleType('berofel.services.qwen3_purec_tts')
            purec.generate_purec_clone = fake_backend
            with patch.dict(sys.modules, {'berofel.services.qwen3_purec_tts': purec}):
                result = generate_narration(request)
            self.assertGreater(len(calls), 1)
            self.assertEqual(' '.join(calls).split(), text.split())
            self.assertTrue(result['continuous_wav'])
            self.assertEqual(result['chunk_count'], len(calls))
            with wave.open(result['path'], 'rb') as audio:
                self.assertEqual(audio.getnframes(), len(calls) * 24000)
                self.assertEqual(audio.getframerate(), 24000)
            manifest_path = Path(result['segment_manifest_path'])
            self.assertTrue(manifest_path.is_file())
            self.assertEqual(result['segment_manifest_warning'], '')
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            self.assertEqual(manifest['schema_version'], 2)
            self.assertTrue(manifest['source_offsets_available'])
            self.assertEqual(manifest['total_frames'], len(calls) * 24000)
            self.assertEqual(manifest['audio_sha256'], hashlib.sha256(
                Path(result['path']).read_bytes()).hexdigest())
            cursor = 0
            for segment in manifest['segments']:
                self.assertEqual(segment['start_frame'], cursor)
                self.assertGreater(segment['end_frame'], segment['start_frame'])
                cursor = segment['end_frame']
                start, end = segment['spoken_text_start'], segment['spoken_text_end']
                aligned = ' '.join(result['spoken_text'][start:end].split())
                self.assertEqual(aligned, ' '.join(segment['spoken_text'].split()))
                self.assertEqual(segment['source_text_start'], start)
                self.assertEqual(segment['source_text_end'], end)
            self.assertEqual(cursor, manifest['total_frames'])

    def test_selective_regeneration_replaces_one_pcm_span_and_keeps_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            reference = root / 'voice.wav'
            self._write_wav(reference, frames=240)
            request = NarrationRequest(
                text=('Esta é uma frase de teste para regeneração seletiva. ' * 70),
                voice=str(reference), language='english', consent=True,
                engine='qwen3-tts-purec-int8',
                project_path=str(root / 'project.bfs'))
            original_calls = []

            def fake_backend(req, **_kwargs):
                original_calls.append(req.text)
                path = root / f'part-{len(original_calls)}.wav'
                self._write_constant_wav(path, frames=24000,
                                         value=len(original_calls) * 100)
                return {'path': str(path), 'duration': 1.0, 'cache_hit': False,
                        'prompt_cache_hit': False, 'generation_seconds': .2}

            purec = types.ModuleType('berofel.services.qwen3_purec_tts')
            purec.generate_purec_clone = fake_backend
            with patch.dict(sys.modules, {'berofel.services.qwen3_purec_tts': purec}):
                result = generate_narration(request)

            self.assertGreaterEqual(len(original_calls), 2)
            manifest = load_narration_segment_manifest(result['path'], request)
            selected = 1
            target = manifest['segments'][selected]
            source_bytes = Path(result['path']).read_bytes()
            source_hash = hashlib.sha256(source_bytes).hexdigest()
            replacement = root / 'replacement.wav'
            seen = []

            def fake_regeneration(part_request, **kwargs):
                seen.append((part_request.text, kwargs.get('_prepared_text')))
                self._write_constant_wav(replacement, frames=12000, value=777)
                return {'path': str(replacement), 'duration': .5, 'cache_hit': False}

            with patch('berofel.services.narration_service.generate_narration',
                       side_effect=fake_regeneration):
                updated = regenerate_narration_segment(
                    result['path'], request, selected)

            self.assertEqual(seen, [(target['spoken_text'], True)])
            self.assertEqual(hashlib.sha256(Path(result['path']).read_bytes()).hexdigest(),
                             source_hash)
            self.assertNotEqual(Path(updated['path']), Path(result['path']))
            with wave.open(result['path'], 'rb') as old, \
                    wave.open(updated['path'], 'rb') as new:
                rate = old.getframerate()
                start = int(target['start_frame']); end = int(target['end_frame'])
                old.setpos(0); prefix = old.readframes(start)
                old.setpos(end); suffix = old.readframes(old.getnframes() - end)
                new.setpos(0)
                self.assertEqual(new.readframes(start), prefix)
                self.assertEqual(new.readframes(12000), b'\x09\x03' * 12000)
                self.assertEqual(new.readframes(new.getnframes() - start - 12000), suffix)
                self.assertEqual(new.getnframes(), old.getnframes() - (end-start) + 12000)
                self.assertAlmostEqual(updated['duration'], new.getnframes() / rate)
            updated_manifest = load_narration_segment_manifest(updated['path'], request)
            self.assertEqual(updated_manifest['segments'][selected]['end_frame'] -
                             updated_manifest['segments'][selected]['start_frame'], 12000)

    def test_segment_manifest_rejects_changed_script_and_audio(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            reference = root / 'voice.wav'
            self._write_wav(reference, frames=240)
            request = NarrationRequest(text='Palavra de roteiro. ' * 100,
                voice=str(reference), language='english', consent=True,
                engine='qwen3-tts-purec-int8', project_path=str(root / 'project.bfs'))
            calls = []

            def fake_backend(req, **_kwargs):
                calls.append(req.text)
                path = root / f'short-{len(calls)}.wav'
                self._write_wav(path, frames=24000)
                return {'path': str(path), 'duration': 1.0, 'cache_hit': False,
                        'prompt_cache_hit': False, 'generation_seconds': .2}

            purec = types.ModuleType('berofel.services.qwen3_purec_tts')
            purec.generate_purec_clone = fake_backend
            with patch.dict(sys.modules, {'berofel.services.qwen3_purec_tts': purec}):
                result = generate_narration(request)
            changed_script = NarrationRequest(**{**request.__dict__,
                'text':request.text + ' Mudança.'})
            with self.assertRaisesRegex(ValueError, 'roteiro mudou'):
                load_narration_segment_manifest(result['path'], changed_script)
            with Path(result['path']).open('ab') as stream:
                stream.write(b'changed')
            with self.assertRaisesRegex(ValueError, 'offsets de trechos'):
                load_narration_segment_manifest(result['path'], request)

    def test_manifest_with_ptbr_normalization_does_not_guess_source_offsets(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            reference = root / 'voice.wav'
            self._write_wav(reference, frames=240)
            text = 'O produto custa R$ 25,00. ' * 90
            request = NarrationRequest(text=text, voice=str(reference),
                language='portuguese', consent=True, engine='qwen3-tts-purec-int8',
                project_path=str(root / 'project.bfs'))
            calls = []

            def fake_backend(req, **_kwargs):
                calls.append(req.text)
                out = root / f'currency-{len(calls)}.wav'
                self._write_wav(out, frames=12000)
                return {'path': str(out), 'duration': .5, 'cache_hit': False,
                        'prompt_cache_hit': False, 'generation_seconds': .25}

            purec = types.ModuleType('berofel.services.qwen3_purec_tts')
            purec.generate_purec_clone = fake_backend
            with patch.dict(sys.modules, {'berofel.services.qwen3_purec_tts': purec}):
                result = generate_narration(request)

            manifest = json.loads(Path(result['segment_manifest_path']).read_text(
                encoding='utf-8'))
            self.assertGreater(len(calls), 1)
            self.assertNotEqual(result['source_text'], result['spoken_text'])
            self.assertFalse(manifest['source_offsets_available'])
            self.assertTrue(all(segment['source_text_start'] is None and
                                segment['source_text_end'] is None
                                for segment in manifest['segments']))
            for segment in manifest['segments']:
                start, end = segment['spoken_text_start'], segment['spoken_text_end']
                aligned = ' '.join(result['spoken_text'][start:end].split())
                self.assertEqual(aligned, ' '.join(segment['spoken_text'].split()))

    def test_long_script_interpretation_is_planned_once_for_whole_text(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            reference = root / 'voice.wav'
            self._write_wav(reference, frames=240)
            text = 'Hoje vamos apresentar o editor. ' * 90
            request = NarrationRequest(text=text, voice=str(reference),
                language='portuguese', consent=True, engine='qwen3-tts-purec-int8',
                project_path=str(root / 'project.bfs'))
            calls = []

            def fake_backend(req, **_kwargs):
                calls.append(req.text)
                out = Path(req.project_path).parent / f'{len(calls)}.wav'
                self._write_wav(out, frames=24000)
                return {'path': str(out), 'duration': 1.0, 'cache_hit': False,
                        'prompt_cache_hit': False, 'generation_seconds': 0.5,
                        'conditioning_mode': 'speaker-embedding-only'}

            purec = types.ModuleType('berofel.services.qwen3_purec_tts')
            purec.generate_purec_clone = fake_backend
            with patch('berofel.services.narration_service.plan_narrative_interpretation',
                       return_value={'version': 'test'}) as planner, \
                 patch.dict(sys.modules, {'berofel.services.qwen3_purec_tts': purec}):
                result = generate_narration(request)

            self.assertGreater(len(calls), 1)
            planner.assert_called_once_with(text)
            self.assertEqual(result['narrative_interpretation'], {'version': 'test'})

    @staticmethod
    def _write_wav(path, frames):
        with wave.open(str(path), 'wb') as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(24000)
            audio.writeframes(b'\x01\x00' * frames)

    @staticmethod
    def _write_constant_wav(path, frames, value):
        sample = int(value).to_bytes(2, 'little', signed=True)
        with wave.open(str(path), 'wb') as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(24000)
            audio.writeframes(sample * frames)
