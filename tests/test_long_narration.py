import tempfile
import wave
import types
import sys
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from berofel.services.narration_service import (
    NarrationRequest, _split_narration_text, generate_narration,
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
            text = 'Uma fala longa em português. ' * 90
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
