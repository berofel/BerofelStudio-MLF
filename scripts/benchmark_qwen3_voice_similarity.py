"""Measure Qwen3 Base speaker-embedding similarity for the configured local voice.

This is an encoder cosine proxy, not a perceptual identity guarantee. Audio is
normalized in a temporary directory, generated in memory, and never saved.
Nothing is uploaded or printed that identifies the reference file or text.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time

os.environ.update({'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1',
                   'HF_HUB_DISABLE_TELEMETRY':'1'})

from pathlib import Path
import tempfile

import numpy as np
import psutil
import torch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from berofel.services.audio_reference import prepare_audio_prompt
from berofel.services.qwen3_tts_local import model_path
from berofel.services.qwen3_tts_worker import _load_model
from scripts.benchmark_qwen3_precision import _configured_reference, _cosine


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--confirm-own-or-authorized-voice',action='store_true',
        help='confirma autorização para processar a referência local configurada.')
    parser.add_argument('--threads',type=int,default=4)
    args=parser.parse_args()
    if not args.confirm_own_or_authorized_voice:
        parser.error('confirme autorização com --confirm-own-or-authorized-voice')
    if not 1<=args.threads<=32:
        parser.error('--threads deve ficar entre 1 e 32')

    os.environ['BEROFEL_QWEN3_CPU_THREADS']=str(args.threads)
    torch.set_num_threads(args.threads)
    try:torch.set_num_interop_threads(1)
    except RuntimeError:pass

    reference,reference_text=_configured_reference()
    process=psutil.Process()
    peak=[process.memory_info().rss]
    stop=threading.Event()
    def sample_memory():
        while not stop.wait(.1):
            try:peak[0]=max(peak[0],process.memory_info().rss)
            except (psutil.NoSuchProcess,psutil.AccessDenied):return
    monitor=threading.Thread(target=sample_memory,daemon=True)
    monitor.start()
    try:
        with tempfile.TemporaryDirectory(prefix='bfs_qwen_similarity_') as folder:
            normalized,prepared=prepare_audio_prompt(
                str(reference),Path(folder)/'reference.wav')
            try:
                model_started=time.perf_counter()
                model=_load_model(model_path())
                model_load=time.perf_counter()-model_started
                prompt_started=time.perf_counter()
                prompt=model.create_voice_clone_prompt(
                    ref_audio=normalized,ref_text=reference_text)
                profile_prepare=time.perf_counter()-prompt_started
                source_embedding=prompt[0].ref_spk_embedding.detach().cpu().float().numpy()
                text=('Esta frase nova testa a geração local da voz preparada '
                      'no BerofelStudio.')
                torch.manual_seed(42);np.random.seed(42)
                generation_started=time.perf_counter()
                waves,rate=model.generate_voice_clone(text=text,language='Portuguese',
                    voice_clone_prompt=prompt,max_new_tokens=128)
                generation=time.perf_counter()-generation_started
                if not waves or not len(waves[0]):
                    raise RuntimeError('Qwen3 não retornou áudio.')
                audio=np.asarray(waves[0],dtype=np.float32).reshape(-1)
                if not np.isfinite(audio).all() or float(np.sqrt(np.mean(audio*audio)))<=1e-5:
                    raise RuntimeError('Qwen3 retornou áudio silencioso ou inválido.')
                output_embedding=model.model.extract_speaker_embedding(
                    audio,int(rate)).detach().cpu().numpy()
                duration=len(audio)/float(rate)
                print(json.dumps({
                    'status':'PASS','model':'Qwen/Qwen3-TTS-12Hz-0.6B-Base',
                    'offline':True,'cpu_threads':args.threads,
                    'model_load_seconds':round(model_load,3),
                    'profile_prepare_seconds':round(profile_prepare,3),
                    'generation_seconds':round(generation,3),
                    'audio_seconds':round(duration,3),
                    'rtf':round(generation/duration,3),
                    'speaker_cosine_proxy':round(_cosine(source_embedding,output_embedding),6),
                    'speaker_metric_note':'encoder cosine proxy; not perceptual MOS or an identity guarantee',
                    'peak_process_rss_gib':round(peak[0]/1024**3,3),
                    'sample_rate':int(rate),'audio_finite_non_silent':True,
                    'reference_file_saved':False,'generated_audio_saved':False,
                },ensure_ascii=False,sort_keys=True),flush=True)
                del model,prompt,waves,audio
            finally:
                if prepared is not None:prepared.unlink(missing_ok=True)
    finally:
        stop.set();monitor.join(timeout=2)
    return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as exc:
        print(f'[FALHOU] {type(exc).__name__}: {str(exc)[:500]}',flush=True)
        raise SystemExit(1)
