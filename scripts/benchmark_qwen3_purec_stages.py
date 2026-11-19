"""Measure Pure C Qwen3 Base CLI stages on authorized local voice profiles.

Each CLI call starts a fresh process, so reports separate model load time from
internal generation stages. WAVs, process logs, and JSON stay outside the repo.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import statistics
import subprocess
import sys
import threading
import time
import wave

import numpy as np
import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from berofel.services import qwen3_purec_tts as purec
from berofel.services.narration_service import _process_flags
from berofel.services.voice_profiles import VoiceProfileManager

TEXTS = {
    "short": "O Berofel Studio mede a velocidade da narração local em português.",
    "medium": (
        "Estamos medindo os estágios internos da geração local de uma narração "
        "em português brasileiro. O mesmo perfil autorizado, texto e seed serão "
        "comparados entre as precisões. O áudio é verificado e salvo para que "
        "também seja possível avaliar a naturalidade e a inteligibilidade."
    ),
    "long": (
        "Esta medição usa uma narração mais extensa em português brasileiro para "
        "observar os custos de prefill, geração autoregressiva e decodificação "
        "acústica. O perfil vocal autorizado é preparado antes do início das "
        "medições e reutilizado em todos os pedidos. Cada execução usa um texto "
        "novo em relação ao cache de áudio e o mesmo seed entre os modos, para "
        "manter uma comparação controlada. Também registramos inicialização, "
        "tempo total, fator de tempo real, RAM e CPU. O WAV resultante fica fora "
        "do repositório para uma comparação auditiva local."
    ),
}


def parse_timings(output: str) -> dict[str, float | None]:
    """Extract measurements emitted by the installed Pure C CLI."""
    patterns = {
        "model_load_seconds": r"Model loaded in\s+([\d.]+)\s*ms",
        "prefill_seconds": r"Prefill:\s*([\d.]+)\s*ms",
        "talker_seconds": r"Talker step:\s*([\d.]+)\s*ms",
        "talker_ms_per_frame": r"Talker step:\s*[\d.]+\s*ms\s*\(([\d.]+)\s*ms/f\)",
        "code_predictor_seconds": r"Code Predictor:\s*([\d.]+)\s*ms",
        "code_predictor_ms_per_frame": r"Code Predictor:\s*[\d.]+\s*ms\s*\(([\d.]+)\s*ms/f\)",
        "embed_seconds": r"Embed:\s*([\d.]+)\s*ms",
        "codec_head_seconds": r"Codec head\+sampling:\s*([\d.]+)\s*ms",
        "decoder_seconds": r"Speech decoder:\s*([\d.]+)\s*ms total",
        "decoder_drain_seconds": r"Speech decoder:\s*[\d.]+\s*ms total\s*\(([\d.]+)\s*ms drain",
        "generated_audio_seconds": r"Audio:\s*([\d.]+)s generated",
        "generation_seconds": r"Audio:\s*[\d.]+s generated in\s*([\d.]+)s",
        "rtf": r"Audio:\s*[\d.]+s generated in\s*[\d.]+s\s*\(RTF\s*([\d.]+)\)",
        "first_audio_seconds": r"TTFA:\s*([\d.]+)\s*ms",
    }
    parsed: dict[str, float | None] = {}
    millisecond_fields = {
        "model_load_seconds", "prefill_seconds", "talker_seconds",
        "code_predictor_seconds", "embed_seconds", "codec_head_seconds",
        "decoder_seconds", "decoder_drain_seconds", "first_audio_seconds",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, output, re.I)
        if match:
            value = float(match.group(1))
            parsed[key] = value / 1000 if key in millisecond_fields else value
        else:
            parsed[key] = None
    return parsed


def _authorized_profile(profile_id: str):
    profiles = VoiceProfileManager().list_profiles()
    return next((profile for profile in profiles
                 if (not profile_id or profile.get("id") == profile_id)
                 and profile.get("authorized") and profile.get("reference_text")
                 and Path(profile.get("sample_path", "")).is_file()), None)


def _run(command: list[str], cwd: Path, env: dict[str, str], timeout: int) -> tuple[str, float, dict]:
    started = time.perf_counter()
    child = subprocess.Popen(command, cwd=str(cwd), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding="utf-8", errors="replace", creationflags=_process_flags())
    stats = {"peak_rss_bytes": 0, "peak_cpu_machine_percent": 0.0}
    done = threading.Event()

    def sample() -> None:
        try:
            proc = psutil.Process(child.pid)
            proc.cpu_percent(None)
        except psutil.Error:
            return
        while not done.wait(.1):
            try:
                process_tree = [proc, *proc.children(recursive=True)]
                rss = sum(item.memory_info().rss for item in process_tree)
                cpu = sum(item.cpu_percent(None) for item in process_tree)
                stats["peak_rss_bytes"] = max(stats["peak_rss_bytes"], rss)
                stats["peak_cpu_machine_percent"] = max(stats["peak_cpu_machine_percent"],
                    cpu / max(1, psutil.cpu_count() or 1))
            except psutil.Error:
                continue

    monitor = threading.Thread(target=sample, name="qwen-purec-stage-monitor", daemon=True)
    monitor.start()
    try:
        output, _ = child.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        child.kill()
        child.communicate()
        raise TimeoutError(f"Pure C CLI excedeu {timeout} segundos.")
    finally:
        done.set()
        monitor.join(timeout=2)
    if child.returncode:
        raise RuntimeError(f"Pure C CLI terminou com código {child.returncode}: {output[-1600:]}")
    return output, time.perf_counter() - started, stats


def _inspect_wav(path: Path) -> dict:
    with wave.open(str(path), "rb") as wav:
        rate, channels, width, frames = (wav.getframerate(), wav.getnchannels(),
            wav.getsampwidth(), wav.getnframes())
        samples = np.frombuffer(wav.readframes(frames), dtype="<i2")
    if rate != 24000 or channels != 1 or width != 2 or not samples.size:
        raise RuntimeError("Pure C não produziu WAV mono 24 kHz PCM16 válido.")
    rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
    if rms < 100:
        raise RuntimeError("Pure C produziu WAV silencioso ou abaixo do limiar RMS.")
    return {"duration_seconds": frames / rate, "sample_rate": rate,
        "channels": channels, "pcm_bits": 16, "rms_pcm16": round(rms, 2),
        "clipped_samples": int(np.count_nonzero(np.abs(samples.astype(np.int32)) >= 32767))}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-own-or-authorized-voice", action="store_true")
    parser.add_argument("--voice-profile-id", default="")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--lengths", nargs="+", choices=tuple(TEXTS), default=("short", "medium"))
    parser.add_argument("--threads", type=int, choices=(2, 4, 6, 8), default=6)
    parser.add_argument("--pool-spin", type=int, choices=(0, 1024, 4096, 8192, 16384, 65536),
                        default=None,
                        help="Override QWEN_POOL_SPIN; omitted uses the engine's x86 default.")
    parser.add_argument("--repeats", type=int, choices=(1, 2, 3, 4, 5), default=3)
    parser.add_argument("--modes", nargs="+", choices=("mixed", "int8"), default=("mixed", "int8"))
    args = parser.parse_args()
    if not args.confirm_own_or_authorized_voice:
        parser.error("Confirme autorização da voz com --confirm-own-or-authorized-voice.")
    output = args.output_dir.expanduser().resolve()
    if output == ROOT or ROOT in output.parents:
        parser.error("A saída precisa ficar fora do repositório.")
    if output.exists() and any(output.iterdir()):
        parser.error("Escolha uma pasta de saída nova e vazia.")
    output.mkdir(parents=True, exist_ok=True)
    profile = _authorized_profile(args.voice_profile_id)
    if profile is None:
        raise RuntimeError("Nenhum perfil vocal autorizado com referência local foi encontrado.")
    if not purec.is_ready():
        raise RuntimeError("O executável e os pesos locais Pure C/Qwen3 Base não estão prontos.")

    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    purec_root = purec.runtime_root()
    exe, model, runtime_paths = purec._layout()
    prepared = purec.prepare_voice_profile(profile["sample_path"],
        profile.get("reference_text", ""), consent=True, engine=purec.ENGINE_ID,
        thread_count=args.threads)
    purec.stop_purec_worker()
    environment = purec._environment(exe, runtime_paths, args.threads)
    environment["HF_HUB_OFFLINE"] = "1"
    environment["TRANSFORMERS_OFFLINE"] = "1"
    environment["OPENBLAS_NUM_THREADS"] = "1"
    if args.pool_spin is None:
        environment.pop("QWEN_POOL_SPIN", None)
    else:
        environment["QWEN_POOL_SPIN"] = str(args.pool_spin)
    records = []
    try:
        # Interleave precision order on successive repetitions to reduce ordering bias.
        for repetition in range(1, args.repeats + 1):
            modes = tuple(args.modes) if repetition % 2 else tuple(reversed(args.modes))
            for length in args.lengths:
                for mode in modes:
                    text = TEXTS[length]
                    seed = 4200 + repetition
                    wav_path = output / f"{mode}_{length}_r{repetition}.wav"
                    command = [str(exe), "-d", str(model), "-t", text,
                        "--load-voice", prepared["path"], "--xvector-only",
                        "--quant-mixed-cpu" if mode == "mixed" else "--int8",
                        "-j", str(args.threads), "--seed", str(seed), "-o", str(wav_path)]
                    raw, wall, resources = _run(command, exe.parent, environment, timeout=900)
                    (output / f"{mode}_{length}_r{repetition}.log").write_text(raw, encoding="utf-8")
                    timings = parse_timings(raw)
                    audio = _inspect_wav(wav_path)
                    if timings["generation_seconds"] is None:
                        raise RuntimeError("O CLI não imprimiu o tempo interno de geração; consulte o log local.")
                    record = {"mode": mode, "length": length, "characters": len(text),
                        "repetition": repetition, "seed": seed, "threads": args.threads,
                        "pool_spin": args.pool_spin if args.pool_spin is not None else "engine_default",
                        "wall_seconds_including_startup": round(wall, 3), **timings,
                        "precision_log_lines": [line.strip() for line in raw.splitlines()
                            if any(marker in line for marker in (
                                "QWEN_CP_PREC=", "Quantizing CP weights", "Code Predictor:",
                                "talker linear:", "CP linear:"))],
                        "peak_rss_gib": round(resources["peak_rss_bytes"] / (1024 ** 3), 3),
                        "peak_cpu_machine_percent": round(resources["peak_cpu_machine_percent"], 1),
                        "audio": audio, "wav": wav_path.name}
                    records.append(record)
                    print(json.dumps(record, ensure_ascii=False, sort_keys=True), flush=True)
    finally:
        purec.stop_purec_worker()

    summary = {}
    for mode in args.modes:
        for length in args.lengths:
            selected = [row for row in records if row["mode"] == mode and row["length"] == length]
            summary[f"{mode}:{length}"] = {key: round(statistics.median(
                float(row[key]) for row in selected if row.get(key) is not None), 4)
                if any(row.get(key) is not None for row in selected) else None
                for key in ("model_load_seconds", "prefill_seconds", "talker_seconds",
                    "code_predictor_seconds", "decoder_seconds", "decoder_drain_seconds",
                    "generation_seconds", "rtf", "first_audio_seconds",
                    "wall_seconds_including_startup", "peak_rss_gib", "peak_cpu_machine_percent")}
    report = {"model": "Qwen/Qwen3-TTS-12Hz-0.6B-Base", "backend": "Pure C Windows CLI",
        "quantization_flags_requested": {"mixed": "--quant-mixed-cpu", "int8": "--int8"},
        "offline": True,
        "profile_cache_hit": bool(prepared.get("cache_hit")),
        "profile_prepare_seconds": prepared.get("profile_prepare_seconds"),
        "model_load_server_seconds": prepared.get("model_load_seconds"),
        "threads": args.threads,
        "pool_spin": args.pool_spin if args.pool_spin is not None else "engine_default",
        "lengths": list(args.lengths), "repeats": args.repeats,
        "summary_medians": summary, "records": records}
    (output / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[PASSOU] {len(records)} WAVs medidos; evidências locais em {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
