import tempfile
import unittest
import wave
from pathlib import Path

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


if __name__ == '__main__':
    unittest.main()
