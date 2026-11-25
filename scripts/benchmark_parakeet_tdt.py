"""Reproducible CPU thread sweep for local Parakeet TDT v3 ONNX INT8.

Supply a folder of authorized 16 kHz mono PCM16 WAV speech recordings. It
measures model load, warm per-file inference, RTF, and resident memory for
2/4/6/8 threads sequentially; it writes only a JSON report next to the input.
No sample is uploaded and no benchmark audio is bundled with the editor.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import time

ROOT = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(ROOT))

from berofel.services.parakeet_asr import load_model, load_vad, read_pcm16_mono_16k, transcribe_file


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio_dir", type=Path)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--threads", nargs="+", type=int, default=[2, 4, 6, 8])
    args = parser.parse_args()
    if not 1 <= args.repeats <= 5:
        parser.error("--repeats precisa ficar entre 1 e 5")
    files = sorted(args.audio_dir.glob("*.wav"))
    if not files:
        parser.error("A pasta precisa conter arquivos .wav PCM16 mono 16 kHz")
    for path in files:
        _, duration = read_pcm16_mono_16k(path)
        if duration <= 0:
            parser.error(f"Arquivo sem áudio: {path.name}")
    report = {"engine": "Parakeet TDT v3 0.6B ONNX INT8 / CPUExecutionProvider",
              "audio_files": [p.name for p in files], "repeats": args.repeats,
              "thread_results": []}
    try:
        import psutil
        process = psutil.Process()
    except ImportError:
        process = None
    for threads in args.threads:
        if not 1 <= threads <= 16:
            parser.error("cada opção de --threads precisa ficar entre 1 e 16")
        started = time.perf_counter()
        model = load_model(threads=threads)
        load_seconds = time.perf_counter() - started
        vad = load_vad(threads=1)
        rss_after_load = process.memory_info().rss if process else None
        records = []
        durations = []
        for path in files:
            _, duration = read_pcm16_mono_16k(path)
            durations.append(duration)
            elapsed_values = []
            word_count = 0
            for _ in range(args.repeats):
                then = time.perf_counter()
                result = transcribe_file(path, model=model, vad=vad, threads=threads)
                elapsed_values.append(time.perf_counter() - then)
                word_count = len(result["words"])
                if not result["segments"] and duration > 0.25:
                    # A silent recording may yield none; keep this explicit in the report.
                    word_count = 0
            median = statistics.median(elapsed_values)
            records.append({"file": path.name, "audio_seconds": round(duration, 3),
                            "median_inference_seconds": round(median, 4),
                            "rtf": round(median / duration, 4), "word_count": word_count,
                            "runs_seconds": [round(x, 4) for x in elapsed_values]})
        rss_after = process.memory_info().rss if process else None
        report["thread_results"].append({"threads": threads,
            "model_load_seconds": round(load_seconds, 3),
            "rss_after_load_mib": round(rss_after_load / 2**20, 1) if rss_after_load else None,
            "rss_after_run_mib": round(rss_after / 2**20, 1) if rss_after else None,
            "audio_total_seconds": round(sum(durations), 3), "files": records,
            "median_rtf": round(statistics.median(row["rtf"] for row in records), 4)})
        del model, vad
        print(json.dumps(report["thread_results"][-1], ensure_ascii=False), flush=True)
    destination = args.audio_dir / "parakeet_tdt_v3_thread_benchmark.json"
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Relatório: {destination}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
