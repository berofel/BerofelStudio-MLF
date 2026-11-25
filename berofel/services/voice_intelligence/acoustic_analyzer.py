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
