"""Fast narration selects an already authorized local voice profile."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')

try:
    from PySide6.QtWidgets import QApplication
    from berofel.services.voice_profiles import VoiceProfileManager
    from berofel.ui.narration_panel import NarrationPanel
except ImportError:
    QApplication=None


@unittest.skipUnless(QApplication is not None,'PySide6 indisponível neste ambiente')
class FastNarrationProfileUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtCore import QSettings
        cls.original_settings_dir=Path(QSettings(
            QSettings.Format.IniFormat,QSettings.Scope.UserScope,
            'Berofel','BerofelStudio').fileName()).parent
        cls.settings_dir=tempfile.TemporaryDirectory(prefix='bfs_fast_ui_settings_')
        QSettings.setPath(QSettings.Format.IniFormat,QSettings.Scope.UserScope,
                          cls.settings_dir.name)
        cls.app=QApplication.instance() or QApplication([])

    @classmethod
    def tearDownClass(cls):
        from PySide6.QtCore import QSettings
        QSettings.setPath(QSettings.Format.IniFormat,QSettings.Scope.UserScope,
                          str(cls.original_settings_dir))
        cls.settings_dir.cleanup()

    def test_panel_preferences_are_isolated_from_real_user_settings(self):
        from PySide6.QtCore import QSettings
        settings=QSettings(QSettings.Format.IniFormat,QSettings.Scope.UserScope,
                           'Berofel','BerofelStudio')
        self.assertTrue(Path(settings.fileName()).is_relative_to(
            Path(self.settings_dir.name)))

    def test_purec_turbo_thread_budget_persists_between_panels(self):
        with patch('berofel.services.qwen3_native_tts.is_ready',return_value=False), \
             patch('berofel.services.qwen3_purec_tts.is_ready',return_value=True):
            panel=NarrationPanel()
            panel.clone_engine.setCurrentIndex(panel.clone_engine.findData('qwen3-tts-purec-mixed'))
            panel.purec_threads.setCurrentIndex(panel.purec_threads.findData(8))
            panel.save_preferences();panel.close()
            restored=NarrationPanel()
            try:
                self.assertEqual(restored.clone_engine.currentData(),'qwen3-tts-purec-mixed')
                self.assertEqual(restored.purec_threads.currentData(),8)
            finally:
                restored.close()

    def test_pre_authorized_profile_generates_without_reconfirming(self):
        with tempfile.TemporaryDirectory(prefix='bfs_fast_voice_ui_') as folder:
            root=Path(folder);store=root/'voices';sample=root/'reference.wav'
            sample.write_bytes(b'RIFF'+b'a'*300)
            with patch.dict(os.environ,{'BEROFEL_VOICE_PROFILE_DIR':str(store)}):
                profile=VoiceProfileManager().create('Voz de teste',sample,
                    'portuguese','texto exato da referência',authorized=True)
                panel=NarrationPanel()
                try:
                    index=panel.voice.findData(f'voice-profile:{profile["id"]}')
                    self.assertGreaterEqual(index,0)
                    panel.voice.setCurrentIndex(index)
                    panel.set_text('Uma frase nova para narrar rapidamente.')
                    self.assertTrue(panel.authorized.isChecked())
                    self.assertFalse(panel.authorized.isEnabled())
                    captured=[]
                    panel.on_generate=lambda request,insert:captured.append((request,insert))
                    panel._generate(True)
                    self.assertEqual(len(captured),1)
                    request,insert=captured[0]
                    self.assertTrue(insert)
                    self.assertTrue(request.consent)
                    self.assertEqual(request.engine,'qwen3-tts-local')
                    self.assertEqual(Path(request.voice).read_bytes(),sample.read_bytes())
                finally:
                    panel.close()

    def test_custom_clone_can_generate_without_reference_transcript(self):
        """Qwen Base supports x-vector-only cloning when ref_text is omitted."""
        with tempfile.TemporaryDirectory(prefix='bfs_xvector_voice_ui_') as folder:
            sample=Path(folder)/'reference.wav'
            sample.write_bytes(b'RIFF'+b'a'*300)
            panel=NarrationPanel()
            try:
                panel.voice.setCurrentIndex(panel.voice.findData('__custom__'))
                panel.sample_path.setText(str(sample))
                panel.reference_text.clear()
                panel.authorized.setChecked(True)
                panel.set_text('Frase de teste sem transcrição da referência.')
                captured=[]
                panel.on_generate=lambda request,insert:captured.append((request,insert))
                panel._generate(False)
                self.assertEqual(len(captured),1)
                request,insert=captured[0]
                self.assertFalse(insert)
                self.assertEqual(request.reference_text,'')
                self.assertEqual(request.engine,'qwen3-tts-local')
                self.assertTrue(request.consent)
            finally:
                panel.close()

    def test_choosing_low_quality_reference_warns_without_editing_the_source(self):
        from PySide6.QtWidgets import QFileDialog,QMessageBox
        report={'warnings':['Mais de 50% do trecho está quase silencioso; escolha uma fala mais contínua.'],
                'silence_fraction':.553}
        with tempfile.TemporaryDirectory(prefix='bfs_voice_warning_ui_') as folder:
            source=Path(folder)/'reference.mp3';source.write_bytes(b'original audio bytes')
            original=source.read_bytes();panel=NarrationPanel()
            try:
                with (patch.object(QFileDialog,'getOpenFileName',return_value=(str(source),'Audio')),
                      patch('berofel.services.audio_reference.inspect_voice_reference',
                            return_value=report),
                      patch.object(QMessageBox,'warning') as warning):
                    panel._choose_sample()
                self.assertEqual(panel.sample_path.text(),str(source))
                self.assertEqual(warning.call_count,1)
                self.assertIn('55%',warning.call_args.args[2])
                self.assertEqual(source.read_bytes(),original)
            finally:
                panel.close()


if __name__=='__main__':unittest.main()
