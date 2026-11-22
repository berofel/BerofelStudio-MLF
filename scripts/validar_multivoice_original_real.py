"""Real local smoke for the Original worker across two voice-profile IDs.

The test reuses one already-authorized reference for both IDs so it never
creates or claims a second speaker identity. All generated files and prompt
caches live in a temporary directory and are deleted on exit.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from berofel.services.multivoice_narration import create_script, generate_script_audio
from berofel.services.narration_service import generate_narration
from berofel.services.qwen3_tts_local import is_ready, stop_local_worker
from berofel.services.voice_profiles import VoiceProfileManager


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--confirm-own-or-authorized-voice', action='store_true',
                        help='Confirma uso de um perfil salvo já marcado como autorizado.')
    args = parser.parse_args()
    if not args.confirm_own_or_authorized_voice:
        parser.error('informe --confirm-own-or-authorized-voice após confirmar autorização.')
    if not is_ready():
        raise SystemExit('Qwen3-TTS Base local não está instalado neste PC.')
    profile = next((entry for entry in VoiceProfileManager().list_profiles()
                    if entry.get('authorized') and Path(entry['sample_path']).is_file()), None)
    if profile is None:
        raise SystemExit('Não há perfil vocal salvo, local e autorizado para este teste.')

    # Two profile IDs deliberately point at the same authorized sample. This
    # exercises profile switching and cache/model reuse, not distinct timbres.
    first = dict(profile, id='real-smoke-profile-1')
    second = dict(profile, id='real-smoke-profile-2')
    profiles = {first['id']: first, second['id']: second}
    script = create_script(
        '[001 | V1]\nEsta é a primeira fala do teste local.\n'
        '[002 | V2]\nEsta é a segunda fala do teste local.',
        {'V1': {'profile_id': first['id']}, 'V2': {'profile_id': second['id']}},
        'qwen3-tts-local', title='Smoke multivozes Original')

    measurements = []
    with tempfile.TemporaryDirectory(prefix='bfs_multivoice_original_') as temp:
        root = Path(temp)
        os.environ['BEROFEL_AI_CACHE'] = str(root / 'ai-cache')
        os.environ['BEROFEL_QWEN3_PROMPT_CACHE'] = str(root / 'voice-prompts')
        os.environ.setdefault('BEROFEL_QWEN3_REQUEST_TIMEOUT', '600')
        project = root / 'multivoice_test.berofel.json'

        def real_generator(request, **kwargs):
            result = generate_narration(request, **kwargs)
            measurements.append({
                'worker_pid': result.get('worker_pid'),
                'model_load_count': result.get('model_load_count'),
                'request_model_load_seconds': result.get('model_load_seconds'),
                'worker_model_load_seconds': result.get('worker_model_load_seconds'),
                'profile_cache_hit': result.get('prompt_cache_hit'),
                'generation_seconds': result.get('generation_seconds'),
            })
            return result

        result = generate_script_audio(script, profiles, str(project),
                                       generator=real_generator)
        durations = []
        for line in result.lines:
            with wave.open(line.audio_path, 'rb') as audio:
                if audio.getnframes() <= 0:
                    raise RuntimeError(f'Fala {line.number} produziu WAV vazio.')
                durations.append(audio.getnframes() / audio.getframerate())
        if len(measurements) != 2 or len({item['worker_pid'] for item in measurements}) != 1:
            raise RuntimeError('O worker mudou entre os dois perfis do roteiro.')
        if any(item['model_load_count'] != 1 for item in measurements):
            raise RuntimeError('A contagem de cargas do worker não permaneceu em um.')
        if not measurements[1]['profile_cache_hit']:
            raise RuntimeError('O prompt vocal igual não foi reaproveitado na segunda fala.')
        report = {
            'engine': 'qwen3-tts-local',
            'authorized_reference_reused_for_both_profile_ids': True,
            'distinct_speaker_identity_tested': False,
            'line_count': len(result.lines),
            'wav_durations_seconds': durations,
            'worker_pid_same_for_both_profile_ids': True,
            'model_load_count_per_request': [item['model_load_count'] for item in measurements],
            'request_model_load_seconds': [item['request_model_load_seconds'] for item in measurements],
            'worker_model_load_seconds': [item['worker_model_load_seconds'] for item in measurements],
            'prompt_cache_hit': [item['profile_cache_hit'] for item in measurements],
            'generation_seconds': [item['generation_seconds'] for item in measurements],
            'temporary_audio_and_prompt_cache_removed': True,
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
    stop_local_worker()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
