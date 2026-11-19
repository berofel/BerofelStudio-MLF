"""Profile native Q4 Qwen stages using the installed Windows CLI.

Runs the actual local Qwen3 Base binary with a cached authorized x-vector.
All WAVs and the JSON report stay outside the repository.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import wave

import numpy as np
import psutil

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from berofel.services import qwen3_native_tts as native
from berofel.services.narration_service import _process_flags
from berofel.services.voice_profiles import VoiceProfileManager

TEXTS={
    'curta':'O Berofel Studio mede o tempo de síntese nativa em português brasileiro.',
    'media':('Estamos medindo a geração local de uma narração em português brasileiro. '
        'A voz autorizada é preparada antes e o mesmo perfil é reutilizado nos dois '
        'modos. O áudio gerado será verificado e poderá seguir para a timeline e exportação.'),
}
STAGE_NAMES={'Tokenize':'tokenize_ms','Encode':'encode_ms',
             'Generate':'generate_ms','Decode':'decode_ms','Total':'engine_total_ms'}


def main()->int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--voice-profile-id',default='')
    parser.add_argument('--confirm-own-or-authorized-voice',action='store_true')
    parser.add_argument('--lengths',nargs='+',choices=tuple(TEXTS),default=tuple(TEXTS))
    parser.add_argument('--threads',type=int,default=6)
    parser.add_argument('--repeats',type=int,default=1)
    parser.add_argument('--temperature',type=float,default=.9)
    parser.add_argument('--top-k',type=int,default=50)
    args=parser.parse_args()
    if not args.confirm_own_or_authorized_voice:
        parser.error('confirme autorização com --confirm-own-or-authorized-voice')
    if not 1<=args.threads<=8:parser.error('--threads deve estar entre 1 e 8')
    if not 1<=args.repeats<=2:parser.error('--repeats deve estar entre 1 e 2')
    if not 0<=args.temperature<=2:parser.error('--temperature deve estar entre 0 e 2')
    if not 1<=args.top_k<=1000:parser.error('--top-k deve estar entre 1 e 1000')
    profiles=VoiceProfileManager().list_profiles()
    profile=(next((p for p in profiles if p['id']==args.voice_profile_id and
                   p.get('authorized') and p.get('reference_text')),None)
             if args.voice_profile_id else next((p for p in profiles
                   if p.get('authorized') and p.get('reference_text')),None))
    if profile is None:raise RuntimeError('Nenhum perfil local autorizado válido foi encontrado.')
    reference=Path(profile['sample_path']).expanduser()
    reference_text=str(profile.get('reference_text','')).strip()
    if not reference.is_file() or not reference_text:
        raise RuntimeError('O perfil autorizado não possui gravação/transcrição válida.')

    exe,model,tokenizer=native._layout()
    embedding,embedding_hit,profile_prepare=native._native_embedding(
        reference,reference_text,model,threads=args.threads)
    run_id=time.strftime('%Y%m%d_%H%M%S')
    out_root=Path.home()/'Desktop'/'BerofelStudio_QwenTurbo_Benchmark_20261119'/f'native_stages_{run_id}'
    out_root.mkdir(parents=True,exist_ok=False)
    records=[]
    for repeat in range(args.repeats):
        order=args.lengths if repeat%2==0 else tuple(reversed(args.lengths))
        for length in order:
            text=TEXTS[length]
            max_tokens=256 if length=='curta' else 512
            output=out_root/f'{length}_repeat{repeat+1}.wav'
            command=[str(exe),'-m',str(model),'--tokenizer',str(tokenizer),
                '-t',text,'-o',str(output),'--embedding-in',str(embedding),
                '-l','portuguese','-j',str(args.threads),'--max-tokens',str(max_tokens),
                '--temperature',str(args.temperature),'--top-k',str(args.top_k)]
            started=time.perf_counter();child=subprocess.Popen(command,cwd=str(exe.parent),
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',
                errors='replace',creationflags=_process_flags(),
                env={**os.environ,'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1'})
            stats={'peak_rss':0,'peak_cpu':0.0};done=threading.Event()
            def sample()->None:
                try:root=psutil.Process(child.pid)
                except psutil.NoSuchProcess:return
                tracked={root.pid:root}
                while not done.wait(.1):
                    total=0;cpu=0.0;current={}
                    try:
                        for proc in [root,*root.children(recursive=True)]:
                            item=tracked.setdefault(proc.pid,proc);current[proc.pid]=item
                            try:total+=item.memory_info().rss;cpu+=max(0.,item.cpu_percent(None))
                            except (psutil.NoSuchProcess,psutil.AccessDenied):pass
                        stats['peak_rss']=max(stats['peak_rss'],total)
                        stats['peak_cpu']=max(stats['peak_cpu'],cpu/max(1,os.cpu_count() or 1))
                        tracked=current
                    except (psutil.NoSuchProcess,psutil.AccessDenied):pass
            monitor=threading.Thread(target=sample,daemon=True);monitor.start()
            try:stdout,stderr=child.communicate(timeout=600)
            except subprocess.TimeoutExpired:
                child.kill();child.communicate();raise TimeoutError('CLI nativo excedeu 600 s.')
            finally:done.set();monitor.join(timeout=2)
            elapsed=time.perf_counter()-started
            if child.returncode or not output.is_file():
                raise RuntimeError('CLI Qwen falhou: '+(stderr or stdout)[-500:])
            (out_root/f'{length}_repeat{repeat+1}.stdout.txt').write_text(stdout,encoding='utf-8')
            (out_root/f'{length}_repeat{repeat+1}.stderr.txt').write_text(stderr,encoding='utf-8')
            timing_text=stdout+'\n'+stderr
            timings={STAGE_NAMES[label]:float(value) for label,value in re.findall(
                r'^\s*(Tokenize|Encode|Generate|Decode|Total):\s*([\d.]+)\s*ms',
                timing_text,re.M|re.I)}
            with wave.open(str(output),'rb') as audio:
                rate=audio.getframerate();frames=audio.getnframes();channels=audio.getnchannels()
                sample_width=audio.getsampwidth()
                raw=audio.readframes(frames)
            if channels!=1 or rate!=24000 or sample_width!=2 or frames<=0:
                raise RuntimeError('CLI nativo não gerou WAV mono 24 kHz PCM16 válido.')
            samples=np.frombuffer(raw,dtype='<i2').astype(np.float32)/32768.0
            rms=float(np.sqrt(np.mean(samples*samples)))
            peak=float(np.max(np.abs(samples)))
            if rms<1e-4:
                raise RuntimeError('CLI nativo gerou áudio silencioso ou abaixo do limiar de RMS.')
            duration=frames/rate
            record={'length':length,'characters':len(text),'repeat':repeat+1,
                'threads':args.threads,'temperature':args.temperature,
                'top_k':args.top_k,'max_tokens':max_tokens,
                'wall_seconds':round(elapsed,3),'audio_seconds':round(duration,3),
                'rtf_wall':round(elapsed/duration,3),'sample_file':output.name,
                'sample_rate':rate,'channels':channels,'sample_width_bytes':sample_width,
                'rms':round(rms,6),'peak':round(peak,6),
                'clipped_samples':int(np.count_nonzero(np.abs(samples)>=.9999)),
                'stages':timings,
                'peak_process_tree_rss_gib':round(stats['peak_rss']/(1024**3),3),
                'peak_cpu_percent_of_logical_machine':round(stats['peak_cpu'],1),
                'max_tokens_near_limit':duration>=max_tokens/12*.9}
            records.append(record);print(json.dumps(record,ensure_ascii=False,sort_keys=True),flush=True)
    report={'backend':'Qwen3-TTS 12Hz 0.6B Base, native GGUF Q4_0',
        'offline':os.environ.get('HF_HUB_OFFLINE')=='1' and os.environ.get('TRANSFORMERS_OFFLINE')=='1',
        'profile_embedding_cache_hit':bool(embedding_hit),
        'profile_prepare_seconds':round(profile_prepare,3),'threads':args.threads,
        'temperature':args.temperature,'top_k':args.top_k,
        'repeats':args.repeats,'records':records}
    (out_root/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    has_stage_times=any(record['stages'] for record in records)
    status='tempos internos do CLI capturados' if has_stage_times else 'síntese real medida; CLI não expôs tempos por estágio'
    print(f'[PASSOU] {status}; evidências em {out_root}')
    return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as exc:
        print(f'[FALHOU] {type(exc).__name__}: {exc}',flush=True)
        raise SystemExit(1)
