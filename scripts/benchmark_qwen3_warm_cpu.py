"""Benchmark real short/medium/long Portuguese Qwen3-TTS requests on this PC.

Reads an explicitly authorized saved profile; prints no path, transcript or
generated audio. Forces empty temporary WAV/prompt caches so the
output includes cold model load, first reference conditioning and warm reuse.
Explicit profile mode separates model initialization and reference preparation.
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
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from berofel.services.narration_service import NarrationRequest
from berofel.services.qwen3_tts_local import generate_local_clone,stop_local_worker
from berofel.services.voice_profiles import VoiceProfileManager

SHORT_TEXT='Olá! Este é um teste curto de aquecimento do Qwen3-TTS.'
MEDIUM_TEXT=('Esta é a validação de uma narração de tamanho médio em português. '
    'O perfil vocal deve ser preparado uma vez e reutilizado nas frases seguintes. '
    'O Berofel Studio mantém o modelo carregado durante a sessão para evitar uma nova inicialização. '
    'Depois da geração, o áudio pode ser reproduzido, ajustado e inserido na timeline. '
    'Também verificamos que a voz permanece local e que o arquivo WAV contém sinal válido.')
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


def synthetic_reference(path: Path) -> Path:
    rate=24000;duration=3.2
    t=np.arange(round(rate*duration),dtype=np.float64)/rate
    fundamental=np.where(t<1.05,132.,np.where(t<2.1,165.,147.))
    phase=2*np.pi*np.cumsum(fundamental)/rate
    envelope=np.minimum(1.,np.minimum(t/.12,(duration-t)/.12))
    signal=envelope*(.22*np.sin(phase)+.11*np.sin(2*phase)+.055*np.sin(3*phase))
    wavfile.write(str(path),rate,np.clip(signal*32767,-32768,32767).astype('<i2'))
    return path


def peak_resources(stop: threading.Event,stats: dict):
    root=psutil.Process()
    tracked={root.pid:root}
    while not stop.is_set():
        total=0;cpu=0.0;current={}
        try:
            for proc in [root,*root.children(recursive=True)]:
                monitor=tracked.setdefault(proc.pid,proc)
                current[proc.pid]=monitor
                try:
                    total+=monitor.memory_info().rss
                    cpu+=max(0.0,monitor.cpu_percent(None))
                except (psutil.NoSuchProcess,psutil.AccessDenied):pass
            normalized=cpu/max(1,os.cpu_count() or 1)
            stats['peak_rss_bytes']=max(stats['peak_rss_bytes'],total)
            stats['peak_cpu_percent']=max(stats['peak_cpu_percent'],normalized)
            stats['cpu_samples'].append(normalized)
            tracked=current
        except (psutil.NoSuchProcess,psutil.AccessDenied):pass
        stop.wait(.2)


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--threads',type=int,default=int(os.getenv('BEROFEL_QWEN3_CPU_THREADS','8')))
    parser.add_argument('--short-only',action='store_true',help='Mede somente o pedido curto, útil para comparar threads.')
    parser.add_argument('--compare-lifecycle',action='store_true',
        help='Compara frase idêntica com worker frio, aquecido e recarregado; força WAVs sem cache.')
    parser.add_argument('--prepare-profile-first',action='store_true',
        help='Mede preparação explícita do perfil e depois gera textos curto, médio e longo com modelo/perfil aquecidos.')
    parser.add_argument('--voice-profile-id',default='',
        help='ID de um perfil salvo e explicitamente autorizado; vazio usa o primeiro perfil autorizado.')
    parser.add_argument('--synthetic-reference',action='store_true',
        help='mede latência/recursos com sinal sintético; não mede qualidade ou identidade vocal.')
    args=parser.parse_args()
    if args.compare_lifecycle and args.prepare_profile_first:
        parser.error('--compare-lifecycle e --prepare-profile-first são modos separados.')
    if not 1<=args.threads<=32:
        raise ValueError('--threads deve ficar entre 1 e 32.')
    os.environ['BEROFEL_QWEN3_CPU_THREADS']=str(args.threads)
    if args.synthetic_reference:
        if args.voice_profile_id:
            raise ValueError('--voice-profile-id não pode ser combinado com --synthetic-reference.')
        reference=None;reference_text=''
    else:
        profiles=VoiceProfileManager().list_profiles()
        profile=(next((item for item in profiles
                       if item['id']==args.voice_profile_id and item.get('authorized')),
                      None) if args.voice_profile_id else
                 next((item for item in profiles if item.get('authorized') and
                       item.get('reference_text')),None))
        if profile is None:
            raise RuntimeError('Salve/autorize um perfil Qwen no painel Narração antes do benchmark.')
        reference=Path(profile['sample_path']).expanduser()
        reference_text=str(profile.get('reference_text','')).strip()
        if not reference.is_file() or not reference_text:
            raise RuntimeError('O perfil autorizado não possui gravação e transcrição válidas.')
    old={key:os.environ.get(key) for key in
         ('BEROFEL_AI_CACHE','BEROFEL_QWEN3_PROMPT_CACHE')}
    try:
        with tempfile.TemporaryDirectory(prefix='bfs_qwen_benchmark_') as folder:
            root=Path(folder)
            if args.synthetic_reference:
                reference=synthetic_reference(root/'synthetic_reference.wav')
            os.environ['BEROFEL_QWEN3_PROMPT_CACHE']=str(root/'voice-prompts')
            project=root/'benchmark.bfs'
            stop=threading.Event();stats={'peak_rss_bytes':0,'peak_cpu_percent':0.0,'cpu_samples':[]}
            watcher=threading.Thread(target=peak_resources,args=(stop,stats),daemon=True)
            watcher.start();records=[]
            if args.prepare_profile_first:
                from berofel.services.qwen3_tts_local import prepare_local_voice_prompt
                prepared_at=time.perf_counter()
                prepared=prepare_local_voice_prompt(str(reference.resolve()),reference_text)
                prepare_elapsed=time.perf_counter()-prepared_at
                if prepared['prompt_cache_hit']:
                    raise RuntimeError('A preparação explícita deveria partir de um cache isolado vazio.')
                print(json.dumps({'phase':'preparacao_explicita_do_perfil',
                    'reference_type':'synthetic' if args.synthetic_reference else 'authorized_profile',
                    'elapsed_seconds':round(prepare_elapsed,3),
                    'model_load_seconds':prepared['model_load_seconds'],
                    'profile_prepare_seconds':prepared['profile_prepare_seconds'],
                    'prompt_cache_hit':prepared['prompt_cache_hit'],
                    'model_load_count':prepared['model_load_count'],
                    'worker_pid':prepared['worker_pid']},ensure_ascii=False,sort_keys=True),flush=True)
            if args.compare_lifecycle:
                cases=(('modelo_frio_perfil_novo',SHORT_TEXT,True),
                       ('modelo_aquecido_perfil_reutilizado',SHORT_TEXT,False),
                       ('modelo_recarregado_perfil_persistido',SHORT_TEXT,True))
            else:
                lengths=(('curta',SHORT_TEXT),) if args.short_only else (
                    ('curta',SHORT_TEXT),('media',MEDIUM_TEXT),('longa',LONG_TEXT))
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
                    'latency_to_first_audio_seconds':elapsed,
                    'rtf':elapsed/duration if duration else None,
                    'cache_hit':bool(result['cache_hit']),
                    'prompt_cache_hit':result['prompt_cache_hit'],
                    'model_load_seconds':result.get('model_load_seconds',0.0),
                    'worker_model_load_seconds':result.get('worker_model_load_seconds',0.0),
                    'profile_prepare_seconds':result.get('profile_prepare_seconds',0.0),
                    'generation_seconds':result.get('generation_seconds',elapsed),
                    'model_load_count':result['model_load_count'],
                    'worker_pid':result['worker_pid'],
                    'wav_signal':bool(np.any(samples) and np.isfinite(samples).all()),
                    'wav_rms':float(np.sqrt(np.mean(np.asarray(samples,dtype=np.float64)**2)))}
                if result['cache_hit'] or not record['wav_signal']:
                    raise RuntimeError('Benchmark não produziu inferência nova com sinal válido.')
                records.append(record)
                print(json.dumps(record,ensure_ascii=False,sort_keys=True),flush=True)
            stop.set();watcher.join(timeout=2)
            expected_pid_count=2 if args.compare_lifecycle else 1
            if len({r['worker_pid'] for r in records})!=expected_pid_count:
                raise RuntimeError('O padrão de worker não corresponde ao modo de comparação escolhido.')
            if any(r['model_load_count']!=1 for r in records):
                raise RuntimeError('Métrica do worker indica carregamento repetido do modelo.')
            expected_prompt_hits=(
                [False,True,True] if args.compare_lifecycle else
                [True]*len(records) if args.prepare_profile_first else
                [False]+[True]*(len(records)-1) if not args.short_only else None)
            if expected_prompt_hits and [r['prompt_cache_hit'] for r in records]!=expected_prompt_hits:
                raise RuntimeError('Prompt da voz não foi reutilizado após a preparação inicial.')
            if args.compare_lifecycle and any(r['cache_hit'] for r in records):
                raise RuntimeError('A comparação não deve reaproveitar WAVs gerados.')
            print('[PASSOU] Benchmark real Base 0.6B em CPU, modo offline.')
            print(json.dumps({'cpu_threads':args.threads,
                'reference_type':'synthetic' if args.synthetic_reference else 'authorized_profile',
                'peak_aggregate_rss_gib':round(stats['peak_rss_bytes']/(1024**3),2),
                'peak_cpu_percent_of_logical_machine':round(stats['peak_cpu_percent'],1),
                'mean_cpu_percent_of_logical_machine':round(
                    sum(stats['cpu_samples'])/len(stats['cpu_samples']),1)
                    if stats['cpu_samples'] else 0.0,
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
