"""Versioned persistent user presets for voice DSP."""
import json
from pathlib import Path
import tempfile
import unittest

from berofel.services.voice_presets import VoicePresetManager


class VoicePresetManagerTests(unittest.TestCase):
    def test_save_reload_rename_and_delete(self):
        with tempfile.TemporaryDirectory(prefix='bfs_voice_presets_') as folder:
            path=Path(folder)/'voice.json'
            presets=VoicePresetManager(path)
            values={'bass_db':2.5,'mids_db':-1.,'treble_db':.5,'pitch_semitones':1.2}
            presets.save(' Minha voz ',values)
            reloaded=VoicePresetManager(path)
            self.assertEqual(reloaded.names(),['Minha voz'])
            self.assertEqual(reloaded.get('Minha voz'),values)
            self.assertEqual(reloaded.rename('Minha voz','Voz quente'), 'Voz quente')
            self.assertEqual(reloaded.get('Voz quente'),values)
            schema=json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(schema['schema_version'],1)
            reloaded.delete('Voz quente')
            self.assertEqual(reloaded.names(),[])

    def test_invalid_values_and_builtin_names_are_rejected(self):
        with tempfile.TemporaryDirectory(prefix='bfs_voice_presets_') as folder:
            presets=VoicePresetManager(Path(folder)/'voice.json')
            with self.assertRaises(ValueError):presets.save('Natural',{})
            with self.assertRaises(ValueError):presets.save('Bad',{'bass_db':float('nan')})
            with self.assertRaises(ValueError):presets.save('Bad',{'pitch_semitones':5})


if __name__=='__main__':unittest.main()
