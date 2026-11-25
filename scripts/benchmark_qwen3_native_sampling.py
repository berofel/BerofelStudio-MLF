"""Measure Q4 server sampling options with a local authorized Qwen Base voice.

Does not alter saved profiles or projects. WAV comparison samples and the
metrics JSON are written outside the repository under the user's Desktop.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import wave

import numpy as np
from scipy.io import wavfile
from scipy.signal import resample_poly

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from berofel.services import qwen3_native_tts as native
from berofel.services.voice_profiles import VoiceProfileManager

TEXTS={
    'curta':'O Berofel Studio está testando a narração rápida em português brasileiro.',
    'media':('Estamos medindo a geração local de uma narração em português brasileiro. '
        'A voz autorizada é preparada antes e o mesmo perfil é reutilizado nos dois '
        'modos. O áudio gerado será verificado e poderá seguir para a timeline e exportação.'),
}
CONFIGS=(('default',.9,50),('greedy',0.0,1),('lower_temp',.7,20))


def main()->int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--voice-profile-id',default='')
    parser.add_argument('--confirm-own-or-authorized-voice',action='store_true')
    parser.add_argument('--repeats',type=int,default=2)
    parser.add_argument('--length',choices=tuple(TEXTS),default='curta')
    parser.add_argument('--configs',nargs='+',choices=tuple(x[0] for x in CONFIGS),
                        default=tuple(x[0] for x in CONFIGS))
    parser.add_argument('--parakeet-wer',action='store_true',
        help='calcula WER com Parakeet TDT v3 INT8 local (proxy textual, não métrica vocal).')
    args=parser.parse_args()
    if not args.confirm_own_or_authorized_voice:
        parser.error('confirme autorização com --confirm-own-or-authorized-voice')
    if not 1<=args.repeats<=3:parser.error('--repeats deve ficar entre 1 e 3')
    text=TEXTS[args.length]
    max_tokens=512 if args.length=='media' else 256
    configs=tuple(config for config in CONFIGS if config[0] in args.configs)
    profiles=VoiceProfileManager().list_profiles()
    profile=(next((p for p in profiles if p['id']==args.voice_profile_id and
                   p.get('authorized') and p.get('reference_text')),None)
             if args.voice_profile_id else next((p for p in profiles
                   if p.get('authorized') and p.get('reference_text')),None))
    if profile is None:raise RuntimeError('Nenhum perfil vocal local autorizado e válido foi encontrado.')
    reference=Path(profile['sample_path']).expanduser()
    reference_text=str(profile.get('reference_text','')).strip()
    if not reference.is_file() or not reference_text:
        raise RuntimeError('O perfil autorizado não possui gravação/transcrição válida.')

    exe,model,tokenizer=native._layout()
    embedding,embedding_hit,profile_prepare=native._native_embedding(
        reference,reference_text,model,threads=6)
    process,model_load=native._start_server(exe,model,tokenizer,None,6)
    run_id=time.strftime('%Y%m%d_%H%M%S')
    output_root=Path.home()/'Desktop'/'BerofelStudio_QwenTurbo_Benchmark_20261119'/f'native_sampling_{args.length}_{run_id}'
    output_root.mkdir(parents=True,exist_ok=False)
    records=[]
    try:
        for repeat in range(args.repeats):
            order=configs if repeat%2==0 else tuple(reversed(configs))
            for name,temperature,top_k in order:
                output=output_root/f'{name}_repeat{repeat+1}.wav'
                payload={'text':text,'output':str(output),'language':'portuguese',
                    'max_tokens':max_tokens,'embedding_in':str(embedding),
                    'temperature':temperature,'top_k':top_k}
                started=time.perf_counter()
                process.stdin.write(json.dumps(payload,ensure_ascii=False)+'\n')
                process.stdin.flush()
                reply=native._read_reply(process,timeout=600)
                elapsed=time.perf_counter()-started
                if not reply.get('success') or not output.is_file():
                    raise RuntimeError('O servidor nativo não produziu o WAV de teste.')
                with wave.open(str(output),'rb') as stream:
                    frames=stream.getnframes();rate=stream.getframerate()
                    channels=stream.getnchannels();duration=frames/rate
                if channels!=1 or rate!=24000 or frames<=0:
                    raise RuntimeError('Formato de áudio inesperado no WAV de teste.')
                record={'config':name,'temperature':temperature,'top_k':top_k,
                    'repeat':repeat+1,'synthesis_seconds':round(elapsed,3),
                    'engine_ms':reply.get('t_total_ms'),'duration_seconds':round(duration,3),
                    'rtf':round(elapsed/duration,3),'sample_rate':rate,
                    'max_tokens':max_tokens,
                    'max_tokens_near_limit':duration>=max_tokens/12*.9,
                    'sample_file':output.name,'cache_hit':False}
                records.append(record)
                print(json.dumps(record,ensure_ascii=False,sort_keys=True),flush=True)
        if args.parakeet_wer:
            from berofel.services.parakeet_asr import load_model,load_vad,transcribe_file
            recognizer=load_model(threads=6)
            vad=load_vad(threads=1)
            reference_words=re.findall(r'\w+',text.lower(),flags=re.UNICODE)
            with tempfile.TemporaryDirectory(prefix='bfs_sampling_wer_') as folder:
                for record in records:
                    rate,samples=wavfile.read(str(output_root/record['sample_file']))
                    signal=np.asarray(samples,dtype=np.float32)
                    if signal.ndim>1:signal=signal.mean(axis=1)
                    if np.issubdtype(samples.dtype,np.integer):
                        signal/=max(1,np.iinfo(samples.dtype).max)
                    if rate!=16000:
                        signal=resample_poly(signal,2,3) if rate==24000 else resample_poly(signal,16000,rate)
                    converted=Path(folder)/(Path(record['sample_file']).stem+'.wav')
                    wavfile.write(str(converted),16000,
                        (np.clip(signal,-1,1)*32767).astype('<i2'))
                    result=transcribe_file(converted,model=recognizer,vad=vad,threads=6)
                    transcript=' '.join(item.get('text','') for item in result.get('segments',[]))
                    hypothesis_words=re.findall(r'\w+',transcript.lower(),flags=re.UNICODE)
                    row=list(range(len(hypothesis_words)+1))
                    for i,word in enumerate(reference_words,1):
                        current=[i]
                        for j,observed in enumerate(hypothesis_words,1):
                            current.append(min(current[-1]+1,row[j]+1,
                                row[j-1]+(word!=observed)))
                        row=current
                    record['parakeet_tdt_v3_int8_wer']=round(row[-1]/max(1,len(reference_words)),3)
                    record['parakeet_words']=len(hypothesis_words)
        report={'backend':'Qwen3-TTS 12Hz 0.6B Base, nativo Q4, CPU, 6 threads',
            'text_length':args.length,'characters':len(text),'max_tokens':max_tokens,
            'offline':bool(os.environ.get('HF_HUB_OFFLINE')=='1' and
                           os.environ.get('TRANSFORMERS_OFFLINE')=='1'),
            'profile_embedding_cache_hit':bool(embedding_hit),
            'profile_prepare_seconds':round(profile_prepare,3),
            'model_load_seconds':round(model_load,3),'parakeet_wer_measured':args.parakeet_wer,
            'repeats':args.repeats,'records':records}
        report_path=output_root/'results.json'
        report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in report.items() if k!='records'},ensure_ascii=False))
        print(f'[PASSOU] Síntese Q4 real; amostras privadas em {output_root}')
    finally:
        native.stop_native_worker()
    return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as exc:
        print(f'[FALHOU] {type(exc).__name__}: {exc}',flush=True)
        raise SystemExit(1)
