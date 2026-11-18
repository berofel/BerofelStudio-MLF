"""Valida Qwen/llama.cpp local com entrada sintética longa, sem rede ou mídia privada."""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from berofel.services.ai_pipeline import (StageRunner, default_llama_cli,
                                          default_qwen_model, qwen_stage_timeout)
from berofel.services.performance import current_profile, qwen_limits, qwen_threads


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--words',type=int,default=800,
                        help='Quantidade de palavras sintéticas (padrão: 800)')
    parser.add_argument('--threads',type=int,default=0,
                        help='Threads do motor local (0 usa o perfil automático)')
    args=parser.parse_args(argv)
    if args.words<1:
        parser.error('--words precisa ser maior que zero')
    if args.threads<0 or args.threads>64:
        parser.error('--threads deve ser 0 (automático) ou entre 1 e 64')
    cli, model = default_llama_cli(), default_qwen_model()
    if not cli.is_file() or not model.is_file():
        raise FileNotFoundError(
            f"Qwen local não encontrado. llama-cli={cli}; modelo={model}"
        )
    vocabulary=('Hoje','vamos','editar','um','vídeo','com','cortes','precisos','e','legendas',
                'sincronizadas','para','publicar','um','resultado','claro','em','diferentes','formatos')
    words = [
        {"id": f"synthetic_{index:04d}", "text": vocabulary[index % len(vocabulary)]}
        for index in range(args.words)
    ]
    profile=current_profile()
    context_size,prompt_max_chars=qwen_limits(profile)
    timeout=qwen_stage_timeout(words,prompt_max_chars)
    threads=args.threads or qwen_threads(profile)
    payload = {
        "words": words,
        "llama_cli": str(cli),
        "qwen_model": str(model),
        "threads": threads,
        "max_tokens": 320,
        "context_size": context_size,
        "prompt_max_chars": prompt_max_chars,
        "timeout": 300,
    }
    started=time.monotonic();progress_events=[]
    def capture_progress(event):
        elapsed=time.monotonic()-started
        progress_events.append({'at':elapsed,**event})
        status=str(event.get('status') or '').strip()
        batch=f"lote {event.get('active_batch',0)}/{event.get('total_batches',0)}"
        print(f"[Qwen {elapsed:7.1f}s] {batch} · {status}",file=sys.stderr,flush=True)
    with tempfile.TemporaryDirectory(prefix="bfs_qwen_check_") as folder:
        output = Path(folder) / "qwen_result.json"
        result = StageRunner()("qwen", payload, output, timeout=timeout,
                               on_progress=capture_progress)
    elapsed=time.monotonic()-started
    model_load=next((event['model_load_seconds'] for event in progress_events
                     if event.get('model_load_seconds') is not None),None)
    batch_seconds=[]
    for event in progress_events:
        status=event.get('status')
        durations=event.get('completed_batch_seconds')
        if isinstance(durations,list):batch_seconds=durations
    if result.get("engine") != "Qwen/llama.cpp":
        raise RuntimeError(f"Motor Qwen inesperado: {result.get('engine')!r}")
    if not isinstance(result.get("removals"), list):
        raise RuntimeError("Resposta Qwen sem lista de propostas válida.")
    print(json.dumps({
        "status": "PASSOU",
        "words": len(words),
        "engine": result["engine"],
        "transport": result.get("transport", "llama-cli"),
        "model": result.get("model"),
        "proposals": len(result["removals"]),
        "profile": profile.level,
        "threads": threads,
        "context_size": context_size,
        "prompt_max_chars": prompt_max_chars,
        "timeout_seconds": timeout,
        "elapsed_seconds": round(elapsed,2),
        "model_load_seconds": model_load,
        "completed_batch_seconds": batch_seconds,
        "completed_batches": len(batch_seconds),
        "prompt_temp_root": str(Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "BFS" / "tmp"),
        "network": "offline; nenhum upload",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
