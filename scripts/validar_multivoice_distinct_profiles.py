"""Validate two or three authorized, distinct local Qwen3 voices offline.

The generated WAVs and temporary prompt caches stay in a temporary directory.
Pass --profile-v3 to execute the 100-line V1/V2/V3 acceptance script (70/20/10).
The report contains timings and audio measurements, but no voice names or paths.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import wave

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from berofel.services.multivoice_narration import create_script, generate_script_audio
from berofel.services.narration_service import generate_narration
from berofel.services.voice_profiles import VoiceProfileManager


ENGINES = ('qwen3-tts-local', 'qwen3-tts-purec-mixed', 'qwen3-tts-purec-int8')
TEXTS = ('Esta é a primeira voz do teste offline.',
         'Esta é a segunda voz do teste offline.')
ACCEPTANCE_VOICE_ORDER = ('V1', 'V1', 'V1', 'V2', 'V1',
                          'V1', 'V3', 'V1', 'V2', 'V1') * 10


def build_100_line_acceptance_script() -> str:
    """Return a mixed-order 70/20/10 acceptance script with stable numbering."""
    return '\n'.join(
        f'[{number:03d} | {voice}]\n'
        f'Esta é a fala {number:03d} da personagem {voice} no teste offline.'
        for number, voice in enumerate(ACCEPTANCE_VOICE_ORDER, 1))


def _sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _list_profiles(manager: VoiceProfileManager) -> int:
    profiles = manager.list_profiles()
    for item in profiles:
        if item.get('authorized') and Path(item.get('sample_path', '')).is_file():
            print(f"{item['id']}  {item['name']}")
    return 0


def select_authorized_distinct_profiles(manager: VoiceProfileManager,
                                        profile_v1: str, profile_v2: str,
                                        profile_v3: str | None = None
                                        ) -> tuple[dict[str, dict], dict[str, str]]:
    """Load two or three selected voices and reject duplicate references."""
    if not profile_v1 or not profile_v2:
        raise ValueError('Informe os IDs dos perfis V1 e V2.')
    requested_ids = [profile_v1, profile_v2]
    if profile_v3:
        requested_ids.append(profile_v3)
    if len(set(requested_ids)) != len(requested_ids):
        raise ValueError('V1, V2 e V3 precisam usar IDs de perfil diferentes.')
    voice_ids = tuple(f'V{index}' for index in range(1, len(requested_ids) + 1))
    profiles = {profile_id: manager.get(profile_id) for profile_id in requested_ids}
    for voice_id, profile_id in zip(voice_ids, requested_ids):
        profile = profiles[profile_id]
        if not profile.get('authorized'):
            raise PermissionError(f'O perfil associado a {voice_id} não está autorizado.')
        if not Path(str(profile.get('sample_path', ''))).is_file():
            raise FileNotFoundError(f'A gravação do perfil associado a {voice_id} não existe.')
    hashes = {profile_id: _sha256(profile['sample_path'])
              for profile_id, profile in profiles.items()}
    if len(set(hashes.values())) != len(requested_ids):
        raise ValueError('As referências precisam ser gravações diferentes entre si.')
    return profiles, hashes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--confirm-own-or-authorized-voice', action='store_true',
                        help='Confirma autorização para usar os perfis selecionados.')
    parser.add_argument('--list-profiles', action='store_true',
                        help='Lista IDs e nomes dos perfis locais já autorizados.')
    parser.add_argument('--profile-v1', help='ID do perfil local autorizado para V1.')
    parser.add_argument('--profile-v2', help='ID do perfil local autorizado para V2.')
    parser.add_argument('--profile-v3', help='ID do perfil local autorizado para V3; ativa o teste de 100 falas.')
    parser.add_argument('--engine', choices=ENGINES, default='qwen3-tts-purec-int8',
                        help='Backend local instalado; padrão: Pure C INT8.')
    args = parser.parse_args()
    manager = VoiceProfileManager()
    if args.list_profiles:
        return _list_profiles(manager)
    if not args.confirm_own_or_authorized_voice:
        parser.error('confirme que os perfis selecionados têm autorização de uso.')
    try:
        profiles, hashes = select_authorized_distinct_profiles(
            manager, args.profile_v1, args.profile_v2, args.profile_v3)
    except (ValueError, PermissionError, FileNotFoundError, KeyError) as exc:
        raise SystemExit(str(exc)) from exc

    if args.engine == 'qwen3-tts-local':
        from berofel.services.qwen3_tts_local import is_ready
        if not is_ready():
            raise SystemExit('O Qwen3-TTS Original não está instalado localmente.')
    else:
        from berofel.services.qwen3_purec_tts import is_ready
        if not is_ready():
            raise SystemExit('O backend Pure C não está instalado localmente.')

    ordered_ids = [args.profile_v1, args.profile_v2]
    if args.profile_v3:
        ordered_ids.append(args.profile_v3)
    assignments = {f'V{index}': {'profile_id': profile_id}
                   for index, profile_id in enumerate(ordered_ids, 1)}
    script_text = (build_100_line_acceptance_script() if args.profile_v3 else
                   f'[001 | V1]\n{TEXTS[0]}\n[002 | V2]\n{TEXTS[1]}')
    script = create_script(script_text, assignments, args.engine,
                           title=('Validação multivozes 100 falas' if args.profile_v3
                                  else 'Validação multivozes offline'))
    lookup = {hashes[profile_id]: f'V{index}'
              for index, profile_id in enumerate(ordered_ids, 1)}
    measurements = []
    started = time.perf_counter()

    with tempfile.TemporaryDirectory(prefix='bfs_multivoice_distinct_') as temp:
        root = Path(temp)
        overrides = {
            'BEROFEL_AI_CACHE': str(root / 'ai-cache'),
            'BEROFEL_QWEN3_PROMPT_CACHE': str(root / 'voice-prompts'),
            'BEROFEL_QWEN3_PUREC_PROFILE_CACHE': str(root / 'purec-profiles'),
            'HF_HUB_OFFLINE': '1',
            'TRANSFORMERS_OFFLINE': '1',
        }
        previous = {key: os.environ.get(key) for key in overrides}
        os.environ.update(overrides)

        def measured_generator(request, **kwargs):
            voice_key = _sha256(request.voice)
            result = generate_narration(request, **kwargs)
            if args.engine == 'qwen3-tts-local':
                from berofel.services import qwen3_tts_local as backend
                worker = backend._WORKER_PROCESS
                process_id = worker.pid if worker is not None else result.get('worker_pid')
            else:
                from berofel.services import qwen3_purec_tts as backend
                process = backend._PROCESS
                process_id = process.pid if process is not None else None
            measurements.append({
                'voice': lookup[voice_key],
                'process_id': process_id,
                'model_load_seconds': float(result.get('model_load_seconds', 0.0)),
                'profile_prepare_seconds': float(result.get('profile_prepare_seconds', 0.0)),
                'generation_seconds': float(result.get('generation_seconds', 0.0)),
                'profile_cache_hit': bool(result.get('profile_cache_hit',
                                                      result.get('prompt_cache_hit', False))),
            })
            return result

        try:
            result = generate_script_audio(
                script, profiles, str(root / 'validation.berofel.json'),
                generator=measured_generator)
            expected_voice_order = (list(ACCEPTANCE_VOICE_ORDER) if args.profile_v3
                                    else ['V1', 'V2'])
            if [item['voice'] for item in measurements] != expected_voice_order:
                raise RuntimeError('A fila não processou os lotes vocais na ordem esperada.')
            independent_wavs = len({line.audio_path for line in result.lines})
            if independent_wavs != len(result.lines):
                raise RuntimeError('Cada fala deve ter seu próprio arquivo WAV.')
            line_metrics = []
            for line in result.lines:
                if line.status != 'generated' or not line.audio_path:
                    raise RuntimeError(f'A fala {line.number:03d} não foi gerada.')
                with wave.open(line.audio_path, 'rb') as audio:
                    frames, rate = audio.getnframes(), audio.getframerate()
                    samples = np.frombuffer(audio.readframes(frames), dtype='<i2')
                    duration = frames / rate if rate else 0.0
                    rms = float(np.sqrt(np.mean(np.square(samples.astype(np.float64))))) / 32768.0
                    peak = float(np.max(np.abs(samples.astype(np.int32)))) / 32768.0
                if duration <= 0.1 or rms <= 1e-4 or peak <= 0:
                    raise RuntimeError(f'A fala {line.number:03d} está vazia ou silenciosa.')
                line_metrics.append({'number': line.number, 'duration_seconds': round(duration, 3),
                                     'sample_rate': rate, 'rms': round(rms, 6),
                                     'peak': round(peak, 6)})
            report = {
                'engine': args.engine,
                'offline_mode': True,
                'distinct_authorized_reference_files': True,
                'generated_wavs': len(line_metrics),
                'independent_wavs': independent_wavs,
                'voice_distribution': {voice: sum(line.voice_id == voice
                                                   for line in result.lines)
                                       for voice in assignments},
                'processed_group_order': [item['voice'] for item in measurements],
                'profile_preparation_seconds': round(result.profile_preparation_seconds, 3),
                'model_load_seconds': round(result.model_load_seconds, 3),
                'line_audio': line_metrics,
                'profile_runs': measurements,
                'worker_process_ids': [item['process_id'] for item in measurements],
                'model_load_count_observed': sum(
                    1 for item in measurements if item['model_load_seconds'] > 0),
                'elapsed_seconds': round(time.perf_counter() - started, 3),
                'temporary_audio_and_caches_removed_on_exit': True,
            }
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
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
