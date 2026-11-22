import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

from scripts.validar_troca_perfis_trechos_voz_autorizada import (
    ENGINES as VOICE_SWITCH_ENGINES, select_speech_segments,
)
from scripts.validar_multivoice_distinct_profiles import (
    select_authorized_distinct_profiles,
)
from berofel.services.voice_profiles import VoiceProfileManager


def _write_reference(path: Path, sample: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24_000)
        audio.writeframes(sample.to_bytes(2, 'little', signed=True) * 2_400)


class DistinctProfileAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='bfs_distinct_profiles_')
        self.root = Path(self.temp.name)
        self.manager = VoiceProfileManager(self.root / 'profiles')

    def tearDown(self):
        self.temp.cleanup()

    def _profile(self, name: str, source: Path, authorized: bool):
        return self.manager.create(name, source, 'portuguese', 'fala de teste',
                                   authorized=authorized)

    def test_selects_two_authorized_profiles_with_distinct_recordings(self):
        first_audio = self.root / 'first.wav'
        second_audio = self.root / 'second.wav'
        _write_reference(first_audio, 512)
        _write_reference(second_audio, 1024)
        first = self._profile('Voz um', first_audio, True)
        second = self._profile('Voz dois', second_audio, True)

        profiles, fingerprints = select_authorized_distinct_profiles(
            self.manager, first['id'], second['id'])

        self.assertEqual(set(profiles), {first['id'], second['id']})
        self.assertEqual(set(fingerprints), {first['id'], second['id']})
        self.assertNotEqual(fingerprints[first['id']], fingerprints[second['id']])

    def test_rejects_two_profile_ids_that_copy_the_same_reference(self):
        reference = self.root / 'same.wav'
        _write_reference(reference, 512)
        first = self._profile('Cópia um', reference, True)
        second = self._profile('Cópia dois', reference, True)

        with self.assertRaisesRegex(ValueError, 'gravações diferentes'):
            select_authorized_distinct_profiles(self.manager, first['id'], second['id'])

    def test_rejects_profile_without_explicit_authorization(self):
        first_audio = self.root / 'first.wav'
        second_audio = self.root / 'second.wav'
        _write_reference(first_audio, 512)
        _write_reference(second_audio, 1024)
        first = self._profile('Voz autorizada', first_audio, True)
        second = self._profile('Voz pendente', second_audio, False)

        with self.assertRaisesRegex(PermissionError, 'V2 não está autorizado'):
            select_authorized_distinct_profiles(self.manager, first['id'], second['id'])

    def test_rejects_reusing_the_same_profile_id_for_both_characters(self):
        reference = self.root / 'voice.wav'
        _write_reference(reference, 512)
        profile = self._profile('Voz única', reference, True)

        with self.assertRaisesRegex(ValueError, 'IDs de perfil diferentes'):
            select_authorized_distinct_profiles(self.manager, profile['id'], profile['id'])

    def test_temporary_segment_selector_returns_distinct_high_energy_windows(self):
        rate = 24_000
        t = np.arange(6 * rate, dtype=np.float64) / rate
        signal = np.where(t < 3, np.sin(2 * np.pi * 125 * t),
                          np.sin(2 * np.pi * 205 * t))
        pcm = np.clip(signal * 12_000, -32768, 32767).astype(np.int16)
        first, second, rms = select_speech_segments(pcm, rate)
        self.assertEqual(len(first), 3 * rate)
        self.assertEqual(len(second), 3 * rate)
        self.assertFalse(np.array_equal(first, second))
        self.assertTrue(all(value > 0.003 for value in rms))

    def test_temporary_segment_selector_rejects_silent_or_short_reference(self):
        rate = 24_000
        with self.assertRaisesRegex(ValueError, 'curta demais'):
            select_speech_segments(np.ones(rate * 3, dtype=np.int16), rate)
        with self.assertRaisesRegex(ValueError, 'pouco sinal'):
            select_speech_segments(np.zeros(rate * 6, dtype=np.int16), rate)

    def test_voice_switch_diagnostic_offers_native_persistent_worker(self):
        self.assertIn('qwen3-tts-native-q4', VOICE_SWITCH_ENGINES)


if __name__ == '__main__':
    unittest.main()
