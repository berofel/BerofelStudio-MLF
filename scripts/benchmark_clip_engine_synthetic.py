"""Synthetic scaling benchmark for the deterministic Clip Engine.

This measures transcript segmentation/ranking only. It does not decode media,
call Parakeet, measure editorial quality, or represent a real recording.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import threading
import time
from pathlib import Path

import psutil

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from berofel.core.project import Clip
from berofel.services.clipper import ClipperOptions, analyze_clips


_SENTENCES = (
    "Como essa ferramenta encontra os melhores momentos da gravação.",
    "A resposta depende do contexto, da fala e dos limites naturais.",
    "O editor reutiliza a transcrição e não executa outro reconhecimento.",
    "Uma pausa pode preparar uma explicação ou uma revelação importante.",
    "No final, a pessoa revisa cada clipe antes de adicionar à timeline.",
    "Também existem perguntas, respostas e mudanças de assunto na conversa.",
    "O resultado é uma classificação editorial explicável, não viralidade.",
)


def _transcript(source: Path, duration_seconds: int) -> list[dict]:
    result: list[dict] = []
    cursor = 0.0
    sentence_index = 0
    while cursor < duration_seconds:
        sentence = _SENTENCES[sentence_index % len(_SENTENCES)]
        sentence_index += 1
        for token in sentence.split():
            if cursor >= duration_seconds:
                break
            result.append({
                "id": f"synthetic-{len(result)}",
                "source": str(source.resolve()),
                "source_start": cursor,
                "source_end": min(cursor + .28, duration_seconds),
                "text": token,
                "probability": None,
            })
            cursor += .4
        cursor += .35
    return result


def _run_one(length_minutes: int, mode: str, repeat: int,
             cache_root: Path) -> dict:
    duration = length_minutes * 60
    source = cache_root / "synthetic-transcript-only.media"
    source.touch(exist_ok=True)
    clip = Clip(str(source), 0.0, float(duration), kind="image",
                title=f"fixture sintético {length_minutes} min")
    words = _transcript(source, duration)
    process = psutil.Process()
    rss_before = process.memory_info().rss
    peak_rss = [rss_before]
    stop = threading.Event()

    def sample_memory() -> None:
        while not stop.wait(.01):
            try:
                peak_rss[0] = max(peak_rss[0], process.memory_info().rss)
            except psutil.Error:
                return

    sampler = threading.Thread(target=sample_memory, daemon=True)
    sampler.start()
    started_wall = time.perf_counter()
    started_cpu = time.process_time()
    result = analyze_clips(
        [clip], words,
        ClipperOptions(15.0, 30.0, 10, 6.0, "Geral", mode),
        cache_dir=cache_root / f"{length_minutes}-{mode}-{repeat}",
    )
    wall = time.perf_counter() - started_wall
    cpu = time.process_time() - started_cpu
    try:
        peak_rss[0] = max(peak_rss[0], process.memory_info().rss)
    finally:
        stop.set()
        sampler.join(timeout=1.0)
    return {
        "duration_minutes": length_minutes,
        "mode": mode,
        "repeat": repeat,
        "input_words": len(words),
        "candidate_count": result["stats"]["candidate_count"],
        "wall_seconds": round(wall, 4),
        "process_cpu_seconds": round(cpu, 4),
        "process_rss_delta_mib_sampled": round(
            max(0, peak_rss[0] - rss_before) / (1024 * 1024), 3),
        "parakeet_calls": 0,
        "audio_decode_seconds": result["stats"]["decoded_seconds"],
        "fixture": "repeated deterministic PT-BR transcript; no real audio/video",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lengths", type=int, nargs="+",
                        default=[5, 20, 60, 80, 120])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", type=Path,
                        help="Optional JSON output path (UTF-8). Defaults to stdout.")
    args = parser.parse_args()
    if args.repeats < 1 or any(length < 1 for length in args.lengths):
        parser.error("lengths e repeats precisam ser positivos")

    rows = []
    with tempfile.TemporaryDirectory(prefix="bfs-clip-synthetic-bench-") as tmp:
        root = Path(tmp)
        for length in args.lengths:
            for mode in ("Rápido", "Equilibrado", "Avançado"):
                for repeat in range(1, args.repeats + 1):
                    rows.append(_run_one(length, mode, repeat, root))

    summary = []
    for length in args.lengths:
        for mode in ("Rápido", "Equilibrado", "Avançado"):
            selected = [row for row in rows
                        if row["duration_minutes"] == length and row["mode"] == mode]
            times = [row["wall_seconds"] for row in selected]
            summary.append({
                "duration_minutes": length,
                "mode": mode,
                "repeats": len(times),
                "median_wall_seconds": round(statistics.median(times), 4),
                "max_wall_seconds": round(max(times), 4),
                "sampled_peak_rss_delta_mib_max": max(
                    row["process_rss_delta_mib_sampled"] for row in selected),
            })
    payload = json.dumps({
        "benchmark": "synthetic transcript-only; not end-to-end or quality evidence",
        "raw": rows,
        "summary": summary,
    }, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
