"""Controlled float32 vs experimental dynamic INT8 Qwen3-TTS clone benchmark.

Run only with a voice reference that you own or are authorized to use. The
script prints metrics only; it never prints the reference path/text or saves
the generated audio. Run it with the isolated Qwen3 TTS Python environment.
"""
from __future__ import annotations

import argparse
from configparser import ConfigParser
import json
import os
from pathlib import Path
import sys
import threading
import time

os.environ.update({
    'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1',
    'HF_HUB_DISABLE_TELEMETRY': '1',
})

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import psutil
import torch

from berofel.services.qwen3_tts_local import model_path
from berofel.services.qwen3_tts_worker import _load_model

DEFAULT_TEXT = 'Olá! Este é um teste curto de aquecimento do Qwen3-TTS.'


def _configured_reference() -> tuple[Path, str]:
    appdata = os.environ.get('APPDATA')
    if not appdata:
        raise RuntimeError('APPDATA não está configurado neste Windows.')
    settings = ConfigParser(interpolation=None)
    settings.read(Path(appdata) / 'Berofel' / 'BerofelStudio.ini', encoding='utf-8')
    reference = Path(settings.get('narration', 'sample_path', fallback='')).expanduser()
    reference_text = settings.get('narration', 'reference_text', fallback='').strip()
    if not reference.is_file() or not reference_text:
        raise RuntimeError('Configure uma referência e sua transcrição no painel Narração.')
    return reference, reference_text


def _cosine(left, right) -> float:
    left = np.asarray(left, dtype=np.float32).reshape(-1)
    right = np.asarray(right, dtype=np.float32).reshape(-1)
    denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
    if not denominator or left.shape != right.shape:
        raise RuntimeError('O encoder Qwen retornou embeddings incompatíveis.')
    return float(np.dot(left, right) / denominator)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--confirm-own-or-authorized-voice', action='store_true',
        help='Confirma autorização para sintetizar usando a referência configurada.')
    parser.add_argument('--threads', type=int, default=4)
    parser.add_argument('--text', default=DEFAULT_TEXT)
    parser.add_argument('--max-new-tokens', type=int, default=128)
    args = parser.parse_args()
    if not args.confirm_own_or_authorized_voice:
        parser.error('confirme autorização com --confirm-own-or-authorized-voice')
    if not 1 <= args.threads <= 32:
        parser.error('--threads deve ficar entre 1 e 32')
    if not args.text.strip() or not 16 <= args.max_new_tokens <= 2048:
        parser.error('texto vazio ou --max-new-tokens fora de 16..2048')

    os.environ['BEROFEL_QWEN3_CPU_THREADS'] = str(args.threads)
    torch.set_num_threads(args.threads)
    try:
        torch.set_num_interop_threads(1)
    except RuntimeError:
        pass

    reference, reference_text = _configured_reference()
    process = psutil.Process()
    peak = [process.memory_info().rss]
    stop = threading.Event()

    def sample_memory():
        while not stop.is_set():
            try:
                peak[0] = max(peak[0], process.memory_info().rss)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                return
            stop.wait(.1)

    model_started = time.perf_counter()
    model = _load_model(model_path())
    model_load = time.perf_counter() - model_started
    prompt_started = time.perf_counter()
    prompt = model.create_voice_clone_prompt(
        ref_audio=str(reference), ref_text=reference_text)
    prompt_seconds = time.perf_counter() - prompt_started
    reference_embedding = prompt[0].ref_spk_embedding.detach().cpu().float().numpy()
    speaker_encoder_fp32 = model.model.speaker_encoder
    monitor = threading.Thread(target=sample_memory, daemon=True)
    monitor.start()
    records = []

    def synthesize(label: str) -> None:
        peak[0] = process.memory_info().rss
        torch.manual_seed(42)
        np.random.seed(42)
        started = time.perf_counter()
        waves, sample_rate = model.generate_voice_clone(
            text=args.text.strip(), language='Portuguese',
            voice_clone_prompt=prompt, max_new_tokens=args.max_new_tokens)
        elapsed = time.perf_counter() - started
        if not waves or len(waves[0]) == 0:
            raise RuntimeError(f'{label}: áudio vazio')
        audio = np.asarray(waves[0], dtype=np.float32).reshape(-1)
        if not np.isfinite(audio).all() or not np.max(np.abs(audio)) > 1e-5:
            raise RuntimeError(f'{label}: sinal inválido ou silencioso')
        embedding = model.model.extract_speaker_embedding(audio, sample_rate)
        similarity = _cosine(reference_embedding, embedding.detach().cpu().numpy())
        duration = len(audio) / float(sample_rate)
        records.append({
            'variant': label,
            'audio_seconds': round(duration, 3),
            'inference_seconds': round(elapsed, 3),
            'rtf': round(elapsed / duration, 3),
            'speaker_cosine_to_reference': round(similarity, 6),
            'sample_rate': int(sample_rate),
            'finite_non_silent_audio': True,
            'peak_process_rss_gib': round(peak[0] / (1024 ** 3), 3),
        })

    try:
        synthesize('float32')
        peak[0] = process.memory_info().rss
        started = time.perf_counter()
        torch.ao.quantization.quantize_dynamic(
            model.model, {torch.nn.Linear}, dtype=torch.qint8, inplace=True)
        quantization_seconds = time.perf_counter() - started
        # Keep a shared FP32 evaluator so the cosine scores use the same encoder.
        model.model.speaker_encoder = speaker_encoder_fp32
        quantized_linears = sum(
            isinstance(module, torch.ao.nn.quantized.dynamic.Linear)
            for module in model.model.modules())
        synthesize('dynamic_int8')
    finally:
        stop.set()
        monitor.join(timeout=2)
        del model
        import gc
        gc.collect()

    print(json.dumps({
        'model': 'Qwen/Qwen3-TTS-12Hz-0.6B-Base',
        'cpu_threads': args.threads,
        'model_load_seconds': round(model_load, 3),
        'voice_prompt_prepare_seconds': round(prompt_seconds, 3),
        'int8_conversion_seconds': round(quantization_seconds, 3),
        'quantized_linear_layers': quantized_linears,
        'seed': 42,
        'speaker_metric_note': 'cosine proxy, not perceptual MOS',
        'results': records,
    }, ensure_ascii=False, sort_keys=True), flush=True)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f'[FALHOU] {type(exc).__name__}: {str(exc)[:600]}', flush=True)
        raise SystemExit(1)
