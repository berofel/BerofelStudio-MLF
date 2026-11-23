"""Offline Qt + Qwen smoke through the editor's multivoice panel.

The default mode maps one authorized profile to two identical lines to verify
cache reuse. Supplying three distinct authorized profiles runs the full
100-line, 70/20/10-speaker acceptance script through the Qt editor.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import time
import wave

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from berofel.services.voice_profiles import VoiceProfileManager
from scripts.validar_multivoice_distinct_profiles import (
    build_100_line_acceptance_script, select_authorized_distinct_profiles,
)


ENGINES = ('qwen3-tts-purec-int8', 'qwen3-tts-purec-mixed',
           'qwen3-tts-native-q4')
TEXT = 'Esta fala repetida será gerada uma vez e usada por dois personagens.'


def validate_distinct_speaker_claim(profile_v2: str | None,
                                    confirmed_distinct_speakers: bool) -> None:
    """Do not equate different reference files with different people."""
    if profile_v2 and not confirmed_distinct_speakers:
        raise ValueError('Confirme que V1/V2/V3 representam locutores distintos; '
                         'arquivos diferentes podem ser trechos da mesma pessoa.')


def _sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _measure_wav(path: str | Path) -> dict:
    with wave.open(str(path), 'rb') as audio:
        channels, width, rate, frames = (audio.getnchannels(), audio.getsampwidth(),
                                         audio.getframerate(), audio.getnframes())
        raw = audio.readframes(frames)
    if channels not in (1, 2) or width not in (2, 3) or rate < 8_000 or frames <= 0:
        raise RuntimeError(f'WAV inválido ou vazio: {Path(path).name} '
                           f'(canais={channels}, bytes/amostra={width}, Hz={rate}, frames={frames})')
    if width == 2:
        samples = np.frombuffer(raw, dtype='<i2').astype(np.int32)
    else:
        octets = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        samples = octets[:, 0] | (octets[:, 1] << 8) | (octets[:, 2] << 16)
        samples = np.where(samples & 0x800000, samples - 0x1000000, samples)
    if samples.size == 0:
        raise RuntimeError(f'WAV sem amostras: {Path(path).name}')
    rms = float(np.sqrt(np.mean(np.square(samples.astype(np.float64)))))
    if rms < 3:
        raise RuntimeError(f'WAV silencioso: {Path(path).name}')
    return {'duration_seconds': round(frames / rate, 3),
            'channels': channels, 'sample_rate': rate, 'rms_pcm': round(rms, 1)}


def _wait_task(window, app, timeout_ms: int = 180_000) -> None:
    from PySide6.QtCore import QEventLoop, QTimer
    task = window.active_task
    if task is None:
        raise RuntimeError('O editor não iniciou a tarefa esperada.')
    loop = QEventLoop()
    timer = QTimer()
    timer.setSingleShot(True)
    finished = [False]
    def on_finished():
        finished[0] = True
        loop.quit()
    task.signals.finished.connect(on_finished)
    timer.timeout.connect(loop.quit)
    timer.start(timeout_ms)
    loop.exec()
    app.processEvents()
    if not finished[0]:
        task.control.cancel()
        wait_loop = QEventLoop()
        task.signals.finished.connect(wait_loop.quit)
        wait_loop.exec()
        raise TimeoutError(f'A tarefa do editor excedeu o limite de {timeout_ms / 1000:.0f} segundos.')
    if window.active_task is not None:
        raise RuntimeError('A tarefa encerrou sem liberar a fila do editor.')
    if window._open_error_dialogs:
        messages = [dialog.text() for dialog in window._open_error_dialogs]
        raise RuntimeError('O editor reportou falha: ' + ' | '.join(messages))


def build_one_voice_script(line_count: int) -> str:
    if not 1 <= line_count <= 1000:
        raise ValueError('O smoke de uma voz aceita entre 1 e 1.000 falas.')
    return '\n'.join(
        f'[{number:03d} | V1]\n'
        f'Esta é a fala número {number:03d} no lote contínuo de validação.'
        for number in range(1, line_count + 1))


class ProcessTreeResourceSampler:
    """Sample editor + child-worker RSS/CPU while real Qwen inference runs."""
    def __init__(self, interval_seconds: float = 0.2):
        self.interval_seconds = interval_seconds
        self.root_pid = os.getpid()
        self.started = 0.0
        self.peak_rss = 0
        self.cpu_start = 0.0
        self.cpu_latest = 0.0
        self._stop = threading.Event()
        self._thread = None
        self._psutil = None

    def _read_tree(self) -> tuple[int, float]:
        psutil = self._psutil
        root = psutil.Process(self.root_pid)
        processes = [root]
        try:
            processes.extend(root.children(recursive=True))
        except psutil.Error:
            pass
        rss = cpu = 0
        for process in processes:
            try:
                rss += process.memory_info().rss
                usage = process.cpu_times()
                cpu += usage.user + usage.system
            except psutil.Error:
                continue
        return rss, cpu

    def _sample(self) -> None:
        while not self._stop.is_set():
            rss, cpu = self._read_tree()
            self.peak_rss = max(self.peak_rss, rss)
            self.cpu_latest = cpu
            self._stop.wait(self.interval_seconds)

    def start(self):
        try:
            import psutil
            self._psutil = psutil
            _rss, self.cpu_start = self._read_tree()
        except ImportError:
            return self
        self.started = time.perf_counter()
        self._thread = threading.Thread(target=self._sample,
                                        name='BFS Qwen resource sampler', daemon=True)
        self._thread.start()
        return self

    def stop(self) -> dict | None:
        if self._thread is None:
            return None
        self._stop.set()
        self._thread.join(timeout=2)
        elapsed = max(0.001, time.perf_counter() - self.started)
        _rss, cpu = self._read_tree()
        self.peak_rss = max(self.peak_rss, _rss)
        self.cpu_latest = max(self.cpu_latest, cpu)
        cpu_seconds = max(0.0, self.cpu_latest - self.cpu_start)
        return {'scope': 'editor process and child processes during synthesis',
                'sample_interval_ms': int(self.interval_seconds * 1000),
                'wall_seconds': round(elapsed, 3),
                'peak_process_tree_rss_bytes': self.peak_rss,
                'peak_process_tree_rss_gib': round(self.peak_rss / (1024 ** 3), 3),
                'process_tree_cpu_seconds': round(cpu_seconds, 3),
                'average_cpu_cores_used': round(cpu_seconds / elapsed, 3)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--confirm-own-or-authorized-voice', action='store_true',
                        help='Confirma autorização para usar os perfis vocais locais selecionados.')
    parser.add_argument('--profile-id', '--profile-v1', dest='profile_v1',
                        help='ID do perfil V1; obrigatório quando há vários autorizados.')
    parser.add_argument('--profile-v2', help='ID distinto para V2; ativa validação de duas vozes.')
    parser.add_argument('--profile-v3', help='ID distinto para V3; ativa o roteiro Qt de 100 falas.')
    parser.add_argument('--one-voice-lines', type=int,
                        help='Gera N textos inéditos em V1 para testar reuso do worker (1–1.000).')
    parser.add_argument('--confirm-distinct-speakers', action='store_true',
                        help='Confirma que os perfis selecionados representam pessoas diferentes.')
    parser.add_argument('--engine', choices=ENGINES, required=True)
    args = parser.parse_args()
    if not args.confirm_own_or_authorized_voice:
        parser.error('confirme autorização para usar a referência vocal local.')
    if args.profile_v3 and not args.profile_v2:
        parser.error('--profile-v3 exige também um perfil distinto em --profile-v2.')
    if args.one_voice_lines is not None and (args.profile_v2 or args.profile_v3):
        parser.error('--one-voice-lines não pode ser combinado com perfis V2/V3.')
    if args.one_voice_lines is not None and not 1 <= args.one_voice_lines <= 1000:
        parser.error('--one-voice-lines aceita entre 1 e 1.000 falas.')
    try:
        validate_distinct_speaker_claim(args.profile_v2, args.confirm_distinct_speakers)
    except ValueError as exc:
        parser.error(str(exc))

    manager = VoiceProfileManager()
    profiles = [item for item in manager.list_profiles()
                if item.get('authorized') and Path(item.get('sample_path', '')).is_file()]
    if args.profile_v1:
        profiles = [item for item in profiles if item['id'] == args.profile_v1]
    elif len(profiles) != 1:
        parser.error('informe --profile-v1 quando houver mais de um perfil autorizado.')
    if not profiles:
        raise SystemExit('Não há perfil local autorizado correspondente à seleção.')
    if args.profile_v2:
        selected_profiles, _fingerprints = select_authorized_distinct_profiles(
            manager, profiles[0]['id'], args.profile_v2, args.profile_v3)
        profiles_by_voice = {f'V{index}': selected_profiles[profile_id]
                             for index, profile_id in enumerate(selected_profiles, 1)}
    elif args.one_voice_lines is not None:
        profiles_by_voice = {'V1': profiles[0]}
    else:
        profiles_by_voice = {'V1': profiles[0], 'V2': profiles[0]}

    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication, QFileDialog
    from unittest.mock import patch
    from berofel.services.project_recovery import load_project
    from berofel.services.qwen3_purec_tts import is_ready as purec_ready, stop_purec_worker
    from berofel.services.qwen3_native_tts import is_ready as native_ready, _layout as native_layout
    from berofel.ui.window import MainWindow
    from berofel.services.multivoice_narration import MultiVoiceScript
    from berofel.core.project import Clip, Project
    from berofel.services.export_multitrack import export_project
    from berofel.services.ffmpeg import ffmpeg_path, media_info

    if (args.engine.startswith('qwen3-tts-purec-') and not purec_ready()) or (
            args.engine == 'qwen3-tts-native-q4' and not native_ready()):
        raise SystemExit(f'O backend {args.engine} não está instalado localmente.')
    native_paths = native_layout() if args.engine == 'qwen3-tts-native-q4' else None

    app = QApplication.instance() or QApplication([])
    old_format = QSettings.defaultFormat()
    previous_voice_dir = os.environ.get('BEROFEL_VOICE_PROFILE_DIR')
    env_keys = ('BEROFEL_AI_CACHE', 'BEROFEL_QWEN3_PROMPT_CACHE',
                'BEROFEL_QWEN3_PUREC_PROFILE_CACHE', 'HF_HUB_OFFLINE',
                'BEROFEL_QWEN3_PUREC_LOG',
                'TRANSFORMERS_OFFLINE', 'HF_HUB_DISABLE_TELEMETRY',
                'BEROFEL_QWEN3_NATIVE_HOME', 'BEROFEL_QWEN3_NATIVE_EXE',
                'BEROFEL_QWEN3_NATIVE_MODEL', 'BEROFEL_QWEN3_NATIVE_TOKENIZER')
    previous = {key: os.environ.get(key) for key in env_keys}
    window = None
    root = None
    resource_sampler = None
    resource_metrics = None
    try:
        with tempfile.TemporaryDirectory(prefix='bfs_multivoice_ui_smoke_',
                                         ignore_cleanup_errors=True) as temp:
            root = Path(temp)
            QSettings.setDefaultFormat(QSettings.Format.IniFormat)
            QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                              str(root / 'settings'))
            os.environ['BEROFEL_VOICE_PROFILE_DIR'] = str(manager.directory)
            temporary_environment = {
                'BEROFEL_AI_CACHE': str(root / 'ai-cache'),
                'BEROFEL_QWEN3_PROMPT_CACHE': str(root / 'prompt-cache'),
                'BEROFEL_QWEN3_PUREC_PROFILE_CACHE': str(root / 'purec-profile-cache'),
                'BEROFEL_QWEN3_PUREC_LOG': str(root / 'purec-server.log'),
                'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1',
                'HF_HUB_DISABLE_TELEMETRY': '1',
            }
            if native_paths:
                exe, model, tokenizer = native_paths
                temporary_environment.update({
                    'BEROFEL_QWEN3_NATIVE_HOME': str(root / 'native-runtime'),
                    'BEROFEL_QWEN3_NATIVE_EXE': str(exe),
                    'BEROFEL_QWEN3_NATIVE_MODEL': str(model),
                    'BEROFEL_QWEN3_NATIVE_TOKENIZER': str(tokenizer),
                })
            os.environ.update(temporary_environment)
            stop_purec_worker()
            project_path = root / 'ui_smoke.berofel.json'
            export_path = root / 'multivoice.wav'
            mp4_path = root / 'multivoice.mp4'
            video = root / 'background.png'
            Image.new('RGB', (320, 180), (28, 38, 54)).save(video)
            project = Project(width=320, height=180, fps=12)
            project.path = str(project_path)
            background_clip = project.add_clip(Clip(str(video), 0, 15,
                                                     track_id=project.tracks[0].id,
                                                     kind='image', title='multivoice smoke background'))
            window = MainWindow()
            window.project = project
            window.refresh([])
            panel = window.narration_panel.multivoice_panel
            panel.refresh_profiles()
            for voice_id, voice_profile in profiles_by_voice.items():
                combo = panel.assignments[voice_id]
                index = combo.findData(voice_profile['id'])
                if index < 0:
                    raise RuntimeError(f'O perfil autorizado não apareceu no slot {voice_id}.')
                combo.setCurrentIndex(index)
            engine_index = panel.engine.findData(args.engine)
            if engine_index < 0:
                raise RuntimeError(f'O perfil {args.engine} não está disponível no painel.')
            panel.engine.setCurrentIndex(engine_index)
            if args.one_voice_lines is not None:
                smoke_script_text = build_one_voice_script(args.one_voice_lines)
            elif args.profile_v3:
                smoke_script_text = build_100_line_acceptance_script()
            elif args.profile_v2:
                smoke_script_text = (
                    f'[001 | V1]\n{TEXT}\n'
                    '[002 | V2]\nUma resposta diferente confirma a troca de personagem.')
            else:
                smoke_script_text = f'[001 | V1]\n{TEXT}\n[002 | V2]\n{TEXT}'
            panel.script_text.setPlainText(smoke_script_text)
            script = panel.build_script(title='Smoke multivozes no editor')
            panel.set_active_script(script)
            resource_sampler = ProcessTreeResourceSampler().start()
            server_pids = []
            if args.one_voice_lines and args.engine.startswith('qwen3-tts-purec-'):
                from berofel.services import qwen3_purec_tts as purec_service
                original_start_server = purec_service._start_server
                def track_server(*call_args, **call_kwargs):
                    result = original_start_server(*call_args, **call_kwargs)
                    process = purec_service._PROCESS
                    if process is not None:
                        server_pids.append(process.pid)
                    return result
                with patch.object(purec_service, '_start_server', side_effect=track_server):
                    window.generate_multivoice_ui(script)
                    _wait_task(window, app, max(180_000, len(script.lines) * 12_000))
            else:
                window.generate_multivoice_ui(script)
                _wait_task(window, app, max(180_000, len(script.lines) * 12_000))

            saved_data = next((item for item in window.project.narration_scripts
                               if item.get('id') == script.id), None)
            if saved_data is None:
                raise RuntimeError('O editor não persistiu o roteiro concluído.')
            result = MultiVoiceScript.from_dict(saved_data)
            clips = [clip for clip in window.project.clips
                     if clip.narration_script_id == script.id]
            expected_line_count = (args.one_voice_lines if args.one_voice_lines is not None else
                                   100 if args.profile_v3 else 2)
            if len(clips) != expected_line_count or len(result.lines) != expected_line_count:
                raise RuntimeError(f'O editor inseriu {len(clips)} clips e {len(result.lines)} falas; '
                                   f'esperado: {expected_line_count}.')
            clips_by_line = {clip.narration_line_id: clip for clip in clips}
            ordered_clips = []
            for line in result.lines:
                clip = clips_by_line.get(line.id)
                if clip is None:
                    raise RuntimeError('Os clips não mantiveram o ID estável de cada fala.')
                ordered_clips.append(clip)
            if any(a.timeline_start > b.timeline_start for a, b in zip(ordered_clips, ordered_clips[1:])):
                raise RuntimeError('A timeline não respeitou a ordem narrativa do roteiro.')
            for previous_clip, next_clip in zip(ordered_clips, ordered_clips[1:]):
                expected_start = previous_clip.timeline_end + result.pause_ms / 1000.0
                if abs(next_clip.timeline_start - expected_start) > 0.001:
                    raise RuntimeError('A pausa entre as falas não foi respeitada na timeline.')
            if not all(line.status == 'generated' for line in result.lines):
                raise RuntimeError('Uma ou mais falas não foram finalizadas com sucesso.')
            resource_metrics = resource_sampler.stop() if resource_sampler else None
            expected_synthesis_calls = expected_line_count if (
                args.profile_v2 or args.one_voice_lines is not None) else 1
            synthesis_calls = sum(not line.cache_hit for line in result.lines)
            if synthesis_calls != expected_synthesis_calls:
                raise RuntimeError(f'Número inesperado de sínteses: {synthesis_calls}; '
                                   f'esperado: {expected_synthesis_calls}.')
            audio_paths = [line.audio_path for line in result.lines]
            if len(set(audio_paths)) != expected_line_count:
                raise RuntimeError('Cada fala precisa ter um WAV independente.')
            if (args.one_voice_lines is None and not args.profile_v2 and
                    _sha256(result.lines[0].audio_path) != _sha256(result.lines[1].audio_path)):
                raise RuntimeError('O cache não reutilizou o áudio idêntico no smoke de uma voz.')
            if args.one_voice_lines and args.engine.startswith('qwen3-tts-purec-'):
                if not server_pids or len(set(server_pids)) != 1:
                    raise RuntimeError(f'O servidor foi recarregado durante o lote: {server_pids!r}.')
                if any(line.profile_prepare_seconds > 0 for line in result.lines[1:]):
                    raise RuntimeError('O perfil vocal foi preparado novamente dentro do lote V1.')
                if any(line.model_load_seconds > 0 for line in result.lines[1:]):
                    raise RuntimeError('O modelo foi recarregado dentro do lote V1.')
            if not window._save_at(str(project_path)):
                raise RuntimeError('O projeto do smoke não pôde ser salvo.')
            reopened = load_project(str(project_path))
            restored = MultiVoiceScript.from_dict(reopened.narration_scripts[0])
            reopened_script_clips = [clip for clip in reopened.clips
                                     if clip.narration_script_id == script.id]
            if (len(reopened_script_clips) != expected_line_count or
                    [line.id for line in restored.lines] != [line.id for line in result.lines]):
                raise RuntimeError('Salvar/reabrir não preservou falas e timeline.')

            with patch.object(QFileDialog, 'getSaveFileName',
                              return_value=(str(export_path), 'WAV PCM')):
                window.export_multivoice_script(result)
            _wait_task(window, app)
            export_metrics = _measure_wav(export_path)
            expected_export_duration = sum(line.duration for line in result.lines) + (
                result.pause_ms / 1000.0 * max(0, len(result.lines) - 1))
            if abs(export_metrics['duration_seconds'] - expected_export_duration) > 0.03:
                raise RuntimeError('A duração exportada não corresponde aos WAVs e à pausa da timeline.')
            video_duration = max(clip.timeline_end for clip in ordered_clips) + 0.1
            background_clip.end = max(background_clip.end, video_duration)
            background_clip.source_length = max(background_clip.source_length, video_duration)
            export_project(window.project, str(mp4_path))
            mp4_duration, has_video, has_audio = media_info(str(mp4_path))
            if (not has_video or not has_audio or
                    mp4_duration + 0.1 < max(clip.timeline_end for clip in ordered_clips)):
                raise RuntimeError('O MP4 multivozes não contém vídeo e áudio válidos.')
            decoded_audio = root / 'multivoice_mp4_audio.wav'
            import subprocess
            subprocess.run([ffmpeg_path(), '-hide_banner', '-loglevel', 'error', '-y',
                            '-i', str(mp4_path), '-map', '0:a:0', '-vn', '-ac', '1',
                            '-ar', '24000', '-c:a', 'pcm_s16le', str(decoded_audio)],
                           check=True, capture_output=True, timeout=120)
            mp4_audio_metrics = _measure_wav(decoded_audio)
            fresh_synthesis_audio_seconds = sum(
                line.duration for line in result.lines if not line.cache_hit)
            cache_hits = [line.cache_hit for line in result.lines]
            voice_counts = {voice_id: sum(line.voice_id == voice_id for line in result.lines)
                            for voice_id in sorted({line.voice_id for line in result.lines})}
            report = {
                'offline': True,
                'through_editor_ui': True,
                'engine': args.engine,
                'model': 'Qwen/Qwen3-TTS-12Hz-0.6B-Base',
                'distinct_reference_audio_files': bool(args.profile_v2),
                'distinct_speakers_confirmed_by_user': bool(
                    args.profile_v2 and args.confirm_distinct_speakers),
                'voice_profile_ids': {voice_id: item['id']
                                      for voice_id, item in profiles_by_voice.items()},
                'voice_line_counts': voice_counts,
                'script_line_count': len(result.lines),
                'synthesis_calls': synthesis_calls,
                'resident_server_pid_count_during_one_voice_batch': len(set(server_pids)),
                'server_start_checks_during_one_voice_batch': len(server_pids),
                'one_voice_batch_reused_profile_and_model': bool(
                    args.one_voice_lines and args.engine.startswith('qwen3-tts-purec-') and
                    server_pids and len(set(server_pids)) == 1 and
                    all(line.profile_prepare_seconds == 0 and line.model_load_seconds == 0
                        for line in result.lines[1:])),
                'cache_hit_per_line': cache_hits,
                'timeline_clips': len(clips),
                'timeline_pause_ms_preserved': result.pause_ms,
                'timeline_order_and_spacing_verified': True,
                'script_wall_seconds': round(result.total_seconds, 3),
                'first_audio_ready_seconds': round(result.first_audio_ready_seconds, 3),
                'first_audio_chunk_seconds_for_first_line': round(
                    result.lines[0].first_audio_seconds, 3),
                'generated_audio_seconds': round(sum(line.duration for line in result.lines), 3),
                'fresh_synthesis_audio_seconds': round(fresh_synthesis_audio_seconds, 3),
                'fresh_synthesis_end_to_end_rtf': round(
                    result.total_seconds / max(.001, fresh_synthesis_audio_seconds), 3),
                'profile_preparation_seconds': round(result.profile_preparation_seconds, 3),
                'model_load_seconds': round(result.model_load_seconds, 3),
                'resource_metrics': resource_metrics,
                'project_reopen_preserved_script_and_clips': True,
                'individual_wav_metrics': [_measure_wav(line.audio_path)
                                           for line in result.lines],
                'individual_wav_hashes_equal': (
                    _sha256(result.lines[0].audio_path) == _sha256(result.lines[1].audio_path)
                    if not args.profile_v2 and args.one_voice_lines is None else None),
                'full_script_wav_export': export_metrics,
                'mp4_export': {'duration_seconds': round(mp4_duration, 3),
                               'has_video': has_video, 'has_audio': has_audio,
                               'decoded_audio_metrics': mp4_audio_metrics},
                'temporary_project_audio_and_caches_removed': True,
            }
            print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        if resource_sampler is not None and resource_metrics is None:
            resource_sampler.stop()
        if window is not None:
            window.close()
        try:
            stop_purec_worker()
        except Exception:
            pass
        try:
            from berofel.services.qwen3_native_tts import stop_native_worker
            stop_native_worker()
        except Exception:
            pass
        if root is not None and root.exists():
            temp_base = Path(tempfile.gettempdir()).resolve()
            resolved_root = root.resolve()
            if (resolved_root.parent == temp_base and
                    resolved_root.name.startswith('bfs_multivoice_ui_smoke_')):
                shutil.rmtree(resolved_root)
        QSettings.setDefaultFormat(old_format)
        if previous_voice_dir is None:
            os.environ.pop('BEROFEL_VOICE_PROFILE_DIR', None)
        else:
            os.environ['BEROFEL_VOICE_PROFILE_DIR'] = previous_voice_dir
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
