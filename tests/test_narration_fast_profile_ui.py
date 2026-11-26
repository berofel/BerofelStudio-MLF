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

    def test_stale_voice_scan_callbacks_do_not_remove_new_scan(self):
        source = str(Path('voice-reference.wav').resolve())
        newer_task = object()
        with patch('berofel.services.qwen3_tts_local.is_ready',return_value=False), \
             patch('berofel.services.qwen3_native_tts.is_ready',return_value=False), \
             patch('berofel.services.qwen3_purec_tts.is_ready',return_value=False):
            panel = NarrationPanel()
            panel._voice_reference_inspections[source] = newer_task
            panel._voice_reference_inspection_modes[source] = 'report'
            try:
                panel._voice_reference_inspection_cancelled(object(), source)
                panel._voice_reference_inspection_finished(
                    object(), source, {'duration': 1.0}, None)
                self.assertIs(panel._voice_reference_inspections[source], newer_task)
                self.assertEqual(panel._voice_reference_inspection_modes[source], 'report')
            finally:
                panel.close()

    def test_long_narration_segment_action_dispatches_one_selected_span(self):
        import json
        from unittest.mock import Mock
        from berofel.services.narration_service import NarrationRequest
        from berofel.ui import narration_panel as panel_module
        with tempfile.TemporaryDirectory(prefix='bfs_segment_ui_') as folder, \
             patch('berofel.services.qwen3_tts_local.is_ready',return_value=False), \
             patch('berofel.services.qwen3_native_tts.is_ready',return_value=False), \
             patch('berofel.services.qwen3_purec_tts.is_ready',return_value=False):
            audio=Path(folder)/'long.wav'
            audio.write_bytes(b'fixture')
            audio.with_suffix('.segments.json').write_text(json.dumps({
                'schema_version':2,'segments':[
                    {'index':1,'start_seconds':0.,'end_seconds':1.,'spoken_text':'Primeira fala.'},
                    {'index':2,'start_seconds':1.,'end_seconds':2.,'spoken_text':'Segunda fala.'},
                ]}),encoding='utf-8')
            request=NarrationRequest(text='Primeira fala. Segunda fala.',voice='voice.wav',
                language='english',consent=True,engine='qwen3-tts-purec-int8')
            panel=NarrationPanel()
            try:
                callback=Mock()
                panel.on_regenerate_segment=callback
                panel.set_result(str(audio),2.,False,request.engine,
                    source_text=request.text,spoken_text=request.text,request=request)
                self.assertTrue(panel.regenerate_segment.isEnabled())
                with patch.object(panel_module.QInputDialog,'getItem',
                                  return_value=('Trecho 2 · 1.0–2.0s · Segunda fala.',True)):
                    panel._regenerate_segment()
                callback.assert_called_once_with(str(audio),request,1)
            finally:
                panel.close()

    def test_reference_report_shows_spectral_metrics_as_non_identity_diagnostics(self):
        from PySide6.QtWidgets import QMessageBox
        with patch('berofel.services.qwen3_native_tts.is_ready',return_value=False), \
             patch('berofel.services.qwen3_purec_tts.is_ready',return_value=False), \
             patch.object(QMessageBox,'information') as show:
            panel=NarrationPanel()
            try:
                panel._show_voice_reference_report({
                    'duration':4.0,'source_duration':4.0,'selected_start':0.0,
                    'audible_signal_seconds':3.8,'sample_rate':24000,'rms_dbfs':-20.0,
                    'peak_dbfs':-2.0,'silence_fraction':.05,'clipped_fraction':0.0,
                    'warnings':[],'acoustic_features':{},'pitch_features':{},
                    'spectral_features':{'status':'measured',
                        'spectral_centroid_hz_p50':1400.0,
                        'spectral_rolloff85_hz_p50':6200.0,
                        'spectral_flatness_p50':.08,
                        'mfcc_median':[1.0,2.0,3.0,4.0,5.0],
                        'hnr_acf_proxy_db_p50':8.0},
                })
                message=show.call_args.args[2]
                self.assertIn('centroide 1400 Hz',message)
                self.assertIn('MFCCs medianos C0–C4',message)
                self.assertIn('não identificam locutor',message)
            finally:
                panel.close()

    def test_quality_inspection_distinguishes_silent_wav_from_parakeet_result(self):
        with patch('berofel.services.qwen3_native_tts.is_ready',return_value=False), \
             patch('berofel.services.qwen3_purec_tts.is_ready',return_value=False):
            panel=NarrationPanel()
            try:
                panel.set_quality_result({
                    'audio_rms_dbfs':-240.0,'audio_peak_dbfs':-240.0,
                    'audio_clipped_fraction':0.0,'audio_warnings':['WAV silencioso.'],
                    'verification_skipped_reason':'Parakeet não foi iniciado porque o WAV está silencioso.',
                    'word_error_rate':1.0,'character_error_rate':1.0,
                    'recognized_text':'','review_required':True,
                })
                status=panel.status.text()
                self.assertIn('comparação textual não executada',status)
                self.assertIn('Parakeet não foi iniciado',status)
                self.assertNotIn('WER 100.0%',status)
            finally:
                panel.close()

    def test_quality_result_shows_speech_rate_only_with_word_timestamps(self):
        with patch('berofel.services.qwen3_native_tts.is_ready',return_value=False), \
             patch('berofel.services.qwen3_purec_tts.is_ready',return_value=False):
            panel=NarrationPanel()
            try:
                panel.set_quality_result({
                    'audio_rms_dbfs':-20.0,'audio_peak_dbfs':-3.0,
                    'audio_clipped_fraction':0.0,'audio_warnings':[],
                    'word_error_rate':0.0,'character_error_rate':0.0,
                    'recognized_text':'Hoje vamos editar.',
                    'speech_rate':{'wpm_wall':90.0,'wpm_active':130.0,
                                   'word_count':3,
                                   'inter_word_gap_p50_seconds':.2,
                                   'inter_word_gap_p90_seconds':.7,
                                   'gaps_at_least_0_5_seconds':1},
                })
                self.assertIn('90 palavras/min no áudio',panel.status.text())
                self.assertIn('130 palavras/min em fala ativa (3 palavras)',
                              panel.status.text())
                self.assertIn('p50 0.20 s · p90 0.70 s · >0,5 s: 1',
                              panel.status.text())
                panel.set_quality_result({
                    'audio_rms_dbfs':-20.0,'audio_peak_dbfs':-3.0,
                    'audio_clipped_fraction':0.0,'audio_warnings':[],
                    'word_error_rate':0.0,'character_error_rate':0.0,
                    'recognized_text':'Hoje vamos editar.',
                    'speech_rate':{'wpm_wall':None,'wpm_active':None},
                })
                self.assertNotIn('palavras/min',panel.status.text())
            finally:
                panel.close()

    def test_purec_turbo_thread_budget_persists_between_panels(self):
        with patch('berofel.services.qwen3_native_tts.is_ready',return_value=False), \
             patch('berofel.services.qwen3_purec_tts.is_ready',return_value=True):
            panel=NarrationPanel()
            panel.language.setCurrentIndex(panel.language.findData('english'))
            panel.clone_engine.setCurrentIndex(panel.clone_engine.findData('qwen3-tts-purec-mixed'))
            panel.purec_threads.setCurrentIndex(panel.purec_threads.findData(8))
            panel.save_preferences();panel.close()
            restored=NarrationPanel()
            try:
                self.assertEqual(restored.clone_engine.currentData(),'qwen3-tts-purec-mixed')
                self.assertEqual(restored.purec_threads.currentData(),8)
            finally:
                restored.close()

    def test_ptbr_defaults_to_purec_when_available_and_keeps_original_manual(self):
        from PySide6.QtCore import QSettings
        QSettings(QSettings.Format.IniFormat,QSettings.Scope.UserScope,
                  'Berofel','BerofelStudio').remove('narration/clone_engine')
        with patch('berofel.services.qwen3_native_tts.is_ready',return_value=True), \
             patch('berofel.services.qwen3_purec_tts.is_ready',return_value=True):
            panel=NarrationPanel()
            try:
                panel.language.setCurrentIndex(panel.language.findData('portuguese'))
                self.assertEqual(panel.clone_engine.currentData(),'qwen3-tts-purec-mixed')
                self.assertIn('Turbo — Pure C Mixer',panel.clone_engine.currentText())
                panel.language.setCurrentIndex(panel.language.findData('english'))
                panel.clone_engine.setCurrentIndex(
                    panel.clone_engine.findData('qwen3-tts-local'))
                self.assertIn('Manual · Original',panel.clone_engine.currentText())
                panel.language.setCurrentIndex(panel.language.findData('portuguese'))
                self.assertEqual(panel.clone_engine.currentData(),'qwen3-tts-local')
                self.assertFalse(panel.clone_engine.isHidden())
            finally:
                panel.close()

    def test_original_is_preserved_when_it_was_explicitly_saved(self):
        from PySide6.QtCore import QSettings
        settings=QSettings(QSettings.Format.IniFormat,QSettings.Scope.UserScope,
                           'Berofel','BerofelStudio')
        settings.setValue('narration/clone_engine','qwen3-tts-local')
        with patch('berofel.services.qwen3_native_tts.is_ready',return_value=False), \
             patch('berofel.services.qwen3_purec_tts.is_ready',return_value=True):
            panel=NarrationPanel()
            try:
                self.assertEqual(panel.clone_engine.currentData(),'qwen3-tts-local')
                self.assertIn('Manual · Original',panel.clone_engine.currentText())
            finally:
                panel.close()

    def test_original_requires_manual_selection_when_purec_is_not_installed(self):
        from PySide6.QtWidgets import QMessageBox
        from unittest.mock import Mock
        from PySide6.QtCore import QSettings
        QSettings(QSettings.Format.IniFormat,QSettings.Scope.UserScope,
                  'Berofel','BerofelStudio').remove('narration/clone_engine')
        with patch('berofel.services.qwen3_native_tts.is_ready',return_value=False), \
             patch('berofel.services.qwen3_purec_tts.is_ready',return_value=False), \
             patch.object(QMessageBox,'information') as information:
            panel=NarrationPanel()
            try:
                panel.on_generate=Mock()
                self.assertEqual(panel.clone_engine.currentData(),'__select_engine__')
                panel._generate(False)
                panel.on_generate.assert_not_called()
                information.assert_called_once()
                self.assertIn('Original Qwen3-TTS Base permanece disponível como escolha manual',
                              information.call_args.args[2])
            finally:
                panel.close()

    def test_pre_authorized_profile_generates_without_reconfirming(self):
        with tempfile.TemporaryDirectory(prefix='bfs_fast_voice_ui_') as folder:
            root=Path(folder);store=root/'voices';sample=root/'reference.wav'
            sample.write_bytes(b'RIFF'+b'a'*300)
            with patch.dict(os.environ,{'BEROFEL_VOICE_PROFILE_DIR':str(store)}):
                profile=VoiceProfileManager().create('Voz de teste',sample,
                    'portuguese','texto exato da referência',authorized=True,
                    reference_text_reviewed=True)
                panel=NarrationPanel()
                try:
                    index=panel.voice.findData(f'voice-profile:{profile["id"]}')
                    self.assertGreaterEqual(index,0)
                    panel.voice.setCurrentIndex(index)
                    panel.clone_engine.setCurrentIndex(panel.clone_engine.findData('qwen3-tts-local'))
                    panel.set_text('Uma frase nova para narrar rapidamente.')
                    self.assertTrue(panel.reference_text_reviewed.isChecked())
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
                    panel.reference_text_reviewed.setChecked(True)
                    prepared=[]
                    panel.on_prepare_voice=lambda *args:prepared.append(args)
                    panel.update_voice_reference.click()
                    reopened=VoiceProfileManager(store).get(profile['id'])
                    self.assertEqual(reopened['reference_text'],
                                     'texto corrigido da referência')
                    self.assertTrue(reopened['reference_text_reviewed'])
                    self.assertTrue(panel.reference_text_reviewed.isChecked())
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

    def test_ptbr_original_requires_transcript_but_purec_is_explicit_xvector(self):
        from PySide6.QtWidgets import QMessageBox
        with tempfile.TemporaryDirectory(prefix='bfs_xvector_voice_ui_') as folder:
            sample=Path(folder)/'reference.wav'
            sample.write_bytes(b'RIFF'+b'a'*300)
            panel=NarrationPanel()
            try:
                if panel.clone_engine.findData('qwen3-tts-purec-int8') < 0:
                    panel.clone_engine.addItem('Equilibrado Pure C INT8',
                                               'qwen3-tts-purec-int8')
                panel.voice.setCurrentIndex(panel.voice.findData('__custom__'))
                panel.clone_engine.setCurrentIndex(panel.clone_engine.findData('qwen3-tts-local'))
                self.assertFalse(panel.reference_text_reviewed.isHidden())
                panel.sample_path.setText(str(sample))
                panel.reference_text.clear()
                panel.authorized.setChecked(True)
                panel.set_text('Frase de teste sem transcrição da referência.')
                captured=[]
                panel.on_generate=lambda request,insert:captured.append((request,insert))
                with patch.object(QMessageBox,'warning') as warning:
                    panel._generate(False)
                self.assertEqual(captured,[])
                warning.assert_called_once()
                self.assertIn('transcrição exata',warning.call_args.args[2])
                panel.reference_text.setText('transcrição revisada da gravação')
                panel.clone_engine.setCurrentIndex(
                    panel.clone_engine.findData('qwen3-tts-purec-int8'))
                panel.authorized.setChecked(True)
                with patch.object(QMessageBox,'warning') as warning:
                    panel._generate(False)
                self.assertEqual(len(captured),1)
                request,insert=captured.pop()
                self.assertEqual(request.engine,'qwen3-tts-purec-int8')
                self.assertEqual(request.reference_text,'')
                self.assertFalse(request.reference_text_reviewed)
                self.assertFalse(insert)
                warning.assert_not_called()
                panel.clone_engine.setCurrentIndex(
                    panel.clone_engine.findData('qwen3-tts-local'))
                self.assertFalse(panel.reference_text_reviewed.isHidden())
                panel.authorized.setChecked(True)
                with patch.object(QMessageBox,'warning') as warning:
                    panel._generate(False)
                self.assertEqual(captured,[])
                warning.assert_called_once()
                self.assertIn('conferi',warning.call_args.args[2].lower())
                panel.reference_text_reviewed.setChecked(True)
                panel._generate(False)
                self.assertEqual(len(captured),1)
                request,insert=captured[0]
                self.assertFalse(insert)
                self.assertEqual(request.reference_text,'transcrição revisada da gravação')
                self.assertEqual(request.engine,'qwen3-tts-local')
                self.assertTrue(request.consent)
            finally:
                panel.close()

    def test_purec_emotional_reference_is_explicit_opt_in_and_uses_reviewed_text(self):
        from PySide6.QtWidgets import QMessageBox
        with tempfile.TemporaryDirectory(prefix='bfs_emotion_ui_') as folder:
            sample=Path(folder)/'authorized.wav'
            sample.write_bytes(b'RIFF'+b'a'*300)
            panel=NarrationPanel()
            try:
                engine='qwen3-tts-purec-int8'
                if panel.clone_engine.findData(engine)<0:
                    panel.clone_engine.addItem('Equilibrado Pure C INT8',engine)
                panel.voice.setCurrentIndex(panel.voice.findData('__custom__'))
                panel.clone_engine.setCurrentIndex(panel.clone_engine.findData(engine))
                panel.sample_path.setText(str(sample))
                panel.reference_text.setText('Transcrição revisada pelo Parakeet TDT v3.')
                panel.reference_text_reviewed.setChecked(True)
                panel.authorized.setChecked(True)
                panel.set_text('Uma frase de teste para síntese.')
                self.assertFalse(panel.use_emotional_reference.isChecked())
                captured=[]
                panel.on_generate=lambda request,insert:captured.append((request,insert))
                with patch.object(QMessageBox,'warning') as warning:
                    panel._generate(False)
                self.assertEqual(len(captured),1)
                self.assertFalse(captured[-1][0].emotion_by_example)
                panel.use_emotional_reference.setChecked(True)
                with patch.object(QMessageBox,'warning') as warning:
                    panel._generate(False)
                self.assertEqual(len(captured),2)
                request,insert=captured[-1]
                self.assertTrue(request.emotion_by_example)
                self.assertEqual(request.reference_text,
                                 'Transcrição revisada pelo Parakeet TDT v3.')
                self.assertTrue(request.reference_text_reviewed)
                self.assertFalse(insert)
                warning.assert_not_called()
            finally:
                panel.close()

    def test_emotional_reference_control_is_hidden_when_installed_binary_lacks_capability(self):
        panel=NarrationPanel()
        try:
            engine='qwen3-tts-purec-int8'
            if panel.clone_engine.findData(engine)<0:
                panel.clone_engine.addItem('Equilibrado Pure C INT8',engine)
            panel.voice.setCurrentIndex(panel.voice.findData('__custom__'))
            panel.clone_engine.setCurrentIndex(panel.clone_engine.findData(engine))
            with patch('berofel.services.qwen3_purec_tts.supports_emotion_by_example',
                       return_value=False):
                panel._update_custom()
            self.assertTrue(panel.use_emotional_reference.isHidden())
            self.assertIn('indisponível',panel.license_note.text())
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
                inspect.assert_called_once()
                self.assertTrue(os.path.samefile(inspect.call_args.args[0],source))
                self.assertEqual(inspect.call_args.args[1],'warning')
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
                inspect.assert_called_once()
                self.assertTrue(os.path.samefile(inspect.call_args.args[0],source))
                self.assertEqual(inspect.call_args.args[1],'warning')
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

    def test_identity_diagnostic_is_manual_and_only_available_for_authorized_purec(self):
        import wave
        with tempfile.TemporaryDirectory(prefix='bfs_identity_ui_') as folder:
            reference=Path(folder)/'reference.wav'
            generated=Path(folder)/'generated.wav'
            for path in (reference,generated):
                with wave.open(str(path),'wb') as wav:
                    wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(24000)
                    wav.writeframes(b'\x01\x00'*2400)
            panel=NarrationPanel()
            try:
                panel.set_result(str(generated),.1,False,'qwen3-tts-purec-int8',
                    6,'Generated',source_text='texto',spoken_text='texto',
                    voice_reference_path=str(reference),voice_consent=True)
                calls=[]
                panel.on_compare_identity=lambda *args:calls.append(args)
                self.assertTrue(panel.compare_identity.isEnabled())
                self.assertEqual(panel._player.playbackState().value,0)
                panel.compare_identity.click()
                self.assertEqual(calls,[(
                    str(generated),str(reference),'qwen3-tts-purec-int8',6,True)])
                self.assertEqual(panel._player.playbackState().value,0)
                panel.set_result(str(generated),.1,False,'qwen3-tts-local',
                    source_text='texto',voice_reference_path=str(reference),voice_consent=True)
                self.assertFalse(panel.compare_identity.isEnabled())
            finally:
                panel.close()

    def test_asr_reference_draft_requires_review_and_text_changes_invalidate_it(self):
        from PySide6.QtWidgets import QMessageBox
        with tempfile.TemporaryDirectory(prefix='bfs_asr_review_gate_') as folder:
            sample=Path(folder)/'reference.wav';sample.write_bytes(b'RIFF'+b'a'*300)
            panel=NarrationPanel()
            try:
                panel.voice.setCurrentIndex(panel.voice.findData('__custom__'))
                panel.clone_engine.setCurrentIndex(panel.clone_engine.findData('qwen3-tts-local'))
                panel.sample_path.setText(str(sample))
                panel.authorized.setChecked(True)
                panel.text.setPlainText('Uma frase diferente da referência.')
                panel.set_reference_transcript({'text':'Rascunho do Parakeet.',
                    'reference_window':{'start':2.0,'duration':12.0},
                    'mean_word_confidence':.64})
                self.assertFalse(panel.reference_text_reviewed.isChecked())
                captured=[];panel.on_generate=lambda request,insert:captured.append(request)
                with patch.object(QMessageBox,'warning') as warning:
                    panel._generate(False)
                self.assertEqual(captured,[])
                warning.assert_called_once()
                panel.reference_text_reviewed.setChecked(True)
                panel._generate(False)
                self.assertEqual(len(captured),1)
                panel.reference_text.setText('Texto corrigido pelo usuário.')
                self.assertFalse(panel.reference_text_reviewed.isChecked())
                panel.reference_text_reviewed.setChecked(True)
                panel._generate(False)
                self.assertEqual(captured[-1].reference_text_reviewed,True)
                sample.write_bytes(b'RIFF'+b'changed authorized recording')
                with patch.object(QMessageBox,'warning') as warning:
                    panel._generate(False)
                self.assertEqual(len(captured),2)
                warning.assert_called_once()
                self.assertFalse(panel.reference_text_reviewed.isChecked())
                replacement=Path(folder)/'different_reference.wav'
                replacement.write_bytes(b'RIFF'+b'b'*300)
                panel.reference_text_reviewed.setChecked(True)
                panel.sample_path.setText(str(replacement))
                self.assertFalse(panel.reference_text_reviewed.isChecked())
                with patch.object(QMessageBox,'warning') as warning:
                    panel._generate(False)
                self.assertEqual(len(captured),2)
                warning.assert_called_once()
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
                if panel.clone_engine.findData('qwen3-tts-purec-int8') < 0:
                    panel.clone_engine.addItem('Equilibrado Pure C INT8',
                                               'qwen3-tts-purec-int8')
                with patch('berofel.services.audio_reference.inspect_voice_reference',
                           return_value=report):
                    panel.voice.setCurrentIndex(panel.voice.findData('__custom__'))
                    panel.sample_path.setText(str(sample))
                    panel.language.setCurrentIndex(panel.language.findData('english'))
                    panel.reference_text.setText('transcrição literal da amostra')
                    panel.clone_engine.setCurrentIndex(
                        panel.clone_engine.findData('qwen3-tts-purec-int8'))
                    panel._update_custom()
                    purec_note=panel.license_note.text()
                    self.assertIn('ignora a transcrição',purec_note)
                    self.assertIn('varrida por inteiro',purec_note)
                    panel.reference_text.setText('uma transcrição nova')
                    self.assertIn('ignora a transcrição',panel.license_note.text())
                    panel.language.setCurrentIndex(panel.language.findData('portuguese'))
                    self.assertEqual(panel.clone_engine.currentData(),'qwen3-tts-purec-int8')
                    self.assertIn('x-vector',panel.license_note.text())
                    panel.clone_engine.setCurrentIndex(panel.clone_engine.findData('qwen3-tts-local'))
                    original_note=panel.license_note.text()
                    self.assertIn('envia o áudio e a transcrição literal',original_note)
                    self.assertNotIn('ignora a transcrição',original_note)
                    self.assertIn('sem token separado de sotaque',original_note)
            finally:
                panel.close()


if __name__=='__main__':unittest.main()
