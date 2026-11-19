"""Profile actual Qwen3-TTS Base CPU stages using an authorized saved voice.

This is an opt-in diagnostic. It runs offline, never prints the profile path or
reference transcript, and only writes generated audio when --save-audio-to is
explicitly supplied. Timings are wall-clock; nested Talker/Code Predictor
values must not be summed as if they were disjoint.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import wraps
import json
import os
from pathlib import Path
import sys
import threading
import time
from typing import Callable

os.environ.update({
    'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1',
    'HF_HUB_DISABLE_TELEMETRY': '1', 'PYTHONIOENCODING': 'utf-8',
})

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import psutil
from scipy.io import wavfile

from berofel.services.qwen3_tts_local import model_path
from berofel.services.qwen3_tts_worker import _load_model
from berofel.services.voice_profiles import VoiceProfileManager


@dataclass
class StageMetrics:
    seconds: dict[str, float] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    first_code_frame_seconds: float | None = None
    generation_started: float = 0.0

    def add(self, name: str, elapsed: float) -> None:
        self.seconds[name] = self.seconds.get(name, 0.0) + elapsed
        self.counts[name] = self.counts.get(name, 0) + 1


@contextmanager
def _timed_method(owner, name: str, record: Callable[[tuple, dict, float], None]):
    """Temporarily wrap one bound method without modifying its class or package."""
    original = getattr(owner, name)
    had_instance_value = name in getattr(owner, '__dict__', {})
    old_instance_value = getattr(owner, '__dict__', {}).get(name)

    @wraps(original)
    def wrapped(*args, **kwargs):
        started = time.perf_counter()
        try:
            return original(*args, **kwargs)
        finally:
            record(args, kwargs, time.perf_counter() - started)

    setattr(owner, name, wrapped)
    try:
        yield
    finally:
        if had_instance_value:
            setattr(owner, name, old_instance_value)
        else:
            delattr(owner, name)


def _sequence_length(args, kwargs) -> int:
    value = kwargs.get('inputs_embeds')
    if value is None and args:
        value = args[0]
    shape = getattr(value, 'shape', ())
    return int(shape[1]) if len(shape) > 1 else 0


@contextmanager
def _instrument(model, metrics: StageMetrics):
    core = model.model
    talker = core.talker
    predictor = talker.code_predictor
    decoder = core.speech_tokenizer
    stack = [
        _timed_method(model, '_build_assistant_text',
                      lambda _a, _k, dt: metrics.add('text_formatting', dt)),
        _timed_method(model, '_tokenize_texts',
                      lambda _a, _k, dt: metrics.add('text_tokenization', dt)),
        _timed_method(core, 'generate',
                      lambda _a, _k, dt: metrics.add('talker_generate_total_inclusive', dt)),
        _timed_method(decoder, 'decode',
                      lambda _a, _k, dt: metrics.add('acoustic_decoder', dt)),
    ]

    def talker_forward(args, kwargs, dt):
        if _sequence_length(args, kwargs) > 1:
            metrics.add('talker_prefill_forward', dt)
        else:
            metrics.add('talker_autoregressive_forward_inclusive_cp', dt)

    def code_predictor(args, kwargs, dt):
        metrics.add('code_predictor', dt)
        if metrics.first_code_frame_seconds is None:
            metrics.first_code_frame_seconds = time.perf_counter() - metrics.generation_started

    stack.extend([
        _timed_method(talker, 'forward', talker_forward),
        _timed_method(predictor, 'generate', code_predictor),
    ])
    entered = []
    try:
        for item in stack:
            item.__enter__()
            entered.append(item)
        yield
    finally:
        for item in reversed(entered):
            item.__exit__(None, None, None)


def _authorized_profile(profile_id: str):
    profiles = VoiceProfileManager().list_profiles()
    profile = next((item for item in profiles
                    if item.get('authorized') and item.get('reference_text') and
                    (not profile_id or item.get('id') == profile_id)), None)
    if profile is None:
        raise RuntimeError('Não encontrei um perfil salvo, autorizado e com transcrição.')
    sample = Path(profile['sample_path']).expanduser()
    transcript = str(profile.get('reference_text', '')).strip()
    if not sample.is_file() or not transcript:
        raise RuntimeError('O perfil selecionado está sem áudio de referência ou transcrição.')
    return sample, transcript


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--confirm-own-or-authorized-voice', action='store_true')
    parser.add_argument('--voice-profile-id', default='')
    parser.add_argument('--threads', type=int, default=4)
    parser.add_argument('--text', default='Olá! Esta é uma medição de desempenho do Berofel Studio.')
    parser.add_argument('--save-audio-to', type=Path,
                        help='Destino opcional fora do repositório para avaliação auditiva.')
    args = parser.parse_args()
    if not args.confirm_own_or_authorized_voice:
        parser.error('confirme autorização com --confirm-own-or-authorized-voice')
    if not 1 <= args.threads <= 32:
        parser.error('--threads deve ficar entre 1 e 32')
    if not args.text.strip():
        parser.error('--text não pode estar vazio')

    os.environ['BEROFEL_QWEN3_CPU_THREADS'] = str(args.threads)
    reference, reference_text = _authorized_profile(args.voice_profile_id)
    import torch
    torch.set_num_threads(args.threads)
    try:
        torch.set_num_interop_threads(1)
    except RuntimeError:
        pass

    proc = psutil.Process()
    samples = {'peak_rss': proc.memory_info().rss, 'cpu': []}
    stopped = threading.Event()

    def monitor():
        while not stopped.is_set():
            try:
                samples['peak_rss'] = max(samples['peak_rss'], proc.memory_info().rss)
                samples['cpu'].append(proc.cpu_percent(None) / max(1, os.cpu_count() or 1))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                return
            stopped.wait(.1)

    monitor_thread = threading.Thread(target=monitor, daemon=True)
    monitor_thread.start()
    try:
        started = time.perf_counter()
        model = _load_model(model_path())
        model_load = time.perf_counter() - started

        started = time.perf_counter()
        prompt = model.create_voice_clone_prompt(
            ref_audio=str(reference), ref_text=reference_text)
        profile_prepare = time.perf_counter() - started

        metrics = StageMetrics(generation_started=time.perf_counter())
        with _instrument(model, metrics):
            generation_started = time.perf_counter()
            waves, rate = model.generate_voice_clone(
                text=args.text.strip(), language='Portuguese',
                voice_clone_prompt=prompt,
                max_new_tokens=min(2048, max(96, int(len(args.text.strip()) * 1.5 + 48))))
            generation_total = time.perf_counter() - generation_started

        if not waves or not len(waves[0]):
            raise RuntimeError('O Qwen retornou áudio vazio.')
        audio = np.asarray(waves[0], dtype=np.float32).reshape(-1)
        if not np.isfinite(audio).all() or float(np.max(np.abs(audio))) <= 1e-5:
            raise RuntimeError('O Qwen retornou sinal inválido ou silencioso.')
        save_seconds = 0.0
        if args.save_audio_to:
            destination = args.save_audio_to.expanduser().resolve()
            destination.parent.mkdir(parents=True, exist_ok=True)
            save_started = time.perf_counter()
            wavfile.write(str(destination), int(rate),
                          (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16))
            save_seconds = time.perf_counter() - save_started
        duration = len(audio) / float(rate)
        stopped.set()
        monitor_thread.join(timeout=2)

        print(json.dumps({
            'model': 'Qwen/Qwen3-TTS-12Hz-0.6B-Base',
            'backend': 'official Python/PyTorch CPU float32',
            'threads': args.threads,
            'model_load_seconds': round(model_load, 3),
            'voice_profile_prepare_seconds': round(profile_prepare, 3),
            'text_formatting_seconds': round(metrics.seconds.get('text_formatting', 0.0), 4),
            'text_tokenization_seconds': round(metrics.seconds.get('text_tokenization', 0.0), 4),
            'talker_prefill_forward_seconds': round(metrics.seconds.get('talker_prefill_forward', 0.0), 4),
            'talker_decode_inclusive_of_code_predictor_seconds': round(
                metrics.seconds.get('talker_autoregressive_forward_inclusive_cp', 0.0), 3),
            'talker_decode_calls': metrics.counts.get('talker_autoregressive_forward_inclusive_cp', 0),
            'code_predictor_nested_seconds': round(metrics.seconds.get('code_predictor', 0.0), 3),
            'code_predictor_calls': metrics.counts.get('code_predictor', 0),
            'first_complete_code_frame_seconds': (round(metrics.first_code_frame_seconds, 3)
                if metrics.first_code_frame_seconds is not None else None),
            'talker_generate_total_inclusive_seconds': round(
                metrics.seconds.get('talker_generate_total_inclusive', 0.0), 3),
            'acoustic_decoder_seconds': round(metrics.seconds.get('acoustic_decoder', 0.0), 3),
            'generation_api_total_seconds': round(generation_total, 3),
            'wav_save_seconds': round(save_seconds, 4),
            'audio_seconds': round(duration, 3),
            'rtf': round(generation_total / duration, 3),
            'first_playable_audio_seconds': None,
            'first_audio_note': 'API oficial sem chunks; primeiro code frame não é áudio reproduzível. O resultado tocável só existe quando generate_voice_clone retorna.',
            'audio_finite_non_silent': True,
            'peak_process_rss_gib': round(samples['peak_rss'] / (1024 ** 3), 3),
            'mean_cpu_percent_of_logical_machine': round(
                sum(samples['cpu']) / len(samples['cpu']), 1) if samples['cpu'] else None,
            'saved_audio': bool(args.save_audio_to),
        }, ensure_ascii=False, sort_keys=True), flush=True)
        return 0
    finally:
        stopped.set()
        monitor_thread.join(timeout=2)
        # Drop local model references before process exit; never changes model files.
        try:
            del model
        except UnboundLocalError:
            pass


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f'[FALHOU] {type(exc).__name__}: {str(exc)[:500]}', flush=True)
        raise SystemExit(1)
