import os
import tempfile
import unittest
import wave
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication

from berofel.services.voice_profiles import VoiceProfileManager
from berofel.ui.multivoice_panel import MultiVoicePanel


def _wav(path):
    with wave.open(str(path), 'wb') as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(24000)
        output.writeframes(b'\x20\x01' * 2400)


class MultiVoicePanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        os.environ['BEROFEL_VOICE_PROFILE_DIR'] = str(Path(self.temp.name) / 'profiles')
        self.manager = VoiceProfileManager()
        sample = Path(self.temp.name) / 'authorized.wav'
        _wav(sample)
        self.profile = self.manager.create('Teste UI', sample, 'portuguese', 'fala de referência',
                                           authorized=True)
        self.panel = MultiVoicePanel()

    def tearDown(self):
        self.panel.close()
        self.temp.cleanup()
        os.environ.pop('BEROFEL_VOICE_PROFILE_DIR', None)

    def test_script_is_built_from_saved_profile_and_ui_keeps_both_modes(self):
        self.panel.assignments['V1'].setCurrentIndex(
            self.panel.assignments['V1'].findData(self.profile['id']))
        self.panel.script_text.setPlainText('[001 | V1 | Ana]\nOlá!')
        script = self.panel.build_script()
        self.assertEqual(script.voices['V1']['profile_id'], self.profile['id'])
        self.assertEqual(script.lines[0].character_name, 'Ana')
        self.assertEqual(script.pause_ms, 200)
        self.assertIn(script.engine_id, {
            'qwen3-tts-purec-int8', 'qwen3-tts-purec-mixed',
            'qwen3-tts-native-q4', 'qwen3-tts-native-q4-balanced', 'qwen3-tts-local'})

    def test_selected_speech_edit_requests_only_its_stable_line_id(self):
        self.panel.assignments['V1'].setCurrentIndex(
            self.panel.assignments['V1'].findData(self.profile['id']))
        self.panel.script_text.setPlainText('[001 | V1]\nOriginal\n[002 | V1]\nIntacta')
        script = self.panel.build_script()
        self.panel.set_active_script(script, script.lines[0].id)
        requests = []
        self.panel.on_regenerate = lambda selected, line_id, text: requests.append(
            (selected.id, line_id, text))
        self.panel.lines.item(0, 2).setText('Corrigida!')
        self.panel.regenerate_selected_line()
        self.assertEqual(requests, [(script.id, script.lines[0].id, 'Corrigida!')])
        self.assertEqual(script.lines[1].text, 'Intacta')

    def test_voice_can_be_changed_per_line_without_discarding_old_audio(self):
        second_sample = Path(self.temp.name) / 'authorized-2.wav'
        _wav(second_sample)
        second = self.manager.create('Teste UI 2', second_sample, 'portuguese',
                                     'outra referência', authorized=True)
        self.panel.refresh_profiles()
        from berofel.services.multivoice_narration import create_script
        script = create_script('[001 | V1]\nTexto',
            {'V1': {'profile_id': self.profile['id']},
             'V2': {'profile_id': second['id']}}, 'qwen3-tts-purec-int8')
        line = script.lines[0]
        line.status = 'generated'; line.audio_path = 'old.wav'; line.duration = 1.1
        changed = []
        self.panel.on_script_changed = lambda current: changed.append(current.id)
        self.panel.set_active_script(script)
        combo = self.panel.lines.cellWidget(0, 1)
        combo.setCurrentIndex(combo.findData('V2'))
        self.assertEqual(line.voice_id, 'V2')
        self.assertEqual(line.status, 'pending')
        self.assertEqual(line.audio_path, 'old.wav')
        self.assertEqual(changed, [script.id])

    def test_purec_warns_when_script_uses_distinct_profiles(self):
        second_sample = Path(self.temp.name) / 'authorized-2.wav'
        _wav(second_sample)
        second = self.manager.create('Teste UI 2', second_sample, 'portuguese',
                                     'outra referência', authorized=True)
        self.panel.refresh_profiles()
        self.panel.assignments['V1'].setCurrentIndex(
            self.panel.assignments['V1'].findData(self.profile['id']))
        self.panel.assignments['V2'].setCurrentIndex(
            self.panel.assignments['V2'].findData(second['id']))
        if self.panel.engine.findData('qwen3-tts-purec-int8') < 0:
            self.panel.engine.addItem('Pure C INT8 test', 'qwen3-tts-purec-int8')
        self.panel.engine.setCurrentIndex(
            self.panel.engine.findData('qwen3-tts-purec-int8'))
        self.assertIn('recarrega o modelo', self.panel.engine_note.text())
        self.panel.assignments['V2'].setCurrentIndex(
            self.panel.assignments['V2'].findData(self.profile['id']))
        self.assertIn('mantém o servidor aquecido', self.panel.engine_note.text())


if __name__ == '__main__':
    unittest.main()
