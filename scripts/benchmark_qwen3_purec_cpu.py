r"""Measure streaming latency, CPU and RSS for the local Pure C Qwen server.

Example (PowerShell):
  $env:PATH = "$env:LOCALAPPDATA\BFS\qwen3_tts\purec\bin;$env:PATH"
  python scripts/benchmark_qwen3_purec_cpu.py `
    --exe "$env:LOCALAPPDATA\BFS\qwen3_tts\purec\bin\qwen_tts.exe" `
    --model "$env:LOCALAPPDATA\BFS\qwen3_tts\model" `
    --voice "C:\path\to\authorized-xvector.bin" --threads 2 4 6 8

This utility never uploads inputs or writes audio files. It emits JSON metrics
to stdout and leaves model/profile files untouched.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import statistics
import subprocess
import threading
import time
import urllib.error
import urllib.request

import psutil


TEXT = (
    "Este é um teste de velocidade e clareza da voz clonada no Berofel Studio. "
    "A frase permanece igual entre as configurações para permitir uma comparação."
)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_ready(process: subprocess.Popen, port: int, timeout: float = 180) -> float:
    started = time.perf_counter()
    url = f"http://127.0.0.1:{port}/v1/health"
    deadline = started + timeout
    while time.perf_counter() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Qwen server exited during startup: {process.returncode}")
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200 and json.load(response).get("status") == "ok":
                    return time.perf_counter() - started
        except (OSError, ValueError, urllib.error.URLError):
            time.sleep(0.1)
    raise TimeoutError("Qwen server did not become ready within 180 s")


def generation(process: subprocess.Popen, port: int) -> dict:
    url = f"http://127.0.0.1:{port}/v1/tts/stream"
    request = urllib.request.Request(
        url,
        data=json.dumps({
            "text": TEXT, "language": "Portuguese", "seed": 42,
            "temperature": 0.5, "top_k": 50, "top_p": 1.0,
            "rep_penalty": 1.05,
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    tracked = psutil.Process(process.pid)
    tracked.cpu_percent(None)  # initialize non-blocking CPU sampler
    samples: list[float] = []
    rss: list[int] = []
    done = threading.Event()

    def sample() -> None:
        while not done.wait(0.1):
            try:
                samples.append(tracked.cpu_percent(None))
                rss.append(tracked.memory_info().rss)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                break

    monitor = threading.Thread(target=sample, daemon=True)
    monitor.start()
    started = time.perf_counter()
    first = None
    byte_count = 0
    try:
        with urllib.request.urlopen(request, timeout=900) as response:
            while chunk := response.read(4096):
                if first is None:
                    first = time.perf_counter() - started
                byte_count += len(chunk)
    finally:
        elapsed = time.perf_counter() - started
        done.set()
        monitor.join(timeout=2)
    if byte_count == 0 or byte_count % 2:
        raise RuntimeError(f"Invalid streamed PCM size: {byte_count}")
    duration = byte_count / 2 / 24000
    logical = psutil.cpu_count(logical=True) or 1
    cpu_avg = statistics.mean(samples) if samples else 0.0
    return {
        "wall_seconds": elapsed,
        "first_audio_seconds": first,
        "audio_seconds": duration,
        "rtf": elapsed / duration,
        "streamed_pcm_bytes": byte_count,
        "cpu_mean_one_core_percent": cpu_avg,
        "cpu_mean_machine_percent": cpu_avg / logical,
        "cpu_peak_one_core_percent": max(samples, default=0.0),
        "rss_peak_gib": max(rss, default=0) / (1024 ** 3),
        "samples": len(samples),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", required=True, type=Path)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--voice", required=True, type=Path,
                        help="Authorized local x-vector profile (.bin).")
    parser.add_argument("--threads", nargs="+", type=int, default=[2, 4, 6, 8])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", type=Path,
                        help="Optional JSON report path; keep outside Git if it contains local metadata.")
    args = parser.parse_args()
    for path in (args.exe, args.model / "config.json", args.voice):
        if not path.exists():
            parser.error(f"Required local input does not exist: {path}")
    if args.repeats < 1 or any(t < 1 for t in args.threads):
        parser.error("threads and repeats must be positive")

    logical = psutil.cpu_count(logical=True)
    report = {
        "model": "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
        "backend": "qwen3-tts-pure-c",
        "quantization": "mixed-cpu (Talker INT8, Code Predictor INT4)",
        "cpu_logical_processors": logical,
        "profile_reused": True,
        "same_text_and_seed": True,
        "results": [],
    }
    env = os.environ.copy()
    env["OMP_NUM_THREADS"] = "8"
    for threads in args.threads:
        port = free_port()
        command = [str(args.exe), "-d", str(args.model), "--load-voice", str(args.voice),
                   "--xvector-only", "--quant-mixed-cpu", "-j", str(threads),
                   "--max-request-seconds", "600", "--serve", str(port)]
        process = subprocess.Popen(command, cwd=str(args.exe.parent), env=env,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            startup = wait_ready(process, port)
            run = [generation(process, port) for _ in range(args.repeats)]
            item = {
                "threads": threads,
                "cold_server_load_seconds": startup,
                "peak_rss_server_gib": max(r["rss_peak_gib"] for r in run),
                "wall_median_seconds": statistics.median(r["wall_seconds"] for r in run),
                "rtf_median": statistics.median(r["rtf"] for r in run),
                "first_audio_median_seconds": statistics.median(r["first_audio_seconds"] for r in run),
                "cpu_mean_machine_percent_median": statistics.median(r["cpu_mean_machine_percent"] for r in run),
                "cpu_peak_one_core_percent_max": max(r["cpu_peak_one_core_percent"] for r in run),
                "runs": run,
            }
            report["results"].append(item)
            print(json.dumps({"progress": item}, ensure_ascii=False), flush=True)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=5)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
