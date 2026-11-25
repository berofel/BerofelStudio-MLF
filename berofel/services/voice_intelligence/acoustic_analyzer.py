"""Low-cost, deterministic PCM measurements for voice-reference windows.

This module intentionally uses the standard library so reference checks can
still start in reduced installations. Features are descriptive measurements,
not speaker identity, perceptual quality, or calibrated SNR.
"""
from __future__ import annotations

from array import array
import math
import sys

ACOUSTIC_FEATURE_VERSION = 1
PITCH_FEATURE_VERSION = 1


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = round((len(ordered) - 1) * max(0.0, min(1.0, fraction)))
    return ordered[index]


def analyze_pcm_f32le(pcm: bytes, *, sample_rate: int = 16000,
                      frame_ms: int = 20) -> dict:
    """Summarize mono little-endian float PCM in bounded short frames."""
    if sample_rate <= 0 or frame_ms <= 0:
        raise ValueError("sample_rate e frame_ms precisam ser positivos")
    usable = len(pcm) - len(pcm) % 4
    if usable == 0:
        raise ValueError("PCM vazio")
    samples = array("f")
    samples.frombytes(pcm[:usable])
    if sys.byteorder != "little":
        samples.byteswap()
    frame_size = max(1, round(sample_rate * frame_ms / 1000))
    frame_rms: list[float] = []
    frame_zcr: list[float] = []
    square_sum = 0.0
    peak = 0.0
    clipped = quiet = crossings = 0
    previous_sign = 0
    for frame_start in range(0, len(samples), frame_size):
        frame_end = min(frame_start + frame_size, len(samples))
        frame_square = 0.0
        frame_crossings = 0
        frame_previous_sign = 0
        for index in range(frame_start, frame_end):
            value = float(samples[index])
            if not math.isfinite(value):
                raise ValueError("PCM contém NaN ou infinito")
            magnitude = abs(value)
            square = value * value
            square_sum += square
            frame_square += square
            peak = max(peak, magnitude)
            clipped += magnitude >= .999
            quiet += magnitude < .005
            sign = 1 if value >= 0 else -1
            if previous_sign and sign != previous_sign:
                crossings += 1
            if frame_previous_sign and sign != frame_previous_sign:
                frame_crossings += 1
            previous_sign = frame_previous_sign = sign
        count = frame_end - frame_start
        frame_rms.append(math.sqrt(frame_square / count))
        frame_zcr.append(frame_crossings / max(1, count - 1))

    count = len(samples)
    rms = math.sqrt(square_sum / count)
    rms_dbfs = 20 * math.log10(max(rms, 1e-12))
    peak_dbfs = 20 * math.log10(max(peak, 1e-12))
    # A quiet-frame contrast is only a rough proxy. It is reported only if
    # there are enough truly low-level frames and enough active frames; music,
    # room tone or continuous speech can invalidate the interpretation.
    quiet_frames = [value for value in frame_rms if value < .00316]  # -50 dBFS
    active_frames = [value for value in frame_rms if value >= .01778]  # -35 dBFS
    proxy = None
    proxy_confidence = "unavailable"
    if len(quiet_frames) >= 5 and len(active_frames) >= 5:
        quiet_level = _percentile(quiet_frames, .5) or 0.0
        active_level = _percentile(active_frames, .5) or 0.0
        if quiet_level > 0 and active_level > quiet_level:
            proxy = 20 * math.log10(active_level / quiet_level)
            proxy_confidence = "rough_quiet_frame_contrast"
    return {
        "feature_version": ACOUSTIC_FEATURE_VERSION,
        "sample_rate": sample_rate,
        "sample_count": count,
        "duration_seconds": count / sample_rate,
        "rms_dbfs": rms_dbfs,
        "peak_dbfs": peak_dbfs,
        "crest_factor_db": peak_dbfs - rms_dbfs,
        "clipped_fraction": clipped / count,
        "near_silence_fraction": quiet / count,
        "zero_crossing_rate": crossings / max(1, count - 1),
        "frame_rms_dbfs_p10": (20 * math.log10(max(_percentile(frame_rms, .1) or 0.0, 1e-12))),
        "frame_rms_dbfs_p50": (20 * math.log10(max(_percentile(frame_rms, .5) or 0.0, 1e-12))),
        "frame_rms_dbfs_p90": (20 * math.log10(max(_percentile(frame_rms, .9) or 0.0, 1e-12))),
        "frame_zcr_p50": _percentile(frame_zcr, .5),
        "speech_to_quiet_level_db_proxy": proxy,
        "level_contrast_confidence": proxy_confidence,
        "snr_db": None,
        "snr_confidence": "unavailable_without_noise_reference",
    }


def analyze_pitch_yin_f32le(pcm: bytes, *, sample_rate: int = 16000,
                            min_f0_hz: float = 65.0,
                            max_f0_hz: float = 400.0,
                            max_frames: int = 60) -> dict:
    """Estimate descriptive voiced F0 statistics with bounded YIN sampling.

    This is an optional diagnostic, not a speaker-identity or emotion
    classifier. At most ``max_frames`` evenly distributed 40 ms frames are
    measured, so long references are not analyzed in a Python loop per sample.
    NumPy is imported lazily; if it is unavailable, the caller can retain the
    other standard-library acoustic features.
    """
    if sample_rate <= 0 or max_frames <= 0:
        raise ValueError("sample_rate e max_frames precisam ser positivos")
    if not (0 < min_f0_hz < max_f0_hz < sample_rate / 2):
        raise ValueError("A faixa de F0 precisa estar dentro da faixa de Nyquist")
    usable = len(pcm) - len(pcm) % 4
    if usable == 0:
        raise ValueError("PCM vazio")
    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("NumPy é necessário para estimar F0 por YIN") from exc

    signal = np.frombuffer(pcm[:usable], dtype="<f4")
    if signal.size < round(sample_rate * .04):
        return {"feature_version": PITCH_FEATURE_VERSION,
                "status": "too_short", "f0_median_hz": None,
                "confidence_median": None, "voiced_frame_count": 0,
                "sampled_frame_count": 0}
    if not bool(np.isfinite(signal).all()):
        raise ValueError("PCM contém NaN ou infinito")

    frame_size = max(16, round(sample_rate * .04))
    hop = max(1, round(sample_rate * .5))
    starts = list(range(0, max(1, len(signal) - frame_size + 1), hop))
    if starts[-1] != len(signal) - frame_size:
        starts.append(len(signal) - frame_size)
    if len(starts) > max_frames:
        indices = np.linspace(0, len(starts) - 1, max_frames, dtype=int)
        starts = [starts[int(index)] for index in indices]

    min_lag = max(2, int(sample_rate / max_f0_hz))
    max_lag = min(frame_size // 2, int(sample_rate / min_f0_hz))
    if max_lag <= min_lag:
        return {"feature_version": PITCH_FEATURE_VERSION,
                "status": "insufficient_frame", "f0_median_hz": None,
                "confidence_median": None, "voiced_frame_count": 0,
                "sampled_frame_count": 0}

    pitches: list[float] = []
    confidences: list[float] = []
    for start in starts:
        frame = signal[start:start + frame_size].astype(np.float64, copy=True)
        frame -= float(frame.mean())
        rms = float(np.sqrt(np.mean(frame * frame)))
        if rms < 1e-4:
            continue
        differences = np.empty(max_lag + 1, dtype=np.float64)
        differences[0] = 0.0
        for lag in range(1, max_lag + 1):
            delta = frame[:-lag] - frame[lag:]
            differences[lag] = float(np.dot(delta, delta))
        cumulative = np.cumsum(differences[1:])
        tau = np.arange(1, max_lag + 1, dtype=np.float64)
        cmnd = np.ones(max_lag + 1, dtype=np.float64)
        cmnd[1:] = differences[1:] * tau / np.maximum(cumulative, 1e-20)
        eligible = cmnd[min_lag:max_lag + 1]
        if eligible.size == 0:
            continue
        local = int(np.argmin(eligible))
        lag = min_lag + local
        # Prefer the first meaningful valley, as in the established YIN
        # threshold step; fall back to the best in-band valley conservatively.
        threshold_hits = np.flatnonzero(eligible < .15)
        if threshold_hits.size:
            lag = min_lag + int(threshold_hits[0])
            while lag < max_lag and cmnd[lag + 1] < cmnd[lag]:
                lag += 1
        confidence = max(0.0, min(1.0, 1.0 - float(cmnd[lag])))
        if confidence < .70:
            continue
        refined = float(lag)
        if 1 <= lag < max_lag:
            left, center, right = float(cmnd[lag - 1]), float(cmnd[lag]), float(cmnd[lag + 1])
            denominator = left - 2.0 * center + right
            if abs(denominator) > 1e-12:
                refined += max(-.5, min(.5, .5 * (left - right) / denominator))
        frequency = sample_rate / refined if refined > 0 else 0.0
        if min_f0_hz <= frequency <= max_f0_hz:
            pitches.append(frequency)
            confidences.append(confidence)

    if len(pitches) < 3:
        status = ("unvoiced_or_low_confidence" if not pitches else
                  "insufficient_voiced_coverage")
        median = p10 = p90 = mad = semitone_mad = None
        confidence_median = None
    else:
        ordered = sorted(pitches)
        median = _percentile(ordered, .5)
        p10, p90 = _percentile(ordered, .1), _percentile(ordered, .9)
        deviations = [abs(value - float(median)) for value in ordered]
        mad = _percentile(deviations, .5)
        semitones = [12.0 * math.log2(value / float(median)) for value in ordered]
        semitone_mad = _percentile(sorted(abs(value) for value in semitones), .5)
        confidence_median = _percentile(confidences, .5)
        status = "measured"
    return {
        "feature_version": PITCH_FEATURE_VERSION,
        "method": "YIN difference function with CMND threshold and parabolic refinement",
        "status": status,
        "f0_median_hz": median,
        "f0_p10_hz": p10,
        "f0_p90_hz": p90,
        "f0_mad_hz": mad,
        "f0_mad_semitones": semitone_mad,
        "confidence_median": confidence_median,
        "voiced_frame_count": len(pitches),
        "sampled_frame_count": len(starts),
        "confidence_threshold": .70,
        "identity_score": None,
    }
