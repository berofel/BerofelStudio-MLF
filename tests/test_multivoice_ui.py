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

    def test_line_can_switch_to_a_configured_voice_unused_in_imported_text(self):
        second_sample = Path(self.temp.name) / 'authorized-2.wav'
        _wav(second_sample)
        second = self.manager.create('Teste UI 2', second_sample, 'portuguese',
                                     'outra referência', authorized=True)
        self.panel.refresh_profiles()
        for voice_id, profile in (('V1', self.profile), ('V2', second)):
            self.panel.assignments[voice_id].setCurrentIndex(
                self.panel.assignments[voice_id].findData(profile['id']))
        if self.panel.engine.findData('qwen3-tts-purec-int8') < 0:
            self.panel.engine.addItem('Pure C INT8 test', 'qwen3-tts-purec-int8')
        self.panel.engine.setCurrentIndex(
            self.panel.engine.findData('qwen3-tts-purec-int8'))
        self.panel.script_text.setPlainText(
            '[001 | V1]\nPrimeira fala.\n[002 | V1]\nSegunda fala.')
        script = self.panel.build_script()
        self.assertIn('V2', script.voices)
        self.panel.set_active_script(script)
        self.assertIn('mantém o servidor aquecido', self.panel.engine_note.text())
        combo = self.panel.lines.cellWidget(0, 1)
        self.assertGreaterEqual(combo.findData('V2'), 0)
        combo.setCurrentIndex(combo.findData('V2'))
        self.assertEqual(script.lines[0].voice_id, 'V2')
        self.assertIn('recarrega o modelo', self.panel.engine_note.text())

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
        self.assertNotIn('recarrega o modelo', self.panel.engine_note.text())
        self.panel.script_text.setPlainText('[001 | V1]\nUma voz.')
        self.assertIn('mantém o servidor aquecido', self.panel.engine_note.text())
        self.panel.script_text.setPlainText(
            '[001 | V1]\nPrimeira voz.\n[002 | V2]\nSegunda voz.')
        self.assertIn('recarrega o modelo', self.panel.engine_note.text())
        self.panel.assignments['V2'].setCurrentIndex(
            self.panel.assignments['V2'].findData(self.profile['id']))
        self.assertIn('mantém o servidor aquecido', self.panel.engine_note.text())
        self.panel.assignments['V2'].setCurrentIndex(
            self.panel.assignments['V2'].findData(second['id']))
        if self.panel.engine.findData('qwen3-tts-local') < 0:
            self.panel.engine.addItem('Original test', 'qwen3-tts-local')
        self.panel.engine.setCurrentIndex(self.panel.engine.findData('qwen3-tts-local'))
        self.assertIn('um único Qwen carregado', self.panel.engine_note.text())
        if self.panel.engine.findData('qwen3-tts-native-q4') < 0:
            self.panel.engine.addItem('Native Q4 test', 'qwen3-tts-native-q4')
        self.panel.engine.setCurrentIndex(
            self.panel.engine.findData('qwen3-tts-native-q4'))
        self.assertIn('um único worker/modelo carregado',
                      self.panel.engine_note.text())
        self.assertIn('embedding de cada personagem',
                      self.panel.engine_note.text())

    def test_same_profile_for_multiple_characters_warns_they_sound_the_same(self):
        self.panel.assignments['V1'].setCurrentIndex(
            self.panel.assignments['V1'].findData(self.profile['id']))
        self.panel.assignments['V2'].setCurrentIndex(
            self.panel.assignments['V2'].findData(self.profile['id']))
        self.panel.script_text.setPlainText(
            '[001 | V1 | Ana]\nPrimeira fala.\n[002 | V2 | Bruno]\nSegunda fala.')
        self.assertIn('V1, V2 usam o mesmo perfil vocal',
                      self.panel.engine_note.text())
        self.assertIn('terão a mesma identidade de voz',
                      self.panel.engine_note.text())

    def test_duplicate_profile_copy_warns_that_reference_identity_is_the_same(self):
        duplicate = self.manager.create(
            'Cópia do mesmo áudio', self.profile['sample_path'], 'portuguese',
            'fala de referência', authorized=True)
        self.assertNotEqual(self.profile['id'], duplicate['id'])
        self.assertEqual(self.profile['sample_sha256'], duplicate['sample_sha256'])
        self.panel.refresh_profiles()
        self.panel.assignments['V1'].setCurrentIndex(
            self.panel.assignments['V1'].findData(self.profile['id']))
        self.panel.assignments['V2'].setCurrentIndex(
            self.panel.assignments['V2'].findData(duplicate['id']))
        self.panel.script_text.setPlainText(
            '[001 | V1 | Ana]\nPrimeira fala.\n[002 | V2 | Bruno]\nSegunda fala.')
        self.assertIn('perfis diferentes, mas a mesma gravação de referência',
                      self.panel.engine_note.text())
        self.assertIn('identidade vocal tende a ser a mesma',
                      self.panel.engine_note.text())


if __name__ == '__main__':
    unittest.main()
