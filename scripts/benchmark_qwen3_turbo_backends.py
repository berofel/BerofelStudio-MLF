r"""Controlled same-text comparison of locally installed Qwen3 Base CPU backends.

The only voice source is an already authorized local voice profile. Audio
outputs and isolated caches stay in the user-selected external output folder.
Example (PowerShell):
  python scripts/benchmark_qwen3_turbo_backends.py `
    --confirm-own-or-authorized-voice `
    --output-dir "$env:USERPROFILE\Desktop\BerofelStudio_QwenTurbo_AB"
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import statistics
import sys
import threading
import tempfile
import time
import wave

import numpy as np
import psutil


TEXT = (
    "No Berofel Studio, esta frase inédita compara os modos locais do Qwen3 "
    "Base em português brasileiro, mantendo o mesmo texto para medir tempo "
    "de geração e disponibilidade do primeiro áudio."
)
ENGINES = (
    ("qwen3-tts-native-q4", "native-q4-turbo"),
    ("qwen3-tts-purec-mixed", "purec-mixed-turbo"),
    ("qwen3-tts-purec-int8", "purec-int8-balanced"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-own-or-authorized-voice", action="store_true",
                        help="Confirma autorização para usar o perfil vocal local.")
    parser.add_argument("--output-dir", type=Path, required=True,
                        help="Pasta externa ao repositório para WAVs e JSON.")
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if not args.confirm_own_or_authorized_voice:
        parser.error("Confirme a autorização da voz local antes do benchmark.")
    if not 1 <= args.repeats <= 10:
        parser.error("--repeats precisa ficar entre 1 e 10.")
    return args


def inspect_wave(path: Path) -> dict:
    with wave.open(str(path), "rb") as wav:
        frames = wav.getnframes()
        rate = wav.getframerate()
        channels = wav.getnchannels()
        samples = np.frombuffer(wav.readframes(frames), dtype="<i2")
    if frames <= rate or not samples.size:
        raise RuntimeError(f"WAV curto ou vazio: {path.name}")
    rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
    if rms < 100:
        raise RuntimeError(f"WAV silencioso: {path.name}")
    return {"duration_seconds": frames / rate, "sample_rate": rate,
            "channels": channels, "rms_pcm16": round(rms, 2)}


def measured(action, server_name: str) -> tuple[dict, float, dict]:
    """Measure wall time and peak process-tree CPU/RSS for one backend call."""
    root = psutil.Process(os.getpid())
    root.cpu_percent(None)
    stop = threading.Event()
    cpu_samples: list[float] = []
    rss_samples: list[int] = []
    previous_cpu: dict[int, tuple[float, float]] = {}

    def sample() -> None:
        while not stop.wait(0.1):
            try:
                selected = [root]
                selected.extend(p for p in root.children(recursive=True)
                                if server_name in p.name().lower())
                now = time.perf_counter()
                cpu = 0.0
                rss = sum(p.memory_info().rss for p in selected)
                for process in selected:
                    times = process.cpu_times()
                    total_cpu = times.user + times.system
                    previous = previous_cpu.get(process.pid)
                    if previous:
                        elapsed = now - previous[1]
                        if elapsed > 0:
                            cpu += max(0.0, total_cpu - previous[0]) / elapsed * 100
                    previous_cpu[process.pid] = (total_cpu, now)
                # CPU-time deltas yield percent of one core; normalize by the
                # number of logical processors for total-machine percent.
                cpu_samples.append(cpu / max(1, psutil.cpu_count() or 1))
                rss_samples.append(rss)
            except (psutil.Error, OSError):
                continue

    thread = threading.Thread(target=sample, name="qwen-benchmark-monitor", daemon=True)
    thread.start()
    started = time.perf_counter()
    try:
        value = action()
    finally:
        wall = time.perf_counter() - started
        stop.set()
        thread.join(timeout=2)
    resources = {
        "peak_cpu_machine_percent": round(max(cpu_samples, default=0.0), 1),
        "peak_process_tree_rss_gib": round(max(rss_samples, default=0) / (1024 ** 3), 3),
        "cpu_samples": len(cpu_samples),
    }
    return value, wall, resources


def main() -> int:
    args = parse_args()
    output = args.output_dir.expanduser().resolve()
    repo = Path(__file__).resolve().parents[1]
    if output == repo or repo in output.parents:
        raise SystemExit("O diretório de saída deve ficar fora do repositório Git.")
    if output.exists() and any(output.iterdir()):
        raise SystemExit("O diretório de saída já contém arquivos; escolha uma pasta nova.")
    output.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(repo))

    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    installed = local / "BFS" / "qwen3_tts"
    native_home = installed / "native_turbo"
    purec_home = installed / "purec"
    if not (native_home / "bin/qwen3-tts-cli.exe").is_file():
        raise SystemExit("Backend CHE3MZ Q4 local não está instalado.")
    if not (purec_home / "bin/qwen_tts.exe").is_file():
        raise SystemExit("Backend Pure C local não está instalado.")

    with tempfile.TemporaryDirectory(prefix="bfs_qwen_turbo_ab_") as temporary:
        isolated = Path(temporary)
        # Keep embedding/profile caches isolated while pointing inference at
        # the already installed local model files. No network access is needed.
        os.environ["BEROFEL_AI_CACHE"] = str(isolated / "cache" / "ai")
        os.environ["BEROFEL_QWEN3_NATIVE_HOME"] = str(isolated / "native-home")
        os.environ["BEROFEL_QWEN3_NATIVE_EXE"] = str(native_home / "bin/qwen3-tts-cli.exe")
        os.environ["BEROFEL_QWEN3_NATIVE_MODEL"] = str(native_home / "models/qwen3-tts-0.6b-q4_0.gguf")
        os.environ["BEROFEL_QWEN3_NATIVE_TOKENIZER"] = str(native_home / "models/qwen3-tts-tokenizer-f16-f32.gguf")
        os.environ["BEROFEL_QWEN3_PUREC_EXE"] = str(purec_home / "bin/qwen_tts.exe")
        os.environ["BEROFEL_QWEN3_PUREC_MODEL"] = str(installed / "model")
        os.environ["BEROFEL_QWEN3_PUREC_RUNTIME_PATHS"] = str(purec_home / "bin")
        os.environ["BEROFEL_QWEN3_PUREC_PROFILE_CACHE"] = str(isolated / "purec-profiles")
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"

        from berofel.services.narration_service import NarrationRequest, generate_narration
        from berofel.services.voice_profiles import VoiceProfileManager
        from berofel.services.ai_cache import cache_root
        from berofel.services.qwen3_native_tts import stop_native_worker
        from berofel.services.qwen3_purec_tts import stop_purec_worker

        profiles = [item for item in VoiceProfileManager().list_profiles()
                    if item.get("authorized") and item.get("reference_text")
                    and Path(item.get("sample_path", "")).is_file()]
        if not profiles:
            raise SystemExit("Nenhum perfil local autorizado com transcrição foi encontrado.")
        voice = Path(profiles[0]["sample_path"]).resolve()
        reference_text = str(profiles[0]["reference_text"])
        project = isolated / "same_text.bfsproj"
        cache_dir = cache_root().parent / "qwen3_native_tts"
        warmup_results = {}
        records: dict[str, list[dict]] = {label: [] for _, label in ENGINES}

        def request(engine: str, title: str, text: str = TEXT):
            return NarrationRequest(text=text, voice=str(voice),
                language="portuguese", consent=True, title=title,
                engine=engine, reference_text=reference_text,
                project_path=str(project))

        try:
            # Warm each backend immediately before its measurement block.
            # Pure C has one server slot, so this avoids switching its
            # precision after warmup and accidentally measuring a reload.
            for engine, label in ENGINES:
                server_name = "qwen3-tts-cli" if engine == "qwen3-tts-native-q4" else "qwen_tts"
                warm_text = TEXT + " Preparação inicial do benchmark."
                warm, warm_wall, warm_resources = measured(
                    lambda: generate_narration(request(engine, f"warm-{label}", warm_text)),
                    server_name)
                warmup_results[label] = {key: warm.get(key) for key in (
                    "generation_seconds", "duration", "profile_prepare_seconds",
                    "model_load_seconds", "profile_cache_hit", "prompt_cache_hit")}
                warmup_results[label]["wall_seconds"] = round(warm_wall, 3)
                warmup_results[label].update(warm_resources)

                # Keep the backend/precision resident for the full block.
                for repetition in range(1, args.repeats + 1):
                    # The native adapter has a full-phrase cache. Clear only
                    # this isolated benchmark cache, never the user's cache.
                    shutil.rmtree(cache_dir, ignore_errors=True)
                    chunks = []
                    result, wall, resources = measured(
                        lambda: generate_narration(
                            request(engine, f"{label}-r{repetition}"),
                            audio_chunk=chunks.append), server_name)
                    wav_path = Path(result["path"])
                    audio = inspect_wave(wav_path)
                    if not chunks:
                        raise RuntimeError(f"O backend {label} não retornou chunks PCM.")
                    sample = output / f"{label}-rep{repetition}.wav"
                    shutil.copy2(wav_path, sample)
                    duration = float(result.get("duration") or audio["duration_seconds"])
                    records[label].append({
                        "repetition": repetition,
                        "engine": engine,
                        "wall_seconds": round(wall, 3),
                        "generation_seconds": round(float(result.get("generation_seconds", 0)), 3),
                        "duration_seconds": round(duration, 3),
                        "rtf_generation": round(float(result.get("generation_seconds", 0)) / duration, 3),
                        "first_audio_seconds": result.get("first_audio_chunk_seconds"),
                        "profile_prepare_seconds": result.get("profile_prepare_seconds"),
                        "model_load_seconds": result.get("model_load_seconds"),
                        "profile_cache_hit": result.get("profile_cache_hit", result.get("prompt_cache_hit")),
                        **resources,
                        "audio": audio,
                        "sample": sample.name,
                    })
            summary = {}
            for label, rows in records.items():
                summary[label] = {
                    "median_wall_seconds": round(statistics.median(r["wall_seconds"] for r in rows), 3),
                    "median_generation_seconds": round(statistics.median(r["generation_seconds"] for r in rows), 3),
                    "median_duration_seconds": round(statistics.median(r["duration_seconds"] for r in rows), 3),
                    "median_rtf_generation": round(statistics.median(r["rtf_generation"] for r in rows), 3),
                    "median_first_audio_seconds": round(statistics.median(
                        r["first_audio_seconds"] for r in rows if r["first_audio_seconds"] is not None), 3)
                        if any(r["first_audio_seconds"] is not None for r in rows) else None,
                    "median_peak_cpu_machine_percent": round(statistics.median(
                        r["peak_cpu_machine_percent"] for r in rows), 2),
                    "median_peak_process_tree_rss_gib": round(statistics.median(
                        r["peak_process_tree_rss_gib"] for r in rows), 3),
                    "repetitions": rows,
                }
            report = {"model": "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
                      "text": TEXT, "threads": {"native": 6, "purec": 6},
                      "offline": True, "warmup": warmup_results, "summary": summary}
            (output / "results.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({"output_dir": str(output), "summary": {
                label: {key: value for key, value in stats.items() if key != "repetitions"}
                for label, stats in summary.items()}, "warmup": warmup_results},
                ensure_ascii=False, indent=2))
        finally:
            stop_native_worker()
            stop_purec_worker()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
