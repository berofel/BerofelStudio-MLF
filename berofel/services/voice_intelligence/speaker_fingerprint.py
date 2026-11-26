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
