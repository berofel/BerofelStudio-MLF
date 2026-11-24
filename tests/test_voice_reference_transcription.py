"""Local-reference transcription and PT-BR clone-conditioning safeguards."""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from berofel.services.narration_service import (
    NarrationRequest, validate_clone_conditioning,
)


class CloneConditioningTests(unittest.TestCase):
    def _request(self, engine='qwen3-tts-local', language='portuguese', text='',
                 reviewed=False):
        return NarrationRequest(text='frase nova', voice='voice.wav',
                                engine=engine, language=language,
                                reference_text=text,
                                reference_text_reviewed=reviewed)

    def test_ptbr_original_requires_reference_transcript(self):
        with self.assertRaisesRegex(ValueError, 'transcrição exata'):
            validate_clone_conditioning(self._request())

    def test_ptbr_purec_is_allowed_as_explicit_xvector_path(self):
        validate_clone_conditioning(self._request(
            'qwen3-tts-purec-int8', text=''))
        validate_clone_conditioning(self._request(
            'qwen3-tts-purec-mixed', text=''))

    def test_ptbr_native_q4_remains_blocked_until_validated(self):
        with self.assertRaisesRegex(ValueError, 'não foi validado'):
            validate_clone_conditioning(self._request('qwen3-tts-native-q4'))

    def test_ptbr_original_accepts_transcribed_reference(self):
        validate_clone_conditioning(self._request(text='texto exato',reviewed=True))

    def test_ptbr_original_rejects_unreviewed_asr_draft(self):
        with self.assertRaisesRegex(ValueError,'ainda não foi confirmada'):
            validate_clone_conditioning(self._request(text='rascunho Whisper'))

    def test_non_portuguese_fast_backend_is_unaffected(self):
        validate_clone_conditioning(self._request(
            'qwen3-tts-purec-int8', language='english'))


class VoiceReferenceTranscriptionTests(unittest.TestCase):
    def test_transcribes_selected_window_offline_and_marks_text_for_review(self):
        from berofel.services.voice_reference_transcription import transcribe_voice_reference

        with tempfile.TemporaryDirectory(prefix='bfs_ref_asr_test_') as folder:
            root = Path(folder)
            source = root / 'authorized-reference.ogg'
            source.write_bytes(b'not decoded by this unit test' * 20)
            models = root / 'whisper-base'
            models.mkdir()
            (models / 'model.bin').write_bytes(b'local model fixture')

            def make_wav(command, **_kwargs):
                Path(command[-1]).write_bytes(b'RIFF' + b'pcm fixture' * 20)
                return SimpleNamespace(returncode=0, stdout='', stderr='')

            def run_stage(name, payload, _output, **_kwargs):
                self.assertEqual(name, 'whisper')
                self.assertEqual(payload['language'], 'pt')
                self.assertTrue(payload['offline_only'])
                self.assertTrue(payload['word_timestamps'])
                self.assertEqual(payload['compute_type'], 'int8')
                return {'result': {
                    'language': 'pt',
                    'segments': [{'text': ' A gente vai narrar hoje. '}],
                    'words': [{'probability': .9}, {'probability': .8}],
                }}

            with (patch('berofel.services.audio_reference._reference_window',
                        return_value=(12.5, 8.0, .91)),
                  patch('berofel.services.ffmpeg.ffmpeg_path', return_value='ffmpeg'),
                  patch('berofel.services.model_paths.whisper_model_dir',
                        return_value=models),
                  patch('berofel.services.voice_reference_transcription.subprocess.run',
                        side_effect=make_wav)):
                result = transcribe_voice_reference(str(source), runner=run_stage)

        self.assertEqual(result['text'], 'A gente vai narrar hoje.')
        self.assertEqual(result['reference_window'], {'start': 12.5, 'duration': 8.0})
        self.assertEqual(result['word_count'], 5)
        self.assertAlmostEqual(result['mean_word_confidence'], .85)
        self.assertTrue(result['review_required'])

    def test_missing_local_whisper_model_has_actionable_error(self):
        from berofel.services.voice_reference_transcription import transcribe_voice_reference

        with tempfile.TemporaryDirectory(prefix='bfs_ref_asr_missing_') as folder:
            source = Path(folder) / 'voice.wav'
            source.write_bytes(b'RIFF' + b'valid-enough-for-path-check' * 5)
            model_dir = Path(folder) / 'missing-model'
            with (patch('berofel.services.audio_reference._reference_window',
                        return_value=(0.0, 4.0, .8)),
                  patch('berofel.services.model_paths.whisper_model_dir',
                        return_value=model_dir)):
                with self.assertRaisesRegex(FileNotFoundError, 'Faster-Whisper Base local'):
                    transcribe_voice_reference(str(source))


if __name__ == '__main__':
    unittest.main()
