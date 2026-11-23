"""Adapter for the optional, local Parakeet Ultra GGUF runtime.

The default transcription engine remains Faster-Whisper. This module loads the
official transcribe.cpp Python binding from its pinned wheel and native DLLs
from the per-user BFS tools directory; nothing is downloaded at runtime.
"""
from __future__ import annotations

from array import array
import importlib
import os
from pathlib import Path
import struct
import sys
import wave

from .model_paths import (parakeet_model_path, transcribe_binding_wheel,
                          transcribe_runtime_dir)


def load_binding(*, wheel: Path | None = None, library: Path | None = None):
    """Load the pinned binding only after confirming all local artifacts exist."""
    wheel = wheel or transcribe_binding_wheel()
    library = library or (transcribe_runtime_dir() / "transcribe.dll")
    if not wheel.is_file():
        raise FileNotFoundError(
            "Binding Python do Parakeet ausente. Execute scripts/install_parakeet_ultra.ps1."
        )
    if not library.is_file():
        raise FileNotFoundError(
            "Runtime nativo do Parakeet ausente. Execute scripts/install_parakeet_ultra.ps1."
        )
    # zipimport lets the official pure-Python wheel stay isolated from the
    # editor's environment. No pip or model downloads happen during a job.
    wheel_text = str(wheel.resolve())
    if wheel_text not in sys.path:
        sys.path.insert(0, wheel_text)
    os.environ["TRANSCRIBE_LIBRARY"] = str(library.resolve())
    try:
        return importlib.import_module("transcribe_cpp")
    except Exception as exc:
        # Keep the diagnostic actionable; do not mask ABI/backend errors.
        raise RuntimeError(f"Não foi possível carregar transcribe.cpp 0.4.2: {exc}") from exc


def read_pcm16_mono_16k(path: str | Path) -> tuple[array, float]:
    """Read the editor's FFmpeg-normalized WAV without NumPy or a second decode."""
    with wave.open(str(path), "rb") as source:
        channels, width, rate = (source.getnchannels(), source.getsampwidth(),
                                 source.getframerate())
        if (channels, width, rate) != (1, 2, 16000):
            raise ValueError("Áudio Parakeet deve ser WAV PCM16 mono a 16000 Hz.")
        count = source.getnframes()
        raw = source.readframes(count)
    if len(raw) != count * 2:
        raise ValueError("WAV incompleto: o número de amostras não corresponde ao cabeçalho.")
    samples = array("h")
    samples.frombytes(raw)
    if sys.byteorder != "little":
        samples.byteswap()
    pcm = array("f", (sample / 32768.0 for sample in samples))
    return pcm, count / rate


def transcribe_file(path: str | Path, *, model_path: str | Path | None = None,
                    backend: str = "cpu", threads: int = 6,
                    language: str | None = "pt", binding_wheel: Path | None = None,
                    library: Path | None = None, model=None) -> dict:
    """Transcribe a single normalized WAV; caller may provide a reused model.

    Times returned from transcribe.cpp are integer milliseconds. They are
    converted once to seconds here and remain relative to this WAV/chunk.
    """
    model_file = Path(model_path) if model_path else parakeet_model_path()
    if model is None and not model_file.is_file():
        raise FileNotFoundError(
            f"Modelo Parakeet Ultra Q8 não encontrado: {model_file}. "
            "Execute scripts/install_parakeet_ultra.ps1."
        )
    binding = load_binding(wheel=binding_wheel, library=library)
    audio, duration = read_pcm16_mono_16k(path)
    created_model = model is None
    model_context = binding.Model(str(model_file), backend=backend) if created_model else model
    try:
        session_context = model_context.session(n_threads=max(1, int(threads)))
        with session_context as session:
            result = session.run(audio, language=(language or "pt"), timestamps="word")
    finally:
        if created_model:
            model_context.close()

    words = []
    output_ids: dict[int, str] = {}
    for source_index, word in enumerate(result.words):
        start = max(0.0, float(word.t0_ms) / 1000.0)
        end = min(duration, float(word.t1_ms) / 1000.0)
        text = str(word.text).strip()
        if end - start < 0.01 or not text:
            continue
        word_id = f"p{word.seg_index}_{source_index}"
        output_ids[source_index] = word_id
        words.append({"id": word_id, "text": text,
                      "start": round(start, 4), "end": round(end, 4),
                      "probability": 0.0})
    segments = []
    for segment in result.segments:
        start = max(0.0, float(segment.t0_ms) / 1000.0)
        end = min(duration, float(segment.t1_ms) / 1000.0)
        if end <= start:
            continue
        first = max(0, int(segment.first_word))
        last = min(len(result.words), first + max(0, int(segment.n_words)))
        segments.append({"start": round(start, 3), "end": round(end, 3),
                         "text": str(segment.text).strip(),
                         "word_ids": [output_ids[i] for i in range(first, last)
                                      if i in output_ids]})
    return {"words": words, "segments": segments,
            "language": str(result.language or language or "pt"),
            "model": "parakeet-ultra-Q8_0", "duration": duration,
            "timestamp_kind": str(result.timestamp_kind),
            "runtime": binding.native_version(), "backend": backend}
