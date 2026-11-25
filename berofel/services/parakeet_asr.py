"""CPU-only Parakeet TDT v3 INT8 adapter for onnx-asr.

Model and Silero ONNX files are installed once, outside the repository. The
adapter accepts the VAD spans already computed by the editor and returns all
times relative to the supplied WAV; it never downloads or silently falls back.
"""
from __future__ import annotations

from array import array
from pathlib import Path
import sys
import wave

MODEL_NAME = "nemo-parakeet-tdt-0.6b-v3"
SAMPLE_RATE = 16_000
MAX_SPEECH_SECONDS = 20.0


def read_pcm16_mono_16k(path: str | Path):
    """Read an FFmpeg-normalized PCM WAV without a second decoder or copy."""
    with wave.open(str(path), "rb") as source:
        channels, width, rate = source.getnchannels(), source.getsampwidth(), source.getframerate()
        if (channels, width, rate) != (1, 2, SAMPLE_RATE):
            raise ValueError("O Parakeet exige WAV PCM16 mono a 16000 Hz.")
        count = source.getnframes()
        raw = source.readframes(count)
    if len(raw) != count * 2:
        raise ValueError("WAV incompleto: amostras não correspondem ao cabeçalho.")
    samples = array("h")
    samples.frombytes(raw)
    if sys.byteorder != "little":
        samples.byteswap()
    return samples, count / rate


def make_session_options(threads: int):
    """Bound ONNX Runtime CPU work; sequential graph execution avoids oversubscription."""
    try:
        import onnxruntime as ort
    except ImportError as exc:
        raise RuntimeError("ONNX Runtime CPU não instalado. Execute INSTALAR_IA_OPCIONAL.bat.") from exc
    options = ort.SessionOptions()
    options.intra_op_num_threads = max(1, min(16, int(threads)))
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    return options


def load_model(*, model_path: str | Path | None = None, threads: int = 6):
    """Load the pinned local INT8 TDT model, with CPU provider only."""
    from .model_paths import parakeet_tdt_model_dir
    path = Path(model_path) if model_path else parakeet_tdt_model_dir()
    files=list(path.rglob("*.onnx")) if path.is_dir() else []
    if not files or not any("int8" in item.name.casefold() for item in files):
        raise FileNotFoundError(
            f"Parakeet TDT v3 INT8 não instalado em {path}. "
            "Execute scripts\\instalar_parakeet_tdt_v3.ps1."
        )
    try:
        import onnx_asr
    except ImportError as exc:
        raise RuntimeError("onnx-asr não instalado. Execute INSTALAR_IA_OPCIONAL.bat.") from exc
    try:
        return onnx_asr.load_model(
            MODEL_NAME, path, quantization="int8",
            sess_options=make_session_options(threads),
            providers=["CPUExecutionProvider"],
            preprocessor_config={"max_concurrent_workers": 1, "use_numpy_preprocessors": True},
        ).with_timestamps()
    except Exception as exc:
        raise RuntimeError(f"Falha ao carregar Parakeet TDT v3 ONNX INT8/CPU: {exc}") from exc


def load_vad(*, vad_path: str | Path | None = None, threads: int = 1):
    """Load the independent local Silero ONNX model on CPU."""
    from .model_paths import silero_vad_model_dir
    path = Path(vad_path) if vad_path else silero_vad_model_dir()
    if not path.is_dir() or not any(path.glob("*.onnx")):
        raise FileNotFoundError(
            f"Silero VAD ONNX não instalado em {path}. "
            "Execute scripts\\instalar_parakeet_tdt_v3.ps1."
        )
    try:
        import onnx_asr
        return onnx_asr.load_vad("silero", path=path,
                                 sess_options=make_session_options(threads),
                                 providers=["CPUExecutionProvider"])
    except Exception as exc:
        raise RuntimeError(f"Falha ao carregar Silero VAD ONNX local: {exc}") from exc


def detect_speech(samples, vad=None, *, threshold: float = .5,
                   min_speech_ms: int = 125, min_silence_ms: int = 350,
                   speech_pad_ms: int = 100, max_speech_seconds: float = MAX_SPEECH_SECONDS):
    """Return bounded, padded Silero regions as seconds, capped for TDT inference."""
    import numpy as np
    values = np.asarray(samples, dtype=np.float32)
    if values.size < SAMPLE_RATE // 10:
        return []
    vad = vad or load_vad()
    batch = values.reshape(1, -1)
    lengths = np.asarray([len(values)], dtype=np.int64)
    segmented = vad.segment_batch(
        batch, lengths, SAMPLE_RATE, threshold=float(threshold),
        min_speech_duration_ms=float(min_speech_ms),
        min_silence_duration_ms=float(min_silence_ms),
        speech_pad_ms=float(speech_pad_ms),
        max_speech_duration_s=float(max_speech_seconds),
    )
    regions = next(iter(segmented), ())
    return [{"start": round(max(0, a) / SAMPLE_RATE, 4),
             "end": round(min(len(values), b) / SAMPLE_RATE, 4)}
            for a, b in regions if b > a]


def _word_groups(tokens, timestamps, offset: float, duration: float):
    """Group SentencePiece tokens into words and map frame timestamps to seconds."""
    if not tokens or timestamps is None or len(tokens) != len(timestamps):
        return []
    groups = []
    for token, frame in zip(tokens, timestamps):
        token = str(token)
        try:
            at = max(0.0, min(duration, float(frame)))
        except (TypeError, ValueError):
            continue
        if not token.strip():
            continue
        begins_word = token[:1].isspace()
        if not groups or (begins_word and groups[-1]["text"].strip()):
            groups.append({"text": token, "start": at})
        else:
            groups[-1]["text"] += token
    words = []
    for index, group in enumerate(groups):
        text = " ".join(group["text"].split())
        if not text:
            continue
        start = group["start"]
        next_start = groups[index + 1]["start"] if index + 1 < len(groups) else duration
        end = max(start + .01, min(duration, next_start))
        words.append({"id": f"p{len(words)}", "text": text,
                      "start": round(offset + start, 4),
                      "end": round(offset + end, 4), "probability": None})
    return words


def transcribe_samples(samples, duration: float, *, speech_spans=None, model=None,
                       vad=None, threads: int = 6) -> dict:
    """Recognize VAD-sized windows using one model instance and exact source offsets."""
    import numpy as np
    samples = np.asarray(samples, dtype=np.float32)
    if not np.isfinite(samples).all():
        raise ValueError("Áudio contém valores inválidos para a inferência ONNX.")
    if model is None:
        model = load_model(threads=threads)
    if speech_spans is None:
        speech_spans = detect_speech(samples, vad=vad)
    words, segments = [], []
    for region_index, span in enumerate(speech_spans):
        start = max(0.0, min(duration, float(span.get("start", 0))))
        end = max(start, min(duration, float(span.get("end", 0))))
        if end - start < .12:
            continue
        # VAD is configured to cap spans at 20 s. Defend again against stale
        # caches/third-party spans; split at a waveform boundary only as fallback.
        pieces = []
        cursor = start
        while cursor < end - .001:
            piece_end = min(end, cursor + MAX_SPEECH_SECONDS)
            pieces.append((cursor, piece_end))
            cursor = piece_end
        for piece_index, (piece_start, piece_end) in enumerate(pieces):
            left = max(0, int(piece_start * SAMPLE_RATE))
            right = min(len(samples), int(piece_end * SAMPLE_RATE))
            if right - left < SAMPLE_RATE // 10:
                continue
            result = model.recognize(samples[left:right], sample_rate=SAMPLE_RATE)
            text = str(getattr(result, "text", "") or "").strip()
            if not text:
                continue
            region_words = _word_groups(getattr(result, "tokens", None),
                                        getattr(result, "timestamps", None),
                                        piece_start, (right - left) / SAMPLE_RATE)
            ids = []
            for word in region_words:
                word["id"] = f"p{region_index}_{piece_index}_{len(words)}"
                ids.append(word["id"])
                words.append(word)
            segments.append({"start": round(piece_start, 3), "end": round(piece_end, 3),
                             "text": text, "word_ids": ids})
    return {"words": words, "segments": segments, "language": "multilingual-auto",
            "model": "parakeet-tdt-0.6b-v3-int8", "duration": float(duration),
            "backend": "onnxruntime-cpu", "threads": int(threads),
            "timestamp_kind": "onnx-asr-token-frame"}


def transcribe_file(path: str | Path, *, model=None, vad=None, speech_spans=None,
                    threads: int = 6, vad_chunk_seconds: float = 30.0) -> dict:
    """Transcribe a WAV with bounded PCM memory and one resident model.

    VAD scans the complete file in fixed-size blocks when no spans are passed.
    Recognition then seeks to each padded speech span and reads at most one
    20-second inference window at once. Precomputed source-time spans remain
    supported, so the editor can share its cached Silero pass.
    """
    import numpy as np
    if vad_chunk_seconds <= 0:
        raise ValueError("vad_chunk_seconds precisa ser positivo")
    path = Path(path)
    try:
        source = wave.open(str(path), "rb")
    except (OSError, wave.Error) as exc:
        raise ValueError(f"Não foi possível abrir o WAV do Parakeet: {exc}") from exc
    with source:
        channels, width, rate = source.getnchannels(), source.getsampwidth(), source.getframerate()
        if (channels, width, rate) != (1, 2, SAMPLE_RATE):
            raise ValueError("O Parakeet exige WAV PCM16 mono a 16000 Hz.")
        total_frames = source.getnframes()
        duration = total_frames / rate
        vad_windows = 0
        if speech_spans is None:
            vad = vad or load_vad(threads=1)
            speech_spans = []
            chunk_frames = max(1, int(vad_chunk_seconds * rate))
            offset_frames = 0
            while offset_frames < total_frames:
                source.setpos(offset_frames)
                raw = source.readframes(min(chunk_frames, total_frames - offset_frames))
                usable = len(raw) - len(raw) % 2
                if not usable:
                    break
                pcm = np.frombuffer(raw[:usable], dtype="<i2")
                audio = pcm.astype(np.float32) / 32768.0
                block_duration = len(audio) / rate
                for span in detect_speech(audio, vad=vad, max_speech_seconds=MAX_SPEECH_SECONDS):
                    start = offset_frames / rate + float(span["start"])
                    end = min(duration, offset_frames / rate + float(span["end"]))
                    if end > start:
                        speech_spans.append({"start": start, "end": end})
                offset_frames += len(audio)
                vad_windows += 1
            # VAD padding can overlap at block boundaries. Merge overlap only;
            # do not bridge an actual pause or alter word-time source offsets.
            merged = []
            for span in sorted(speech_spans, key=lambda item: float(item.get("start", 0))):
                start = max(0.0, min(duration, float(span.get("start", 0))))
                end = max(start, min(duration, float(span.get("end", 0))))
                if end <= start:
                    continue
                if merged and start <= merged[-1]["end"]:
                    merged[-1]["end"] = max(merged[-1]["end"], end)
                else:
                    merged.append({"start": start, "end": end})
            speech_spans = merged
        else:
            # Normalize and validate user/cache spans before using wave.setpos.
            normalized_spans = []
            for span in speech_spans:
                try:
                    start = max(0.0, min(duration, float(span["start"])))
                    end = max(start, min(duration, float(span["end"])))
                except (KeyError, TypeError, ValueError):
                    continue
                if end > start:
                    normalized_spans.append({"start": start, "end": end})
            speech_spans = normalized_spans
        if model is None and speech_spans:
            model = load_model(threads=threads)
        words, segments = [], []
        for region_index, span in enumerate(speech_spans):
            start, end = span["start"], span["end"]
            cursor = start
            piece_index = 0
            while cursor < end - .001:
                piece_end = min(end, cursor + MAX_SPEECH_SECONDS)
                left = max(0, min(total_frames, int(cursor * rate)))
                right = max(left, min(total_frames, int(piece_end * rate)))
                if right - left < rate // 10:
                    cursor = piece_end
                    piece_index += 1
                    continue
                source.setpos(left)
                raw = source.readframes(right - left)
                usable = len(raw) - len(raw) % 2
                if usable != (right - left) * 2:
                    raise ValueError("WAV incompleto durante leitura de uma janela de fala.")
                pcm = np.frombuffer(raw, dtype="<i2")
                audio = pcm.astype(np.float32) / 32768.0
                result = model.recognize(audio, sample_rate=SAMPLE_RATE)
                actual_duration = len(audio) / rate
                region_words = _word_groups(getattr(result, "tokens", None),
                    getattr(result, "timestamps", None), left / rate, actual_duration)
                ids = []
                for word in region_words:
                    word["id"] = f"p{region_index}_{piece_index}_{len(words)}"
                    ids.append(word["id"])
                    words.append(word)
                text = str(getattr(result, "text", "") or "").strip()
                if text:
                    segments.append({"start": round(left / rate, 3),
                        "end": round(right / rate, 3), "text": text, "word_ids": ids})
                cursor = piece_end
                piece_index += 1
    return {"words": words, "segments": segments, "language": "multilingual-auto",
            "model": "parakeet-tdt-0.6b-v3-int8", "duration": float(duration),
            "backend": "onnxruntime-cpu", "threads": int(threads),
            "timestamp_kind": "onnx-asr-token-frame", "vad_windows": vad_windows,
            "memory_strategy": "streamed_pcm_windows",
            "model_loaded": model is not None}


def summarize_model_files(path: str | Path | None = None) -> dict:
    from .model_paths import parakeet_tdt_model_dir
    folder = Path(path) if path else parakeet_tdt_model_dir()
    files = sorted(p for p in folder.rglob("*.onnx")) if folder.is_dir() else []
    valid = bool(files) and any("int8" in p.name.casefold() for p in files)
    return {"installed": valid, "model": "Parakeet TDT 0.6B v3 INT8",
            "provider": "CPUExecutionProvider", "path": str(folder),
            "onnx_files": [p.name for p in files],
            "size_bytes": sum(p.stat().st_size for p in files)}
