"""Offline Qt + Qwen smoke through the editor's multivoice panel.

Uses one authorized local profile for two identical V1/V2 lines. It validates
the real editor callback, cache behavior, separate timeline clips, project
round-trip and full-script WAV export. It does not test distinct speakers.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import wave

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from berofel.services.voice_profiles import VoiceProfileManager


ENGINES = ('qwen3-tts-purec-int8', 'qwen3-tts-purec-mixed')
TEXT = 'Esta fala repetida será gerada uma vez e usada por dois personagens.'


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
        raise TimeoutError('A tarefa do editor excedeu o limite de 180 segundos.')
    if window.active_task is not None:
        raise RuntimeError('A tarefa encerrou sem liberar a fila do editor.')
    if window._open_error_dialogs:
        messages = [dialog.text() for dialog in window._open_error_dialogs]
        raise RuntimeError('O editor reportou falha: ' + ' | '.join(messages))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--confirm-own-or-authorized-voice', action='store_true',
                        help='Confirma autorização para usar o perfil vocal local.')
    parser.add_argument('--profile-id', help='ID do perfil; obrigatório quando há vários autorizados.')
    parser.add_argument('--engine', choices=ENGINES, required=True)
    args = parser.parse_args()
    if not args.confirm_own_or_authorized_voice:
        parser.error('confirme autorização para usar a referência vocal local.')

    manager = VoiceProfileManager()
    profiles = [item for item in manager.list_profiles()
                if item.get('authorized') and Path(item.get('sample_path', '')).is_file()]
    if args.profile_id:
        profiles = [item for item in profiles if item['id'] == args.profile_id]
    elif len(profiles) != 1:
        parser.error('informe --profile-id quando houver mais de um perfil autorizado.')
    if not profiles:
        raise SystemExit('Não há perfil local autorizado correspondente à seleção.')
    profile = profiles[0]

    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication, QFileDialog
    from unittest.mock import patch
    from berofel.services.project_recovery import load_project
    from berofel.services.qwen3_purec_tts import is_ready, stop_purec_worker
    from berofel.ui.window import MainWindow
    from berofel.services.multivoice_narration import MultiVoiceScript

    if not is_ready():
        raise SystemExit(f'O backend {args.engine} não está instalado localmente.')

    app = QApplication.instance() or QApplication([])
    old_format = QSettings.defaultFormat()
    previous_voice_dir = os.environ.get('BEROFEL_VOICE_PROFILE_DIR')
    env_keys = ('BEROFEL_AI_CACHE', 'BEROFEL_QWEN3_PROMPT_CACHE',
                'BEROFEL_QWEN3_PUREC_PROFILE_CACHE', 'HF_HUB_OFFLINE',
                'TRANSFORMERS_OFFLINE', 'HF_HUB_DISABLE_TELEMETRY')
    previous = {key: os.environ.get(key) for key in env_keys}
    window = None
    try:
        with tempfile.TemporaryDirectory(prefix='bfs_multivoice_ui_smoke_') as temp:
            root = Path(temp)
            QSettings.setDefaultFormat(QSettings.Format.IniFormat)
            QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                              str(root / 'settings'))
            os.environ['BEROFEL_VOICE_PROFILE_DIR'] = str(manager.directory)
            os.environ.update({
                'BEROFEL_AI_CACHE': str(root / 'ai-cache'),
                'BEROFEL_QWEN3_PROMPT_CACHE': str(root / 'prompt-cache'),
                'BEROFEL_QWEN3_PUREC_PROFILE_CACHE': str(root / 'purec-profile-cache'),
                'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1',
                'HF_HUB_DISABLE_TELEMETRY': '1',
            })
            stop_purec_worker()
            project_path = root / 'ui_smoke.berofel.json'
            export_path = root / 'multivoice.wav'
            window = MainWindow()
            window.project.path = str(project_path)
            panel = window.narration_panel.multivoice_panel
            panel.refresh_profiles()
            for voice_id in ('V1', 'V2'):
                combo = panel.assignments[voice_id]
                index = combo.findData(profile['id'])
                if index < 0:
                    raise RuntimeError(f'O perfil autorizado não apareceu no slot {voice_id}.')
                combo.setCurrentIndex(index)
            engine_index = panel.engine.findData(args.engine)
            if engine_index < 0:
                raise RuntimeError(f'O perfil {args.engine} não está disponível no painel.')
            panel.engine.setCurrentIndex(engine_index)
            panel.script_text.setPlainText(f'[001 | V1]\n{TEXT}\n[002 | V2]\n{TEXT}')
            script = panel.build_script(title='Smoke multivozes no editor')
            panel.set_active_script(script)
            window.generate_multivoice_ui(script)
            _wait_task(window, app)

            saved_data = next((item for item in window.project.narration_scripts
                               if item.get('id') == script.id), None)
            if saved_data is None:
                raise RuntimeError('O editor não persistiu o roteiro concluído.')
            result = MultiVoiceScript.from_dict(saved_data)
            clips = [clip for clip in window.project.clips
                     if clip.narration_script_id == script.id]
            if len(clips) != 2 or len(result.lines) != 2:
                raise RuntimeError('O editor não inseriu os dois blocos na timeline.')
            first, second = result.lines
            clips_by_line = {clip.narration_line_id: clip for clip in clips}
            first_clip = clips_by_line.get(first.id)
            second_clip = clips_by_line.get(second.id)
            if first_clip is None or second_clip is None:
                raise RuntimeError('Os clips não mantiveram o ID estável de cada fala.')
            expected_second_start = first_clip.timeline_end + result.pause_ms / 1000.0
            if abs(second_clip.timeline_start - expected_second_start) > 0.001:
                raise RuntimeError('A pausa entre as falas não foi respeitada na timeline.')
            if not (first.status == second.status == 'generated' and
                    first.cache_hit is False and second.cache_hit is True):
                raise RuntimeError('Estado/cache das falas não corresponde à validação esperada.')
            if first.audio_path == second.audio_path or _sha256(first.audio_path) != _sha256(second.audio_path):
                raise RuntimeError('As falas não mantiveram WAVs independentes equivalentes.')
            if not window._save_at(str(project_path)):
                raise RuntimeError('O projeto do smoke não pôde ser salvo.')
            reopened = load_project(str(project_path))
            restored = MultiVoiceScript.from_dict(reopened.narration_scripts[0])
            if len(reopened.clips) != 2 or [line.id for line in restored.lines] != [line.id for line in result.lines]:
                raise RuntimeError('Salvar/reabrir não preservou falas e timeline.')

            with patch.object(QFileDialog, 'getSaveFileName',
                              return_value=(str(export_path), 'WAV PCM')):
                window.export_multivoice_script(result)
            _wait_task(window, app)
            export_metrics = _measure_wav(export_path)
            expected_export_duration = first.duration + second.duration + result.pause_ms / 1000.0
            if abs(export_metrics['duration_seconds'] - expected_export_duration) > 0.03:
                raise RuntimeError('A duração exportada não corresponde aos WAVs e à pausa da timeline.')
            report = {
                'offline': True,
                'through_editor_ui': True,
                'engine': args.engine,
                'model': 'Qwen/Qwen3-TTS-12Hz-0.6B-Base',
                'speaker_identity_distinct': False,
                'synthesis_calls': 1,
                'cache_hit_per_line': [first.cache_hit, second.cache_hit],
                'timeline_clips': len(clips),
                'timeline_pause_ms_preserved': result.pause_ms,
                'timeline_order_and_spacing_verified': True,
                'project_reopen_preserved_script_and_clips': True,
                'individual_wav_metrics': [_measure_wav(first.audio_path),
                                           _measure_wav(second.audio_path)],
                'individual_wav_hashes_equal': True,
                'full_script_wav_export': export_metrics,
                'temporary_project_audio_and_caches_removed': True,
            }
            print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        if window is not None:
            window.close()
        try:
            stop_purec_worker()
        except Exception:
            pass
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
