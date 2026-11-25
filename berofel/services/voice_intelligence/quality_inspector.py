"""Optional local speech-text inspection using only Parakeet TDT ONNX INT8.

This must be requested explicitly: ASR adds latency and memory load. Metrics
are diagnostic edit rates, not calibrated perceptual or voice-identity scores.
"""
from __future__ import annotations

from pathlib import Path
import math
import re
import subprocess
import tempfile
import unicodedata
import wave
from typing import Callable

from .text_normalizer import normalize_pt_br


def _normalized_words(text: str) -> list[str]:
    folded = unicodedata.normalize("NFKD", str(text or "").casefold())
    folded = "".join(char for char in folded if not unicodedata.combining(char))
    return re.findall(r"[a-z0-9]+", folded)


def _edit_distance(left, right) -> int:
    """Levenshtein distance using O(min(n,m)) memory."""
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        current = [i]
        for j, b in enumerate(right, 1):
            current.append(min(current[-1] + 1, previous[j] + 1,
                               previous[j - 1] + (a != b)))
        previous = current
    return previous[-1]


def calculate_text_error_rates(expected: str, recognized: str) -> dict:
    """Return WER/CER-like normalized edit rates, unbounded above at 1.0."""
    # Compare numeric forms on the same spoken-text representation, while
    # leaving both displayed source strings untouched for the user.
    expected_comparable = normalize_pt_br(str(expected or "")).spoken
    recognized_comparable = normalize_pt_br(str(recognized or "")).spoken
    expected_words = _normalized_words(expected_comparable)
    recognized_words = _normalized_words(recognized_comparable)
    expected_chars = "".join(expected_words)
    recognized_chars = "".join(recognized_words)
    word_errors = _edit_distance(expected_words, recognized_words)
    char_errors = _edit_distance(expected_chars, recognized_chars)
    return {
        "word_error_rate": word_errors / max(1, len(expected_words)),
        "character_error_rate": char_errors / max(1, len(expected_chars)),
        "expected_word_count": len(expected_words),
        "recognized_word_count": len(recognized_words),
        "word_edit_count": word_errors,
        "character_edit_count": char_errors,
        "comparison_normalization": "pt-br-deterministic-v2",
    }


def calculate_temporal_coverage(words, audio_duration: float | None) -> dict:
    """Report where Parakeet's last word ends; never label it as truncation.

    Word timestamps can include VAD padding and ASR alignment error. A tail gap
    is therefore a listening cue, not proof that synthesis omitted speech.
    """
    valid_ends = []
    for word in words or ():
        try:
            end = float(word.get("end"))
        except (AttributeError, TypeError, ValueError):
            continue
        if end >= 0 and math.isfinite(end):
            valid_ends.append(end)
    if audio_duration is None or not audio_duration or float(audio_duration) <= 0:
        return {"audio_duration_seconds": None,
                "last_recognized_word_end_seconds": max(valid_ends) if valid_ends else None,
                "trailing_gap_seconds": None,
                "review_ending": False,
                "note": "WAV duration or word timestamps unavailable."}
    duration = float(audio_duration)
    last_end = min(duration, max(valid_ends)) if valid_ends else None
    gap = max(0.0, duration - last_end) if last_end is not None else None
    return {
        "audio_duration_seconds": duration,
        "last_recognized_word_end_seconds": last_end,
        "trailing_gap_seconds": gap,
        "review_ending": bool(gap is not None and gap >= 1.5),
        "note": ("Possible long tail pause or unrecognized ending; listen manually."
                 if gap is not None and gap >= 1.5 else
                 "Timing is diagnostic only; it does not prove truncation."),
    }


def inspect_generated_wav_with_parakeet(
    audio_path: str | Path, expected_spoken_text: str, *,
    transcriber: Callable | None = None, control=None, stage=None,
    ffmpeg: str | None = None, threads: int = 4, runner: Callable | None = None,
) -> dict:
    """Transcribe a generated WAV with local Parakeet; never calls another ASR.

    A short temporary 16 kHz mono copy is created for the Parakeet adapter.
    It is deleted on exit. The source WAV is never modified and the check does
    not start playback or regenerate the narration.
    """
    source = Path(audio_path).expanduser().resolve()
    if not source.is_file() or source.stat().st_size <= 44:
        raise ValueError("O WAV para inspeção não existe ou está incompleto.")
    if not str(expected_spoken_text or "").strip():
        raise ValueError("O texto esperado para a verificação está vazio.")
    if control:
        control.checkpoint()
    if stage:
        stage("FFmpeg · preparando uma cópia temporária para o Parakeet")
    if ffmpeg is None:
        from ..ffmpeg import ffmpeg_path
        ffmpeg = ffmpeg_path()
    with tempfile.TemporaryDirectory(prefix="bfs_parakeet_voice_check_") as folder:
        normalized = Path(folder) / "generated_16k.wav"
        command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin",
                   "-y", "-i", str(source), "-map", "0:a:0", "-vn", "-ac",
                   "1", "-ar", "16000", "-c:a", "pcm_s16le", str(normalized)]
        process_runner = runner or subprocess.run
        try:
            if control:
                done = control.run(command, timeout=180, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, text=True, encoding="utf-8",
                    errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            else:
                done = process_runner(command, timeout=180, capture_output=True,
                    text=True, encoding="utf-8", errors="replace",
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError("A preparação do WAV para o Parakeet excedeu 180 segundos.") from exc
        if done.returncode or not normalized.is_file() or normalized.stat().st_size <= 44:
            detail = (done.stderr or done.stdout or "").strip()[-500:]
            raise RuntimeError("Não foi possível preparar o WAV para o Parakeet." +
                               (f" Detalhe: {detail}" if detail else ""))
        if control:
            control.checkpoint()
        if stage:
            stage("Parakeet TDT v3 ONNX INT8 · verificando o texto sintetizado")
        if transcriber is None:
            from ..parakeet_asr import transcribe_file
            result = transcribe_file(normalized, threads=threads)
        else:
            result = transcriber(normalized)
        if control:
            control.checkpoint()
        segments = result.get("segments") or []
        recognized = str(result.get("text") or " ".join(
            str(segment.get("text") or "") for segment in segments)).strip()
        try:
            with wave.open(str(normalized), "rb") as wav:
                audio_duration = wav.getnframes() / float(wav.getframerate())
        except (OSError, wave.Error, ZeroDivisionError):
            audio_duration = None
        temporal = calculate_temporal_coverage(result.get("words"), audio_duration)
        rates = calculate_text_error_rates(expected_spoken_text, recognized)
        return {
            **rates,
            **temporal,
            "recognized_text": recognized,
            "asr_model": "Parakeet TDT v3 ONNX INT8",
            "provider": "CPUExecutionProvider",
            "backend": str(result.get("backend") or "onnxruntime-cpu"),
            "review_required": True,
            "metric_note": "Heuristic text edit rates; not a perceptual MOS or identity score.",
        }
