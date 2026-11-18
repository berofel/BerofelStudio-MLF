"""Isolated worker for public, offline Qwen3-TTS voice cloning."""
from __future__ import annotations
import json
import os
from pathlib import Path
import sys

import numpy as np
from scipy.io import wavfile

from .pocket_tts_worker import prepare_audio_prompt


def run(request_path: str,result_path: str):
    request=json.loads(Path(request_path).read_text(encoding='utf-8'))
    if not request.get('consent'):
        raise PermissionError('Qwen3-TTS requer autorização expressa para a referência.')
    model_path=Path(request['model_path'])
    if not (model_path/'config.json').is_file():
        raise FileNotFoundError(f'Modelo Qwen3 local incompleto: {model_path}')
    import torch
    from qwen_tts import Qwen3TTSModel
    # Limit resource pressure on the main editor; no GPU is required.
    cpu_total=os.cpu_count() or 4
    torch.set_num_threads(max(1,min(8,cpu_total-2)))
    model=Qwen3TTSModel.from_pretrained(str(model_path),device_map='cpu',
        dtype=torch.float32,attn_implementation='eager',local_files_only=True)
    output=Path(request['output'])
    sample_path=output.with_name('qwen_reference_local.wav')
    reference,prepared=prepare_audio_prompt(request['reference'],sample_path)
    try:
        reference_text=str(request.get('reference_text','')).strip()
        wavs,rate=model.generate_voice_clone(text=request['text'],
            language=request['language'],ref_audio=reference,
            ref_text=reference_text if reference_text else None,
            x_vector_only_mode=not bool(reference_text))
    finally:
        if prepared is not None:prepared.unlink(missing_ok=True)
    if not wavs or len(wavs[0])==0:
        raise RuntimeError('Qwen3-TTS retornou áudio vazio.')
    audio=np.asarray(wavs[0],dtype=np.float32).reshape(-1)
    if not np.all(np.isfinite(audio)):
        raise RuntimeError('Qwen3-TTS retornou amostras não finitas.')
    pcm=np.clip(audio,-1.,1.)
    pending=output.with_suffix('.part.wav')
    wavfile.write(str(pending),int(rate),(pcm*32767).astype(np.int16))
    os.replace(pending,output)
    Path(result_path).write_text(json.dumps({'duration':len(pcm)/int(rate),
        'sample_rate':int(rate),'bytes':output.stat().st_size},ensure_ascii=False),
        encoding='utf-8')


if __name__=='__main__':
    for stream in (sys.stdout,sys.stderr):
        try:stream.reconfigure(encoding='utf-8',errors='replace')
        except (AttributeError,OSError,ValueError):pass
    try:
        if len(sys.argv)!=3:raise ValueError('Uso: python -m berofel.services.qwen3_tts_worker pedido.json resultado.json')
        run(sys.argv[1],sys.argv[2])
    except Exception as exc:
        print(f'Falha Qwen3-TTS local: {type(exc).__name__}: {exc}',file=sys.stderr)
        raise SystemExit(1)
