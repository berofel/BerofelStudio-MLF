"""Compare real native Q4 narration latency across Portuguese text lengths.

Uses an explicitly authorized saved local voice, writes all generated audio and
cache data to a temporary directory, and prints no voice path or transcript.
Run with HF_HUB_OFFLINE=1 and TRANSFORMERS_OFFLINE=1 for a network-free test.
"""
from __future__ import annotations

import argparse
import json
import os
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

from berofel.services.narration_service import NarrationRequest,generate_narration
from berofel.services.qwen3_native_tts import stop_native_worker
from berofel.services.voice_profiles import VoiceProfileManager

TEXTS={
    'curta':'Olá! Esta é uma medição curta da narração local do Berofel Studio.',
    'media':('Estamos medindo a geração local de uma narração em português brasileiro. '
        'A voz autorizada é preparada antes e o mesmo perfil é reutilizado nos dois '
        'modos. O áudio gerado será verificado e poderá seguir para a timeline e exportação.'),
    'longa':('Hoje estamos medindo a narração local do Berofel Studio em português. '
        'O editor carrega o modelo uma vez, prepara a referência autorizada e reutiliza '
        'o perfil de voz nas frases seguintes. Este trecho verifica a geração de um texto '
        'mais comprido, com pausas naturais entre as ideias. A linha do tempo recebe o '
        'áudio em um bloco independente, mantendo o projeto editável e sem alterar a '
        'gravação original. O objetivo é avaliar o tempo real no processador deste '
        'computador, a memória usada e a consistência do áudio. Depois da geração, os '
        'mesmos arquivos podem ser reproduzidos, ajustados e exportados pelo editor sem '
        'chamar novamente o modelo para cada controle DSP. Este teste funciona sem '
        'conexão externa quando o modelo já está instalado.'),
}


def sample_resources(stop:threading.Event,stats:dict)->None:
    root=psutil.Process();tracked={root.pid:root}
    while not stop.is_set():
        current={};rss=0;cpu=0.0
        try:
            for proc in [root,*root.children(recursive=True)]:
                item=tracked.setdefault(proc.pid,proc);current[proc.pid]=item
                try:
                    rss+=item.memory_info().rss
                    cpu+=max(0.0,item.cpu_percent(None))
                except (psutil.NoSuchProcess,psutil.AccessDenied):
                    pass
            stats['peak_rss']=max(stats['peak_rss'],rss)
            stats['peak_cpu']=max(stats['peak_cpu'],cpu/max(1,os.cpu_count() or 1))
            tracked=current
        except (psutil.NoSuchProcess,psutil.AccessDenied):
            pass
        stop.wait(.1)


def main()->int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--voice-profile-id',default='')
    parser.add_argument('--confirm-own-or-authorized-voice',action='store_true')
    parser.add_argument('--repeats',type=int,default=1)
    args=parser.parse_args()
    if not args.confirm_own_or_authorized_voice:
        parser.error('confirme autorização com --confirm-own-or-authorized-voice')
    if not 1<=args.repeats<=3:
        parser.error('--repeats deve ficar entre 1 e 3')
    profiles=VoiceProfileManager().list_profiles()
    profile=(next((p for p in profiles if p['id']==args.voice_profile_id and
                   p.get('authorized')),None) if args.voice_profile_id else
             next((p for p in profiles if p.get('authorized') and
                   p.get('reference_text')),None))
    if profile is None:
        raise RuntimeError('Nenhum perfil vocal local autorizado e válido foi encontrado.')
    reference=Path(profile['sample_path']).expanduser()
    reference_text=str(profile.get('reference_text','')).strip()
    if not reference.is_file() or not reference_text:
        raise RuntimeError('O perfil autorizado não possui gravação/transcrição válida.')

    records=[];stop=threading.Event()
    stats={'peak_rss':0,'peak_cpu':0.0}
    watcher=threading.Thread(target=sample_resources,args=(stop,stats),daemon=True)
    old_cache=os.environ.get('BEROFEL_AI_CACHE')
    try:
        with tempfile.TemporaryDirectory(prefix='bfs_native_lengths_') as folder:
            root=Path(folder)
            os.environ['BEROFEL_AI_CACHE']=str(root/'cache')
            watcher.start()
            project=root/'benchmark.bfs'
            # Alternate engine order by repetition to reduce systematic bias.
            engines=('qwen3-tts-native-q4','qwen3-tts-native-q4-balanced')
            for repeat in range(args.repeats):
                order=engines if repeat%2==0 else tuple(reversed(engines))
                for length,text in TEXTS.items():
                    for engine in order:
                        # Clear only this isolated run's result cache, so each
                        # identical text is a genuine inference on every repeat.
                        run_cache=root/'cache'
                        if run_cache.exists():
                            import shutil
                            shutil.rmtree(run_cache)
                        request=NarrationRequest(text=text,voice=str(reference.resolve()),
                            language='portuguese',consent=True,
                            project_path=str(project),title=f'{length}_{repeat}_{engine}',
                            engine=engine,reference_text=reference_text)
                        stream={'chunks':0,'bytes':0,'first_chunk_elapsed':None}
                        generation_started=time.perf_counter()
                        def on_chunk(data):
                            if stream['first_chunk_elapsed'] is None:
                                stream['first_chunk_elapsed']=time.perf_counter()-generation_started
                            stream['chunks']+=1
                            stream['bytes']+=len(data)
                        started=time.perf_counter()
                        result=generate_narration(request,audio_chunk=on_chunk)
                        elapsed=time.perf_counter()-started
                        rate,samples=wavfile.read(result['path'])
                        signal=np.asarray(samples,dtype=np.float64)
                        duration=len(signal)/float(rate)
                        if not signal.size or not np.isfinite(signal).all() or not np.any(signal):
                            raise RuntimeError('A geração produziu WAV vazio, não finito ou silencioso.')
                        if result.get('cache_hit'):
                            raise RuntimeError('O benchmark reutilizou áudio em vez de sintetizar texto novo.')
                        record={'length':length,'characters':len(text),'engine':engine,
                            'repeat':repeat+1,'wall_seconds':round(elapsed,3),
                            'generation_seconds':round(float(result.get('generation_seconds',elapsed)),3),
                            'model_load_seconds':round(float(result.get('model_load_seconds',0)),3),
                            'profile_prepare_seconds':round(float(result.get('profile_prepare_seconds',0)),3),
                            'first_audio_seconds':result.get('first_audio_request_seconds'),
                            'first_chunk_elapsed_seconds':round(stream['first_chunk_elapsed'],3)
                                if stream['first_chunk_elapsed'] is not None else None,
                            'stream_chunks':stream['chunks'],'stream_bytes':stream['bytes'],
                            'duration_seconds':round(duration,3),
                            'rtf':round(float(result.get('generation_seconds',elapsed))/duration,3),
                            'sample_rate':int(rate),'samples':int(len(signal)),
                            'cache_hit':bool(result.get('cache_hit')),
                            'profile_embedding_cache_hit':bool(result.get('prompt_cache_hit'))}
                        records.append(record)
                        print(json.dumps(record,ensure_ascii=False,sort_keys=True),flush=True)
            stop.set();watcher.join(timeout=2)
            summary={'machine':'local Windows CPU','records':len(records),
                'peak_aggregate_rss_gib':round(stats['peak_rss']/(1024**3),3),
                'peak_cpu_percent_of_logical_machine':round(stats['peak_cpu'],1),
                'offline_env':{'HF_HUB_OFFLINE':os.environ.get('HF_HUB_OFFLINE'),
                               'TRANSFORMERS_OFFLINE':os.environ.get('TRANSFORMERS_OFFLINE')},
                'records_data':records}
            result_file=Path.home()/'Desktop'/'BerofelStudio_QwenTurbo_Benchmark_20261119'/'native_lengths_results.json'
            result_file.parent.mkdir(parents=True,exist_ok=True)
            result_file.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({k:v for k,v in summary.items() if k!='records_data'},
                             ensure_ascii=False,sort_keys=True),flush=True)
            print('[PASSOU] Benchmark nativo Q4 curto/médio/longo; WAVs temporários removidos.')
    finally:
        stop.set();watcher.join(timeout=2)
        stop_native_worker()
        if old_cache is None:os.environ.pop('BEROFEL_AI_CACHE',None)
        else:os.environ['BEROFEL_AI_CACHE']=old_cache
    return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as exc:
        print(f'[FALHOU] {type(exc).__name__}: {exc}',flush=True)
        raise SystemExit(1)
