"""Compare the clip engine's prior level-only extractor to current DSP features.

This is a reproducible synthetic PCM streaming benchmark. It measures feature
extraction only: it does not include FFmpeg, Parakeet, video decode, ranking, or
editorial accuracy. It does not allocate the full source signal in memory.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import threading
import time
from pathlib import Path

import numpy as np
import psutil

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from berofel.services.clip_audio_signals import extract_frames_from_chunks

RATE = 16_000
FRAME_MS = 20
FRAME_SAMPLES = RATE * FRAME_MS // 1000


def pcm_chunks(seconds: int, chunk_samples: int = 65_536):
    total = seconds * RATE
    cursor = 0
    while cursor < total:
        count = min(chunk_samples, total - cursor)
        sample_index = np.arange(cursor, cursor + count, dtype=np.float64)
        # A deterministic 220 Hz tone with short, bounded amplitude changes.
        amplitude = np.where((sample_index // RATE) % 17 == 0, .06, .035)
        yield (amplitude * np.sin(2 * np.pi * 220 * sample_index / RATE)).astype(np.float32)
        cursor += count


def legacy_level_features(chunks):
    """Reference equivalent of the former RMS/peak/clipping-only pass."""
    rms_values, peak_values, clipped_values = [], [], []
    remainder = np.empty(0, dtype=np.float32)
    for chunk in chunks:
        values = np.asarray(chunk, dtype=np.float32).reshape(-1)
        if remainder.size:
            values = np.concatenate((remainder, values))
        full = (len(values) // FRAME_SAMPLES) * FRAME_SAMPLES
        if full:
            framed = values[:full].reshape(-1, FRAME_SAMPLES)
            rms_values.extend(np.sqrt(np.mean(framed.astype(np.float64) ** 2, axis=1)).tolist())
            peak_values.extend(np.max(np.abs(framed), axis=1).tolist())
            clipped_values.extend(np.mean(np.abs(framed) >= .995, axis=1).tolist())
        remainder = values[full:].copy()
    if remainder.size:
        rms_values.append(float(np.sqrt(np.mean(remainder.astype(np.float64) ** 2))))
        peak_values.append(float(np.max(np.abs(remainder))))
        clipped_values.append(float(np.mean(np.abs(remainder) >= .995)))
    return len(rms_values)


def run_once(seconds: int, method: str) -> dict:
    process = psutil.Process()
    before_rss = process.memory_info().rss
    peak = [before_rss]
    stop = threading.Event()

    def sample_rss():
        while not stop.wait(.01):
            try:
                peak[0] = max(peak[0], process.memory_info().rss)
            except psutil.Error:
                return

    sampler = threading.Thread(target=sample_rss, daemon=True)
    sampler.start()
    started = time.perf_counter()
    cpu_started = time.process_time()
    try:
        if method == 'level_only_reference':
            count = legacy_level_features(pcm_chunks(seconds))
        else:
            frames = extract_frames_from_chunks(pcm_chunks(seconds), RATE, FRAME_MS)
            count = len(frames.times_ms)
            if frames.spectral_flux is None or frames.zero_crossing_rate is None:
                raise RuntimeError('The current extractor did not return the DSP arrays.')
    finally:
        wall = time.perf_counter() - started
        cpu = time.process_time() - cpu_started
        peak[0] = max(peak[0], process.memory_info().rss)
        stop.set()
        sampler.join(timeout=1.)
    return {
        'seconds': seconds,
        'method': method,
        'frames': count,
        'wall_seconds': round(wall, 4),
        'cpu_seconds': round(cpu, 4),
        'sampled_peak_rss_delta_mib': round(max(0, peak[0] - before_rss) / 2**20, 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--minutes', type=int, nargs='+', default=[5, 80])
    parser.add_argument('--repeats', type=int, default=1)
    args = parser.parse_args()
    if args.repeats < 1 or any(value < 1 for value in args.minutes):
        parser.error('minutes e repeats precisam ser positivos')
    rows = []
    for minutes in args.minutes:
        for method in ('level_only_reference', 'current_spectral_flux_zcr'):
            for repeat in range(args.repeats):
                row = run_once(minutes * 60, method)
                row['minutes'] = minutes
                row['repeat'] = repeat + 1
                rows.append(row)
    summary = []
    for minutes in args.minutes:
        for method in ('level_only_reference', 'current_spectral_flux_zcr'):
            group = [row for row in rows if row['minutes'] == minutes and row['method'] == method]
            summary.append({
                'minutes': minutes,
                'method': method,
                'repeats': len(group),
                'median_wall_seconds': round(statistics.median(row['wall_seconds'] for row in group), 4),
                'max_sampled_peak_rss_delta_mib': max(row['sampled_peak_rss_delta_mib'] for row in group),
            })
    print(json.dumps({
        'benchmark': 'synthetic PCM streaming; no media decode, Parakeet, ranking, or editorial-quality measurement',
        'sample_rate': RATE,
        'frame_ms': FRAME_MS,
        'results': rows,
        'summary': summary,
    }, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
