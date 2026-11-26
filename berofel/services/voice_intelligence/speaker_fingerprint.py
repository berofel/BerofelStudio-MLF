"""Strict validation and comparison for compatible Pure C speaker x-vectors.

The score is a diagnostic similarity, not a calibrated probability or proof of
speaker identity. The current Pure C profile format is 1024 little-endian f32s.
"""
from __future__ import annotations

from pathlib import Path
import math
import struct


VECTOR_DIMENSION = 1024
VECTOR_FORMAT = "qwen3-tts-purec-xvector-1024-f32-le-v1"
EMOTION_DIRECTION_FORMAT = "qwen3-tts-purec-emotion-direction-1024-f32-le-v1"
_EMOTION_TOKENS = {"ang", "disgust", "fear", "joy", "sad", "surprise"}


def read_purec_xvector(path: str | Path) -> tuple[float, ...]:
    """Read a Pure C profile only when its byte length and values are valid."""
    raw = Path(path).read_bytes()
    expected = VECTOR_DIMENSION * 4
    if len(raw) != expected:
        raise ValueError(f"x-vector inválido: esperado {expected} bytes, recebido {len(raw)}.")
    values = struct.unpack("<1024f", raw)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("x-vector contém NaN ou infinito.")
    norm = math.sqrt(sum(value * value for value in values))
    if norm <= 1e-8:
        raise ValueError("x-vector possui norma zero ou inválida.")
    return values


def read_purec_emotion_direction(path: str | Path) -> tuple[float, ...]:
    """Read a named upstream 0.6B direction asset after strict validation.

    This only validates the 1024 little-endian float format. It does not prove
    that the installed runtime consumes the asset or that applying it improves
    perceived emotion or preserves speaker identity.
    """
    source = Path(path)
    if source.stem.casefold().removeprefix("dir_") not in _EMOTION_TOKENS:
        raise ValueError("Arquivo de direção emocional com nome não reconhecido.")
    raw = source.read_bytes()
    expected = VECTOR_DIMENSION * 4
    if len(raw) != expected:
        raise ValueError(f"Direção emocional inválida: esperado {expected} bytes, recebido {len(raw)}.")
    values = struct.unpack("<1024f", raw)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("Direção emocional contém NaN ou infinito.")
    norm = math.sqrt(sum(value * value for value in values))
    if norm <= 1e-8:
        raise ValueError("Direção emocional possui norma zero ou inválida.")
    return values


def apply_emotion_direction(xvector: tuple[float, ...],
                            direction: tuple[float, ...], *,
                            strength: float = 0.25) -> tuple[float, ...]:
    """Return a norm-preserving experimental 0.6B x-vector displacement.

    ``strength`` is the direct low-level alpha described by the Pure C
    0.6B recipe (its documented default is 0.25; 0.35 is a stronger setting).
    The function is deliberately not wired into narration: only a one-shot
    local CLI path has been observed to change audio; the installed resident
    HTTP path did not. The bounded strength prevents uncalibrated extreme
    displacements. Returned values remain Python floats until the caller
    explicitly serializes a compatible profile.
    """
    if len(xvector) != VECTOR_DIMENSION or len(direction) != VECTOR_DIMENSION:
        raise ValueError("x-vector e direção emocional precisam ter 1024 dimensões.")
    if not math.isfinite(strength) or not 0.0 <= strength <= 0.35:
        raise ValueError("A intensidade experimental precisa ficar entre 0 e 0,35.")
    if not all(math.isfinite(value) for value in (*xvector, *direction)):
        raise ValueError("x-vector ou direção emocional contém NaN ou infinito.")
    x_norm = math.sqrt(sum(value * value for value in xvector))
    d_norm = math.sqrt(sum(value * value for value in direction))
    if x_norm <= 1e-8 or d_norm <= 1e-8:
        raise ValueError("x-vector e direção precisam ter norma não nula.")
    if strength == 0.0:
        return tuple(float(value) for value in xvector)
    scale = strength * x_norm / d_norm
    shifted = tuple(float(value) + scale * float(delta)
                    for value, delta in zip(xvector, direction))
    shifted_norm = math.sqrt(sum(value * value for value in shifted))
    if not math.isfinite(shifted_norm) or shifted_norm <= 1e-8:
        raise ValueError("O deslocamento produziu uma direção vocal inválida.")
    restore = x_norm / shifted_norm
    result = tuple(value * restore for value in shifted)
    if not all(math.isfinite(value) for value in result):
        raise ValueError("O x-vector resultante contém NaN ou infinito.")
    return result


def cosine_similarity(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    """Return cosine similarity for compatible finite nonzero vectors."""
    if len(left) != len(right) or not left:
        raise ValueError("x-vectors têm dimensões incompatíveis.")
    if not all(math.isfinite(value) for value in (*left, *right)):
        raise ValueError("x-vector contém NaN ou infinito.")
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm <= 1e-8 or right_norm <= 1e-8:
        raise ValueError("x-vector possui norma zero ou inválida.")
    score = sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)
    return max(-1.0, min(1.0, score))
