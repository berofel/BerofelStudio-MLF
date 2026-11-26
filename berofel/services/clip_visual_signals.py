"""Lightweight relative visual-change features from existing timeline thumbs.

This module never decodes source video or requests missing thumbnails. It can
only read JPEG files already present in the timeline cache. Scores describe
relative image change, not semantic importance or event recognition.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class CachedVisualSignals:
    sample_times_ms: np.ndarray
    change_times_ms: np.ndarray
    frame_change: np.ndarray
    histogram_change: np.ndarray
    frame_count: int
    expected_count: int
    cache_hit: bool = False


def read_cached_visual_signals(source: str, start: float, end: float,
                               provider, *, step_seconds: int = 1,
                               max_samples: int = 7200,
                               cache_dir: Path | None = None,
                               control=None) -> CachedVisualSignals | None:
    """Read existing thumbnails at a sparse fixed cadence without enqueuing.

    Pillow is already a core editor dependency. A missing optional provider,
    corrupt thumbnail, or absent cache simply yields no visual evidence.
    """
    if provider is None or not np.isfinite(start + end) or end <= start:
        return None
    step_seconds = max(1, int(step_seconds))
    first = max(0, int(np.ceil(float(start) / step_seconds) * step_seconds))
    last = int(np.floor(float(end) / step_seconds) * step_seconds)
    if last < first:
        return None
    expected = min(max_samples, (last - first) // step_seconds + 1)
    if expected <= 0:
        return None
    stride = max(1, int(np.ceil(((last-first)//step_seconds+1) / max_samples)))
    try:
        from PIL import Image
    except ImportError:
        return None

    available=[]
    for sample_index,at in enumerate(range(first,last+1,step_seconds*stride)):
        if control is not None and sample_index % 32 == 0:
            control.checkpoint()
        try:
            path = provider.get_thumb(source, at, request=False)
            if not path or not Path(path).is_file():
                continue
            stat=Path(path).stat()
        except (OSError, ValueError, TypeError):
            continue
        available.append((at,str(Path(path).resolve()),stat.st_size,stat.st_mtime_ns))

    expected=min(max_samples,(last-first)//step_seconds+1)
    signature=repr(('clip-visual-v1',str(Path(source).resolve()),
        round(float(start),3),round(float(end),3),step_seconds,stride,available))
    key=hashlib.sha256(signature.encode('utf-8','surrogatepass')).hexdigest()[:32]
    cache_path=(Path(cache_dir)/'visual'/key[:2]/f'{key}.npz'
                if cache_dir is not None else None)
    if cache_path is not None:
        try:
            with np.load(cache_path,allow_pickle=False) as data:
                if str(data['key'].item())==key:
                    return CachedVisualSignals(
                        data['sample_times_ms'].astype(np.float64,copy=True),
                        data['change_times_ms'].astype(np.float64,copy=True),
                        data['frame_change'].astype(np.float32,copy=True),
                        data['histogram_change'].astype(np.float32,copy=True),
                        int(data['frame_count'][0]),int(data['expected_count'][0]),True)
        except (OSError,ValueError,KeyError,EOFError):
            pass

    times: list[float] = []
    images: list[np.ndarray] = []
    for sample_index,(at,path,_size,_mtime) in enumerate(available):
        if control is not None and sample_index % 32 == 0:
            control.checkpoint()
        try:
            with Image.open(path) as image:
                gray=image.convert('L').resize((32,18),Image.Resampling.BILINEAR)
                pixels=np.asarray(gray,dtype=np.uint8)
            if pixels.shape!=(18,32):
                continue
        except (OSError,ValueError,TypeError):
            continue
        times.append(float(at)*1000.)
        images.append(pixels)

    if len(images) < 2:
        result=CachedVisualSignals(np.asarray(times,dtype=np.float64),
            np.empty(0, dtype=np.float64), np.empty(0, dtype=np.float32),
            np.empty(0, dtype=np.float32),
            len(images), expected)
        _save_visual_features(cache_path,key,result)
        return result

    frame_changes: list[float] = []
    histogram_changes: list[float] = []
    change_times: list[float] = []
    for index in range(1, len(images)):
        gap = times[index] - times[index - 1]
        # A large unobserved interval cannot represent adjacent-frame motion.
        if gap > max(2500., step_seconds * stride * 1500.):
            continue
        left = images[index - 1]
        right = images[index]
        frame_changes.append(float(np.mean(np.abs(
            right.astype(np.int16) - left.astype(np.int16))) / 255.))
        left_hist = np.histogram(left, bins=16, range=(0, 256))[0].astype(np.float64)
        right_hist = np.histogram(right, bins=16, range=(0, 256))[0].astype(np.float64)
        left_hist /= max(1., float(left_hist.sum()))
        right_hist /= max(1., float(right_hist.sum()))
        histogram_changes.append(float(.5 * np.abs(left_hist-right_hist).sum()))
        change_times.append(times[index])

    result=CachedVisualSignals(np.asarray(times,dtype=np.float64),
        np.asarray(change_times, dtype=np.float64),
        np.asarray(frame_changes, dtype=np.float32),
        np.asarray(histogram_changes, dtype=np.float32), len(images), expected)
    _save_visual_features(cache_path,key,result)
    return result


def _save_visual_features(path: Path | None, key: str,
                          signals: CachedVisualSignals) -> None:
    if path is None:
        return
    temporary=path.with_name(path.name+f'.{os.getpid()}.tmp')
    try:
        path.parent.mkdir(parents=True,exist_ok=True)
        with temporary.open('wb') as stream:
            np.savez_compressed(stream,key=np.asarray(key),
                sample_times_ms=signals.sample_times_ms,
                change_times_ms=signals.change_times_ms,
                frame_change=signals.frame_change,
                histogram_change=signals.histogram_change,
                frame_count=np.asarray([signals.frame_count],dtype=np.int32),
                expected_count=np.asarray([signals.expected_count],dtype=np.int32))
        os.replace(temporary,path)
    except OSError:
        pass
    finally:
        temporary.unlink(missing_ok=True)


def _robust_relative(values: np.ndarray, baseline: np.ndarray) -> float | None:
    if not len(values) or not len(baseline):
        return None
    center = float(np.median(baseline))
    mad = float(np.median(np.abs(baseline - center)))
    # If this recording's sampled signal is constant, do not amplify tiny JPEG
    # noise into a high visual score.
    if mad < 1e-5:
        spread = float(np.percentile(baseline, 90) - np.percentile(baseline, 10))
        if spread < 1e-5:
            return .5
        scale = max(spread / 2.563, 1e-4)
    else:
        scale = max(1.4826 * mad, 1e-4)
    z = (float(np.median(values)) - center) / scale
    return float(np.clip(.5 + z / 5., 0., 1.))


def score_cached_visual_interval(signals: CachedVisualSignals | None,
                                 start_ms: float, end_ms: float,
                                 *, minimum_coverage: float = .50,
                                 minimum_frames: int = 5) -> dict:
    """Return a cautious visual-change proxy only when cache coverage is usable."""
    unavailable = {'score': None, 'coverage': 0., 'frames': 0,
                   'reason': 'Sem miniaturas suficientes no cache visual.'}
    if signals is None or not 0 <= start_ms < end_ms:
        return unavailable
    duration_seconds = max(1., (end_ms - start_ms) / 1000.)
    expected = max(1, int(np.ceil(duration_seconds)))
    frame_times = signals.sample_times_ms
    count = int(np.searchsorted(frame_times, end_ms, side='left') -
                np.searchsorted(frame_times, start_ms, side='left'))
    coverage = min(1., count / expected)
    if count < minimum_frames or coverage < minimum_coverage or not len(signals.frame_change):
        return {'score': None, 'coverage': round(coverage, 3), 'frames': count,
                'reason': 'Cobertura de miniaturas insuficiente para pontuação visual.'}
    change_left = int(np.searchsorted(signals.change_times_ms, start_ms, side='left'))
    change_right = int(np.searchsorted(signals.change_times_ms, end_ms, side='left'))
    frame_values = signals.frame_change[change_left:change_right]
    hist_values = signals.histogram_change[change_left:change_right]
    if len(frame_values) < minimum_frames - 1:
        return {'score': None, 'coverage': round(coverage, 3), 'frames': count,
                'reason': 'Poucas transições visuais no intervalo em cache.'}
    motion = _robust_relative(frame_values, signals.frame_change)
    scene = _robust_relative(hist_values, signals.histogram_change)
    if motion is None or scene is None:
        return unavailable
    return {'score': round(float(np.clip(.6*motion + .4*scene, 0., 1.)), 3),
            'coverage': round(coverage, 3), 'frames': count,
            'reason': 'Mudança visual relativa à amostra em cache; não identifica conteúdo.'}


def detect_cached_visual_events(signals: CachedVisualSignals | None, *,
                                max_events: int = 32,
                                minimum_distance_ms: float = 1500.) -> list[dict]:
    """Return sparse visual-change cues from already cached thumbnails.

    These are not semantic scene or action labels. The conservative robust
    threshold prevents constant JPEG noise from becoming an event, and the
    caller must keep the cue explicitly identified as a visual proxy.
    """
    if (signals is None or len(signals.change_times_ms) == 0 or
            len(signals.frame_change) != len(signals.histogram_change)):
        return []
    values = (.6 * signals.frame_change.astype(np.float64) +
              .4 * signals.histogram_change.astype(np.float64))
    valid = np.isfinite(values) & np.isfinite(signals.change_times_ms)
    if not np.any(valid):
        return []
    values = values[valid]
    times = signals.change_times_ms[valid]
    center = float(np.median(values))
    mad = float(np.median(np.abs(values - center)))
    spread = float(np.percentile(values, 90) - np.percentile(values, 10))
    scale = max(1.4826 * mad, spread / 2.563, .015)
    threshold = center + max(2.5 * scale, .08)
    eligible = np.flatnonzero(values >= threshold)
    if not len(eligible):
        return []

    # Greedy non-maximum suppression by cue strength avoids returning a run of
    # nearly identical 1-FPS thumbnail changes around the same visual moment.
    ranked = sorted(eligible.tolist(), key=lambda index: values[index], reverse=True)
    selected: list[int] = []
    for index in ranked:
        if any(abs(float(times[index] - times[other])) < minimum_distance_ms
               for other in selected):
            continue
        selected.append(index)
        if len(selected) >= max(1, int(max_events)):
            break
    result = []
    for index in selected:
        strength = float(np.clip((values[index] - threshold) /
                                 max(4. * scale, .1), 0., 1.))
        result.append({
            'kind': 'cached_thumbnail_change',
            'start_ms': round(float(times[index])),
            'end_ms': round(float(times[index]) + 1000.),
            'strength': round(strength, 3),
            'visual_change': round(float(values[index]), 4),
            'source': 'cached_thumbnail_proxy',
            'meaning': 'visual change only; no semantic action recognition',
        })
    return sorted(result, key=lambda event: event['start_ms'])
