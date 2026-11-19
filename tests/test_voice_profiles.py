"""Persistent private voice reference profile tests."""
import json
from pathlib import Path
import tempfile
import unittest

from berofel.services.voice_profiles import VoiceProfileManager


class VoiceProfileManagerTests(unittest.TestCase):
    def test_profile_copies_source_locally_and_survives_manager_reopen(self):
        with tempfile.TemporaryDirectory(prefix='bfs_voice_profiles_') as folder:
            root=Path(folder);source=root/'recording.wav'
            original=b'RIFF'+b'a'*300
            source.write_bytes(original)
            manager=VoiceProfileManager(root/'profile_store')
            profile=manager.create('Minha voz',source,'portuguese')
            self.assertEqual(source.read_bytes(),original)
            self.assertNotEqual(Path(profile['sample_path']),source)
            self.assertEqual(Path(profile['sample_path']).read_bytes(),original)
            self.assertEqual(manager.get(profile['id'])['name'],'Minha voz')
            reopened=VoiceProfileManager(root/'profile_store')
            self.assertEqual(reopened.list_profiles()[0]['sample_path'],profile['sample_path'])
            manifest=json.loads((root/'profile_store'/'profiles.json').read_text(encoding='utf-8'))
            self.assertEqual(manifest['schema_version'],1)

    def test_authorization_is_explicit_and_persists_for_fast_reuse(self):
        with tempfile.TemporaryDirectory(prefix='bfs_voice_profiles_') as folder:
            root=Path(folder);source=root/'recording.wav';source.write_bytes(b'RIFF'+b'a'*300)
            manager=VoiceProfileManager(root/'profile_store')
            profile=manager.create('Minha voz',source,'portuguese','texto da referência')
            self.assertFalse(profile['authorized'])
            self.assertTrue(manager.authorize(profile['id'])['authorized'])
            reopened=VoiceProfileManager(root/'profile_store')
            self.assertTrue(reopened.get(profile['id'])['authorized'])

    def test_rename_and_delete_only_remove_private_copy_not_original(self):
        with tempfile.TemporaryDirectory(prefix='bfs_voice_profiles_') as folder:
            root=Path(folder);source=root/'voice.mp3';source.write_bytes(b'ID3'+b'x'*300)
            manager=VoiceProfileManager(root/'store')
            profile=manager.create('Voz',source)
            manager.rename(profile['id'],'Voz nova')
            private=Path(manager.get(profile['id'])['sample_path'])
            self.assertEqual(manager.get(profile['id'])['name'],'Voz nova')
            manager.delete(profile['id'])
            self.assertFalse(private.exists())
            self.assertEqual(source.read_bytes(),b'ID3'+b'x'*300)
            self.assertEqual(manager.list_profiles(),[])

    def test_rejects_duplicate_names_unsupported_files_and_corrupt_profile_copy(self):
        with tempfile.TemporaryDirectory(prefix='bfs_voice_profiles_') as folder:
            root=Path(folder);source=root/'voice.wav';source.write_bytes(b'RIFF'+b'x'*300)
            manager=VoiceProfileManager(root/'store')
            profile=manager.create('Voz',source)
            with self.assertRaises(ValueError):manager.create(' voz ',source)
            unsupported=root/'voice.txt';unsupported.write_text('no audio')
            with self.assertRaises(ValueError):manager.create('Texto',unsupported)
            Path(profile['sample_path']).write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'alterada ou está corrompida'):
                manager.get(profile['id'])

    def test_rejects_manifest_path_traversal_before_opening_external_files(self):
        with tempfile.TemporaryDirectory(prefix='bfs_voice_profiles_') as folder:
            root=Path(folder);source=root/'voice.wav';source.write_bytes(b'RIFF'+b'x'*300)
            manager=VoiceProfileManager(root/'store')
            profile=manager.create('Voz',source)
            data=json.loads(manager.manifest.read_text(encoding='utf-8'))
            data['profiles'][profile['id']]['sample']='samples/../../voice.wav'
            manager.manifest.write_text(json.dumps(data),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'Caminho inseguro'):
                manager.get(profile['id'])

    def test_legacy_pocket_checkpoint_is_not_accepted_as_qwen_reference(self):
        with tempfile.TemporaryDirectory(prefix='bfs_voice_profiles_') as folder:
            root=Path(folder);source=root/'voice.safetensors';source.write_bytes(b'safe'+b'x'*200)
            manager=VoiceProfileManager(root/'store')
            with self.assertRaisesRegex(ValueError,'WAV, MP3, FLAC, OGG ou M4A'):
                manager.create('Perfil serializado',source)
            self.assertEqual(source.read_bytes(),b'safe'+b'x'*200)


if __name__=='__main__':unittest.main()
