"""Tests for the opt-in Pure C Qwen3 Base adapter."""
from __future__ import annotations

import os
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from contextlib import contextmanager
from unittest.mock import patch

import numpy as np
import psutil

from berofel.services import qwen3_purec_tts as purec
from berofel.services.narration_service import NarrationRequest, generate_narration


@contextmanager
def _isolated_qsettings(folder):
    """Keep opt-in GUI integration tests from overwriting user preferences."""
    from PySide6.QtCore import QSettings
    original=QSettings(QSettings.Format.IniFormat,QSettings.Scope.UserScope,
                       'Berofel','BerofelStudio').fileName()
    target=Path(folder)/'test_settings'
    target.mkdir(parents=True,exist_ok=True)
    QSettings.setPath(QSettings.Format.IniFormat,QSettings.Scope.UserScope,str(target))
    try:
        yield
    finally:
        QSettings.setPath(QSettings.Format.IniFormat,QSettings.Scope.UserScope,
                          str(Path(original).parent))


class PureCTests(unittest.TestCase):
    def test_runtime_caps_openblas_to_one_thread(self):
        with patch.dict(os.environ, {'OPENBLAS_NUM_THREADS': '16',
                                    'BEROFEL_QWEN3_PUREC_THREADS': '4'}, clear=False):
            env = purec._environment(Path('qwen_tts.exe'), [])
        self.assertEqual(env['OMP_NUM_THREADS'], '4')
        self.assertEqual(env['OPENBLAS_NUM_THREADS'], '1')

    def test_explicit_thread_budget_overrides_environment_and_is_bounded(self):
        with patch.dict(os.environ, {'BEROFEL_QWEN3_PUREC_THREADS': '4'}, clear=False):
            self.assertEqual(purec.threads_for_engine(8),8)
            self.assertEqual(purec.threads_for_engine(99),8)
            self.assertEqual(purec.threads_for_engine(1),2)
            self.assertEqual(purec.threads_for_engine(),4)

    def test_profile_validator_accepts_only_finite_1024_float_vectors(self):
        with tempfile.TemporaryDirectory() as folder:
            profile = Path(folder) / 'voice.bin'
            np.ones(1024, dtype='<f4').tofile(profile)
            self.assertTrue(purec._valid_profile(profile))
            np.full(1024, np.nan, dtype='<f4').tofile(profile)
            self.assertFalse(purec._valid_profile(profile))
            profile.write_bytes(b'too short')
            self.assertFalse(purec._valid_profile(profile))

    def test_runtime_requires_base_weights_and_runtime_directories(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            exe = root / 'bin' / 'qwen_tts.exe'; exe.parent.mkdir()
            exe.write_bytes(b'exe')
            model = root / 'model'; (model / 'speech_tokenizer').mkdir(parents=True)
            (model / 'config.json').write_text('{}', encoding='utf-8')
            (model / 'model.safetensors').write_bytes(b'weights')
            (model / 'speech_tokenizer' / 'model.safetensors').write_bytes(b'codec')
            runtime = root / 'msys'; runtime.mkdir()
            with patch.dict(os.environ, {
                'BEROFEL_QWEN3_PUREC_EXE': str(exe),
                'BEROFEL_QWEN3_PUREC_MODEL': str(model),
                'BEROFEL_QWEN3_PUREC_RUNTIME_PATHS': str(runtime),
            }, clear=False):
                self.assertTrue(purec.is_ready())
                (model / 'speech_tokenizer' / 'model.safetensors').unlink()
                self.assertFalse(purec.is_ready())

    def test_canonical_service_routes_purec_without_changing_original_default(self):
        with tempfile.TemporaryDirectory() as folder:
            voice = Path(folder) / 'voice.wav'; voice.write_bytes(b'authorized sample' * 8)
            default = NarrationRequest(text='Teste', voice=str(voice), consent=True)
            turbo = NarrationRequest(text='Teste', voice=str(voice), consent=True,
                                     engine=purec.ENGINE_ID)
            balanced = NarrationRequest(text='Teste', voice=str(voice), consent=True,
                                        engine=purec.ENGINE_INT8_ID)
            self.assertEqual(default.engine, 'qwen3-tts-local')
            with patch.object(purec, 'generate_purec_clone',
                              side_effect=lambda req, **_: {'engine': req.engine}) as backend:
                self.assertEqual(generate_narration(turbo)['engine'], purec.ENGINE_ID)
                self.assertEqual(generate_narration(balanced)['engine'], purec.ENGINE_INT8_ID)
            self.assertEqual(backend.call_count, 2)

    def test_quantization_modes_are_explicit_and_distinct(self):
        self.assertEqual(purec._quantization_flag(purec.ENGINE_ID), ['--quant-mixed-cpu'])
        self.assertEqual(purec._quantization_flag(purec.ENGINE_INT8_ID), ['--int8'])
        with self.assertRaises(ValueError):
            purec._quantization_flag('unsupported')


@unittest.skipUnless(os.environ.get('BEROFEL_RUN_PUREC_TURBO_INTEGRATION') == '1',
                     'Defina BEROFEL_RUN_PUREC_TURBO_INTEGRATION=1 para usar o backend local compilado.')
class PureCRealIntegrationTests(unittest.TestCase):
    def test_real_profile_generation_stream_and_wave_through_canonical_service(self):
        from berofel.services.voice_profiles import VoiceProfileManager
        profile = next(item for item in VoiceProfileManager().list_profiles()
                       if item.get('authorized') and item.get('reference_text'))
        test_engine = os.environ.get('BEROFEL_PUREC_TEST_ENGINE', purec.ENGINE_ID)
        with tempfile.TemporaryDirectory(prefix='bfs_purec_real_test_') as work:
            with patch.dict(os.environ, {'BEROFEL_QWEN3_PUREC_PROFILE_CACHE': work}, clear=False):
                source = Path(work) / 'authorized_reference.wav'
                from berofel.services.audio_reference import prepare_audio_prompt
                prepare_audio_prompt(profile['sample_path'], source)
                # Add 100 ms to create a distinct disposable test fixture without
                # modifying or duplicating the user's source outside this temp dir.
                with __import__('wave').open(str(source), 'rb') as wav:
                    rate=wav.getframerate();pcm=wav.readframes(wav.getnframes())
                with __import__('wave').open(str(source), 'wb') as wav:
                    wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(rate)
                    wav.writeframes(pcm + np.zeros(rate // 10, dtype='<i2').tobytes())
                chunks = []
                request = NarrationRequest(
                    text='O Berofel Studio está testando a narração local com Qwen Base.',
                    voice=str(source), reference_text=profile['reference_text'],
                    language='portuguese', consent=True, engine=test_engine,
                    title='Pure C integração',
                    project_path=str(Path(work) / 'project.bfsproj'))
                result = generate_narration(request, audio_chunk=chunks.append)
                path = Path(result['path'])
                self.assertTrue(path.is_file())
                with __import__('wave').open(str(path), 'rb') as wav:
                    self.assertEqual(wav.getframerate(), 24000)
                    self.assertEqual(wav.getnchannels(), 1)
                    self.assertGreater(wav.getnframes(), 24000)
                    samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype='<i2')
                self.assertGreater(float(np.sqrt(np.mean(samples.astype(np.float32) ** 2))), 100)
                self.assertGreater(result['streamed_pcm_bytes'], 0)
                self.assertGreater(result['streamed_chunk_count'], 0)
                self.assertTrue(chunks)
                stage_fields=(
                    'payload_prepare_seconds','http_headers_seconds',
                    'stream_read_seconds','wav_write_seconds',
                    'pcm_analysis_seconds','pcm_to_float_seconds',
                    'audio_callback_seconds','wav_close_seconds',
                    'wav_replace_seconds')
                self.assertTrue(all(np.isfinite(result[field]) and result[field]>=0
                                    for field in stage_fields))
                self.assertGreater(result['http_headers_seconds'],0)
                self.assertGreater(result['stream_read_seconds'],0)
                self.assertGreater(result['wav_write_seconds'],0)
                self.assertGreater(result['wav_close_seconds'],0)
                self.assertGreater(result['wav_replace_seconds'],0)
                self.assertGreaterEqual(result['generation_seconds'],
                                        result['first_audio_chunk_seconds'])
                self.assertFalse(result['profile_cache_hit'])
                self.assertGreater(result['profile_prepare_seconds'], 0)
                self.assertGreater(result['model_load_seconds'], 0)
                self.assertEqual(result['engine'], test_engine)
                self.assertIsNotNone(purec._PROCESS)
                server_process = psutil.Process(purec._PROCESS.pid)
                listeners = [connection.laddr.ip for connection in
                             server_process.net_connections(kind='inet')
                             if connection.status == psutil.CONN_LISTEN]
                self.assertTrue(listeners, 'Pure C HTTP server did not expose a listener')
                self.assertEqual(set(listeners), {'127.0.0.1'},
                                 'Pure C server must bind only loopback')
                first_server_pid = purec._PROCESS.pid
                print('PUREC_REAL_RESULT ' + json.dumps({
                    key: result.get(key) for key in ('engine', 'duration', 'threads',
                        'profile_cache_hit', 'profile_prepare_seconds', 'model_load_seconds',
                        'generation_seconds', 'first_audio_chunk_seconds',
                        'streamed_pcm_bytes', 'streamed_chunk_count',
                        'payload_prepare_seconds','http_headers_seconds',
                        'stream_read_seconds','wav_write_seconds',
                        'pcm_analysis_seconds','pcm_to_float_seconds',
                        'audio_callback_seconds','wav_close_seconds',
                        'wav_replace_seconds')}, ensure_ascii=False))

                # A new text must reuse both the prepared voice vector and the
                # loaded model/server; only text synthesis should run again.
                from dataclasses import replace
                second_chunks = []
                second_request = replace(
                    request,
                    text='Esta é uma segunda frase inédita para validar o reuso local da voz.',
                    title='Pure C integração reuso')
                second_result = generate_narration(second_request,
                                                   audio_chunk=second_chunks.append)
                second_path = Path(second_result['path'])
                self.assertTrue(second_path.is_file())
                with __import__('wave').open(str(second_path), 'rb') as wav:
                    self.assertEqual(wav.getframerate(), 24000)
                    self.assertGreater(wav.getnframes(), 24000)
                    second_samples = np.frombuffer(
                        wav.readframes(wav.getnframes()), dtype='<i2')
                self.assertGreater(float(np.sqrt(np.mean(
                    second_samples.astype(np.float32) ** 2))), 100)
                self.assertTrue(second_chunks)
                self.assertTrue(second_result['profile_cache_hit'])
                self.assertEqual(second_result['profile_prepare_seconds'], 0.0)
                self.assertEqual(second_result['model_load_seconds'], 0.0)
                self.assertEqual(purec._PROCESS.pid, first_server_pid)
                self.assertNotEqual(path, second_path)
                print('PUREC_REUSE_RESULT ' + json.dumps({
                    key: second_result.get(key) for key in (
                        'engine', 'duration', 'threads', 'profile_cache_hit',
                        'profile_prepare_seconds', 'model_load_seconds',
                        'generation_seconds', 'first_audio_chunk_seconds',
                        'streamed_pcm_bytes', 'streamed_chunk_count')}, ensure_ascii=False))


@unittest.skipUnless(os.environ.get('BEROFEL_RUN_PUREC_GUI_INTEGRATION') == '1',
                     'Defina BEROFEL_RUN_PUREC_GUI_INTEGRATION=1 para abrir o editor Qt.')
class PureCEditorIntegrationTests(unittest.TestCase):
    def test_user_selecting_saved_profile_prewarms_server_before_first_generation(self):
        import time
        from PySide6.QtWidgets import QApplication
        from berofel.ui.window import MainWindow
        from berofel.services.voice_profiles import VoiceProfileManager

        profile = next(item for item in VoiceProfileManager().list_profiles()
                       if item.get('authorized') and item.get('reference_text'))
        test_engine = os.environ.get('BEROFEL_PUREC_TEST_ENGINE', purec.ENGINE_ID)
        with tempfile.TemporaryDirectory(prefix='bfs_purec_prewarm_test_') as work:
            with patch.dict(os.environ, {'BEROFEL_QWEN3_PUREC_PROFILE_CACHE': work}, clear=False), \
                 _isolated_qsettings(work):
                app = QApplication.instance() or QApplication([])
                window = MainWindow()
                try:
                    window.project.path = str(Path(work) / 'prewarm_test.bfsproj')
                    window.show(); app.processEvents()
                    panel = window.narration_panel
                    voice_index = panel.voice.findData(f'voice-profile:{profile["id"]}')
                    engine_index = panel.clone_engine.findData(test_engine)
                    self.assertGreaterEqual(voice_index, 0)
                    self.assertGreaterEqual(engine_index, 0)
                    panel.voice.setCurrentIndex(voice_index)
                    panel.clone_engine.setCurrentIndex(engine_index)
                    # Simulate the user's explicit selection. Preference
                    # restoration uses currentIndexChanged and must not prewarm.
                    prewarm_started=time.perf_counter()
                    panel.clone_engine.activated.emit(engine_index)
                    deadline = time.monotonic() + 180
                    while (window._ai_busy or window.active_task is not None) and time.monotonic() < deadline:
                        app.processEvents(); time.sleep(.03)
                    prewarm_wall=time.perf_counter()-prewarm_started
                    app.processEvents()
                    self.assertFalse(window._ai_busy, 'Turbo prewarm did not finish')
                    self.assertIsNotNone(purec._PROCESS,
                        f'prewarm did not leave a server ready: {panel.status.text()} / {panel.clone_engine.currentData()} / {panel.voice.currentData()} / {window._ai_busy} / {window.active_task} / {[d.text() for d in window._open_error_dialogs]}')
                    server_pid = purec._PROCESS.pid
                    self.assertIsNone(purec._PROCESS.poll())

                    panel.text.setPlainText('Esta frase inédita confirma que a voz pré-carregada foi reutilizada.')
                    panel.name.setText('Teste de primeira geração após preparo')
                    original_start = purec._start_server
                    incremental_loads = []
                    generated_results = []
                    def record_load(*args, **kwargs):
                        result = original_start(*args, **kwargs)
                        incremental_loads.append(result[1])
                        return result
                    from functools import wraps
                    from berofel.services.narration_service import generate_narration as real_generate
                    @wraps(real_generate)
                    def record_generation(request, **kwargs):
                        result = real_generate(request, **kwargs)
                        generated_results.append(result)
                        return result
                    with patch.object(purec, '_start_server', side_effect=record_load), \
                         patch('berofel.ui.window.generate_narration',new=record_generation):
                        panel._generate(False)
                        deadline = time.monotonic() + 180
                        while (window._ai_busy or window.active_task is not None) and time.monotonic() < deadline:
                            app.processEvents(); time.sleep(.03)
                    app.processEvents()
                    self.assertFalse(window._ai_busy, 'first Turbo generation did not finish')
                    self.assertFalse(window._open_error_dialogs)
                    self.assertTrue(Path(panel.last_audio).is_file())
                    self.assertTrue(incremental_loads)
                    self.assertEqual(incremental_loads[-1], 0.0)
                    self.assertEqual(len(generated_results),1)
                    self.assertTrue(generated_results[0]['profile_cache_hit'])
                    self.assertEqual(generated_results[0]['profile_prepare_seconds'],0.0)
                    self.assertEqual(generated_results[0]['model_load_seconds'],0.0)
                    self.assertEqual(purec._PROCESS.pid, server_pid)
                    self.assertIsNotNone(window.narration_stream.first_chunk_latency_seconds,
                        'Pure C PCM chunks must reach the editor preview player.')
                    print('PUREC_PREWARM_GUI_RESULT ' + json.dumps({
                        key: generated_results[0].get(key) for key in (
                            'engine','duration','generation_seconds',
                            'first_audio_chunk_seconds','profile_prepare_seconds',
                            'model_load_seconds','profile_cache_hit')},ensure_ascii=False) +
                        f' prewarm_wall_seconds={prewarm_wall:.3f}')
                finally:
                    window.close(); app.processEvents()

    def test_editor_generates_and_inserts_purec_clip(self):
        import time
        from PySide6.QtWidgets import QApplication
        from berofel.ui.window import MainWindow
        from berofel.services.voice_profiles import VoiceProfileManager

        profile = next(item for item in VoiceProfileManager().list_profiles()
                       if item.get('authorized') and item.get('reference_text'))
        test_engine = os.environ.get('BEROFEL_PUREC_TEST_ENGINE', purec.ENGINE_ID)
        with tempfile.TemporaryDirectory(prefix='bfs_purec_editor_test_') as work:
            with patch.dict(os.environ, {'BEROFEL_QWEN3_PUREC_PROFILE_CACHE': work}, clear=False), \
                 _isolated_qsettings(work):
                app = QApplication.instance() or QApplication([])
                window = MainWindow(); window.project.path = str(Path(work) / 'editor_test.bfsproj')
                window.show(); app.processEvents()
                panel = window.narration_panel
                original = (panel.voice.currentIndex(), panel.clone_engine.currentIndex(),
                            panel.text.toPlainText(), panel.language.currentIndex(), panel.name.text(),
                            panel.purec_threads.currentIndex())
                profile_index = panel.voice.findData(f'voice-profile:{profile["id"]}')
                engine_index = panel.clone_engine.findData(test_engine)
                self.assertGreaterEqual(profile_index, 0)
                self.assertGreaterEqual(engine_index, 0)
                self.assertGreaterEqual(panel.clone_engine.findData(purec.ENGINE_INT8_ID), 0)
                for widget in (panel.voice, panel.clone_engine, panel.text, panel.language,
                               panel.name, panel.sample_path, panel.reference_text):
                    widget.blockSignals(True)
                panel.voice.setCurrentIndex(profile_index)
                panel.clone_engine.setCurrentIndex(engine_index)
                if test_engine == purec.ENGINE_ID:
                    panel.purec_threads.setCurrentIndex(panel.purec_threads.findData(8))
                panel.language.setCurrentIndex(panel.language.findData('portuguese'))
                panel.text.setPlainText('Esta narração está sendo inserida na timeline do editor.')
                title = f'Pure C editor test {test_engine}'
                panel.name.setText(title)
                panel._update_custom()
                for widget in (panel.voice, panel.clone_engine, panel.text, panel.language,
                               panel.name, panel.sample_path, panel.reference_text):
                    widget.blockSignals(False)
                panel._generate(True)
                deadline = time.monotonic() + 180
                while (window._ai_busy or window.active_task is not None) and time.monotonic() < deadline:
                    app.processEvents(); time.sleep(.03)
                app.processEvents()
                self.assertFalse(window._ai_busy, 'editor generation did not finish')
                self.assertFalse(window._open_error_dialogs, 'editor reported a generation error')
                clips = [clip for clip in window.project.clips if clip.title == title]
                self.assertEqual(len(clips), 1)
                self.assertTrue(Path(clips[0].source).is_file())
                if test_engine == purec.ENGINE_ID:
                    self.assertIn('8 threads',panel.audio_history[-1][1])
                    self.assertIsNotNone(window.narration_stream.first_chunk_latency_seconds,
                        'Pure C PCM chunks must reach the editor preview player.')
                self.assertGreater(clips[0].duration, 1.0)
                self.assertIn(clips[0].source, window.project.media)
                from berofel.core.project import Clip
                from berofel.services.ffmpeg import ffmpeg_path, media_info
                from berofel.services.export_multitrack import export_audio_wav, export_project
                video = Path(work) / 'synthetic_video.mp4'
                subprocess.run([ffmpeg_path(), '-hide_banner', '-loglevel', 'error', '-y',
                    '-f', 'lavfi', '-i',
                    f'color=c=black:s=320x180:r=24:d={clips[0].duration:.3f}',
                    '-an', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(video)],
                    check=True, capture_output=True, timeout=30)
                video_track = window.project.add_track('Vídeo de teste', 0)
                window.project.add_clip(Clip(str(video), 0, clips[0].duration,
                    kind='video', track_id=video_track.id))
                wav_out = str(Path(work) / 'narration_mix.wav')
                mp4_out = str(Path(work) / 'narration_mix.mp4')
                export_audio_wav(window.project, wav_out)
                export_project(window.project, mp4_out)
                self.assertGreater(Path(wav_out).stat().st_size, 1000)
                wav_duration, _, wav_has_audio = media_info(wav_out)
                mp4_duration, mp4_has_video, mp4_has_audio = media_info(mp4_out)
                self.assertTrue(wav_has_audio)
                self.assertTrue(mp4_has_video and mp4_has_audio)
                self.assertAlmostEqual(wav_duration, clips[0].duration, delta=.2)
                self.assertAlmostEqual(mp4_duration, clips[0].duration, delta=.3)
                print('PUREC_GUI_RESULT ' + json.dumps({
                    'clip_id': clips[0].id, 'duration': clips[0].duration,
                    'source': clips[0].source, 'engine': test_engine,
                    'threads': panel.audio_history[-1][1],
                    'wav_seconds': wav_duration, 'mp4_seconds': mp4_duration,
                    'mp4_video': mp4_has_video, 'mp4_audio': mp4_has_audio}, ensure_ascii=False))
                for widget in (panel.voice, panel.clone_engine, panel.text, panel.language,
                               panel.name, panel.sample_path, panel.reference_text):
                    widget.blockSignals(True)
                panel.voice.setCurrentIndex(original[0]); panel.clone_engine.setCurrentIndex(original[1])
                panel.text.setPlainText(original[2]); panel.language.setCurrentIndex(original[3])
                panel.name.setText(original[4]); panel.purec_threads.setCurrentIndex(original[5])
                panel._update_custom()
                for widget in (panel.voice, panel.clone_engine, panel.text, panel.language,
                               panel.name, panel.sample_path, panel.reference_text):
                    widget.blockSignals(False)
                panel._preferences_timer.stop()
                window.close(); app.processEvents()


if __name__ == '__main__':
    unittest.main()
