"""Optional local speech-text inspection using only Parakeet TDT ONNX INT8.

This must be requested explicitly: ASR adds latency and memory load. Metrics
are diagnostic edit rates, not calibrated perceptual or voice-identity scores.
"""
from __future__ import annotations

from pathlib import Path
import json
import math
import os
import re
import subprocess
import tempfile
import threading
import unicodedata
import wave
from typing import Callable

from ..ai_cache import cache_root, digest, file_sha256
from .text_normalizer import normalize_pt_br

PARAKEET_CHECK_CACHE_VERSION = 1
_PARAKEET_CHECK_LOCK = threading.RLock()


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


def inspect_pcm16_wav(path: str | Path, *, block_seconds: float = 1.0) -> dict:
    """Measure normalized mono PCM16 in bounded blocks (no whole-file load)."""
    if block_seconds <= 0:
        raise ValueError("block_seconds precisa ser positivo")
    square_sum = 0.0
    peak = clipped = near_silence = count = 0
    with wave.open(str(path), "rb") as wav:
        channels, width, rate = wav.getnchannels(), wav.getsampwidth(), wav.getframerate()
        if channels != 1 or width != 2 or rate <= 0 or wav.getcomptype() != "NONE":
            raise ValueError("O WAV temporário precisa ser PCM16 mono válido.")
        frame_block = max(1, int(rate * block_seconds))
        while True:
            raw = wav.readframes(frame_block)
            if not raw:
                break
            usable = len(raw) - len(raw) % 2
            if not usable:
                continue
            try:
                import numpy as np
            except ImportError:
                from array import array
                values = array("h")
                values.frombytes(raw[:usable])
                if __import__("sys").byteorder != "little":
                    values.byteswap()
                for sample in values:
                    magnitude = abs(sample)
                    square_sum += sample * sample
                    peak = max(peak, magnitude)
                    clipped += magnitude >= 32760
                    near_silence += magnitude <= 16
                count += len(values)
            else:
                values = np.frombuffer(raw[:usable], dtype="<i2").astype(np.int32)
                magnitude = np.abs(values)
                square_sum += float(np.dot(values.astype(np.float64), values))
                peak = max(peak, int(magnitude.max(initial=0)))
                clipped += int(np.count_nonzero(magnitude >= 32760))
                near_silence += int(np.count_nonzero(magnitude <= 16))
                count += int(values.size)
        if not count:
            raise ValueError("O WAV temporário não contém amostras PCM.")
        duration = count / rate
    rms = math.sqrt(square_sum / count) / 32768.0
    peak_norm = peak / 32768.0
    rms_dbfs = 20 * math.log10(max(rms, 1e-12))
    peak_dbfs = 20 * math.log10(max(peak_norm, 1e-12))
    # Only exact digital silence skips ASR. A very quiet but nonzero voice can
    # still contain useful speech, so low-level audio is warned about, not
    # silently withheld from Parakeet.
    digitally_silent = peak == 0
    warnings = []
    if digitally_silent:
        warnings.append("O WAV contém silêncio digital (todas as amostras são zero).")
    elif peak <= 32:
        warnings.append("O pico do WAV está extremamente baixo; confira o nível e a inteligibilidade.")
    if clipped / count >= .001:
        warnings.append("Há amostras próximas do clipping; confira o áudio manualmente.")
    if rms_dbfs < -45 and not digitally_silent:
        warnings.append("O nível médio está baixo; confira o áudio manualmente.")
    return {
        "audio_duration_seconds": duration,
        "audio_rms_dbfs": rms_dbfs,
        "audio_peak_dbfs": peak_dbfs,
        "audio_clipped_fraction": clipped / count,
        "audio_near_silence_fraction": near_silence / count,
        "audio_sample_count": count,
        "audio_integrity_method": "bounded_pcm16_rms_peak_clip_v1",
        "audio_digitally_silent": digitally_silent,
        "audio_warnings": warnings,
    }


def _parakeet_cache_identity() -> dict:
    """Describe the installed ASR/runtime without loading either model."""
    from .. import parakeet_asr
    try:
        from importlib.metadata import version
        runtime_version = version("onnx-asr")
    except Exception:
        runtime_version = "unknown"
    model_files = []
    try:
        from ..model_paths import parakeet_tdt_model_dir
        model_root = Path(parakeet_tdt_model_dir())
        for model in sorted(model_root.rglob("*.onnx"), key=lambda item: item.name.casefold()):
            try:
                stat = model.stat()
                model_files.append({"name": model.name, "size": stat.st_size,
                                    "mtime_ns": stat.st_mtime_ns})
            except OSError:
                continue
    except (OSError, RuntimeError, ValueError):
        # A missing/unreadable model changes the key to an empty inventory;
        # it can never turn a previous cache entry into a hit accidentally.
        model_files = []
    return {
        "cache_version": PARAKEET_CHECK_CACHE_VERSION,
        "adapter_model": parakeet_asr.MODEL_NAME,
        "sample_rate": parakeet_asr.SAMPLE_RATE,
        "adapter_max_speech_seconds": parakeet_asr.MAX_SPEECH_SECONDS,
        "onnx_asr_version": runtime_version,
        "provider": "CPUExecutionProvider",
        "model_files": model_files,
        "normalization": "ffmpeg-mono-16k-pcm16-v1",
        "integrity_method": "bounded_pcm16_rms_peak_clip_v1",
    }


def _parakeet_cache_path(source: Path,
                         directory: str | Path | None) -> tuple[Path, str]:
    identity = {"source_sha256": file_sha256(source),
                # CPU thread count changes throughput, not the ASR contract;
                # reuse transcript results across thread-count adjustments.
                "pipeline": _parakeet_cache_identity()}
    key = digest(identity)
    root = (Path(directory).expanduser().resolve() if directory is not None else
            cache_root() / "voice_quality" / "parakeet")
    return root / key[:2] / f"{key}.json", key


def _read_parakeet_cache(path: Path, key: str) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        result = payload.get("result") if isinstance(payload, dict) else None
        if (payload.get("schema") != PARAKEET_CHECK_CACHE_VERSION or
                payload.get("key") != key or not isinstance(result, dict) or
                not isinstance(result.get("recognized_text"), str) or
                not isinstance(result.get("words"), list) or
                not isinstance(result.get("audio_metrics"), dict) or
                not isinstance(result.get("backend"), str)):
            return None
        metrics = result["audio_metrics"]
        for field in ("audio_duration_seconds", "audio_rms_dbfs", "audio_peak_dbfs",
                      "audio_clipped_fraction", "audio_near_silence_fraction",
                      "audio_sample_count"):
            value = metrics.get(field)
            if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                return None
        if (metrics["audio_duration_seconds"] <= 0 or
                metrics["audio_sample_count"] <= 0 or
                not isinstance(metrics.get("audio_digitally_silent"), bool) or
                not isinstance(metrics.get("audio_warnings"), list)):
            return None
        # Do not trust a partially written or manually edited cache payload.
        for word in result["words"]:
            if not isinstance(word, dict):
                return None
            for field in ("start", "end"):
                value = word.get(field)
                if value is not None and (not isinstance(value, (int, float)) or
                                          not math.isfinite(float(value))):
                    return None
        return result
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def _write_parakeet_cache(path: Path, key: str, result: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump({"schema": PARAKEET_CHECK_CACHE_VERSION, "key": key,
                       "result": result}, stream, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def inspect_generated_wav_with_parakeet(
    audio_path: str | Path, expected_spoken_text: str, *,
    transcriber: Callable | None = None, control=None, stage=None,
    ffmpeg: str | None = None, threads: int = 4, runner: Callable | None = None,
    cache_directory: str | Path | None = None,
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
    cache_file = cache_key = None
    cached = None
    # Injected transcribers are test/custom adapters and are deliberately not
    # mixed with the canonical Parakeet cache namespace.
    if transcriber is None:
        try:
            cache_file, cache_key = _parakeet_cache_path(source, cache_directory)
            with _PARAKEET_CHECK_LOCK:
                cached = _read_parakeet_cache(cache_file, cache_key)
        except (OSError, RuntimeError, ValueError, ImportError):
            # Cache/hash/model-inventory problems must not block a manual check.
            cache_file = cache_key = None
    if cached is not None:
        if stage:
            stage("Cache local · reutilizando a verificação Parakeet desta mídia")
        if control:
            control.checkpoint()
        audio_metrics = cached["audio_metrics"]
        result = {"words": cached["words"], "backend": cached["backend"]}
        recognized = cached["recognized_text"]
        verification_skipped_reason = cached.get("verification_skipped_reason")
        cache_hit = True
    else:
        if stage:
            stage("FFmpeg · preparando uma cópia temporária para o Parakeet")
        cache_hit = False
        audio_metrics = None
        result = None
        recognized = ""
        verification_skipped_reason = None
    if cached is None:
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
            audio_metrics = inspect_pcm16_wav(normalized)
            if audio_metrics["audio_digitally_silent"]:
                recognized = ""
                result = {"words": []}
                verification_skipped_reason = "Parakeet não foi iniciado porque o WAV está silencioso."
            else:
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
                verification_skipped_reason = None
            if cache_file is not None and cache_key is not None:
                cache_result = {"recognized_text": recognized,
                                "words": result.get("words") or [],
                                "audio_metrics": audio_metrics,
                                "verification_skipped_reason": verification_skipped_reason,
                                "backend": str(result.get("backend") or
                                    ("not_run" if verification_skipped_reason else "onnxruntime-cpu"))}
                try:
                    with _PARAKEET_CHECK_LOCK:
                        _write_parakeet_cache(cache_file, cache_key, cache_result)
                except (OSError, TypeError, ValueError):
                    # A read-only cache must not prevent inspection of a WAV.
                    pass
    audio_duration = audio_metrics["audio_duration_seconds"]
    temporal = calculate_temporal_coverage(result.get("words"), audio_duration)
    rates = calculate_text_error_rates(expected_spoken_text, recognized)
    return {
        **rates,
        **temporal,
        **audio_metrics,
        "recognized_text": recognized,
        "verification_skipped_reason": verification_skipped_reason,
        "asr_model": "Parakeet TDT v3 ONNX INT8",
        "provider": (None if verification_skipped_reason else "CPUExecutionProvider"),
        "backend": str(result.get("backend") or
                       ("not_run" if verification_skipped_reason else "onnxruntime-cpu")),
        "cache_hit": cache_hit,
        "review_required": True,
        "metric_note": "Heuristic text edit rates; not a perceptual MOS or identity score.",
    }
