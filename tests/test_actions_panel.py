"""Verificação Qt do painel real, executada no Windows com PySide6 instalado."""
import os
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from PySide6.QtCore import QThreadPool, QPoint, QPointF, QSettings, QEventLoop, QTimer, Qt
    from PySide6.QtGui import QFontDatabase, QWheelEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QLabel,
                                   QMessageBox, QToolButton, QAbstractScrollArea)
    from berofel import __version__
    from berofel.ui.actions_panel import ActionsPanel, parse_timecode,format_timecode
    from berofel.ui.clipper_dialog import ClipperDialog
    from berofel.ui.narration_panel import NarrationPanel
    from berofel.ui.window import MainWindow, SuggestionsDialog
    from berofel.core.project import Project,Clip
    from berofel.core.motion import put_keyframe
    from berofel.services.project_recovery import write_autosave_snapshot
except ImportError:
    QApplication=None


def _snapshot_narration_settings(settings):
    keys=('narration/voice','narration/clone_engine','narration/purec_threads',
          'narration/sample_path','narration/reference_text','narration/draft',
          'narration/title','narration/language')
    return {key:(settings.contains(key),settings.value(key)) for key in keys}


def _restore_narration_settings(settings,snapshot):
    for key,(present,value) in snapshot.items():
        if present:settings.setValue(key,value)
        else:settings.remove(key)
    settings.sync()


@unittest.skipUnless(QApplication is not None,'PySide6 não instalado neste ambiente')
class ActionsUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        cls.app=QApplication.instance() or QApplication([])
        cls.original_settings_dir=Path(QSettings(
            QSettings.Format.IniFormat,QSettings.Scope.UserScope,
            'Berofel','BerofelStudio').fileName()).parent
        cls.original_settings_format=QSettings.defaultFormat()
        cls.settings_dir=tempfile.TemporaryDirectory()
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat,QSettings.Scope.UserScope,cls.settings_dir.name)

    def setUp(self):
        settings=QSettings(QSettings.Format.IniFormat,QSettings.Scope.UserScope,
                            'Berofel','BerofelStudio')
        settings.clear()
        settings.sync()

    @classmethod
    def tearDownClass(cls):
        QSettings.setPath(QSettings.Format.IniFormat,QSettings.Scope.UserScope,
                          str(cls.original_settings_dir))
        QSettings.setDefaultFormat(cls.original_settings_format)
        cls.settings_dir.cleanup()

    def test_mouse_wheel_scroll_does_not_change_unfocused_controls(self):
        from PySide6.QtWidgets import QScrollArea, QVBoxLayout, QWidget
        from berofel.ui.wheel_controls import (WheelGuardComboBox,
            WheelGuardDoubleSpinBox, WheelGuardSlider)
        area=QScrollArea();area.resize(260,120)
        content=QWidget();layout=QVBoxLayout(content)
        combo=WheelGuardComboBox();combo.addItems(['Português','English','Español'])
        spin=WheelGuardDoubleSpinBox();spin.setRange(0,10);spin.setValue(5)
        slider=WheelGuardSlider(Qt.Orientation.Horizontal);slider.setRange(0,10);slider.setValue(5)
        layout.addWidget(combo);layout.addWidget(spin);layout.addWidget(slider)
        for _ in range(12):layout.addWidget(QLabel('rolagem'))
        area.setWidget(content);area.show();self.app.processEvents()
        area.setFocus();combo.clearFocus();spin.clearFocus();slider.clearFocus()
        self.assertFalse(combo.hasFocus())
        area.verticalScrollBar().setValue(0)
        event=QWheelEvent(QPointF(10,10),QPointF(10,10),QPoint(0,0),QPoint(0,-120),
            Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.ScrollUpdate,False)
        before_index=combo.currentIndex()
        before_spin=spin.value();before_slider=slider.value()
        QApplication.sendEvent(combo,event)
        self.assertEqual(combo.currentIndex(),before_index)
        QApplication.sendEvent(spin,QWheelEvent(QPointF(10,10),QPointF(10,10),
            QPoint(0,0),QPoint(0,-120),Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.ScrollUpdate,False))
        QApplication.sendEvent(slider,QWheelEvent(QPointF(10,10),QPointF(10,10),
            QPoint(0,0),QPoint(0,-120),Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.ScrollUpdate,False))
        self.assertEqual((combo.currentIndex(),spin.value(),slider.value()),
                         (before_index,before_spin,before_slider))
        self.assertGreater(area.verticalScrollBar().value(),0,
                           'A roda deve continuar rolando o painel sob o controle.')
        combo.setFocus();self.app.processEvents()
        QApplication.sendEvent(combo,QWheelEvent(QPointF(10,10),QPointF(10,10),
            QPoint(0,0),QPoint(0,-120),Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.ScrollUpdate,False))
        QApplication.sendEvent(spin,QWheelEvent(QPointF(10,10),QPointF(10,10),
            QPoint(0,0),QPoint(0,-120),Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.ScrollUpdate,False))
        QApplication.sendEvent(slider,QWheelEvent(QPointF(10,10),QPointF(10,10),
            QPoint(0,0),QPoint(0,-120),Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.ScrollUpdate,False))
        self.assertEqual((combo.currentIndex(),spin.value(),slider.value()),
                         (before_index,before_spin,before_slider),
                         'Foco no controle não deve habilitar alteração pela roda.')
        area.close()

    def test_timecode_and_scope_ui(self):
        self.assertEqual(parse_timecode('01:02:03.500'),3723.5)
        self.assertEqual(parse_timecode('00:12.5'),12.5)
        self.assertEqual(format_timecode(3723.5),'01:02:03.500')
        panel=ActionsPanel()
        project=Project()
        a=Clip(source='fake.mp4',start=0,end=60,track_id=project.tracks[0].id)
        project.add_clip(a)
        panel.set_context(project,[a.id],a.track_id,5)
        self.assertIn('1 bloco(s)',panel.summary.text())
        panel.scope.setCurrentIndex(3)
        panel.start.setText('00:00:02')
        panel.end.setText('00:00:05')
        self.assertIn('00:00:03',panel.summary.text())
        panel.close()

    def test_clipper_button_opens_callback_and_dialog_keeps_options_explicit(self):
        panel=ActionsPanel()
        calls=[]
        panel.on_clipper=lambda:calls.append('open')
        panel.clipper_button.click()
        self.assertEqual(calls,['open'])
        dialog=ClipperDialog()
        self.assertEqual(dialog.options().min_seconds,15.)
        self.assertEqual(dialog.options().max_seconds,60.)
        candidate={'id':'candidate-1','clip_id':'clip-1','title':'Teste',
            'source_start':1.,'source_end':8.,'duration':7.,'score':74.,
            'text':'Uma fala de teste.','reasons':['Fecha em limite de frase'],
            'warnings':[],'events':[],'audio_available':False,'checked':False,
            'start_ms':1000,'end_ms':8000,'min_duration_ms':3000,'max_duration_ms':10000,
            'start_choices':[{'ms':900,'word':'A'}, {'ms':1000,'word':'Uma'},
                             {'ms':1100,'word':'fala'}],
            'end_choices':[{'ms':7900,'word':'teste'}, {'ms':8000,'word':'teste.'},
                           {'ms':8100,'word':'final'}],
            'word_spans':[{'start_ms':900,'end_ms':1000,'text':'A'},
                          {'start_ms':1000,'end_ms':2000,'text':'Uma'},
                          {'start_ms':2000,'end_ms':3000,'text':'fala'},
                          {'start_ms':3000,'end_ms':4500,'text':'de'},
                          {'start_ms':4500,'end_ms':6000,'text':'teste.'}]}
        dialog.set_results({'candidates':[candidate],'events':[],'stats':{}})
        self.assertEqual(dialog.selected_candidates(),[])
        dialog.select_all.click()
        self.assertEqual(dialog.selected_candidates()[0]['id'],'candidate-1')
        dialog.start_boundary.setCurrentIndex(dialog.start_boundary.findData(1100))
        adjusted=dialog.selected_candidates()[0]
        self.assertEqual(adjusted['source_start'],1.1)
        self.assertTrue(adjusted['score_adjusted'])
        self.assertTrue(any('nota original não foi recalculada' in warning
                            for warning in adjusted['warnings']))
        previews=[];dialog.preview_requested.connect(previews.append)
        dialog.table.selectRow(0);dialog.preview_button.click()
        self.assertEqual(previews[0]['id'],'candidate-1')
        dialog.close();panel.close()

    def test_clipador_inserts_selected_source_interval_non_destructively_with_undo(self):
        import wave
        from berofel.core.project import Clip
        win=MainWindow()
        with tempfile.TemporaryDirectory(prefix='bfs_clipper_insert_') as folder:
            source=Path(folder)/'source.wav'
            with wave.open(str(source),'wb') as audio:
                audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(16000)
                audio.writeframes(b'\x00\x00'*16000*10)
            original=win.project.add_clip(Clip(str(source),0.,10.,kind='audio',
                track_id=win.project.tracks[-1].id,timeline_start=2.))
            original_bounds=(original.start,original.end,original.timeline_start)
            win.refresh([original.id])
            dialog=ClipperDialog(win)
            candidate={'clip_id':original.id,'title':original.title,
                'source_start':2.,'source_end':5.,'score':80.}
            win.insert_clipper_candidates(dialog,[candidate])
            self.assertEqual(len(win.project.clips),2)
            inserted=next(clip for clip in win.project.clips if clip.id!=original.id)
            self.assertEqual((original.start,original.end,original.timeline_start),original_bounds)
            self.assertEqual((inserted.start,inserted.end),(2.,5.))
            self.assertAlmostEqual(inserted.timeline_start,12.)
            self.assertEqual(inserted.generated_by,'clipper')
            win.undo()
            self.assertEqual(len(win.project.clips),1)
            dialog.close();win.close()

    def test_clipador_event_markers_map_source_time_to_timeline_and_undo(self):
        from berofel.core.project import Clip
        win=MainWindow()
        with tempfile.TemporaryDirectory(prefix='bfs_clipper_marker_') as folder:
            source=Path(folder)/'source.wav';source.write_bytes(b'fake')
            clip=win.project.add_clip(Clip(str(source),10.,20.,kind='audio',speed=2.,
                track_id=win.project.tracks[-1].id,timeline_start=3.))
            win.refresh([clip.id])
            dialog=ClipperDialog(win)
            win.mark_clipper_events(dialog,[{'clip_id':clip.id,'start_ms':12000,
                                             'rise_db':8.5}])
            self.assertEqual(len(win.project.markers),1)
            self.assertAlmostEqual(win.project.markers[0]['time'],4.)
            self.assertIn('energia +8.5 dB',win.project.markers[0]['label'])
            win.undo()
            self.assertEqual(win.project.markers,[])
            dialog.close();win.close()

    def test_clipador_ui_reuses_saved_transcript_and_dispatches_background_task(self):
        from unittest.mock import patch
        from berofel.core.project import Clip
        win=MainWindow()
        with tempfile.TemporaryDirectory(prefix='bfs_clipper_ui_flow_') as folder:
            source=Path(folder)/'talk.wav'
            source.write_bytes(b'audio fixture')
            clip=win.project.add_clip(Clip(str(source),0.,6.,kind='audio',
                track_id=win.project.tracks[-1].id))
            from tests.test_clipper import transcript
            words=transcript(source,count=48,step=.1)
            win.project.transcripts=words
            win.refresh([clip.id])
            win.open_clipper()
            dialog=win._clipper_dialog
            self.assertIsNotNone(dialog)
            dialog.minimum.setValue(3);dialog.maximum.setValue(5)
            with patch('berofel.ui.window.analyze_clip_candidates',return_value={
                    'clips':[],'candidates':[],'events':[],
                    'stats':{'elapsed_seconds':.01,'cache_hits':0,'cache_misses':0,
                             'decoded_seconds':0.,'candidate_count':0,'rss_mb':None}}) as analyze:
                dialog._analyze()
                deadline=time.monotonic()+5
                while time.monotonic()<deadline and dialog.cancel_button.isEnabled():
                    QTest.qWait(25)
            self.assertFalse(dialog.cancel_button.isEnabled(),dialog.status.text())
            analyze.assert_called_once()
            self.assertEqual(analyze.call_args.args[0][0].id,clip.id)
            self.assertEqual(analyze.call_args.args[1],words)
            dialog.close();win.close()

    def test_custom_voice_panel_defaults_to_recommended_int8_and_keeps_other_profiles(self):
        with patch('berofel.services.qwen3_native_tts.is_ready',return_value=True):
            panel=NarrationPanel()
        panel.voice.setCurrentIndex(panel.voice.findData('__custom__'))
        self.assertEqual(panel.clone_engine.currentData(),'qwen3-tts-purec-int8')
        self.assertGreaterEqual(panel.clone_engine.findData('qwen3-tts-local'),0)
        self.assertGreaterEqual(panel.clone_engine.findData('qwen3-tts-native-q4'),0)
        self.assertGreaterEqual(panel.clone_engine.findData('qwen3-tts-native-q4-balanced'),0)
        self.assertFalse(panel.sample_path.isHidden())
        self.assertFalse(panel.validate_sample.isHidden())
        self.assertFalse(panel.clone_detail_title.isHidden())
        self.assertTrue(panel.activate_cloning.isHidden())
        self.assertIn('Qwen3',panel.license_note.text())
        self.assertFalse(panel.clone_engine.isVisible())
        panel.close()

    def test_turbo_panel_selection_builds_native_narration_request(self):
        import tempfile
        with patch('berofel.services.qwen3_native_tts.is_ready',return_value=True):
            panel=NarrationPanel()
        panel.voice.setCurrentIndex(panel.voice.findData('__custom__'))
        panel.clone_engine.setCurrentIndex(panel.clone_engine.findData('qwen3-tts-local'))
        panel.clone_engine.setCurrentIndex(panel.clone_engine.findData('qwen3-tts-native-q4'))
        sample=tempfile.NamedTemporaryFile(suffix='.wav',delete=False)
        sample.close()
        panel.sample_path.setText(sample.name)
        panel.authorized.setChecked(True)
        panel.text.setPlainText('Olá, esta é uma narração rápida.')
        panel.reference_text.setText('Esta gravação é a referência autorizada.')
        requests=[]
        panel.on_generate=lambda request,insert:requests.append((request,insert))
        panel._generate(False)
        Path(sample.name).unlink(missing_ok=True)
        self.assertEqual(requests[0][0].engine,'qwen3-tts-native-q4')
        self.assertTrue(requests[0][0].consent)
        self.assertEqual(requests[0][0].reference_text,'Esta gravação é a referência autorizada.')
        self.assertIn('experimental',panel.license_note.text())
        panel.save_preferences()
        panel.close()
        with patch('berofel.services.qwen3_native_tts.is_ready',return_value=True):
            restored=NarrationPanel()
        self.assertEqual(restored.clone_engine.currentData(),'qwen3-tts-native-q4')
        restored.close()

    def test_selecting_saved_purec_voice_prewarms_only_authorized_profile(self):
        from unittest.mock import Mock
        with patch('berofel.services.qwen3_native_tts.is_ready',return_value=False), \
             patch('berofel.services.qwen3_purec_tts.is_ready',return_value=True):
            panel=NarrationPanel()
        settings_snapshot=_snapshot_narration_settings(panel._settings)
        original_threads=panel.purec_threads.currentIndex()
        with tempfile.NamedTemporaryFile(suffix='.wav',delete=False) as sample:
            sample_path=sample.name
        profile={'sample_path':sample_path,'reference_text':'fala de referência',
                 'authorized':True,'name':'Minha voz'}
        prepare=Mock()
        panel.on_prepare_voice=prepare
        try:
            with patch.object(panel.voice_profiles,'get',return_value=profile):
                panel.voice.addItem('Perfil local · Minha voz','voice-profile:profile-1')
                voice_index=panel.voice.findData('voice-profile:profile-1')
                panel.voice.setCurrentIndex(voice_index)
                turbo_index=panel.clone_engine.findData('qwen3-tts-purec-mixed')
                self.assertGreaterEqual(turbo_index,0)
                panel.clone_engine.setCurrentIndex(turbo_index)
                self.assertFalse(panel.purec_threads.isHidden())
                panel.purec_threads.setCurrentIndex(panel.purec_threads.findData(8))
                panel.voice.activated.emit(voice_index)
                prepare.assert_called_once_with(sample_path,'fala de referência','Minha voz',8)
                prepare.reset_mock()
                panel.voice_profiles.get.return_value={**profile,'authorized':False}
                panel._prewarm_selected_fast_profile()
                prepare.assert_not_called()
        finally:
            panel.purec_threads.setCurrentIndex(original_threads)
            Path(sample_path).unlink(missing_ok=True)
            panel._preferences_timer.stop()
            panel.close()
            _restore_narration_settings(panel._settings,settings_snapshot)

    def test_purec_turbo_request_carries_selected_thread_budget(self):
        import tempfile
        with patch('berofel.services.qwen3_native_tts.is_ready',return_value=False), \
             patch('berofel.services.qwen3_purec_tts.is_ready',return_value=True):
            panel=NarrationPanel()
        settings_snapshot=_snapshot_narration_settings(panel._settings)
        original_threads=panel.purec_threads.currentIndex()
        panel.voice.setCurrentIndex(panel.voice.findData('__custom__'))
        panel.clone_engine.setCurrentIndex(panel.clone_engine.findData('qwen3-tts-local'))
        panel.clone_engine.setCurrentIndex(panel.clone_engine.findData('qwen3-tts-purec-mixed'))
        panel.purec_threads.setCurrentIndex(panel.purec_threads.findData(8))
        with tempfile.NamedTemporaryFile(suffix='.wav',delete=False) as sample:
            panel.sample_path.setText(sample.name)
            panel.authorized.setChecked(True)
            panel.text.setPlainText('Teste Turbo com oito threads.')
            requests=[]
            panel.on_generate=lambda request,insert:requests.append(request)
            panel._generate(False)
        Path(sample.name).unlink(missing_ok=True)
        self.assertEqual(requests[0].thread_count,8)
        self.assertFalse(panel.purec_threads.isHidden())
        panel.purec_threads.setCurrentIndex(original_threads)
        panel._preferences_timer.stop()
        panel.close()
        _restore_narration_settings(panel._settings,settings_snapshot)

    def test_balanced_panel_selection_builds_native_narration_request(self):
        import tempfile
        with patch('berofel.services.qwen3_native_tts.is_ready',return_value=True):
            panel=NarrationPanel()
        panel.voice.setCurrentIndex(panel.voice.findData('__custom__'))
        panel.clone_engine.setCurrentIndex(panel.clone_engine.findData('qwen3-tts-native-q4-balanced'))
        sample=tempfile.NamedTemporaryFile(suffix='.wav',delete=False);sample.close()
        panel.sample_path.setText(sample.name);panel.authorized.setChecked(True)
        panel.text.setPlainText('Perfil equilibrado local do Qwen.')
        requests=[];panel.on_generate=lambda request,insert:requests.append(request)
        panel._generate(False);Path(sample.name).unlink(missing_ok=True)
        self.assertEqual(requests[0].engine,'qwen3-tts-native-q4-balanced')
        self.assertIn('Equilibrado',panel.license_note.text())
        panel.close()

    def test_narration_panel_can_alternate_latest_and_previous_mode_samples(self):
        import tempfile
        import wave
        with tempfile.TemporaryDirectory(prefix='bfs_voice_ab_') as folder:
            samples=[]
            for name in ('turbo.wav','balanced.wav'):
                path=Path(folder)/name
                with wave.open(str(path),'wb') as output:
                    output.setnchannels(1);output.setsampwidth(2);output.setframerate(24000)
                    output.writeframes(b'\x01\x00'*2400)
                samples.append(path)
            panel=NarrationPanel();panel.set_result(str(samples[0]),.1,False,'qwen3-tts-native-q4')
            self.assertFalse(panel.listen_previous.isEnabled())
            panel.set_result(str(samples[1]),.1,False,'qwen3-tts-native-q4-balanced')
            self.assertTrue(panel.listen_previous.isEnabled())
            self.assertIn('Turbo',panel.audio_history[0][1])
            self.assertIn('Equilibrado',panel.audio_history[1][1])
            class FakePlayer:
                def setSource(self,url): self._source=url
                def source(self): return self._source
                def stop(self): pass
                def play(self): pass
            panel._player=FakePlayer()
            panel._listen_previous()
            self.assertEqual(Path(panel._player.source().toLocalFile()),samples[0])
            panel._listen()
            self.assertEqual(Path(panel._player.source().toLocalFile()),samples[1])
            panel.close()

    def test_new_custom_voice_uses_qwen_and_requires_reference_audio(self):
        with tempfile.TemporaryDirectory(prefix='bfs_qwen_voice_ui_') as folder:
            sample=Path(folder)/'reference.wav';sample.write_bytes(b'RIFF'+b'valid reference'*10)
            panel=NarrationPanel()
            panel.voice.setCurrentIndex(panel.voice.findData('__custom__'))
            panel.clone_engine.setCurrentIndex(panel.clone_engine.findData('qwen3-tts-local'))
            panel.sample_path.setText(str(sample))
            panel.authorized.setChecked(True)
            panel.reference_text.setText('Texto exato da referência gravada.')
            panel.text.setPlainText('Teste de voz local.')
            captured=[]
            panel.on_generate=lambda request,insert:captured.append((request,insert))
            panel._generate(False)
            self.assertEqual(captured[0][0].engine,'qwen3-tts-local')
            self.assertEqual(captured[0][0].voice,str(sample))
            panel.close()

    def test_voice_profile_is_reusable_and_delete_preserves_source_audio(self):
        with tempfile.TemporaryDirectory(prefix='bfs_voice_profile_ui_') as folder, \
                patch.dict(os.environ,{'BEROFEL_VOICE_PROFILE_DIR':str(Path(folder)/'profiles')}):
            source=Path(folder)/'my_voice.wav';original=b'RIFF'+b'voice audio'*50
            source.write_bytes(original)
            panel=NarrationPanel()
            panel.voice.setCurrentIndex(panel.voice.findData('__custom__'))
            panel.sample_path.setText(str(source));panel.authorized.setChecked(True)
            panel.reference_text.setText('A referência usada para esta voz local.')
            with patch('berofel.ui.narration_panel.QInputDialog.getText',
                       return_value=('Minha voz',True)):
                panel._save_voice_profile()
            profile_id=str(panel.voice.currentData()).split(':',1)[1]
            private=Path(panel.sample_path.text())
            self.assertNotEqual(private,source)
            self.assertEqual(private.read_bytes(),original)
            panel.text.setPlainText('Teste de perfil local.')
            captured=[];panel.on_generate=lambda request,insert:captured.append(request)
            panel._generate(False)
            self.assertEqual(captured[0].voice,str(private))

            with patch('berofel.ui.narration_panel.QInputDialog.getText',
                       return_value=('Voz revisada',True)):
                panel._rename_voice_profile()
            self.assertIn('Voz revisada',panel.voice.currentText())
            with patch('berofel.ui.narration_panel.QMessageBox.question',
                       return_value=QMessageBox.StandardButton.Yes):
                panel._delete_voice_profile()
            self.assertFalse(private.exists())
            self.assertEqual(source.read_bytes(),original)
            self.assertEqual(panel.voice.currentData(),'__custom__')
            panel.close()

    def test_qwen_voice_clone_request_routes_locally_with_optional_reference_transcript(self):
        import tempfile
        panel=NarrationPanel()
        panel.voice.setCurrentIndex(panel.voice.findData('__custom__'))
        panel.clone_engine.setCurrentIndex(panel.clone_engine.findData('qwen3-tts-local'))
        sample=tempfile.NamedTemporaryFile(suffix='.wav',delete=False)
        sample.close()
        panel.sample_path.setText(sample.name)
        panel.authorized.setChecked(True)
        panel.text.setPlainText('Olá, esta é uma narração de teste.')
        panel.reference_text.setText('Este texto foi falado na gravação original.')
        requests=[]
        panel.on_generate=lambda request,insert:requests.append((request,insert))
        panel._generate(False)
        Path(sample.name).unlink(missing_ok=True)
        self.assertEqual(len(requests),1)
        request,insert=requests[0]
        self.assertEqual(request.engine,'qwen3-tts-local')
        self.assertEqual(request.reference_text,'Este texto foi falado na gravação original.')
        self.assertTrue(request.consent)
        self.assertFalse(insert)
        self.assertIn('Apache-2.0',panel.license_note.text())
        self.assertTrue(panel.activate_cloning.isHidden())
        self.assertFalse(panel.install_qwen.isHidden())
        panel.close()

    def test_narration_draft_voice_and_sample_path_persist_but_consent_does_not(self):
        panel=NarrationPanel()
        panel.text.setPlainText('Meu roteiro salvo localmente.')
        panel.name.setText('Minha voz')
        panel.language.setCurrentIndex(panel.language.findData('portuguese'))
        panel.voice.setCurrentIndex(panel.voice.findData('__custom__'))
        panel.sample_path.setText(r'C:\Audio\minha_voz.m4a')
        panel.clone_engine.setCurrentIndex(panel.clone_engine.findData('qwen3-tts-local'))
        panel.reference_text.setText('Texto de referência persistido.')
        panel.quantize.setChecked(True)
        panel.authorized.setChecked(True)
        QTest.qWait(500)  # gravação automática depois que a edição fica ociosa
        self.assertEqual(panel._settings.value('narration/draft'),
                         'Meu roteiro salvo localmente.')
        panel.close()

        restored=NarrationPanel()
        self.assertEqual(restored.text.toPlainText(),'Meu roteiro salvo localmente.')
        self.assertEqual(restored.name.text(),'Minha voz')
        self.assertEqual(restored.voice.currentData(),'__custom__')
        self.assertEqual(restored.sample_path.text(),r'C:\Audio\minha_voz.m4a')
        self.assertEqual(restored.clone_engine.currentData(),'qwen3-tts-local')
        self.assertEqual(restored.reference_text.text(),'Texto de referência persistido.')
        self.assertTrue(restored.quantize.isChecked())
        self.assertFalse(restored.authorized.isChecked())
        restored.close()

    def test_voice_eq_slider_updates_selected_clip_and_supports_undo_redo(self):
        import wave
        with tempfile.TemporaryDirectory(prefix='bfs_voice_eq_ui_') as folder:
            source=Path(folder)/'voice.wav'
            with wave.open(str(source),'wb') as audio:
                audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(48000)
                audio.writeframes(b'\x00\x00'*48000)
            win=MainWindow()
            clip=win.project.add_clip(Clip(str(source),0,1,kind='audio',
                track_id=win.project.tracks[-1].id,title='Narração'))
            win.selected_ids=[clip.id]
            win.refresh([clip.id])
            panel=win.narration_panel
            self.assertEqual(panel._eq_clip_id,clip.id)
            slider=panel.eq_sliders['bass_db']
            self.assertTrue(slider.isEnabled())
            with patch('berofel.ui.window.generate_narration') as tts:
                slider.setValue(40)  # controle interno usa décimos de dB
                QTest.qWait(240)
                panel.pitch_slider.setValue(30)
                QTest.qWait(240)
                panel.speed_slider.setValue(111)
                self.assertEqual(panel.speed_slider.value(),110)
                panel.speed_readout.setValue(1.10)
                panel.speed_readout.editingFinished.emit()
                tts.assert_not_called()
            self.assertEqual(win.project.clip(clip.id).voice_eq_bass_db,4.)
            self.assertEqual(win.project.clip(clip.id).voice_pitch_semitones,3.)
            self.assertAlmostEqual(win.project.clip(clip.id).speed,1.1)
            self.assertTrue(win.project.clip(clip.id).preserve_pitch)
            self.assertAlmostEqual(win.project.clip(clip.id).duration,1/1.1)
            self.assertEqual(panel.eq_readouts['bass_db'].value(),4.)
            self.assertEqual(panel.pitch_readout.value(),3.)
            self.assertEqual(len(win.history),3)
            win.undo()
            self.assertEqual(win.project.clip(clip.id).voice_pitch_semitones,3.)
            self.assertAlmostEqual(win.project.clip(clip.id).speed,1.)
            win.redo()
            self.assertEqual(win.project.clip(clip.id).voice_eq_bass_db,4.)
            self.assertEqual(win.project.clip(clip.id).voice_pitch_semitones,3.)
            self.assertAlmostEqual(win.project.clip(clip.id).speed,1.1)
            win.close();self.app.processEvents()

    def test_narration_speed_slider_keeps_linked_video_and_captions_in_sync(self):
        from berofel.services.ffmpeg import supports_filter
        win=MainWindow()
        try:
            video_track,audio_track=win.project.tracks[:2]
            video=win.project.add_clip(Clip('source.mp4',0,2,kind='video',
                track_id=video_track.id,group_id='narration-av'))
            audio=win.project.add_clip(Clip('source.mp4',0,2,kind='audio',
                track_id=audio_track.id,group_id='narration-av'))
            caption=win.project.add_clip(Clip('',0,.5,kind='text',text='Olá',
                track_id=win.project.tracks[-1].id,timeline_start=1.,
                generated_by='auto_caption',caption_anchor_clip_id=audio.id,
                caption_source_start=1.,caption_source_end=1.5,
                caption_generated_text='Olá'))
            win.selected_ids=[audio.id];win.refresh([audio.id])
            panel=win.narration_panel
            self.assertTrue(panel.speed_slider.isEnabled())
            panel.speed_slider.setValue(125)
            panel.speed_slider.sliderReleased.emit()
            self.assertAlmostEqual(win.project.clip(video.id).speed,1.25)
            self.assertAlmostEqual(win.project.clip(audio.id).speed,1.25)
            self.assertAlmostEqual(win.project.clip(caption.id).timeline_start,.8)
            self.assertAlmostEqual(win.project.clip(caption.id).duration,.4)
            if supports_filter('rubberband'):
                self.assertTrue(win.project.clip(video.id).preserve_pitch)
                self.assertTrue(win.project.clip(audio.id).preserve_pitch)
            self.assertEqual(len(win.history),1)
            win.undo()
            self.assertAlmostEqual(win.project.clip(video.id).speed,1.)
            self.assertAlmostEqual(win.project.clip(audio.id).speed,1.)
            self.assertAlmostEqual(win.project.clip(caption.id).timeline_start,1.)
            self.assertAlmostEqual(win.project.clip(caption.id).duration,.5)
            win.redo()
            self.assertAlmostEqual(win.project.clip(caption.id).timeline_start,.8)
        finally:
            win.close();self.app.processEvents()

    def test_voice_eq_edit_resumes_preview_from_current_playhead(self):
        from unittest.mock import patch
        from PySide6.QtCore import QTimer
        win=MainWindow()
        try:
            clip=win.project.add_clip(Clip('voice.wav',0,3,kind='audio',
                track_id=win.project.tracks[-1].id))
            win.selected_ids=[clip.id]
            win.refresh([clip.id])
            win.timeline.set_cursor(1.25)
            win.live.active=True
            win.live.paused=False
            with patch.object(win,'refresh'),patch.object(win,'toggle_play') as restart:
                win.begin_voice_eq_edit(clip.id)
                win.apply_voice_eq_edit(clip.id,{'bass_db':2.,'mids_db':0.,
                    'treble_db':0.,'pitch_semitones':0.},False,'Personalizado')
                QTimer.singleShot(0,self.app.processEvents)
                self.app.processEvents()
                self.assertTrue(restart.called)
                self.assertAlmostEqual(win.timeline.view.cursor_time,1.25)
        finally:
            win.live.active=False
            win.close();self.app.processEvents()

    def test_saved_voice_preset_applies_to_selected_clip_without_tts(self):
        from berofel.services.voice_presets import VoicePresetManager
        with tempfile.TemporaryDirectory(prefix='bfs_voice_preset_ui_') as folder:
            win=MainWindow()
            try:
                clip=win.project.add_clip(Clip('voice.wav',0,2,kind='audio',
                    track_id=win.project.tracks[-1].id))
                win.selected_ids=[clip.id];win.refresh([clip.id])
                panel=win.narration_panel
                panel.voice_presets=VoicePresetManager(Path(folder)/'presets.json')
                panel.voice_presets.save('Locução grave',{'bass_db':3.,'mids_db':.5,
                    'treble_db':-2.,'pitch_semitones':-1.5})
                panel._refresh_voice_presets()
                with patch('berofel.ui.window.generate_narration') as tts:
                    panel.eq_preset.setCurrentText('Locução grave')
                    tts.assert_not_called()
                updated=win.project.clip(clip.id)
                self.assertEqual(updated.voice_eq_bass_db,3.)
                self.assertEqual(updated.voice_eq_mids_db,.5)
                self.assertEqual(updated.voice_eq_treble_db,-2.)
                self.assertEqual(updated.voice_pitch_semitones,-1.5)
            finally:
                win.close();self.app.processEvents()

    def test_voice_adjustments_copy_and_paste_as_single_undoable_action(self):
        win=MainWindow()
        try:
            track=win.project.tracks[-1].id
            source=win.project.add_clip(Clip('source.wav',0,4,kind='audio',
                track_id=track,voice_eq_bass_db=3.5,voice_eq_mids_db=-1.,
                voice_eq_treble_db=2.,voice_pitch_semitones=-1.5,
                voice_dsp_bypass=False,voice_dsp_preset='Voz clara',speed=1.1,
                preserve_pitch=True))
            target=win.project.add_clip(Clip('target.wav',0,4,kind='audio',
                track_id=track,timeline_start=5))
            win.selected_ids=[source.id]
            win.narration_panel.set_clip(source)
            win.narration_panel.copy_voice_adjustments.click()
            self.assertIsNotNone(win._voice_adjustment_clipboard)
            win.selected_ids=[target.id]
            win.narration_panel.set_clip(target)
            with patch.object(win,'refresh'):
                win.narration_panel.paste_voice_adjustments.click()
                updated=win.project.clip(target.id)
                self.assertEqual(updated.voice_eq_bass_db,3.5)
                self.assertEqual(updated.voice_eq_mids_db,-1.)
                self.assertEqual(updated.voice_eq_treble_db,2.)
                self.assertEqual(updated.voice_pitch_semitones,-1.5)
                self.assertEqual(updated.voice_dsp_preset,'Voz clara')
                self.assertAlmostEqual(updated.speed,1.1)
                self.assertTrue(updated.preserve_pitch)
                self.assertEqual(len(win.history),1)
                win.undo()
                restored=win.project.clip(target.id)
                self.assertEqual(restored.voice_eq_bass_db,0.)
                self.assertEqual(restored.voice_pitch_semitones,0.)
                self.assertAlmostEqual(restored.speed,1.)
                win.redo()
                self.assertEqual(win.project.clip(target.id).voice_eq_bass_db,3.5)
        finally:
            win.close();self.app.processEvents()

    def test_voice_dsp_paste_works_with_locked_link_when_speed_stays_and_refuses_partial_speed(self):
        win=MainWindow()
        try:
            video_track=win.project.tracks[0]
            audio_track=win.project.tracks[-1]
            source_track=win.project.add_track('Ajustes de origem')
            source=win.project.add_clip(Clip('source.wav',0,2,kind='audio',
                track_id=source_track.id,voice_eq_bass_db=2.))
            linked_video=win.project.add_clip(Clip('pair.mp4',0,2,kind='video',
                track_id=video_track.id,timeline_start=5,group_id='pair',
                voice_eq_bass_db=0.))
            linked_audio=win.project.add_clip(Clip('pair.mp4',0,2,kind='audio',
                track_id=audio_track.id,timeline_start=5,group_id='pair',
                voice_eq_bass_db=0.))
            audio_track.locked=True
            self.assertFalse(win.project.can_edit_linked_av(linked_video.id))
            self.assertTrue(win.copy_voice_adjustments(source.id))
            with patch.object(win,'refresh'):
                # EQ can be changed because the copied time properties already match.
                self.assertTrue(win.paste_voice_adjustments(linked_video.id))
                self.assertEqual(win.project.clip(linked_video.id).voice_eq_bass_db,2.)
                self.assertEqual(win.project.clip(linked_audio.id).voice_eq_bass_db,0.)
                # A speed change would split the linked pair, so reject it atomically.
                source.speed=1.1
                source.voice_eq_bass_db=4.
                self.assertTrue(win.copy_voice_adjustments(source.id))
                win.project.clip(linked_video.id).voice_eq_bass_db=0.
                self.assertFalse(win.paste_voice_adjustments(linked_video.id))
                self.assertEqual(win.project.clip(linked_video.id).voice_eq_bass_db,0.)
                self.assertEqual(win.project.clip(linked_video.id).speed,1.)
        finally:
            win.close();self.app.processEvents()

    def test_voice_formant_panel_is_disabled_with_backend_limitation(self):
        from PySide6.QtWidgets import QWidget
        from berofel.ui.narration_panel import NarrationPanel
        panel=NarrationPanel()
        try:
            section=panel.findChild(QWidget,'voiceFormantUnavailable')
            self.assertIsNotNone(section)
            self.assertFalse(section.isEnabled())
            self.assertIn('ajuste independente de ressonância',
                          panel.formant_explanation.text())
        finally:panel.close()

    def test_eq_and_pitch_adjustment_updates_active_preview_without_restart(self):
        import copy
        from unittest.mock import patch
        win=MainWindow()
        try:
            clip=win.project.add_clip(Clip('voice.wav',0,2,kind='audio',
                track_id=win.project.tracks[-1].id))
            win.selected_ids=[clip.id];win.refresh([clip.id])
            win._playback_snapshot=copy.deepcopy(win.project)
            win.live.active=True
            with patch.object(win.live,'update_voice_eq',return_value=True) as update, \
                 patch.object(win.live,'discard_prefetch') as discard, \
                 patch.object(win,'_refresh_voice_edit_ui') as ui_refresh, \
                 patch.object(win,'refresh') as restart:
                win.begin_voice_eq_edit(clip.id)
                win.apply_voice_eq_edit(clip.id,{'bass_db':4.,'mids_db':-1.,
                    'treble_db':2.,'pitch_semitones':-1.},False,'Personalizado')
                update.assert_called_once()
                discard.assert_called_once()
                ui_refresh.assert_called_once_with(clip.id)
                restart.assert_not_called()
                self.assertEqual(win.project.clip(clip.id).voice_eq_bass_db,4.)
                self.assertEqual(win.project.clip(clip.id).voice_pitch_semitones,-1.)
        finally:
            win.live.active=False
            win.close();self.app.processEvents()

    def test_batch_choices_and_select_300_cuts_one_click(self):
        panel=ActionsPanel()
        panel.set_actions(('silence','fillers','subtitles'))
        self.assertEqual(panel.checked_actions(),('silence','fillers','subtitles'))
        self.assertIn('Silero',panel.plan_label.text())
        self.assertIn('Qwen',panel.plan_label.text())
        proposals=[{'clip_id':'one','title':'Teste','a':i,'b':i+.4,
                    'type':'silencio','note':'Pausa'} for i in range(300)]
        dialog=SuggestionsDialog(proposals)
        self.assertEqual(len(dialog.accepted_findings()),0)
        self.assertEqual(dialog.review_position.text(),'Sugestão 1 de 300')
        self.assertIn('Teste  ·  0.00–0.40s',dialog.review_interval.text())
        dialog.cut_button.click()
        self.assertEqual(len(dialog.accepted_findings()),1)
        dialog.next_button.click()
        self.assertEqual(dialog.review_position.text(),'Sugestão 2 de 300')
        dialog.keep_button.click()
        self.assertEqual(len(dialog.accepted_findings()),1)
        dialog.previous_button.click();dialog.keep_button.click()
        self.assertEqual(len(dialog.accepted_findings()),0)
        dialog._set_all(True)
        self.assertEqual(len(dialog.accepted_findings()),300)
        self.assertIn('300 de 300',dialog.counter.text())
        dialog._set_all(False)
        self.assertEqual(len(dialog.accepted_findings()),0)
        dialog.close();panel.close()

    def test_review_can_audition_suggestion_through_the_main_preview_at_clip_speed(self):
        win=MainWindow()
        dialog=None
        try:
            clip=win.project.add_clip(Clip('',2,8,title='Teste',
                track_id=win.project.tracks[0].id,timeline_start=10,speed=2))
            finding={'clip_id':clip.id,'title':'Teste','a':3.,'b':4.,
                     'type':'silencio','note':'Pausa sugerida'}
            dialog=SuggestionsDialog([finding],parent=win)
            emitted=[]
            dialog.preview_requested.connect(lambda *values:emitted.append(values))
            dialog.preview_button.click()
            self.assertEqual(emitted,[(clip.id,3.,4.)])
            with patch.object(win,'refresh') as refresh, \
                 patch.object(win,'seek_to') as seek, \
                 patch.object(win,'toggle_play') as play:
                win._preview_review_finding(*emitted[0])
            refresh.assert_called_once_with([clip.id])
            seek.assert_called_once_with(11.175)
            play.assert_called_once_with()
            self.assertEqual(win.selected_ids,[clip.id])
            self.assertEqual(win._review_preview_end,12.)
        finally:
            if dialog:dialog.close()
            win.close()

    def test_review_preview_stops_at_suggestion_end_and_keeps_monitor_on_boundary(self):
        win=MainWindow()
        try:
            win._review_preview_end=12.
            with patch.object(win,'stop_playback') as stop, \
                 patch.object(win,'seek_to') as seek:
                win._live_position(12.08)
            stop.assert_called_once_with()
            seek.assert_called_once_with(12.)
            self.assertIsNone(win._review_preview_end)
            self.assertIn('Fim da prévia da sugestão',win.statusBar().currentMessage())
        finally:
            win.close()

    def test_one_click_approves_and_routes_all_300_filtered_suggestions_to_cuts(self):
        from copy import deepcopy
        from berofel.services.action_scope import ScopeTarget
        from berofel.services.batch_editing import apply_reviewed_cuts
        win=MainWindow()
        dialog=None
        try:
            project=win.project
            clip=project.add_clip(Clip('',0,225,track_id=project.tracks[0].id))
            win.refresh([clip.id])
            target=ScopeTarget(clip.id,0,225,0,225,clip.track_id)
            findings=[{'clip_id':clip.id,'title':'Clipe','a':i*.75,'b':i*.75+.25,
                       'type':'silencio' if i%2==0 else 'contexto','note':'Sugestão'}
                      for i in range(300)]
            dialog=SuggestionsDialog(findings,parent=win)
            dialog.filter_type.setCurrentIndex(dialog.filter_type.findData('silencio'))
            self.assertIn('150 de 300',dialog.filter_count.text())
            dialog.approve_all_button.click()
            self.assertEqual(dialog.result(),QDialog.DialogCode.Accepted)
            approved=dialog.accepted_findings()
            self.assertEqual(len(approved),300)
            self.assertEqual(sum(item['type']=='contexto' for item in approved),150)
            working=deepcopy(project)
            remapped=apply_reviewed_cuts(working,[target],approved)
            self.assertEqual(len(working.clips),300)
            self.assertEqual(len(remapped),300)
            self.assertEqual(len(project.clips),1)  # aplicar ocorre na cópia primeiro
            win.snapshot()
            win.project=working
            win.refresh([piece.id for piece in working.clips])
            self.assertEqual(len(win.project.clips),300)
            win.undo()
            self.assertEqual(len(win.project.clips),1)
            self.assertEqual(win.project.clips[0].id,clip.id)
        finally:
            if dialog:dialog.close()
            win.close()

    def test_suggestion_filters_preserve_hidden_selection_and_global_select(self):
        findings=[
            {'clip_id':'a','title':'Entrevista A','a':1,'b':2,'type':'contexto',
             'note':'Contexto importante','text':'manter esta fala'},
            {'clip_id':'b','title':'Entrevista B','a':3,'b':4,'type':'silencio',
             'note':'Pausa longa'},
            {'clip_id':'c','title':'Entrevista C','a':5,'b':6,'type':'contexto',
             'note':'Contexto repetido','text':'cortar repetição'},
        ]
        dialog=SuggestionsDialog(findings)
        dialog.filter_type.setCurrentIndex(dialog.filter_type.findData('contexto'))
        self.assertIn('2 de 3',dialog.filter_count.text())
        dialog._set_visible(True)
        self.assertEqual([i for i,c in enumerate(dialog.checks) if c.isChecked()],[0,2])
        dialog.filter_search.setText('repetido')
        self.assertEqual(dialog._visible_indices(),[2])
        dialog._set_visible(False)
        self.assertEqual([i for i,c in enumerate(dialog.checks) if c.isChecked()],[0])
        dialog._set_all(True)
        self.assertEqual(len(dialog.accepted_findings()),3)
        dialog.filter_search.clear()
        dialog.next_button.click()
        self.assertEqual(dialog.current_index,0)
        dialog.close()

    def test_integrated_window_has_fixed_actions_tab(self):
        win=MainWindow()
        self.assertIn(__version__,win.windowTitle())
        self.assertIs(win.project_name,win.header.project_name)
        self.assertIs(win.play_button,win.transport.play_button)
        self.assertEqual(win.header.findChild(QLabel,'brandName').text(),'BEROFEL')
        logo=win.header.findChild(QLabel,'brandMark')
        self.assertEqual(logo.accessibleName(),'Logo Berofel Studio')
        self.assertIsNotNone(logo.pixmap())
        self.assertFalse(logo.pixmap().isNull())
        self.assertFalse(hasattr(win.header,'stage_buttons'))
        self.assertIs(win.process_panel.parentWidget(),win.header.task_slot)
        self.assertLessEqual(win.header.height(),62)
        self.assertEqual(win.side_tabs.indexOf(win.actions_panel),0)
        expected_tabs=(['IA','Clipes','Voz','Leg.'] if win.width()<1180 else
                       ['Assistente IA','Propriedades','🎙 Narração','Legendas'])
        self.assertEqual([win.side_tabs.tabText(i) for i in range(4)],expected_tabs)
        self.assertNotIn('ai_button',win.header.__dict__)
        self.assertNotIn('narration_button',win.header.__dict__)
        self.assertEqual(win.side_tabs.indexOf(win.captions_panel),3)
        self.assertIs(win.side_tabs.currentWidget(),win.actions_panel)
        self.assertIsNotNone(win.process_panel)
        win.open_actions()
        self.assertIs(win.side_tabs.currentWidget(),win.actions_panel)
        win._header_stage_action('review')
        self.assertIn('revisadas antes',win.statusBar().currentMessage())
        self.assertIs(win.media_list,win.library.media_list)
        self.assertEqual(win.library.marker_list.count(),len(win.project.markers))
        win.close()

    def test_caption_library_opens_docked_editor_without_modal_dialog(self):
        from unittest.mock import patch
        win=MainWindow()
        try:
            with patch('berofel.ui.window.QInputDialog.getMultiLineText',
                       side_effect=AssertionError('não deve abrir pop-up')):
                win.open_captions()
            self.assertIs(win.side_tabs.currentWidget(),win.captions_panel)
            self.assertEqual(win.captions_panel.caption_list.count(),0)
            win.captions_panel.text_edit.setPlainText('Legenda criada no painel')
            win.captions_panel.add_button.click()
            clip=win.project.clip(win.selected_ids[0])
            self.assertEqual(clip.kind,'text')
            self.assertEqual(clip.text,'Legenda criada no painel')
            self.assertIs(win.side_tabs.currentWidget(),win.captions_panel)
            self.assertEqual(win.captions_panel.caption_list.count(),1)
            win.captions_panel.font_size.setValue(58)
            win.captions_panel.font_size.editingFinished.emit()
            self.assertEqual(win.project.clip(clip.id).font_size,58)
            win.captions_panel.preset_requested.emit(3)
            self.assertEqual(win.project.clip(clip.id).font_size,54)
        finally:
            win.close()

    def test_header_removes_redundant_steps_and_keeps_top_actions(self):
        win=MainWindow()
        try:
            self.assertFalse(hasattr(win.header,'stage_buttons'))
            self.assertFalse(hasattr(win.header,'ai_button'))
            self.assertFalse(hasattr(win.header,'narration_button'))
            with patch('berofel.ui.window.QFileDialog.getOpenFileNames',
                       return_value=(['sample.mp4'],'Vídeos')):
                win.library.import_requested.emit()
            self.assertIn('sample.mp4',win.project.media)
            win.open_actions()
            self.assertIs(win.side_tabs.currentWidget(),win.actions_panel)
            clip=win.project.add_clip(Clip('sample.mp4',0,2,track_id=win.project.tracks[0].id))
            with patch('berofel.ui.window.QFileDialog.getSaveFileName',
                       return_value=('cut.mp4','MP4')), patch.object(win,'_task') as task:
                win.export_video()
            task.assert_called_once()
            with patch('berofel.ui.window.QMessageBox.question',
                       return_value=QMessageBox.StandardButton.Yes):
                win.new_project()
            self.assertEqual(win.project.media,[])
        finally:
            win.close()

    def test_timeline_wheel_over_track_headers_and_page_buttons_scroll_horizontally(self):
        win=MainWindow()
        try:
            win.show();self.app.processEvents()
            view=win.timeline.view
            view.scene_.setSceneRect(0,0,5000,700)
            bar=view.horizontalScrollBar()
            self.assertGreater(bar.maximum(),0)
            bar.setValue(250)
            event=QWheelEvent(QPointF(10,10),QPointF(10,10),QPoint(0,0),QPoint(0,-120),
                              Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier,
                              Qt.ScrollPhase.ScrollUpdate,False)
            win.timeline.headers.wheelEvent(event)
            self.assertGreater(bar.value(),250)
            before=bar.value()
            win.pan_timeline_page(-1)
            self.assertLess(bar.value(),before)
        finally:
            win.close()

    def test_timeline_ctrl_wheel_zoom_keeps_time_under_pointer_fixed(self):
        win=MainWindow()
        try:
            win.show();self.app.processEvents()
            track=win.project.tracks[0]
            win.project.add_clip(Clip('synthetic_long.mp4',0,240,kind='video',track_id=track.id))
            win.timeline.set_project(win.project,())
            self.app.processEvents()
            view=win.timeline.view
            bar=view.horizontalScrollBar()
            self.assertGreater(bar.maximum(),4000,
                               'A timeline de 240 s precisa rolar além da cena inicial.')
            bar.setValue(900)
            anchor_x=max(40,view.viewport().width()//3)
            anchor_y=max(20,view.viewport().height()//2)
            before=view.mapToScene(QPoint(anchor_x,anchor_y)).x()/view.pps
            event=QWheelEvent(QPointF(anchor_x,anchor_y),QPointF(anchor_x,anchor_y),
                QPoint(0,0),QPoint(0,120),Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.ControlModifier,Qt.ScrollPhase.ScrollUpdate,False)
            view.wheelEvent(event)
            self.app.processEvents()
            after=view.mapToScene(QPoint(anchor_x,anchor_y)).x()/view.pps
            self.assertAlmostEqual(after,before,delta=.08)
            self.assertGreater(view.pps,21.)
        finally:
            win.close()

    def test_applied_ai_cut_results_stay_selected_and_are_revealed_without_zoom_change(self):
        from types import SimpleNamespace
        win=MainWindow()
        try:
            track=win.project.tracks[0]
            clip=win.project.add_clip(Clip('synthetic_ai_result.mp4',0,6,
                kind='video',track_id=track.id,timeline_start=70))
            win.show();self.app.processEvents()
            win.timeline.set_project(win.project,())
            self.app.processEvents()
            view=win.timeline.view
            old_zoom=view.pps
            target=SimpleNamespace(original_id=clip.id,timeline_start=70.,timeline_end=76.)
            win._reveal_ai_edit_result([target],[{'clip_id':'source','a':1.,'b':2.}])
            self.app.processEvents()
            self.assertEqual(win.selected_ids,[clip.id])
            self.assertIn(clip.id,view.selected_ids())
            self.assertGreater(view.horizontalScrollBar().value(),0)
            self.assertAlmostEqual(view.pps,old_zoom)
        finally:
            win.close()

    def test_clearing_timeline_project_resets_horizontal_and_vertical_scroll_ranges(self):
        win=MainWindow()
        try:
            win.show();self.app.processEvents()
            win.project.add_clip(Clip('long.mp4',0,240,kind='video',
                track_id=win.project.tracks[0].id))
            win.timeline.set_project(win.project,())
            self.app.processEvents()
            view=win.timeline.view
            self.assertGreater(view.horizontalScrollBar().maximum(),0)
            view.set_project(None)
            self.app.processEvents()
            self.assertEqual(view.horizontalScrollBar().maximum(),0)
            self.assertEqual(view.verticalScrollBar().maximum(),0)
        finally:
            win.close()

    def test_only_timeline_scrollbars_keep_visible_extent(self):
        win=MainWindow()
        try:
            win.show();self.app.processEvents()
            timeline=win.timeline.view
            self.assertEqual(timeline.horizontalScrollBarPolicy(),
                             Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
            self.assertGreaterEqual(timeline.horizontalScrollBar().sizeHint().height(),12)
            self.assertGreaterEqual(timeline.verticalScrollBar().sizeHint().width(),12)
            for area in win.findChildren(QAbstractScrollArea):
                if area is timeline:
                    continue
                with self.subTest(area=area.objectName() or type(area).__name__):
                    self.assertEqual(area.horizontalScrollBarPolicy(),
                                     Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
                    self.assertEqual(area.verticalScrollBarPolicy(),
                                     Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        finally:
            win.close()

    def test_review_stage_reopens_pending_suggestions_with_checks_preserved(self):
        win=MainWindow()
        finding={'clip_id':'future-clip','title':'Pausa','a':1.,'b':2.,
                 'type':'silencio','note':'Silêncio detectado','checked':False}
        opened=[]
        def dismiss(dialog):
            opened.append(dialog)
            if len(opened)==1:
                dialog.checks[0].setChecked(True)
            else:
                self.assertTrue(dialog.checks[0].isChecked())
            return QDialog.DialogCode.Rejected
        try:
            with patch.object(SuggestionsDialog,'exec',new=dismiss):
                win._review([finding],'Revisar silêncios')
                self.assertEqual(len(win._pending_review_findings),1)
                self.assertTrue(win._pending_review_findings[0]['checked'])
                self.assertEqual(win.project.review_queue,win._pending_review_findings)
                self.assertEqual(win.project.review_title,'Revisar silêncios')
                win._header_stage_action('review')
            self.assertEqual(len(opened),2)
            self.assertFalse(hasattr(win.header,'stage_buttons'))
        finally:
            win.close()

    def test_review_refuses_cut_when_source_clip_changed_since_analysis(self):
        win=MainWindow()
        clip=win.project.add_clip(Clip('source.mp4',0,8,
            track_id=win.project.tracks[0].id,timeline_start=4))
        finding={'clip_id':clip.id,'title':'Pausa','a':1.,'b':1.5,
                 'type':'silencio','note':'Silêncio','checked':False}
        def approve_after_edit(dialog):
            dialog.checks[0].setChecked(True)
            clip.speed=2.
            return QDialog.DialogCode.Accepted
        try:
            with patch.object(SuggestionsDialog,'exec',new=approve_after_edit), \
                 patch.object(QMessageBox,'warning') as warning, \
                 patch.object(win,'_task') as task:
                win._review([finding],'Revisar silêncios')
            warning.assert_called_once()
            task.assert_not_called()
            self.assertIsNotNone(win._pending_review_findings)
            self.assertTrue(win.project.review_queue[0]['checked'])
        finally:
            win.close()

    def test_manual_timeline_split_remains_available_during_ai_task_and_is_undoable(self):
        win=MainWindow()
        track=win.project.tracks[0]
        original=Clip(source='missing-during-test.mp4',start=0,end=10,
                      track_id=track.id)
        win.project.add_clip(original)
        win.selected_ids=[original.id]
        win.refresh([original.id])
        win.timeline.set_cursor(5)
        started=threading.Event()
        release=threading.Event()

        def heavy_worker():
            started.set()
            if not release.wait(5):
                raise TimeoutError('A liberação do teste não chegou a tempo.')
            return 'IA concluída'

        task=win._task(heavy_worker,lambda _result:None,label='IA em segundo plano · teste')
        self.assertIsNotNone(task)
        self.assertTrue(started.wait(2),'O worker em segundo plano não iniciou.')
        self.assertIs(win.active_task,task)
        try:
            win.split_at_cursor()
            self.assertIs(win.active_task,task,'A edição não deve interromper a tarefa pesada.')
            self.assertEqual(len(win.project.clips),2)
            self.assertEqual([(clip.start,clip.end) for clip in win.project.clips],
                             [(0,5),(5,10)])
            win.undo()
            self.assertIs(win.active_task,task)
            self.assertEqual(len(win.project.clips),1)
            self.assertEqual((win.project.clips[0].start,win.project.clips[0].end),
                             (0,10))
        finally:
            finished=QEventLoop()
            task.signals.finished.connect(finished.quit)
            release.set()
            QTimer.singleShot(3000,finished.quit)
            finished.exec()
            self.app.processEvents()
            win.close()
        self.assertIsNone(win.active_task,'O worker deve liberar a fila ao concluir.')

    def test_slip_tool_moves_source_and_linked_audio_with_undo(self):
        win=MainWindow()
        project=Project()
        group='av_pair'
        video=project.add_clip(Clip('source.mp4',10,20,track_id=project.tracks[0].id,
            timeline_start=4,source_length=40,group_id=group))
        audio=project.add_clip(Clip('source.mp4',10,20,track_id=project.tracks[1].id,
            timeline_start=4,source_length=40,kind='audio',group_id=group))
        win.project=project;win.refresh([video.id])
        try:
            slip_button=next(button for button in win.timeline_tool_buttons
                             if 'Slip da fonte' in button.accessibleName())
            with patch('berofel.ui.window.QInputDialog.getDouble',return_value=(3.,True)):
                slip_button.click()
            self.assertEqual([(clip.start,clip.end) for clip in (video,audio)],
                             [(13,23),(13,23)])
            self.assertEqual([(clip.timeline_start,clip.duration) for clip in (video,audio)],
                             [(4,10),(4,10)])
            win.undo()
            restored_video=win.project.clip(video.id)
            restored_audio=win.project.clip(audio.id)
            self.assertEqual((restored_video.start,restored_video.end),(10,20))
            self.assertEqual((restored_audio.start,restored_audio.end),(10,20))
        finally:
            win.close()

    def test_roll_tool_moves_cut_and_linked_audio_with_undo(self):
        win=MainWindow()
        project=Project()
        left_group,right_group='left_pair','right_pair'
        left=project.add_clip(Clip('left.mp4',0,4,track_id=project.tracks[0].id,
            timeline_start=0,source_length=8,group_id=left_group))
        right=project.add_clip(Clip('right.mp4',0,4,track_id=project.tracks[0].id,
            timeline_start=4,source_length=8,group_id=right_group))
        left_audio=project.add_clip(Clip('left.mp4',0,4,track_id=project.tracks[1].id,
            timeline_start=0,source_length=8,kind='audio',group_id=left_group))
        right_audio=project.add_clip(Clip('right.mp4',0,4,track_id=project.tracks[1].id,
            timeline_start=4,source_length=8,kind='audio',group_id=right_group))
        win.project=project;win.refresh([left.id,right.id])
        try:
            roll_button=next(button for button in win.timeline_tool_buttons
                             if 'Roll emenda' in button.accessibleName())
            with patch('berofel.ui.window.QInputDialog.getDouble',return_value=(1.,True)):
                roll_button.click()
            self.assertEqual((left.end,right.start,right.timeline_start),(5,1,5))
            self.assertEqual((left_audio.end,right_audio.start,right_audio.timeline_start),
                             (5,1,5))
            self.assertEqual(project.duration,8)
            win.undo()
            self.assertEqual((win.project.clip(left.id).end,win.project.clip(right.id).start,
                              win.project.clip(right.id).timeline_start),(4,0,4))
            self.assertEqual((win.project.clip(left_audio.id).end,
                              win.project.clip(right_audio.id).start,
                              win.project.clip(right_audio.id).timeline_start),(4,0,4))
        finally:
            win.close()

    def test_slide_tool_adjusts_neighbors_and_linked_audio_with_undo(self):
        win=MainWindow();project=Project()
        vt,at=project.tracks[0].id,project.tracks[1].id
        groups=('left','middle','right')
        pieces=[]
        for group,source,kind,track,start,end,position in (
                ('left','left.mp4','video',vt,0,4,0),
                ('middle','mid.mp4','video',vt,0,2,4),
                ('right','right.mp4','video',vt,0,4,6),
                ('left','left.mp4','audio',at,0,4,0),
                ('middle','mid.mp4','audio',at,0,2,4),
                ('right','right.mp4','audio',at,0,4,6)):
            pieces.append(project.add_clip(Clip(source,start,end,track_id=track,
                timeline_start=position,source_length=8,kind=kind,group_id=group)))
        left,middle,right,left_audio,middle_audio,right_audio=pieces
        caption=project.add_clip(Clip('',0,.5,track_id=project.tracks[2].id,timeline_start=4.5,
            kind='text',text='Legenda',generated_by='auto_caption',
            caption_anchor_clip_id=middle.id,caption_source_start=.5,
            caption_source_end=1.,caption_generated_text='Legenda'))
        win.project=project;win.refresh([middle.id])
        try:
            slide_button=win.findChild(QToolButton,'timelineSlideNumeric')
            self.assertIsNotNone(slide_button)
            self.assertEqual(slide_button.text(),'±s')
            self.assertEqual(slide_button.accessibleName(),
                             'Ajustar Slide numericamente em segundos')
            self.assertIn('segundos',slide_button.toolTip())
            with patch('berofel.ui.window.QInputDialog.getDouble',return_value=(1.,True)):
                slide_button.click()
            self.assertEqual((left.end,middle.timeline_start,right.start,right.timeline_start),
                             (5,5,1,7))
            self.assertEqual((left_audio.end,middle_audio.timeline_start,
                              right_audio.start,right_audio.timeline_start),(5,5,1,7))
            self.assertAlmostEqual(caption.timeline_start,5.5)
            self.assertAlmostEqual(win.project.duration,10.)
            win.undo()
            restored={clip.id:clip for clip in win.project.clips}
            self.assertEqual((restored[left.id].end,restored[middle.id].timeline_start,
                              restored[right.id].start,restored[right.id].timeline_start),
                             (4,4,0,6))
            self.assertEqual(restored[left_audio.id].end,4)
            self.assertEqual(restored[middle_audio.id].timeline_start,4)
            self.assertEqual(restored[right_audio.id].start,0)
            self.assertEqual(restored[right_audio.id].timeline_start,6)
        finally:
            win.close()

    def test_dragging_slide_mode_updates_linked_sequence_and_undoes(self):
        win=MainWindow();project=Project()
        vt,at=project.tracks[0].id,project.tracks[1].id
        created=[]
        for group,source,kind,track,start,end,position in (
                ('left','left.mp4','video',vt,0,4,0),
                ('middle','mid.mp4','video',vt,0,2,4),
                ('right','right.mp4','video',vt,0,4,6),
                ('left','left.mp4','audio',at,0,4,0),
                ('middle','mid.mp4','audio',at,0,2,4),
                ('right','right.mp4','audio',at,0,4,6)):
            created.append(project.add_clip(Clip(source,start,end,track_id=track,
                timeline_start=position,source_length=8,kind=kind,group_id=group)))
        left,middle,right,left_audio,middle_audio,right_audio=created
        win.project=project;win.refresh([middle.id]);win.resize(1000,700);win.show()
        self.app.processEvents()
        try:
            win.snap_btn.setChecked(False)
            win.activate_slide()
            view=win.timeline.view;view.pps=40
            win.timeline.set_project(project,[middle.id]);self.app.processEvents()
            item=view.items_by_id[middle.id]
            left_item=view.items_by_id[left.id];right_item=view.items_by_id[right.id]
            left_audio_item=view.items_by_id[left_audio.id]
            right_audio_item=view.items_by_id[right_audio.id]
            old_left_width=left_item.rect().width()
            old_right_end=right_item.scenePos().x()+right_item.rect().width()
            old_audio_left_width=left_audio_item.rect().width()
            old_audio_right_end=right_audio_item.scenePos().x()+right_audio_item.rect().width()
            start=view.mapFromScene(item.scenePos()+QPointF(item.rect().width()/2,22))
            end=type(start)(start.x()+20,start.y())
            QTest.mousePress(view.viewport(),Qt.MouseButton.LeftButton,pos=start)
            QTest.mouseMove(view.viewport(),end,delay=20)
            self.assertAlmostEqual(left_item.rect().width(),old_left_width+20.,delta=1.)
            self.assertAlmostEqual(right_item.scenePos().x()+right_item.rect().width(),
                                   old_right_end,delta=1.)
            self.assertAlmostEqual(left_audio_item.rect().width(),old_audio_left_width+20.,delta=1.)
            self.assertAlmostEqual(right_audio_item.scenePos().x()+right_audio_item.rect().width(),
                                   old_audio_right_end,delta=1.)
            self.assertEqual((middle.timeline_start,middle_audio.timeline_start),(4,4))
            QTest.mouseRelease(view.viewport(),Qt.MouseButton.LeftButton,pos=end)
            self.app.processEvents()
            self.assertAlmostEqual(win.project.clip(middle.id).timeline_start,4.5,delta=.03)
            self.assertAlmostEqual(win.project.clip(left.id).timeline_end,4.5,delta=.03)
            self.assertAlmostEqual(win.project.clip(right.id).timeline_start,6.5,delta=.03)
            self.assertAlmostEqual(win.project.clip(middle_audio.id).timeline_start,4.5,delta=.03)
            self.assertAlmostEqual(win.project.clip(left_audio.id).timeline_end,4.5,delta=.03)
            self.assertAlmostEqual(win.project.clip(right_audio.id).timeline_start,6.5,delta=.03)
            win.undo()
            self.assertAlmostEqual(win.project.clip(middle.id).timeline_start,4.)
            self.assertAlmostEqual(win.project.clip(right_audio.id).timeline_start,6.)
        finally:
            win.close()

    def test_copy_paste_keeps_linked_audio_and_caption_anchors_with_undo_redo(self):
        win=MainWindow()
        project=Project()
        group='source_pair'
        video=project.add_clip(Clip('source.mp4',2,8,track_id=project.tracks[0].id,
            timeline_start=5,source_length=20,group_id=group))
        audio=project.add_clip(Clip('source.mp4',2,8,track_id=project.tracks[1].id,
            timeline_start=5,source_length=20,kind='audio',group_id=group))
        caption=project.add_clip(Clip('',0,1,track_id=project.tracks[2].id,
            timeline_start=5.5,kind='text',text='Legenda vinculada',
            generated_by='auto_caption',caption_anchor_clip_id=video.id,
            caption_source_start=2.5,caption_source_end=3.5,
            caption_generated_text='Legenda vinculada'))
        win.project=project;win.refresh([video.id])
        try:
            win.copy_selected_clips()
            self.assertEqual(len(win._clip_clipboard),3)
            win.timeline.set_cursor(20)
            win.paste_clips()
            self.assertEqual(len(win.project.clips),6)
            pasted={clip.id:clip for clip in win.project.clips if clip.timeline_start>=20}
            pasted_video=next(clip for clip in pasted.values() if clip.kind=='video')
            pasted_audio=next(clip for clip in pasted.values() if clip.kind=='audio')
            pasted_caption=next(clip for clip in pasted.values() if clip.kind=='text')
            self.assertEqual((pasted_video.timeline_start,pasted_audio.timeline_start),
                             (20,20))
            self.assertEqual((pasted_video.start,pasted_audio.start),(2,2))
            self.assertEqual(pasted_video.group_id,pasted_audio.group_id)
            self.assertNotEqual(pasted_video.group_id,group)
            self.assertNotEqual(pasted_video.id,video.id)
            self.assertEqual(pasted_caption.caption_anchor_clip_id,pasted_video.id)
            self.assertIn('source.mp4',win.project.media)
            win.undo()
            self.assertEqual(len(win.project.clips),3)
            win.redo()
            self.assertEqual(len(win.project.clips),6)
        finally:
            win.close()

    def test_main_window_routes_live_video_audio_and_clock_to_preview_ui(self):
        from berofel.services.ffmpeg import ffmpeg_path
        with tempfile.TemporaryDirectory(prefix='bfs_window_preview_') as folder:
            source=Path(folder)/'source.mp4'
            subprocess.run([ffmpeg_path(),'-hide_banner','-loglevel','error','-y',
                '-f','lavfi','-i','testsrc=size=160x90:rate=12:duration=1',
                '-f','lavfi','-i','sine=frequency=440:duration=1',
                '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(source)],
                check=True,capture_output=True,timeout=30)
            win=MainWindow()
            project=Project(width=160,height=90,fps=12)
            clip=project.add_clip(Clip(str(source),0,1,track_id=project.tracks[0].id))
            win.project=project;win.refresh([clip.id]);win.show();self.app.processEvents()
            expected_width=win.preview_quality.currentData()[0]
            def use_monotonic_clock():
                win.live._ready=True
                win.live._time0=time.monotonic()
                win.live._paused_total=0.
                win.live._audio_clock_offset=0.
            win.live._start_clock=use_monotonic_clock
            loop=QEventLoop();timeout=QTimer(win);timeout.setSingleShot(True)
            expired=[];frames=[];decoded_audio=[];failures=[]
            timeout.timeout.connect(lambda:(expired.append(True),loop.quit()))
            win.live.frame_ready.connect(lambda frame:frames.append(frame.size().width()))
            win.live.failed.connect(failures.append)
            win.live.reached_end.connect(loop.quit)
            def record_frame(_frame):
                reader=win.live._audio
                decoded_audio.append(bool(reader and reader.output.qsize()>0))
            win.live.frame_ready.connect(record_frame)
            try:
                with patch('berofel.ui.window.QMessageBox.warning'):
                    timeout.start(7000);win.toggle_play();loop.exec()
                self.assertFalse(expired,'A reprodução da janela não chegou ao fim.')
                self.assertFalse(failures,'; '.join(failures))
                self.assertGreaterEqual(len(frames),4)
                self.assertTrue(all(width==expected_width for width in frames))
                self.assertTrue(any(decoded_audio),'O pipe de áudio não entregou PCM à prévia.')
                self.assertIsNotNone(win.preview_image.pixmap)
                self.assertGreaterEqual(win.timeline.view.cursor_time,.98)
                self.assertEqual(win.transport.play_button.text(),'▶')
            finally:
                timeout.stop();win.close();self.app.processEvents()

    def test_main_window_previews_and_seeks_through_300_sequential_cuts(self):
        from berofel.services.ffmpeg import ffmpeg_path
        with tempfile.TemporaryDirectory(prefix='bfs_window_300_cuts_') as folder:
            source=Path(folder)/'source.mp4'
            subprocess.run([ffmpeg_path(),'-hide_banner','-loglevel','error','-y',
                '-f','lavfi','-i','testsrc=size=160x90:rate=12:duration=25',
                '-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=25',
                '-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p',
                '-c:a','aac','-b:a','48k','-shortest',str(source)],
                check=True,capture_output=True,timeout=60)
            win=MainWindow()
            project=Project(width=160,height=90,fps=12)
            source_duration=1/12
            clips=[Clip(str(source),i*source_duration,(i+1)*source_duration,
                        track_id=project.tracks[0].id,timeline_start=i*source_duration,
                        include_audio=True,source_length=25)
                   for i in range(300)]
            project.clips=clips
            project.media=[str(source)]
            win.project=project
            win.refresh([clips[0].id])
            win.show();self.app.processEvents()
            frames=[];audio_packets=[];failures=[];positions=[]
            def record_frame(frame):
                frames.append(frame.size().width())
                reader=win.live._audio
                audio_packets.append(reader.output.qsize() if reader else 0)
            win.live.frame_ready.connect(record_frame)
            win.live.failed.connect(failures.append)
            win.live.position_changed.connect(positions.append)
            def use_monotonic_clock():
                win.live._ready=True
                win.live._time0=time.monotonic()
                win.live._paused_total=0.
                win.live._audio_clock_offset=0.
            win.live._start_clock=use_monotonic_clock

            def wait_for_frame(previous_count,timeout_ms=12000):
                if len(frames)>previous_count:return
                loop=QEventLoop();timer=QTimer(win);timer.setSingleShot(True)
                timer.timeout.connect(loop.quit)
                quit_loop=lambda _frame:loop.quit()
                win.live.frame_ready.connect(quit_loop)
                timer.start(timeout_ms);loop.exec();timer.stop()
                win.live.frame_ready.disconnect(quit_loop)
                self.app.processEvents()

            try:
                win.toggle_play()
                wait_for_frame(0)
                self.assertTrue(frames,'A prévia não entregou quadro no início dos 300 cortes.')
                self.assertFalse(failures,'; '.join(failures))
                self.assertEqual(frames[-1],win.preview_quality.currentData()[0])
                self.assertTrue(any(count>0 for count in audio_packets),
                                'O pipe de áudio não recebeu PCM nos 300 cortes.')

                loop=QEventLoop();timer=QTimer(win);timer.setSingleShot(True)
                advanced=[]
                def crossed_window(at):
                    command=win.live._commands
                    if command and command.source_time>2.3 and at>2.3:
                        advanced.append(at);loop.quit()
                win.live.position_changed.connect(crossed_window)
                timer.timeout.connect(loop.quit);timer.start(12000);loop.exec();timer.stop()
                win.live.position_changed.disconnect(crossed_window)
                self.assertTrue(advanced,'A prévia não avançou para a janela seguinte dos 300 cortes.')
                self.assertFalse(failures,'; '.join(failures))

                win.stop_playback()
                win.seek_to(12.5)
                before=len(frames)
                win.toggle_play()
                wait_for_frame(before)
                self.assertGreater(len(frames),before,
                                   'A busca no meio da sequência não entregou quadro.')
                self.assertFalse(failures,'; '.join(failures))
                self.assertGreaterEqual(win.timeline.view.cursor_time,12.5)
            finally:
                win.close();self.app.processEvents()

    def test_video_properties_are_grouped_in_legacy_style_inspector(self):
        from berofel.ui.window import InspectorGroup
        win=MainWindow()
        try:
            clip=Clip(source='sample.mp4',start=0,end=12,track_id=win.project.tracks[0].id)
            win.project.add_clip(clip)
            win.selection_changed([clip.id])
            win.side_tabs.setCurrentWidget(win.props_scroll)
            win.show();self.app.processEvents()
            groups=win.props_inner.findChildren(InspectorGroup)
            titles=[group.toggle.text().split('  ',1)[-1] for group in groups]
            self.assertEqual(titles,['Bloco e tempo','Movimento e velocidade','Cor e recorte',
                                     'Aparência e duração','Áudio e limpeza','Keyframes'])
            self.assertIsNotNone(win.auto_key)
            self.assertEqual(win.key_field_combo.count(),6)
            motion=groups[1]
            before=motion.body_layout.count()
            motion.toggle.click()
            self.assertFalse(motion.body.isVisible())
            self.assertEqual(motion.body_layout.count(),before)
            motion.toggle.click()
            self.assertTrue(motion.body.isVisible())
        finally:
            win.close()

    def test_color_and_crop_tool_opens_existing_inspector_controls(self):
        from berofel.ui.window import InspectorGroup
        win=MainWindow()
        try:
            clip=win.project.add_clip(Clip('sample.mp4',0,10,
                                           track_id=win.project.tracks[0].id))
            win.refresh([clip.id])
            win.open_color_controls()
            self.assertIs(win.side_tabs.currentWidget(),win.props_scroll)
            group=next(group for group in win.props_scroll.findChildren(InspectorGroup)
                       if group.toggle.text().endswith('Cor e recorte'))
            self.assertTrue(group.toggle.isChecked())
            labels=[label.text() for label in group.findChildren(QLabel)]
            self.assertTrue(any('Brilho' in label for label in labels))
            self.assertTrue(any('Saturação' in label for label in labels))
            self.assertTrue(any('Recorte à esquerda' in label for label in labels))
        finally:
            win.close()

    def test_keyframe_inspector_navigation_seeks_preview_without_editing_project(self):
        win=MainWindow()
        project=Project()
        clip=project.add_clip(Clip('sample.mp4',0,10,track_id=project.tracks[0].id))
        for at,value in ((0,1.),(3,1.5),(7,2.)):
            put_keyframe(clip,'scale',at,value)
        win.project=project;win.refresh([clip.id])
        try:
            win.key_field_combo.setCurrentIndex(win.key_field_combo.findData('scale'))
            self.assertFalse(win.key_previous.isEnabled())
            self.assertTrue(win.key_next.isEnabled())
            win.key_next.click()
            self.assertAlmostEqual(win.timeline.view.cursor_time,3.)
            self.assertTrue(win.key_previous.isEnabled())
            win.key_next.click()
            self.assertAlmostEqual(win.timeline.view.cursor_time,7.)
            self.assertFalse(win.key_next.isEnabled())
            win.key_previous.click()
            self.assertAlmostEqual(win.timeline.view.cursor_time,3.)
            self.assertEqual(len(win.history),0,'Navegar pelos pontos não edita o projeto.')
        finally:
            win.close()

    def test_responsive_layout_800_to_1920_keeps_controls_inside(self):
        from berofel.services.process_control import ProcessControl
        for width,height in ((800,620),(1024,768),(1366,768),(1920,1080)):
            win=MainWindow()
            try:
                win.resize(width,height);self.app.processEvents()
                win.show();self.app.processEvents()
                if os.name=='nt':
                    families=QFontDatabase.families()
                    self.assertIn('Segoe UI',families)
                    self.assertIn('Segoe UI Symbol',families)
                root=win.centralWidget();bounds=root.rect()
                timeline_box=win.timeline.parentWidget()
                def rect(widget):
                    return widget.geometry().translated(widget.mapTo(root,QPoint(0,0))-widget.geometry().topLeft())
                self.assertEqual(win.workspace_splitter.objectName(),'workspaceSplitter')
                self.assertEqual(win.workspace_splitter.orientation(),Qt.Orientation.Vertical)
                for widget in (win.header,win.workspace_splitter,win.horizontal,
                               win.process_panel,timeline_box):
                    box=rect(widget)
                    self.assertGreaterEqual(box.left(),bounds.left())
                    self.assertGreaterEqual(box.top(),bounds.top())
                    self.assertLessEqual(box.right(),bounds.right())
                    self.assertLessEqual(box.bottom(),bounds.bottom())
                for label in ('Dissolvência','Separar áudio'):
                    button=next(b for b in win.timeline_tool_buttons
                                if label in b.accessibleName())
                    self.assertLessEqual(button.width(),68)
                    self.assertTrue(button.toolTip())
                    self.assertLessEqual(len(button.text()),3)
                for button in win.timeline_tool_buttons:
                    self.assertLessEqual(len(button.text()),3,
                                         'a ferramenta deve caber na faixa vertical')
                    self.assertTrue(button.accessibleName())
                heading=win.findChild(QLabel,'timelineHeading')
                self.assertIsNotNone(heading)
                self.assertEqual(heading.text(),'TIMELINE | CAMADAS LIVRES')
                self.assertFalse(heading.wordWrap())
                self.assertGreaterEqual(heading.width(),heading.sizeHint().width())
                self.assertEqual(win.findChild(QLabel,'previewHeading').text(),'PRÉVIA')
                if width<1180:
                    self.assertFalse(win.header.local_status.isVisible())
                    self.assertFalse(hasattr(win.header,'ai_button'))
                    self.assertFalse(hasattr(win.header,'narration_button'))
                    for button in (win.header.project_menu_button,win.header.save_button,
                                   win.header.export_button):
                        self.assertTrue(button.isVisible())
                        self.assertGreaterEqual(button.width(),button.sizeHint().width())
                    self.assertIs(win.side_tabs.widget(2),win.narration_panel)
                    self.assertIs(win.side_tabs.widget(3),win.captions_panel)
                    self.assertGreaterEqual(win.side_tabs.width(),150)
                    self.assertEqual([win.side_tabs.tabText(i) for i in range(4)],
                                     ['IA','Clipes','Voz','Leg.'])
                    self.assertEqual(win.actions_panel.horizontalScrollBar().maximum(),0)
                    self.assertEqual(win.actions_panel.widget().width(),
                                     win.actions_panel.viewport().width())
                    self.assertEqual(win.transport._compact,win.transport.width()<680)
                    self.assertEqual(win.transport.volume.accessibleName(),'Volume da prévia')
                    if win.transport._compact:
                        self.assertEqual(win.transport.quality.itemText(0),'640 px')
                        for widget in (win.transport.begin_button,win.transport.end_button,
                                       win.transport.volume_label,win.transport.final_frame_button):
                            self.assertFalse(widget.isVisible())
                    else:
                        self.assertEqual(win.transport.quality.itemText(0),'Leve · 640px')
                    controls=(win.transport.back_button,win.transport.previous_frame_button,
                              win.transport.play_button,win.transport.next_frame_button,
                              win.transport.forward_button,win.transport.time_label,
                              win.transport.quality,win.transport.volume)
                    right=-1
                    for control in controls:
                        if not control.isVisible():continue
                        x=control.mapTo(win.transport,QPoint(0,0)).x()
                        self.assertGreaterEqual(x,right)
                        right=x+control.width()
                    self.assertLessEqual(right,win.transport.width())
                else:
                    self.assertTrue(win.header.local_status.isVisible())
                    self.assertFalse(hasattr(win.header,'ai_button'))
                    self.assertFalse(hasattr(win.header,'narration_button'))
                    self.assertFalse(win.transport._compact)
                    self.assertEqual(win.transport.quality.itemText(0),'Leve · 640px')
                jobs=rect(win.process_panel);timeline=rect(timeline_box)
                self.assertLess(win.process_panel.height(),60)
                self.assertLessEqual(jobs.bottom(),timeline.top())
                if width<=1366 and height<=768:
                    self.assertGreater(win.timeline.view.verticalScrollBar().maximum(),0,
                                       'faixas inferiores da timeline precisam continuar acessíveis')
                if width==1366:
                    timeline_before=timeline_box.geometry()
                    win.process_panel.begin('Teste de faixa de trabalho',ProcessControl())
                    self.app.processEvents()
                    self.assertLessEqual(win.process_panel.height(),53)
                    jobs=rect(win.process_panel);timeline=rect(timeline_box)
                    self.assertLessEqual(jobs.bottom(),timeline.top())
                    self.assertEqual(timeline_box.geometry(),timeline_before,
                                     'a barra de progresso no cabeçalho não deve encolher a timeline')
                    win.process_panel.finish('concluido')
            finally:
                win.close()

    def test_window_geometry_and_panel_widths_persist_on_reopen(self):
        first=MainWindow()
        first.resize(780,620);first.show();self.app.processEvents()
        first.horizontal.setSizes([300,520,360]);self.app.processEvents()
        first.workspace_splitter.setSizes([300,200]);self.app.processEvents()
        first.preview_quality.setCurrentIndex(2)
        first.transport.volume.setValue(42)
        first.side_tabs.setCurrentWidget(first.props_scroll)
        first.timeline.view.zoom(2.0)
        first.snap_btn.setChecked(False)
        expected_size=first.size()
        expected_panels=first.horizontal.sizes()
        expected_workspace=first.workspace_splitter.sizes()
        first.close();self.app.processEvents()

        reopened=MainWindow()
        try:
            reopened.show();self.app.processEvents()
            self.assertEqual(reopened.size(),expected_size)
            self.assertEqual(reopened.horizontal.sizes(),expected_panels)
            self.assertEqual(reopened.workspace_splitter.sizes(),expected_workspace)
            self.assertEqual(reopened.preview_quality.currentIndex(),2)
            self.assertEqual(reopened.transport.volume.value(),42)
            self.assertIs(reopened.side_tabs.currentWidget(),reopened.props_scroll)
            self.assertAlmostEqual(reopened.timeline.view.pps,42.0)
            self.assertFalse(reopened.snap_btn.isChecked())
            self.assertFalse(reopened.timeline.view.snapping)
        finally:
            reopened.close()

    def test_project_menu_restores_default_layout_without_editing_project(self):
        win=MainWindow()
        try:
            win.resize(1000,700);win.show();self.app.processEvents()
            clip=win.project.add_clip(Clip(source='preserved.mp4',start=1,end=4,
                                           track_id=win.project.tracks[0].id))
            before=(clip.id,clip.source,clip.start,clip.end,clip.timeline_start)
            win.horizontal.setSizes([76,220,240,220])
            win.workspace_splitter.setSizes([180,320])
            win.side_tabs.setCurrentIndex(2)
            win.timeline.view.pps=73.

            win._header_project_action('reset_layout')
            self.app.processEvents()

            self.assertEqual(win.side_tabs.currentIndex(),0)
            self.assertEqual(win.timeline.view.pps,21.)
            self.assertTrue(all(size>0 for size in win.horizontal.sizes()))
            self.assertTrue(all(size>0 for size in win.workspace_splitter.sizes()))
            self.assertEqual((clip.id,clip.source,clip.start,clip.end,clip.timeline_start),before)
            self.assertIn('Restaurar layout padrão',
                          [action.text() for action in win.header.project_menu_button.menu().actions()])
        finally:
            win.close()

    def test_visible_select_and_blade_tools_follow_keyboard_modes(self):
        win=MainWindow()
        try:
            win.resize(1000,700);win.show();self.app.processEvents()
            self.assertTrue(win.select_tool_btn.isVisible())
            self.assertTrue(win.blade_tool_btn.isVisible())
            self.assertTrue(win.slide_tool_btn.isVisible())
            self.assertTrue(win.select_tool_btn.isChecked())
            self.assertFalse(win.blade_tool_btn.isChecked())
            self.assertFalse(win.slide_tool_btn.isChecked())

            win.slide_tool_btn.click()
            self.assertTrue(win.timeline.view.slide_mode)
            self.assertTrue(win.slide_tool_btn.isChecked())
            self.assertFalse(win.select_tool_btn.isChecked())
            QTest.keyClick(win.timeline.view,Qt.Key.Key_V)
            self.assertFalse(win.timeline.view.slide_mode)
            self.assertTrue(win.select_tool_btn.isChecked())

            win.blade_tool_btn.click()
            self.assertTrue(win.timeline.view.blade_mode)
            self.assertTrue(win.blade_tool_btn.isChecked())
            self.assertFalse(win.select_tool_btn.isChecked())
            QTest.keyClick(win.timeline.view,Qt.Key.Key_V)
            self.assertFalse(win.timeline.view.blade_mode)
            self.assertTrue(win.select_tool_btn.isChecked())
            QTest.keyClick(win.timeline.view,Qt.Key.Key_B)
            self.assertTrue(win.timeline.view.blade_mode)
            self.assertTrue(win.blade_tool_btn.isChecked())
            QTest.keyClick(win.timeline.view,Qt.Key.Key_G)
            self.assertFalse(win.timeline.view.blade_mode)
            self.assertTrue(win.timeline.view.slide_mode)
            self.assertTrue(win.slide_tool_btn.isChecked())
        finally:
            win.close()

    def test_audio_selection_does_not_show_video_transform_handles(self):
        win=MainWindow()
        try:
            clip=win.project.add_clip(Clip(source='voice.wav',start=0,end=3,
                kind='audio',track_id=win.project.tracks[1].id))
            win.refresh([clip.id])
            self.assertEqual(win.selected_ids,[clip.id])
            self.assertIsNone(win.preview_image.selection)
        finally:
            win.close()

    def test_pitch_preservation_toggle_is_project_edit_with_undo(self):
        win=MainWindow()
        try:
            group='pitch_pair'
            video=win.project.add_clip(Clip(source='movie.mp4',start=0,end=3,speed=2,
                kind='video',include_audio=False,group_id=group,
                track_id=win.project.tracks[0].id))
            audio=win.project.add_clip(Clip(source='movie.mp4',start=0,end=3,speed=2,
                kind='audio',group_id=group,track_id=win.project.tracks[1].id))
            win.refresh([audio.id])
            toggle=win.findChild(QCheckBox,'preservePitch')
            self.assertIsNotNone(toggle)
            toggle.setChecked(True)
            self.assertTrue(win.project.clip(video.id).preserve_pitch)
            self.assertTrue(win.project.clip(audio.id).preserve_pitch)
            win.undo()
            self.assertFalse(win.project.clip(video.id).preserve_pitch)
            self.assertFalse(win.project.clip(audio.id).preserve_pitch)
        finally:
            win.close()

    def test_volume_keyframe_edits_are_undoable_and_keep_other_points(self):
        win=MainWindow()
        try:
            clip=win.project.add_clip(Clip(source='voice.wav',start=0,end=4,
                kind='audio',track_id=win.project.tracks[1].id,
                keyframes={'volume':[{'t':.5,'value':.4,'easing':'linear'},
                                     {'t':2.,'value':1.2,'easing':'smooth'}]}))
            win.refresh([clip.id])
            win.timeline.volume_keyframe_changed.emit(clip.id,.5,.8,.9)
            self.assertEqual(clip.keyframes['volume'][0],
                {'t':.8,'value':.9,'easing':'linear'})
            self.assertEqual(clip.keyframes['volume'][1]['t'],2.)
            win.timeline.volume_keyframe_delete_requested.emit(clip.id,2.)
            self.assertEqual(len(win.project.clip(clip.id).keyframes['volume']),1)
            win.undo()
            restored=win.project.clip(clip.id)
            self.assertEqual(len(restored.keyframes['volume']),2)
            self.assertAlmostEqual(restored.keyframes['volume'][0]['t'],.8)
            win.undo()
            restored=win.project.clip(clip.id)
            self.assertEqual(restored.keyframes['volume'][0],
                {'t':.5,'value':.4,'easing':'linear'})
            self.assertEqual(restored.keyframes['volume'][1]['value'],1.2)
        finally:
            win.close()

    def test_frame_step_uses_project_rate_and_clamps_at_sequence_edges(self):
        win=MainWindow()
        try:
            win.show();self.app.processEvents();win.timeline.view.setFocus()
            win.project.fps=24
            win.project.add_clip(Clip(source='frame-test.mp4',start=0,end=2,
                                      track_id=win.project.tracks[0].id))
            win.timeline.set_cursor(1.)
            QTest.keyClick(win.timeline.view,Qt.Key.Key_Period)
            self.assertAlmostEqual(win.timeline.view.cursor_time,1+1/24)
            QTest.keyClick(win.timeline.view,Qt.Key.Key_Comma)
            self.assertAlmostEqual(win.timeline.view.cursor_time,1.)
            win.timeline.set_cursor(0.)
            win.step_frame(-1)
            self.assertEqual(win.timeline.view.cursor_time,0.)
            win.timeline.set_cursor(win.project.duration)
            win.step_frame(1)
            self.assertEqual(win.timeline.view.cursor_time,win.project.duration)
        finally:
            win.close()

    def test_timeline_audio_fade_signal_uses_undoable_project_edit(self):
        win=MainWindow()
        try:
            clip=win.project.add_clip(Clip(source='voice.wav',start=0,end=3,
                kind='audio',track_id=win.project.tracks[1].id,audio_fade_in=.25))
            win.refresh([clip.id])
            win.timeline.audio_fade_changed.emit(clip.id,'audio_fade_in',.8)
            self.assertAlmostEqual(win.project.clip(clip.id).audio_fade_in,.8)
            win.undo()
            self.assertAlmostEqual(win.project.clip(clip.id).audio_fade_in,.25)
        finally:
            win.close()

    def test_blade_split_of_group_with_locked_audio_is_atomic_and_creates_no_undo_step(self):
        win=MainWindow()
        try:
            group='linked_test'
            video=win.project.add_clip(Clip('source.mp4',0,4,kind='video',
                track_id=win.project.tracks[0].id,group_id=group))
            audio=win.project.add_clip(Clip('source.mp4',0,4,kind='audio',
                track_id=win.project.tracks[1].id,group_id=group))
            win.project.track(audio.track_id).locked=True
            history_size=len(win.history)
            win.split_on_blade(video.id,2.)
            self.assertEqual(len(win.project.clips),2)
            self.assertEqual((video.start,video.end),(0,4))
            self.assertEqual((audio.start,audio.end),(0,4))
            self.assertEqual(len(win.history),history_size)
            self.assertIn('desbloqueie',win.statusBar().currentMessage())
        finally:
            win.close()

    def test_inspector_edits_bezier_control_points_reversibly(self):
        win=MainWindow()
        try:
            clip=win.project.add_clip(Clip('',0,2,track_id=win.project.tracks[0].id,
                keyframes={'scale':[{'t':.5,'value':1.2,'easing':'bezier',
                                     'bezier_c1':.1,'bezier_c2':.9},
                                    {'t':1.5,'value':1.8,'easing':'linear'}]}))
            win.refresh([clip.id])
            index=win.ease_combo.findData('bezier')
            self.assertGreaterEqual(index,0)
            self.assertEqual(win.ease_combo.itemText(index),'Bézier suave')
            win.timeline.set_cursor(.5)
            win._load_keyframe_curve_at_cursor()
            self.assertFalse(win.bezier_controls.isHidden())
            self.assertTrue(win.key_apply_curve.isEnabled())
            before=len(win.history)
            win.bezier_c1.setValue(.3);win.bezier_c2.setValue(.7)
            win.apply_keyframe_curve()
            point=win.project.clip(clip.id).keyframes['scale'][0]
            self.assertAlmostEqual(point['bezier_c1'],.3)
            self.assertAlmostEqual(point['bezier_c2'],.7)
            self.assertEqual(len(win.history),before+1)
            win.undo()
            point=win.project.clip(clip.id).keyframes['scale'][0]
            self.assertAlmostEqual(point['bezier_c1'],.1)
            self.assertAlmostEqual(point['bezier_c2'],.9)
        finally:
            win.close()

    def test_timeline_keyframe_retime_is_undoable_and_rejects_collision(self):
        win=MainWindow()
        try:
            clip=win.project.add_clip(Clip(source='',start=0,end=3,
                track_id=win.project.tracks[0].id,
                keyframes={'scale':[{'t':.5,'value':1.2,'easing':'smooth'},
                                    {'t':1.5,'value':1.6,'easing':'linear'}]}))
            win.refresh([clip.id])
            before=len(win.history)
            win.timeline.keyframe_time_changed.emit(clip.id,'scale',.5,.8)
            points=win.project.clip(clip.id).keyframes['scale']
            self.assertAlmostEqual(points[0]['t'],.8)
            self.assertEqual(points[0]['easing'],'smooth')
            self.assertEqual(len(win.history),before+1)
            win.timeline.keyframe_time_changed.emit(clip.id,'scale',.8,1.5)
            self.assertEqual(win.project.clip(clip.id).keyframes['scale'][0]['t'],.8)
            self.assertEqual(len(win.history),before+1)
            win.undo()
            self.assertAlmostEqual(win.project.clip(clip.id).keyframes['scale'][0]['t'],.5)
        finally:
            win.close()

    def test_timeline_keyframe_delete_is_undoable(self):
        win=MainWindow()
        try:
            clip=win.project.add_clip(Clip(source='',start=0,end=3,
                track_id=win.project.tracks[0].id,
                keyframes={'scale':[{'t':.75,'value':1.4,'easing':'smooth'}]}))
            win.refresh([clip.id])
            before=len(win.history)
            win.timeline.keyframe_delete_requested.emit(clip.id,'scale',.75)
            self.assertEqual(win.project.clip(clip.id).keyframes.get('scale',[]),[])
            self.assertEqual(len(win.history),before+1)
            win.undo()
            point=win.project.clip(clip.id).keyframes['scale'][0]
            self.assertEqual(point,{'t':.75,'value':1.4,'easing':'smooth'})
        finally:
            win.close()

    def test_legacy_style_library_filters_media_and_navigates_markers(self):
        from berofel.ui.library_panel import LibraryDock
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            media=[]
            for name in ('gameplay.mp4','voice.wav','cover.png'):
                path=root/name;path.write_bytes(b'fixture');media.append(str(path))
            dock=LibraryDock()
            dock.set_media(media)
            self.assertEqual(dock.media_list.count(),3)
            dock.type_filter.setCurrentIndex(dock.type_filter.findData('audio'))
            self.assertEqual(sum(not dock.media_list.isRowHidden(i)
                                 for i in range(dock.media_list.count())),1)
            self.assertIn('voice.wav',dock.media_list.item(1).text())
            dock.type_filter.setCurrentIndex(dock.type_filter.findData('all'))
            dock.search.setText('cover')
            self.assertEqual(sum(not dock.media_list.isRowHidden(i)
                                 for i in range(dock.media_list.count())),1)
            dock.set_markers([{'time':73.5,'label':'Gancho'}])
            times=[];dock.marker_activated.connect(times.append)
            dock.show_page('markers')
            dock.marker_list.itemDoubleClicked.emit(dock.marker_list.item(0))
            self.assertEqual(times,[73.5])
            self.assertTrue(dock.nav_buttons['markers'].isChecked())
            dock.close()

    def test_open_project_offers_newer_autosave_and_preserves_original(self):
        with tempfile.TemporaryDirectory() as folder:
            original=Path(folder)/'project.berofel.json'
            backup=Path(str(original)+'.autosave')
            Project(name='saved').save(str(original))
            original_bytes=original.read_bytes()
            Project(name='recovered').save(str(backup))
            stamp=original.stat().st_mtime_ns+2_000_000
            os.utime(backup,ns=(stamp,stamp))
            win=MainWindow()
            try:
                with patch('berofel.ui.window.QFileDialog.getOpenFileName',
                           return_value=(str(original),'')), \
                     patch('berofel.ui.window.QMessageBox.question',
                           return_value=QMessageBox.StandardButton.Yes) as prompt:
                    win.open_project()
                prompt.assert_called_once()
                self.assertEqual(win.project.name,'recovered')
                self.assertEqual(Path(win.project.path),original.resolve())
                self.assertEqual(original.read_bytes(),original_bytes)
            finally:
                win.close()

    def test_autosave_writes_a_single_snapshot_off_the_ui_thread(self):
        with tempfile.TemporaryDirectory() as folder:
            original=Path(folder)/'project.berofel.json'
            Project(name='saved').save(str(original))
            win=MainWindow()
            win.project=Project(name='snapshot',path=str(original))
            entered=threading.Event();release=threading.Event()
            calls=[]
            def slow_write(snapshot,path,*args,**kwargs):
                calls.append((snapshot,path,threading.get_ident()))
                entered.set()
                release.wait(3)
                return write_autosave_snapshot(snapshot,path,*args,**kwargs)
            ui_thread=threading.get_ident()
            try:
                with patch('berofel.ui.window.write_autosave_snapshot',side_effect=slow_write):
                    started=time.monotonic()
                    win._autosave()
                    elapsed=time.monotonic()-started
                    self.assertLess(elapsed,.5,'O autosave bloqueou a interface.')
                    self.assertTrue(entered.wait(2),'O worker não iniciou o autosave.')
                    task=win._autosave_task
                    win._autosave()
                    self.assertIs(win._autosave_task,task)
                    self.assertEqual(len(calls),1,'Foram iniciados autosaves simultâneos.')
                    self.assertNotEqual(calls[0][2],ui_thread)
                    release.set()
                    self.assertTrue(QThreadPool.globalInstance().waitForDone(3000))
                    QApplication.processEvents()
                self.assertEqual(win.project.path,str(original))
                self.assertEqual(Project.load(str(original)+'.autosave').name,'snapshot')
            finally:
                release.set()
                QThreadPool.globalInstance().waitForDone(3000)
                win.close()

    def test_missing_library_media_can_be_relinked_from_the_ui(self):
        with tempfile.TemporaryDirectory() as folder:
            from PIL import Image
            old=str(Path(folder)/'offline'/'footage.png')
            restored=Path(folder)/'restored'/'footage.png'
            restored.parent.mkdir();Image.new('RGB',(160,90),'teal').save(restored)
            win=MainWindow()
            win.project=Project(media=[old])
            clip=win.project.add_clip(Clip(old,0,1,kind='image',
                                           track_id=win.project.tracks[0].id))
            try:
                win.refresh([clip.id])
                item=win.media_list.item(0)
                self.assertIn('ausente',item.text())
                win.media_list.setCurrentItem(item)
                with patch('berofel.ui.window.QFileDialog.getOpenFileName',
                           return_value=(str(restored),'')):
                    win.relink_selected_media()
                self.assertEqual(win.project.clip(clip.id).source,str(restored.resolve()))
                self.assertIn(str(restored.resolve()),win.project.media)
                self.assertNotIn('ausente',win.media_list.item(0).text())
            finally:
                win.close()
                self.assertFalse(win._frame_debounce.isActive())

    def test_track_context_mixer_changes_gain_and_pan_reversibly(self):
        from PySide6.QtWidgets import QDialog, QDoubleSpinBox
        win=MainWindow()
        track=win.project.tracks[0]
        def accept_with_values(dialog):
            controls=dialog.findChildren(QDoubleSpinBox)
            controls[0].setValue(.55)
            controls[1].setValue(.8)
            return QDialog.DialogCode.Accepted
        try:
            with patch('PySide6.QtWidgets.QDialog.exec',accept_with_values):
                win.track_action(track.id,'mix')
            self.assertAlmostEqual(track.volume,.55)
            self.assertAlmostEqual(track.pan,.8)
            self.assertEqual((win.history[-1].tracks[0].volume,
                              win.history[-1].tracks[0].pan),(1.,0.))
        finally:
            win.close()

    def test_separate_audio_preserves_processing_automation_and_track_mix(self):
        win=MainWindow()
        project=Project()
        source_track=project.tracks[1]
        source_track.volume=.62;source_track.pan=.3
        source_track.muted=True;source_track.solo=True
        video=project.add_clip(Clip('source.mp4',2,12,track_id=source_track.id,
            timeline_start=4,source_length=30,speed=1.5,volume=.75,
            audio_fade_in=.3,audio_fade_out=.4,audio_highpass=400,
            audio_lowpass=12000,audio_denoise=True,preserve_pitch=True))
        put_keyframe(video,'volume',2,.5)
        win.project=project;win.refresh([video.id])
        try:
            with patch('berofel.ui.window.media_info',return_value=(30.,True,True)):
                win.separate_audio()
            audio=next(clip for clip in win.project.clips if clip.kind=='audio')
            audio_track=win.project.track(audio.track_id)
            self.assertFalse(win.project.clip(video.id).include_audio)
            self.assertEqual((audio.start,audio.end,audio.timeline_start,audio.speed),
                             (2,12,4,1.5))
            self.assertEqual((audio.volume,audio.audio_fade_in,audio.audio_fade_out),
                             (.75,.3,.4))
            self.assertEqual((audio.audio_highpass,audio.audio_lowpass,audio.audio_denoise),
                             (400,12000,True))
            self.assertTrue(audio.preserve_pitch)
            self.assertEqual(audio.keyframes['volume'],[{'t':2.,'value':.5,'easing':'linear'}])
            self.assertEqual((audio_track.volume,audio_track.pan,audio_track.muted,audio_track.solo),
                             (.62,.3,True,True))
            win.undo()
            self.assertTrue(win.project.clip(video.id).include_audio)
            self.assertEqual(len(win.project.tracks),4)
            self.assertFalse(any(clip.kind=='audio' for clip in win.project.clips))
        finally:
            win.close()

    def test_separated_audio_export_keeps_stereo_pan_and_fades(self):
        import numpy as np
        import wave
        from berofel.services.ffmpeg import ffmpeg_path,media_info
        from berofel.services.export_multitrack import export_project
        with tempfile.TemporaryDirectory(prefix='bfs_separate_audio_export_') as folder:
            root=Path(folder);source=root/'source.mp4';destination=root/'separated.mp4'
            subprocess.run([ffmpeg_path(),'-hide_banner','-loglevel','error','-y',
                '-f','lavfi','-i','color=c=navy:s=160x90:r=12:d=2',
                '-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=2',
                '-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p',
                '-c:a','aac','-shortest',str(source)],check=True,capture_output=True,timeout=30)
            win=MainWindow()
            project=Project(width=160,height=90,fps=12)
            track=project.tracks[1];track.volume=.6;track.pan=-1.;track.solo=True
            video=project.add_clip(Clip(str(source),0,2,track_id=track.id,
                source_length=2,audio_fade_in=.25,audio_fade_out=.25))
            win.project=project;win.refresh([video.id])
            try:
                win.separate_audio()
                export_project(win.project,str(destination))
                duration,has_video,has_audio=media_info(str(destination))
                self.assertTrue(has_video and has_audio)
                self.assertAlmostEqual(duration,2.,delta=.12)
                decoded=root/'decoded.wav'
                subprocess.run([ffmpeg_path(),'-hide_banner','-loglevel','error','-y',
                    '-i',str(destination),'-map','0:a:0','-c:a','pcm_s16le',str(decoded)],
                    check=True,capture_output=True,timeout=30)
                with wave.open(str(decoded),'rb') as stream:
                    self.assertEqual(stream.getnchannels(),2)
                    rate=stream.getframerate()
                    pcm=np.frombuffer(stream.readframes(stream.getnframes()),dtype='<i2')
                pcm=pcm.reshape((-1,2)).astype(np.float64)
                def rms(channel,at,duration=.08):
                    start=round(at*rate);stop=round((at+duration)*rate)
                    return float(np.sqrt(np.mean(pcm[start:stop,channel]**2)))
                middle=rms(0,.75)
                self.assertGreater(middle,100,'A faixa separada precisa continuar audível.')
                self.assertLess(rms(1,.75),middle*.08,
                                'O balanço panorâmico da faixa não foi preservado.')
                self.assertLess(rms(0,.03),middle*.35,'O fade de entrada não chegou à exportação.')
                self.assertLess(rms(0,1.92),middle*.35,'O fade de saída não chegou à exportação.')
            finally:
                win.close()

    def test_track_solo_is_undoable(self):
        win=MainWindow()
        track=win.project.tracks[0]
        try:
            win.track_action(track.id,'solo')
            self.assertTrue(track.solo)
            self.assertFalse(win.history[-1].tracks[0].solo)
        finally:
            win.close()

    def test_track_header_controls_have_accessible_actions_and_distinct_states(self):
        from berofel.ui.timeline import TrackHeader
        track=Project().tracks[0]
        track.hidden=True;track.muted=True;track.solo=True;track.locked=True
        header=TrackHeader(track,70)
        actions=[];header.change_requested.connect(lambda track_id,action:actions.append((track_id,action)))
        for action in ('up','down','hide','mute','solo','lock'):
            button=header.findChild(QToolButton,f'trackAction_{action}')
            self.assertIsNotNone(button)
            self.assertTrue(button.accessibleName())
            if action in ('hide','mute','solo','lock'):
                self.assertTrue(button.isChecked())
                self.assertIn(f'trackAction_{action}:checked',header.styleSheet())
            button.click()
        self.assertEqual([action for _,action in actions],
                         ['up','down','hide','mute','solo','lock'])
        self.assertTrue(all(track_id==track.id for track_id,_ in actions))
        header.close()

if __name__=='__main__':unittest.main()

