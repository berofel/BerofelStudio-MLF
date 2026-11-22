"""Small librosa-compatible audio helpers used by the pinned Qwen3-TTS API.

Qwen3-TTS 0.1.1 only calls ``librosa.load`` and ``librosa.resample`` in its
clone-prompt path. Importing the full librosa/numba stack is unusually slow on
some Windows CPU installations. These equivalents use the already-installed
SoundFile and SciPy libraries and keep the normalized local reference path.
"""
from __future__ import annotations

from fractions import Fraction
from importlib.machinery import ModuleSpec
import sys
import types

import numpy as np
from scipy.signal import resample_poly


def resample(y, orig_sr: int, target_sr: int, *, axis: int = -1,
             fix: bool = True, scale: bool = False,
             res_type: str = 'soxr_hq', **kwargs) -> np.ndarray:
    """Resample like librosa, preferring the same installed soxr backend."""
    if kwargs:
        raise TypeError('Parâmetros de reamostragem Qwen não suportados: ' +
                        ', '.join(sorted(kwargs)))
    original = int(orig_sr)
    target = int(target_sr)
    if original <= 0 or target <= 0:
        raise ValueError('Taxas de amostragem precisam ser positivas.')
    samples = np.asarray(y, dtype=np.float32)
    if original == target or samples.size == 0:
        return samples.copy()
    ratio = Fraction(target, original)
    if res_type.startswith('soxr'):
        try:
            import soxr
        except ImportError:
            result = resample_poly(samples, ratio.numerator, ratio.denominator,
                                   axis=axis, window=('kaiser', 8.6))
        else:
            quality = res_type.removeprefix('soxr_').upper()
            result = np.apply_along_axis(soxr.resample, axis=axis, arr=samples,
                in_rate=original, out_rate=target, quality=quality)
    elif res_type == 'polyphase':
        result = resample_poly(samples, ratio.numerator, ratio.denominator,
                               axis=axis)
    else:
        raise ValueError(f'Modo de reamostragem Qwen não suportado: {res_type}')
    result = np.asarray(result, dtype=np.float32)
    if fix:
        expected = int(np.ceil(samples.shape[axis] * target / original))
        current = result.shape[axis]
        if current > expected:
            index = [slice(None)] * result.ndim
            index[axis] = slice(0, expected)
            result = result[tuple(index)]
        elif current < expected:
            pad = [(0, 0)] * result.ndim
            pad[axis] = (0, expected - current)
            result = np.pad(result, pad)
    if scale:
        result /= np.sqrt(target / original)
    return result


def load(path, *, sr: int | None = None, mono: bool = True,
         offset: float = 0.0, duration: float | None = None,
         dtype: str = 'float32', **kwargs):
    """Read a local audio file or SoundFile stream like Qwen's librosa call."""
    if kwargs:
        raise TypeError('Parâmetros de leitura Qwen não suportados: ' +
                        ', '.join(sorted(kwargs)))
    if dtype != 'float32':
        raise ValueError('A leitura de áudio Qwen local requer dtype=float32.')
    if offset < 0 or (duration is not None and duration < 0):
        raise ValueError('Offset e duração de áudio não podem ser negativos.')
    import soundfile as sf
    with sf.SoundFile(path) as source:
        source_rate = int(source.samplerate)
        if offset:
            source.seek(min(len(source), int(round(offset * source_rate))))
        frames = -1 if duration is None else int(round(duration * source_rate))
        audio = source.read(frames=frames, dtype='float32', always_2d=True)
    if mono:
        audio = np.mean(audio, axis=1, dtype=np.float32)
    else:
        audio = audio.T
    if sr is not None and int(sr) != source_rate:
        audio = resample(audio, source_rate, int(sr))
        source_rate = int(sr)
    return np.asarray(audio, dtype=np.float32), source_rate


def mel(*, sr: float, n_fft: int, n_mels: int = 128,
        fmin: float = 0.0, fmax: float | None = None,
        htk: bool = False, norm: str | float | None = 'slaney',
        dtype=np.float32) -> np.ndarray:
    """Build the Slaney/HTK triangular bank used by Qwen's mel encoders.

    This follows librosa.filters.mel's public algorithm. Keep calculations in
    float64 until the final matrix cast, as librosa does for its frequency grid.
    """
    if sr <= 0 or n_fft <= 0 or n_mels <= 0:
        raise ValueError('sr, n_fft e n_mels precisam ser positivos.')
    if fmax is None:
        fmax = float(sr) / 2
    if fmin < 0 or fmax < fmin or fmax > sr / 2:
        raise ValueError('Limites de frequência mel inválidos.')
    if norm not in (None, 'slaney'):
        raise ValueError('A compatibilidade Qwen aceita norm=None ou Slaney.')

    def hz_to_mel(value):
        value = np.asanyarray(value)[()]
        if htk:
            return 2595.0 * np.log10(1.0 + value / 700.0)
        f_sp = 200.0 / 3
        result = value / f_sp
        min_log_hz = 1000.0
        min_log_mel = min_log_hz / f_sp
        logstep = np.log(6.4) / 27.0
        if np.ndim(value):
            mask = value >= min_log_hz
            result[mask] = min_log_mel + np.log(value[mask] / min_log_hz) / logstep
        elif value >= min_log_hz:
            result = min_log_mel + np.log(value / min_log_hz) / logstep
        return result

    def mel_to_hz(value):
        value = np.asanyarray(value)[()]
        if htk:
            return 700.0 * (10.0 ** (value / 2595.0) - 1.0)
        f_sp = 200.0 / 3
        result = f_sp * value
        min_log_mel = 1000.0 / f_sp
        logstep = np.log(6.4) / 27.0
        if np.ndim(value):
            mask = value >= min_log_mel
            result[mask] = 1000.0 * np.exp(logstep * (value[mask] - min_log_mel))
        elif value >= min_log_mel:
            result = 1000.0 * np.exp(logstep * (value - min_log_mel))
        return result

    mel_limits = np.linspace(hz_to_mel(fmin), hz_to_mel(fmax), n_mels + 2)
    mel_points = mel_to_hz(mel_limits)
    fft_freqs = np.arange(0, 1 + n_fft // 2, dtype=np.float64) * (sr / n_fft)
    diffs = np.diff(mel_points)
    ramps = np.subtract.outer(mel_points, fft_freqs)
    weights = np.zeros((n_mels, fft_freqs.size), dtype=dtype)
    for index in range(n_mels):
        lower = -ramps[index] / diffs[index]
        upper = ramps[index + 2] / diffs[index + 1]
        weights[index] = np.maximum(0, np.minimum(lower, upper))
    if norm == 'slaney':
        weights *= (2.0 / (mel_points[2:n_mels + 2] - mel_points[:n_mels]))[:, None]
    return weights


def install_librosa_compat() -> None:
    """Provide the small librosa API surface imported by pinned Qwen3-TTS."""
    if 'librosa' in sys.modules:
        return
    module = types.ModuleType('librosa')
    module.__version__ = '0.10.2'
    module.__spec__ = ModuleSpec('librosa', loader=None)
    module.__path__ = []
    module.load = load
    module.resample = resample
    filters = types.ModuleType('librosa.filters')
    filters.__spec__ = ModuleSpec('librosa.filters', loader=None)
    filters.mel = mel
    module.filters = filters
    sys.modules['librosa'] = module
    sys.modules['librosa.filters'] = filters
