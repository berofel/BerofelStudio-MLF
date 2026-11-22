"""Exercise Pure C voice-group switching with synthetic, non-personal audio.

This diagnoses profile preparation and server reload behavior. It is not a
voice-identity, naturalness, or speaker-similarity acceptance test.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import time
import wave

import numpy as np
from scipy.io import wavfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from berofel.services.multivoice_narration import (
    create_script, generate_script_audio, group_script_lines_by_profile,
)
from berofel.services.narration_service import generate_narration
from berofel.services.qwen3_purec_tts import is_ready, stop_purec_worker
from berofel.services.voice_profiles import VoiceProfileManager


ENGINES = ('qwen3-tts-purec-int8', 'qwen3-tts-purec-mixed')


def _make_reference(path: Path, fundamental: float,
                    formants: tuple[float, ...]) -> None:
    rate = 24_000
    duration = 4.0
    t = np.arange(round(rate * duration), dtype=np.float64) / rate
    phase = 2 * np.pi * np.cumsum(fundamental + 7 * np.sin(2 * np.pi * 2.7 * t)) / rate
    carrier = np.zeros_like(t)
    for harmonic in range(1, 18):
        frequency = harmonic * fundamental
        envelope = sum(math.exp(-.5 * ((frequency - center) / 190.) ** 2)
                       for center in formants)
        carrier += (envelope / harmonic) * np.sin(harmonic * phase)
    syllables = .55 + .45 * (.5 + .5 * np.sin(2 * np.pi * 3.1 * t))
    signal = carrier * syllables
    signal *= min(.8, .2 / (np.max(np.abs(signal)) or 1))
    wavfile.write(path, rate,
                  np.clip(signal * 32767, -32768, 32767).astype('<i2'))


def _measure(path: str) -> tuple[float, float, int]:
    with wave.open(path, 'rb') as audio:
        frames = audio.getnframes()
        rate = audio.getframerate()
        pcm = audio.readframes(frames)
        if audio.getsampwidth() != 2 or audio.getnchannels() != 1:
            raise RuntimeError('O WAV de teste não é PCM mono de 16 bits.')
    samples = np.frombuffer(pcm, dtype='<i2')
    if not samples.size:
        raise RuntimeError('O WAV sintético de teste ficou vazio.')
    rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
    if rms <= 0:
        raise RuntimeError('O WAV sintético de teste ficou silencioso.')
    return frames / rate, rms, len(pcm)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', choices=ENGINES,
                        default='qwen3-tts-purec-int8')
    args = parser.parse_args()
    if not is_ready():
        raise SystemExit('O Qwen3 Base ou o runtime Pure C não está disponível localmente.')

    temp = tempfile.TemporaryDirectory(prefix='bfs_synthetic_voice_switch_')
    root = Path(temp.name)
    overrides = {
        'BEROFEL_VOICE_PROFILE_DIR': str(root / 'profiles'),
        'BEROFEL_AI_CACHE': str(root / 'ai-cache'),
        'BEROFEL_QWEN3_PUREC_PROFILE_CACHE': str(root / 'purec-profiles'),
        'HF_HUB_OFFLINE': '1',
        'TRANSFORMERS_OFFLINE': '1',
        'HF_HUB_DISABLE_TELEMETRY': '1',
    }
    previous = {key: os.environ.get(key) for key in overrides}
    os.environ.update(overrides)
    try:
        profiles = []
        for index, (fundamental, formants) in enumerate((
                (125., (700., 1200., 2500.)),
                (185., (450., 1650., 2800.))), 1):
            source = root / f'synthetic_reference_{index}.wav'
            _make_reference(source, fundamental, formants)
            profiles.append(VoiceProfileManager().create(
                f'Synthetic validation {index}', source, 'portuguese', '',
                authorized=True))

        assignments = {
            'V1': {'profile_id': profiles[0]['id']},
            'V2': {'profile_id': profiles[1]['id']},
        }
        script = create_script(
            '[001 | V1]\nEsta é a primeira voz sintética do teste.\n'
            '[002 | V2]\nEsta é a segunda voz sintética do teste.',
            assignments, args.engine, title='Troca sintética de perfil')
        profile_map = {item['id']: VoiceProfileManager().get(item['id'])
                       for item in profiles}
        started = time.perf_counter()
        result = generate_script_audio(script, profile_map,
            str(root / 'validation_project.bfs'), generator=generate_narration)

        group_order = []
        for profile_id, lines in group_script_lines_by_profile(result):
            group_order.extend(line.voice_id for line in lines)
        measurements = []
        for line in result.lines:
            if line.status != 'generated' or not Path(line.audio_path).is_file():
                raise RuntimeError(f'A fala sintética {line.number} não foi gerada.')
            duration, rms, byte_count = _measure(line.audio_path)
            measurements.append({
                'voice': line.voice_id,
                'duration_seconds': round(duration, 3),
                'rms_pcm16': round(rms, 1),
                'wav_bytes': byte_count,
                'profile_prepare_seconds': round(line.profile_prepare_seconds, 3),
                'model_load_seconds': round(line.model_load_seconds, 3),
                'generation_seconds': round(line.generation_seconds, 3),
                'first_audio_seconds': round(line.first_audio_seconds, 3),
            })
        if group_order != ['V1', 'V2']:
            raise RuntimeError('A fila não processou os perfis na ordem dos lotes.')
        if any(item['model_load_seconds'] <= 0 for item in measurements):
            raise RuntimeError('A troca de perfil não foi observada como nova carga do servidor.')

        print(json.dumps({
            'test': 'synthetic-references-only',
            'engine': args.engine,
            'distinct_synthetic_profiles': len({item['id'] for item in profiles}) == 2,
            'ordered_voice_groups': group_order,
            'line_count': len(result.lines),
            'total_seconds': round(time.perf_counter() - started, 3),
            'measurements': measurements,
            'voice_identity_or_naturalness_validated': False,
        }, ensure_ascii=False, indent=2))
        return 0
    finally:
        stop_purec_worker()
        temp.cleanup()
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == '__main__':
    raise SystemExit(main())
