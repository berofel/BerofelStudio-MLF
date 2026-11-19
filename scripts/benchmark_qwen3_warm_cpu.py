"""Benchmark real short/long Portuguese Qwen3-TTS requests on this PC.

Reads the authorized sample already configured in the editor; prints no path,
transcript or generated audio. Forces empty temporary WAV/prompt caches so the
output includes cold model load, first reference conditioning and warm reuse.
"""
from __future__ import annotations

import os
os.environ.update({'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1',
                   'HF_HUB_DISABLE_TELEMETRY':'1'})

import json
import argparse
from pathlib import Path
import sys
import tempfile
import threading
import time

import numpy as np
import psutil
from scipy.io import wavfile
from PySide6.QtCore import QSettings

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from berofel.services.narration_service import NarrationRequest
from berofel.services.qwen3_tts_local import generate_local_clone,stop_local_worker

SHORT_TEXT='Olá! Este é um teste curto de aquecimento do Qwen3-TTS.'
LONG_TEXT=('Hoje estamos medindo a narração local do Berofel Studio em português. '
    'O editor carrega o modelo uma vez, prepara a referência autorizada e reutiliza '
    'o perfil de voz nas frases seguintes. Este trecho também verifica a geração '
    'de um texto mais comprido, com pausas naturais entre as ideias. '
    'A linha do tempo recebe o áudio em um bloco independente, mantendo o projeto '
    'editável e sem alterar a gravação original. O objetivo é avaliar o tempo real '
    'no processador deste computador, a memória usada e a consistência do áudio. '
    'Depois da geração, os mesmos arquivos podem ser reproduzidos, ajustados e '
    'exportados pelo editor sem chamar novamente o modelo para cada controle DSP. '
    'Este teste funciona sem conexão externa quando o modelo já está instalado.')


def peak_rss(stop: threading.Event,peak: list[int]):
    root=psutil.Process()
    while not stop.is_set():
        total=0
        try:
            for proc in [root,*root.children(recursive=True)]:
                try:total+=proc.memory_info().rss
                except (psutil.NoSuchProcess,psutil.AccessDenied):pass
            peak[0]=max(peak[0],total)
        except (psutil.NoSuchProcess,psutil.AccessDenied):pass
        stop.wait(.2)


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--threads',type=int,default=int(os.getenv('BEROFEL_QWEN3_CPU_THREADS','8')))
    parser.add_argument('--short-only',action='store_true',help='Mede somente o pedido curto, útil para comparar threads.')
    parser.add_argument('--compare-lifecycle',action='store_true',
        help='Compara frase idêntica com worker frio, aquecido e recarregado; força WAVs sem cache.')
    args=parser.parse_args()
    if not 1<=args.threads<=32:
        raise ValueError('--threads deve ficar entre 1 e 32.')
    os.environ['BEROFEL_QWEN3_CPU_THREADS']=str(args.threads)
    settings=QSettings(QSettings.Format.IniFormat,QSettings.Scope.UserScope,
                       'Berofel','BerofelStudio')
    reference=Path(str(settings.value('narration/sample_path','') or '')).expanduser()
    reference_text=str(settings.value('narration/reference_text','') or '').strip()
    if not reference.is_file() or not reference_text:
        raise RuntimeError('Configure uma gravação autorizada e sua transcrição exata no painel Narração.')
    old={key:os.environ.get(key) for key in
         ('BEROFEL_AI_CACHE','BEROFEL_QWEN3_PROMPT_CACHE')}
    try:
        with tempfile.TemporaryDirectory(prefix='bfs_qwen_benchmark_') as folder:
            root=Path(folder)
            os.environ['BEROFEL_QWEN3_PROMPT_CACHE']=str(root/'voice-prompts')
            project=root/'benchmark.bfs'
            stop=threading.Event();peak=[0]
            watcher=threading.Thread(target=peak_rss,args=(stop,peak),daemon=True)
            watcher.start();records=[]
            if args.compare_lifecycle:
                cases=(('modelo_frio_perfil_novo',SHORT_TEXT,True),
                       ('modelo_aquecido_perfil_reutilizado',SHORT_TEXT,False),
                       ('modelo_recarregado_perfil_persistido',SHORT_TEXT,True))
            else:
                lengths=(('curta',SHORT_TEXT),) if args.short_only else (
                    ('curta',SHORT_TEXT),('longa',LONG_TEXT))
                cases=tuple((name,text,False) for name,text in lengths)
            for name,text,restart in cases:
                if restart:stop_local_worker()
                # Use identical text but force a fresh WAV for each lifecycle case.
                cache=(root/'cache'/name/'ai' if args.compare_lifecycle else
                       root/'cache'/'ai')
                os.environ['BEROFEL_AI_CACHE']=str(cache)
                request=NarrationRequest(text=text,voice=str(reference.resolve()),
                    language='portuguese',consent=True,project_path=str(project),
                    title=f'Qwen benchmark {name}',engine='qwen3-tts-local',
                    reference_text=reference_text)
                started=time.perf_counter();result=generate_local_clone(request)
                elapsed=time.perf_counter()-started
                rate,samples=wavfile.read(result['path'])
                duration=len(samples)/float(rate)
                record={'case':name,'audio_seconds':duration,'elapsed_seconds':elapsed,
                    'rtf':elapsed/duration if duration else None,
                    'cache_hit':bool(result['cache_hit']),
                    'prompt_cache_hit':result['prompt_cache_hit'],
                    'model_load_count':result['model_load_count'],
                    'worker_pid':result['worker_pid'],
                    'wav_signal':bool(np.any(samples))}
                if result['cache_hit'] or not record['wav_signal']:
                    raise RuntimeError('Benchmark não produziu inferência nova com sinal válido.')
                records.append(record)
            stop.set();watcher.join(timeout=2)
            expected_pid_count=2 if args.compare_lifecycle else 1
            if len({r['worker_pid'] for r in records})!=expected_pid_count:
                raise RuntimeError('O padrão de worker não corresponde ao modo de comparação escolhido.')
            if any(r['model_load_count']!=1 for r in records):
                raise RuntimeError('Métrica do worker indica carregamento repetido do modelo.')
            expected_prompt_hits=([False,True,True] if args.compare_lifecycle else
                ([False,True] if not args.short_only else None))
            if expected_prompt_hits and [r['prompt_cache_hit'] for r in records]!=expected_prompt_hits:
                raise RuntimeError('Prompt da voz não foi reutilizado após a preparação inicial.')
            if args.compare_lifecycle and any(r['cache_hit'] for r in records):
                raise RuntimeError('A comparação não deve reaproveitar WAVs gerados.')
            print('[PASSOU] Benchmark real Base 0.6B em CPU, modo offline.')
            for item in records:
                print(json.dumps(item,ensure_ascii=False,sort_keys=True))
            print(json.dumps({'cpu_threads':args.threads,
                'peak_aggregate_rss_gib':round(peak[0]/(1024**3),2),
                'same_worker_pid':expected_pid_count==1,
                'worker_processes':expected_pid_count,
                'model_loads_per_worker':1,
                'audio_cache_hits':False},ensure_ascii=False,sort_keys=True))
        stop_local_worker()
    finally:
        stop_local_worker()
        for key,value in old.items():
            if value is None:os.environ.pop(key,None)
            else:os.environ[key]=value
    return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as exc:
        print(f'[FALHOU] {type(exc).__name__}: {exc}',flush=True)
        raise SystemExit(1)
