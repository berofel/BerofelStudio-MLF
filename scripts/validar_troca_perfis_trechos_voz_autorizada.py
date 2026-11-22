"""Offline diagnostic of Qwen voice switching using one authorized speaker.

Creates two temporary profiles from non-identical, high-energy segments of one
authorized recording. This exercises runtime switching, not distinct-speaker
identity. The source recording and persistent profile library are untouched.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import uuid
import wave

import numpy as np
from scipy.io import wavfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from berofel.services.audio_reference import prepare_audio_prompt
from berofel.services.multivoice_narration import (
    create_script, generate_script_audio, group_script_lines_by_profile,
)
from berofel.services.narration_service import generate_narration
from berofel.services.voice_profiles import VoiceProfileManager

ENGINES = ('qwen3-tts-purec-int8', 'qwen3-tts-purec-mixed',
           'qwen3-tts-native-q4', 'qwen3-tts-local')
TEXTS = ('Primeira fala do diagnóstico local.',
         'Segunda fala do diagnóstico local.')


def select_speech_segments(samples: np.ndarray, sample_rate: int,
                           segment_seconds: int = 3) -> tuple[np.ndarray, np.ndarray, list[float]]:
    """Choose two distinct, energetic speech windows without exporting audio."""
    values = np.asarray(samples)
    if values.ndim != 1 or sample_rate <= 0 or not np.issubdtype(values.dtype, np.integer):
        raise ValueError('A referência normalizada precisa ser PCM inteiro mono.')
    frame_count = int(sample_rate * segment_seconds)
    if len(values) < frame_count + sample_rate // 2:
        raise ValueError('A amostra autorizada é curta demais para dois trechos de fala.')
    normalized = values.astype(np.float64) / max(abs(np.iinfo(values.dtype).min),
                                                   np.iinfo(values.dtype).max)
    step = max(1, sample_rate // 2)
    starts = list(range(0, len(values) - frame_count + 1, step))
    rms = [float(np.sqrt(np.mean(normalized[start:start + frame_count] ** 2)))
           for start in starts]
    first_index = max(range(len(starts)), key=rms.__getitem__)
    min_distance = frame_count // 2
    second_indices = [index for index, start in enumerate(starts)
                      if abs(start - starts[first_index]) >= min_distance]
    if not second_indices:
        raise ValueError('Não foi possível selecionar dois trechos de referência distintos.')
    second_index = max(second_indices, key=rms.__getitem__)
    if min(rms[first_index], rms[second_index]) < 0.003:
        raise ValueError('Os trechos selecionados têm pouco sinal de fala audível.')
    first = values[starts[first_index]:starts[first_index] + frame_count].copy()
    second = values[starts[second_index]:starts[second_index] + frame_count].copy()
    if np.array_equal(first, second):
        raise ValueError('Os trechos selecionados ficaram idênticos.')
    return first, second, [rms[first_index], rms[second_index]]


def _wav_stats(path: str) -> dict:
    with wave.open(path, 'rb') as audio:
        frames, rate, width, channels = (audio.getnframes(), audio.getframerate(),
                                         audio.getsampwidth(), audio.getnchannels())
        data = np.frombuffer(audio.readframes(frames), dtype='<i2')
    if frames <= 0 or rate <= 0 or width != 2 or channels != 1 or not data.size:
        raise RuntimeError('Uma fala não produziu WAV mono PCM16 válido.')
    rms = float(np.sqrt(np.mean(data.astype(np.float64) ** 2)))
    if rms < 3:
        raise RuntimeError('Uma fala gerada ficou vazia ou silenciosa.')
    return {'duration_seconds': round(frames / rate, 3), 'rms_pcm16': round(rms, 1)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--confirm-own-or-authorized-voice', action='store_true',
                        help='Confirma o uso local do perfil selecionado para este diagnóstico.')
    parser.add_argument('--profile-id', help='ID do perfil autorizado. Se omitido, aceita somente um perfil.')
    parser.add_argument('--engine', choices=ENGINES, action='append',
                        help='Pode repetir; padrão executa Pure C INT8 e Pure C Mixer.')
    args = parser.parse_args()
    if not args.confirm_own_or_authorized_voice:
        parser.error('confirme a autorização da referência com --confirm-own-or-authorized-voice.')

    manager = VoiceProfileManager()
    available = [profile for profile in manager.list_profiles()
                 if profile.get('authorized') and Path(profile.get('sample_path', '')).is_file()]
    if args.profile_id:
        available = [profile for profile in available if profile['id'] == args.profile_id]
    elif len(available) != 1:
        parser.error('informe --profile-id quando houver mais de um perfil autorizado.')
    if not available:
        raise SystemExit('Não há perfil local autorizado correspondente à seleção.')
    source_profile = manager.get(available[0]['id'])
    engines = tuple(args.engine or ENGINES[:2])

    env_keys = ('BEROFEL_VOICE_PROFILE_DIR', 'BEROFEL_AI_CACHE',
                'BEROFEL_QWEN3_PROMPT_CACHE', 'BEROFEL_QWEN3_PUREC_PROFILE_CACHE',
                'BEROFEL_QWEN3_NATIVE_HOME', 'BEROFEL_QWEN3_NATIVE_EXE',
                'BEROFEL_QWEN3_NATIVE_MODEL', 'BEROFEL_QWEN3_NATIVE_TOKENIZER',
                'HF_HUB_OFFLINE', 'TRANSFORMERS_OFFLINE', 'HF_HUB_DISABLE_TELEMETRY')
    previous = {key: os.environ.get(key) for key in env_keys}
    native_layout = None
    if 'qwen3-tts-native-q4' in engines:
        from berofel.services.qwen3_native_tts import _layout
        native_layout = _layout()
    try:
        with tempfile.TemporaryDirectory(prefix='bfs_voice_switch_diagnostic_') as temp:
            root = Path(temp)
            temporary_environment = {
                'BEROFEL_VOICE_PROFILE_DIR': str(root / 'profiles'),
                'BEROFEL_AI_CACHE': str(root / 'ai-cache'),
                'BEROFEL_QWEN3_PROMPT_CACHE': str(root / 'prompt-cache'),
                'BEROFEL_QWEN3_PUREC_PROFILE_CACHE': str(root / 'purec-profile-cache'),
                'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1',
                'HF_HUB_DISABLE_TELEMETRY': '1',
            }
            if native_layout:
                exe, model, tokenizer = native_layout
                temporary_environment.update({
                    'BEROFEL_QWEN3_NATIVE_HOME': str(root / 'native-runtime'),
                    'BEROFEL_QWEN3_NATIVE_EXE': str(exe),
                    'BEROFEL_QWEN3_NATIVE_MODEL': str(model),
                    'BEROFEL_QWEN3_NATIVE_TOKENIZER': str(tokenizer),
                })
            os.environ.update(temporary_environment)
            normalized = root / 'normalized.wav'
            prepare_audio_prompt(source_profile['sample_path'], normalized)
            sample_rate, pcm = wavfile.read(normalized)
            first, second, segment_rms = select_speech_segments(pcm, sample_rate)
            temp_manager = VoiceProfileManager()
            temp_profiles = []
            for index, segment in enumerate((first, second), 1):
                sample = root / f'reference_{index}.wav'
                wavfile.write(sample, sample_rate, segment)
                temp_profiles.append(temp_manager.create(
                    f'Diagnóstico temporário {index}', sample, 'portuguese', '',
                    authorized=True))
            profile_map = {profile['id']: temp_manager.get(profile['id'])
                           for profile in temp_profiles}
            report = {
                'diagnostic': 'two non-identical temporary segments from one authorized speaker',
                'speaker_identity_distinct': False,
                'offline': True,
                'segment_seconds': len(first) / sample_rate,
                'reference_segment_rms': [round(value, 5) for value in segment_rms],
                'engines': [],
            }
            for engine in engines:
                if engine == 'qwen3-tts-local':
                    from berofel.services.qwen3_tts_local import is_ready, stop_local_worker
                    if not is_ready():
                        raise RuntimeError('Qwen3 Original não está instalado localmente.')
                    stop_local_worker()
                elif engine == 'qwen3-tts-native-q4':
                    from berofel.services.qwen3_native_tts import is_ready, stop_native_worker
                    if not is_ready():
                        raise RuntimeError('Qwen3 Turbo Q4 nativo não está instalado localmente.')
                    stop_native_worker()
                else:
                    from berofel.services.qwen3_purec_tts import is_ready, stop_purec_worker
                    if not is_ready():
                        raise RuntimeError(f'{engine} não está instalado localmente.')
                    stop_purec_worker()

                script = create_script(
                    f'[001 | V1]\n{TEXTS[0]}\n[002 | V2]\n{TEXTS[1]}',
                    {'V1': {'profile_id': temp_profiles[0]['id']},
                     'V2': {'profile_id': temp_profiles[1]['id']}},
                    engine, title='Diagnóstico temporário de troca vocal')
                runs = []

                def measured_generator(request, **kwargs):
                    result = generate_narration(request, **kwargs)
                    if engine == 'qwen3-tts-local':
                        from berofel.services import qwen3_tts_local as backend
                        process = backend._WORKER_PROCESS
                        process_id = process.pid if process is not None else result.get('worker_pid')
                    elif engine == 'qwen3-tts-native-q4':
                        from berofel.services import qwen3_native_tts as backend
                        process = backend._PROCESS
                        process_id = process.pid if process is not None else None
                    else:
                        from berofel.services import qwen3_purec_tts as backend
                        process = backend._PROCESS
                        process_id = process.pid if process is not None else None
                    runs.append({
                        'process_id': process_id,
                        'model_load_seconds': round(float(result.get('model_load_seconds', 0) or 0), 3),
                        'profile_prepare_seconds': round(float(result.get('profile_prepare_seconds', 0) or 0), 3),
                        'generation_seconds': round(float(result.get('generation_seconds', 0) or 0), 3),
                        'profile_cache_hit': bool(result.get('profile_cache_hit',
                                                              result.get('prompt_cache_hit', False))),
                    })
                    return result

                started = time.perf_counter()
                result = generate_script_audio(
                    script, profile_map, str(root / f'{engine}.berofel.json'),
                    generator=measured_generator)
                if engine == 'qwen3-tts-native-q4':
                    process_ids = {item['process_id'] for item in runs}
                    if len(process_ids) != 1 or None in process_ids:
                        raise RuntimeError('O servidor Native Q4 não permaneceu no mesmo processo entre V1 e V2.')
                    if runs[1]['model_load_seconds'] != 0:
                        raise RuntimeError('Native Q4 recarregou o modelo na troca de perfil vocal.')
                grouped_order = [line.voice_id for _, lines in group_script_lines_by_profile(result)
                                 for line in lines]
                if grouped_order != ['V1', 'V2']:
                    raise RuntimeError('A fila não processou V1 e V2 em lotes ordenados.')
                wav_metrics = [_wav_stats(line.audio_path) for line in result.lines]
                report['engines'].append({
                    'engine': engine,
                    'elapsed_seconds': round(time.perf_counter() - started, 3),
                    'grouped_order': grouped_order,
                    'runs': runs,
                    'wavs': wav_metrics,
                })
                if engine == 'qwen3-tts-local':
                    stop_local_worker()
                elif engine == 'qwen3-tts-native-q4':
                    from berofel.services.qwen3_native_tts import stop_native_worker
                    stop_native_worker()
                else:
                    stop_purec_worker()
            report['temporary_profiles_audio_caches_removed'] = True
            print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        try:
            from berofel.services.qwen3_tts_local import stop_local_worker
            stop_local_worker()
        except ImportError:
            pass
        try:
            from berofel.services.qwen3_purec_tts import stop_purec_worker
            stop_purec_worker()
        except ImportError:
            pass
        try:
            from berofel.services.qwen3_native_tts import stop_native_worker
            stop_native_worker()
        except ImportError:
            pass
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
