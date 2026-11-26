"""Persistent private voice reference profile tests."""
import json
import os
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
            self.assertFalse(profile['reference_text_reviewed'])
            self.assertTrue(manager.authorize(profile['id'])['authorized'])
            reopened=VoiceProfileManager(root/'profile_store')
            self.assertTrue(reopened.get(profile['id'])['authorized'])

    def test_transcript_review_confirmation_persists_with_profile(self):
        with tempfile.TemporaryDirectory(prefix='bfs_reviewed_voice_profile_') as folder:
            root=Path(folder);source=root/'recording.wav';source.write_bytes(b'RIFF'+b'a'*300)
            manager=VoiceProfileManager(root/'profiles')
            profile=manager.create('Voz confirmada',source,'portuguese',
                'transcrição conferida',authorized=True,reference_text_reviewed=True)
            self.assertTrue(profile['reference_text_reviewed'])
            manager.update_reference_text(profile['id'],'transcrição editada',reviewed=True)
            reopened=VoiceProfileManager(root/'profiles').get(profile['id'])
            self.assertEqual(reopened['reference_text'],'transcrição editada')
            self.assertTrue(reopened['reference_text_reviewed'])
            manager.update_reference_text(profile['id'],'rascunho novo',reviewed=False)
            self.assertFalse(manager.get(profile['id'])['reference_text_reviewed'])

    def test_reference_transcript_update_preserves_authorization_and_audio(self):
        with tempfile.TemporaryDirectory(prefix='bfs_voice_profiles_') as folder:
            root=Path(folder);source=root/'recording.wav';original=b'RIFF'+b'a'*300
            source.write_bytes(original)
            manager=VoiceProfileManager(root/'profile_store')
            profile=manager.create('Minha voz',source,'portuguese',
                                   'texto antigo',authorized=True)
            private=Path(profile['sample_path']);private_bytes=private.read_bytes()
            updated=manager.update_reference_text(profile['id'],
                '  texto   revisado\n com a transcrição correta  ')
            self.assertEqual(updated['reference_text'],
                             'texto revisado com a transcrição correta')
            self.assertTrue(updated['authorized'])
            self.assertEqual(updated['id'],profile['id'])
            self.assertEqual(private.read_bytes(),private_bytes)
            self.assertEqual(source.read_bytes(),original)
            reopened=VoiceProfileManager(root/'profile_store')
            self.assertEqual(reopened.get(profile['id'])['reference_text'],
                             updated['reference_text'])
            with self.assertRaisesRegex(ValueError,'4000 caracteres'):
                reopened.update_reference_text(profile['id'],'x'*4001)
            self.assertEqual(reopened.get(profile['id'])['reference_text'],
                             updated['reference_text'])

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

    def test_reuses_verified_sample_hash_until_file_identity_changes(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory(prefix='bfs_profile_hash_cache_') as folder:
            root = Path(folder)
            source = root / 'voice.wav'
            source.write_bytes(b'RIFF' + b'a' * 300)
            manager = VoiceProfileManager(root / 'profiles')
            profile = manager.create('Voz longa', source)
            sample = Path(profile['sample_path'])
            original_hash = manager._hash_file
            with patch.object(manager, '_hash_file', wraps=original_hash) as hash_file:
                manager.get(profile['id'])
                manager.list_profiles()
                manager.get(profile['id'])
                self.assertEqual(hash_file.call_count, 0)

                before = sample.stat()
                sample.write_bytes(b'RIFF' + b'b' * 300)
                os.utime(sample, ns=(before.st_atime_ns, before.st_mtime_ns + 5_000_000_000))
                with self.assertRaisesRegex(ValueError, 'alterada ou está corrompida'):
                    manager.get(profile['id'])
                self.assertEqual(hash_file.call_count, 1)

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

    def test_acoustic_summary_is_private_versioned_and_bound_to_sample_hash(self):
        import math
        with tempfile.TemporaryDirectory(prefix='bfs_voice_fingerprint_') as folder:
            root=Path(folder);source=root/'voice.wav';source.write_bytes(b'RIFF'+b'a'*300)
            manager=VoiceProfileManager(root/'profiles')
            profile=manager.create('Perfil local',source,authorized=True)
            saved=manager.save_acoustic_fingerprint(profile['id'],{
                'source_sha256':profile['sample_sha256'],
                'duration':12.0,'rms_dbfs':-20.0,'absolute_source_path':'C:/private.wav',
                'reference_text':'private words','pitch_features':{'f0_median_hz':145.0},
                'acoustic_features':{'snr_db':None,'snr_confidence':'unavailable'},
                'reference_quality_components':{'duration':0.7},
                'unexpected_nan':math.nan,
            })
            reopened=VoiceProfileManager(root/'profiles').get_voice_intelligence(profile['id'])
            self.assertEqual(saved,reopened)
            self.assertEqual(reopened['measurements']['pitch_features']['f0_median_hz'],145.0)
            self.assertNotIn('absolute_source_path',json.dumps(reopened))
            self.assertNotIn('private words',json.dumps(reopened))
            self.assertNotIn('unexpected_nan',json.dumps(reopened))
            self.assertFalse(reopened['interpretation']['pitch_is_speaker_identity'])
            self.assertTrue((root/'profiles'/'intelligence'/f"{profile['id']}.json").is_file())
            with self.assertRaisesRegex(ValueError,'não corresponde exatamente'):
                manager.save_acoustic_fingerprint(profile['id'],{
                    'source_sha256':'0'*64,'duration':99.0})

    def test_purec_vector_metadata_validates_existing_cache_without_copying_vector(self):
        import struct
        from unittest.mock import patch
        with tempfile.TemporaryDirectory(prefix='bfs_profile_vector_') as folder:
            root=Path(folder);source=root/'voice.wav';source.write_bytes(b'RIFF'+b'a'*300)
            cache=root/'qwen_cache';cache.mkdir()
            vector=cache/('a'*64+'.bin')
            vector.write_bytes(struct.pack('<1024f',1.0,*([0.0]*1023)))
            manager=VoiceProfileManager(root/'profiles')
            profile=manager.create('Perfil local',source)
            with patch('berofel.services.qwen3_purec_tts._profile_cache_root',return_value=cache):
                result=manager.bind_purec_fingerprint(profile['id'],vector,
                    engine='qwen3-tts-purec-int8',
                    source_sha256=profile['sample_sha256'],model_key='test-model-key')
            metadata=result['purec_identity_vector']
            self.assertEqual(metadata['dimension'],1024)
            self.assertEqual(metadata['cache_key'],vector.stem)
            self.assertEqual(metadata['model_key'],'test-model-key')
            self.assertIsNone(metadata['calibrated_similarity_threshold'])
            self.assertTrue(vector.is_file())
            self.assertEqual(metadata['sha256'],manager._hash_file(vector))
            with self.assertRaisesRegex(ValueError,'não corresponde'):
                manager.bind_purec_fingerprint(profile['id'],vector,
                    engine='qwen3-tts-purec-int8',source_sha256='0'*64)

    def test_profile_delete_removes_its_fingerprint_metadata_only(self):
        with tempfile.TemporaryDirectory(prefix='bfs_profile_delete_fingerprint_') as folder:
            root=Path(folder);source=root/'voice.wav';source.write_bytes(b'RIFF'+b'a'*300)
            manager=VoiceProfileManager(root/'profiles')
            profile=manager.create('Perfil local',source)
            manager.save_acoustic_fingerprint(profile['id'],{
                'source_sha256':profile['sample_sha256'],'duration':5.0})
            metadata=root/'profiles'/'intelligence'/f"{profile['id']}.json"
            self.assertTrue(metadata.is_file())
            manager.delete(profile['id'])
            self.assertFalse(metadata.exists())
            self.assertEqual(source.read_bytes(),b'RIFF'+b'a'*300)


if __name__=='__main__':unittest.main()
