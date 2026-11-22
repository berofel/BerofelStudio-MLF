"""Offline real smoke for duplicate dialogue lines sharing one saved voice.

The script uses the same authorized local profile for V1 and V2, synthesizes
one identical Portuguese line twice through the selected Pure C backend, and
checks that the second line reuses cache while retaining its own WAV file.
It validates cache/runtime behavior, not distinct speaker identities.
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

from berofel.services.multivoice_narration import create_script, generate_script_audio
from berofel.services.narration_service import generate_narration
from berofel.services.voice_profiles import VoiceProfileManager


ENGINES = ('qwen3-tts-purec-int8', 'qwen3-tts-purec-mixed')
TEXT = 'Esta fala repetida deve ser sintetizada uma única vez.'


def _sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open('rb') as audio:
        for block in iter(lambda: audio.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _wav_metrics(path: str | Path) -> dict:
    with wave.open(str(path), 'rb') as audio:
        channels, width, rate, frames = (audio.getnchannels(), audio.getsampwidth(),
                                         audio.getframerate(), audio.getnframes())
        pcm = np.frombuffer(audio.readframes(frames), dtype='<i2')
    if channels != 1 or width != 2 or rate != 24_000 or frames <= 0 or pcm.size == 0:
        raise RuntimeError('O WAV gerado não está em mono PCM16/24 kHz ou está vazio.')
    rms = float(np.sqrt(np.mean(np.square(pcm.astype(np.float64)))))
    if rms < 3:
        raise RuntimeError('O WAV gerado está silencioso.')
    return {'duration_seconds': round(frames / rate, 3), 'rms_pcm16': round(rms, 1)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--confirm-own-or-authorized-voice', action='store_true',
                        help='Confirma autorização para usar o perfil local selecionado.')
    parser.add_argument('--profile-id', help='ID do perfil. Necessário se houver mais de um autorizado.')
    parser.add_argument('--engine', choices=ENGINES, required=True,
                        help='Pure C INT8 (Equilibrado) ou Pure C Mixer (Turbo).')
    args = parser.parse_args()
    if not args.confirm_own_or_authorized_voice:
        parser.error('confirme autorização para usar a referência vocal local.')

    manager = VoiceProfileManager()
    available = [item for item in manager.list_profiles()
                 if item.get('authorized') and Path(item.get('sample_path', '')).is_file()]
    if args.profile_id:
        available = [item for item in available if item['id'] == args.profile_id]
    elif len(available) != 1:
        parser.error('informe --profile-id quando houver mais de um perfil autorizado.')
    if not available:
        raise SystemExit('Não há perfil local autorizado correspondente à seleção.')
    profile = available[0]

    from berofel.services.qwen3_purec_tts import is_ready, stop_purec_worker
    if not is_ready():
        raise SystemExit(f'O backend {args.engine} não está instalado localmente.')

    env_keys = ('BEROFEL_AI_CACHE', 'BEROFEL_QWEN3_PROMPT_CACHE',
                'BEROFEL_QWEN3_PUREC_PROFILE_CACHE', 'HF_HUB_OFFLINE',
                'TRANSFORMERS_OFFLINE', 'HF_HUB_DISABLE_TELEMETRY')
    previous = {key: os.environ.get(key) for key in env_keys}
    try:
        stop_purec_worker()
        with tempfile.TemporaryDirectory(prefix='bfs_duplicate_voice_cache_') as temp:
            root = Path(temp)
            os.environ.update({
                'BEROFEL_AI_CACHE': str(root / 'ai-cache'),
                'BEROFEL_QWEN3_PROMPT_CACHE': str(root / 'prompt-cache'),
                'BEROFEL_QWEN3_PUREC_PROFILE_CACHE': str(root / 'purec-profile-cache'),
                'HF_HUB_OFFLINE': '1',
                'TRANSFORMERS_OFFLINE': '1',
                'HF_HUB_DISABLE_TELEMETRY': '1',
            })
            script = create_script(
                f'[001 | V1]\n{TEXT}\n[002 | V2]\n{TEXT}',
                {'V1': {'profile_id': profile['id']},
                 'V2': {'profile_id': profile['id']}},
                args.engine, title='Validação local do cache entre vozes')
            metrics = []

            def measured_generator(request, **kwargs):
                result = generate_narration(request, **kwargs)
                metrics.append({key: result.get(key) for key in (
                    'generation_seconds', 'model_load_seconds',
                    'profile_prepare_seconds', 'first_audio_chunk_seconds')})
                return result

            result = generate_script_audio(
                script, {profile['id']: profile}, str(root / 'smoke.berofel.json'),
                generator=measured_generator)
            first, second = result.lines
            if len(metrics) != 1 or first.cache_hit or not second.cache_hit:
                raise RuntimeError('O cache não reduziu as duas falas a uma inferência.')
            if first.audio_path == second.audio_path:
                raise RuntimeError('As falas precisam manter WAVs independentes.')
            if _sha256(first.audio_path) != _sha256(second.audio_path):
                raise RuntimeError('As cópias de WAV do cache têm conteúdo diferente.')

            report = {
                'offline': True,
                'engine': args.engine,
                'model': 'Qwen/Qwen3-TTS-12Hz-0.6B-Base',
                'speaker_identity_distinct': False,
                'same_profile_for_v1_v2': True,
                'synthesis_calls': len(metrics),
                'cache_hit_per_line': [first.cache_hit, second.cache_hit],
                'independent_wav_paths': first.audio_path != second.audio_path,
                'wav_sha256_equal': True,
                'wav_metrics': [_wav_metrics(first.audio_path), _wav_metrics(second.audio_path)],
                'generation_metrics': metrics,
                'temporary_outputs_and_caches_removed': True,
            }
            print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        stop_purec_worker()
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
