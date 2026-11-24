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
                    panel.clone_engine.setCurrentIndex(panel.clone_engine.findData('qwen3-tts-local'))
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

    def test_saved_profile_reference_transcript_can_be_corrected_in_place(self):
        with tempfile.TemporaryDirectory(prefix='bfs_profile_transcript_ui_') as folder:
            root=Path(folder);store=root/'voices';sample=root/'reference.wav'
            original=b'RIFF'+b'private voice bytes'*20;sample.write_bytes(original)
            with patch.dict(os.environ,{'BEROFEL_VOICE_PROFILE_DIR':str(store)}):
                profile=VoiceProfileManager().create('Voz local',sample,'portuguese',
                    'texto incorreto',authorized=True)
                private=Path(profile['sample_path']);private_bytes=private.read_bytes()
                panel=NarrationPanel()
                try:
                    index=panel.voice.findData(f'voice-profile:{profile["id"]}')
                    self.assertGreaterEqual(index,0)
                    panel.voice.setCurrentIndex(index)
                    original_engine=panel.clone_engine.findData('qwen3-tts-local')
                    self.assertGreaterEqual(original_engine,0)
                    panel.clone_engine.setCurrentIndex(original_engine)
                    self.assertFalse(panel.update_voice_reference.isHidden())
                    panel.reference_text.setText('  texto   corrigido da referência  ')
                    prepared=[]
                    panel.on_prepare_voice=lambda *args:prepared.append(args)
                    panel.update_voice_reference.click()
                    reopened=VoiceProfileManager(store).get(profile['id'])
                    self.assertEqual(reopened['reference_text'],
                                     'texto corrigido da referência')
                    self.assertTrue(reopened['authorized'])
                    self.assertEqual(Path(reopened['sample_path']).read_bytes(),private_bytes)
                    self.assertEqual(sample.read_bytes(),original)
                    self.assertEqual(len(prepared),1)
                    self.assertEqual(prepared[0][1],reopened['reference_text'])
                finally:
                    panel.close()

    def test_selecting_saved_voice_warns_once_for_cached_low_quality_reference(self):
        from PySide6.QtWidgets import QMessageBox
        with tempfile.TemporaryDirectory(prefix='bfs_saved_voice_quality_ui_') as folder:
            root=Path(folder);store=root/'voices';sample=root/'reference.wav'
            sample.write_bytes(b'RIFF'+b'authorized sample bytes'*20)
            with patch.dict(os.environ,{'BEROFEL_VOICE_PROFILE_DIR':str(store)}):
                profile=VoiceProfileManager().create('Voz com pausas',sample,
                    'portuguese','texto da referência',authorized=True)
                panel=NarrationPanel()
                try:
                    index=panel.voice.findData(f'voice-profile:{profile["id"]}')
                    self.assertGreaterEqual(index,0)
                    panel.voice.setCurrentIndex(index)
                    private=Path(profile['sample_path']);stat=private.stat()
                    key=(str(private.resolve()),stat.st_size,stat.st_mtime_ns)
                    panel._voice_reference_quality_cache[key]={
                        'warnings':['Mais de 50% do trecho está quase silencioso.'],
                        'source_duration':6.0,'duration':6.0,'selected_start':0.0,
                        'audible_signal_seconds':2.7,'silence_fraction':.55}
                    with (patch.object(QMessageBox,'warning') as warning,
                          patch.object(panel,'_start_voice_reference_inspection') as inspect):
                        panel.voice.activated.emit(index)
                        panel.voice.activated.emit(index)
                    warning.assert_called_once()
                    self.assertIn('quase silencioso',warning.call_args.args[2])
                    inspect.assert_not_called()
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
                panel.clone_engine.setCurrentIndex(panel.clone_engine.findData('qwen3-tts-local'))
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
                      patch.object(panel,'_start_voice_reference_inspection') as inspect,
                      patch.object(QMessageBox,'warning') as warning):
                    panel._choose_sample()
                self.assertEqual(panel.sample_path.text(),str(source))
                inspect.assert_called_once_with(str(source),'warning')
                self.assertEqual(warning.call_count,0)
                self.assertEqual(source.read_bytes(),original)
            finally:
                panel.close()

    def test_choosing_reference_with_moderate_silence_warns_consistently(self):
        from PySide6.QtWidgets import QFileDialog,QMessageBox
        report={'warnings':[],'silence_fraction':.35,
                'audible_signal_seconds':9.6}
        with tempfile.TemporaryDirectory(prefix='bfs_voice_moderate_silence_') as folder:
            source=Path(folder)/'reference.wav';source.write_bytes(b'RIFF'+b'a'*300)
            panel=NarrationPanel()
            try:
                with (patch.object(QFileDialog,'getOpenFileName',return_value=(str(source),'Audio')),
                      patch.object(panel,'_start_voice_reference_inspection') as inspect,
                      patch.object(QMessageBox,'warning') as warning):
                    panel._choose_sample()
                inspect.assert_called_once_with(str(source),'warning')
                self.assertEqual(warning.call_count,0)
            finally:
                panel.close()

    def test_voice_reference_scan_runs_off_ui_thread_and_reports_selected_window(self):
        import time
        from PySide6.QtWidgets import QMessageBox
        report={'warnings':[],'source_duration':3600.0,'duration':15.0,
                'selected_start':1840.0,'active_fraction':.95,
                'audible_signal_seconds':14.2,'sample_rate':24000,
                'rms_dbfs':-21.0,'peak_dbfs':-3.0,
                'silence_fraction':.05,'clipped_fraction':0.0}
        with tempfile.TemporaryDirectory(prefix='bfs_reference_scan_thread_') as folder:
            source=Path(folder)/'long.wav';source.write_bytes(b'local test source')
            panel=NarrationPanel();panel.sample_path.setText(str(source))
            try:
                with patch('berofel.services.audio_reference.inspect_voice_reference',
                           return_value=report), \
                     patch.object(QMessageBox,'information') as info:
                    panel._start_voice_reference_inspection(str(source),'report')
                    deadline=time.monotonic()+3
                    while time.monotonic()<deadline and panel._voice_reference_inspections:
                        self.app.processEvents();time.sleep(.01)
                    self.app.processEvents()
                self.assertEqual(info.call_count,1)
                self.assertIn('3600.00 s',info.call_args.args[2])
                self.assertIn('1840.00 s',info.call_args.args[2])
            finally:
                panel.close()

    def test_original_qwen_result_shows_used_reference_window_and_mode(self):
        panel=NarrationPanel()
        try:
            panel.set_result('clone.wav',4.0,False,'qwen3-tts-local',title='Clone',
                reference_window={'start':37.5,'duration':12.0},
                conditioning_mode='audio+transcript')
            self.assertIn('Referência usada: 37.5–49.5s',panel.status.text())
            self.assertIn('áudio + transcrição',panel.status.text())
        finally:
            panel.close()

    def test_fast_clone_result_discloses_embedding_only_conditioning(self):
        panel=NarrationPanel()
        try:
            panel.set_result('fast-clone.wav',4.0,False,'qwen3-tts-purec-int8',
                title='Fast clone',conditioning_mode='speaker-embedding-only')
            self.assertIn('não utiliza a transcrição',panel.status.text())
        finally:
            panel.close()

    def test_clone_guidance_explains_purec_reference_limit_and_portuguese_dialect(self):
        with tempfile.TemporaryDirectory(prefix='bfs_clone_guidance_ui_') as folder:
            sample=Path(folder)/'reference.wav';sample.write_bytes(b'RIFF'+b'a'*200)
            report={'warnings':[],'duration':12.0,'sample_rate':24000,
                    'rms_dbfs':-20.0,'peak_dbfs':-3.0,
                    'silence_fraction':.35,'clipped_fraction':0.0,
                    'audible_signal_seconds':9.6}
            panel=NarrationPanel()
            try:
                with patch('berofel.services.audio_reference.inspect_voice_reference',
                           return_value=report):
                    panel.voice.setCurrentIndex(panel.voice.findData('__custom__'))
                    panel.sample_path.setText(str(sample))
                    panel.language.setCurrentIndex(panel.language.findData('portuguese'))
                    panel.reference_text.setText('transcrição literal da amostra')
                    panel.clone_engine.setCurrentIndex(
                        panel.clone_engine.findData('qwen3-tts-purec-int8'))
                    panel._update_custom()
                    purec_note=panel.license_note.text()
                    self.assertIn('não envia a transcrição',purec_note)
                    self.assertIn('não oferece um seletor separado de sotaque',purec_note)
                    self.assertIn('Original Qwen3-TTS Base',purec_note)
                    self.assertIn('varrida por inteiro',purec_note)
                    panel.reference_text.setText('uma transcrição nova')
                    self.assertIn('não envia a transcrição',panel.license_note.text())
                    self.assertEqual(panel.license_note.text().count(
                        'PT-BR usa o idioma Português'),1)

                    panel.clone_engine.setCurrentIndex(
                        panel.clone_engine.findData('qwen3-tts-local'))
                    original_note=panel.license_note.text()
                    self.assertIn('envia o áudio e a transcrição literal',original_note)
                    self.assertNotIn('não envia a transcrição',original_note)
                    self.assertEqual(original_note.count('PT-BR usa o idioma Português'),1)
            finally:
                panel.close()


if __name__=='__main__':unittest.main()
