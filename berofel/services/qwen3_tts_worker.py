"""Isolated Qwen3-TTS Base worker with a warm model and safe voice prompts."""
from __future__ import annotations

import hashlib
from contextlib import redirect_stdout
import json
import os
from pathlib import Path
import sys
import time

import numpy as np
from scipy.io import wavfile

from .audio_reference import prepare_audio_prompt
from .qwen3_audio_compat import install_librosa_compat

PROMPT_SCHEMA=5  # caches include safe edge-only trimming with internal pauses
_MAX_PROMPTS=64


def _load_model(model_path: str | Path, progress=None):
    model_path=Path(model_path)
    if not (model_path/'config.json').is_file():
        raise FileNotFoundError(f'Modelo Qwen3 local incompleto: {model_path}')
    if progress: progress('Importando PyTorch para CPU…')
    import torch
    if progress: progress('Importando Qwen3-TTS…')
    install_librosa_compat()
    from qwen_tts import Qwen3TTSModel
    cpu_total=os.cpu_count() or 4
    configured=os.environ.get('BEROFEL_QWEN3_CPU_THREADS','')
    try:threads=int(configured) if configured else max(1,min(4,cpu_total-2))
    except ValueError:threads=max(1,min(4,cpu_total-2))
    torch.set_num_threads(max(1,min(cpu_total,threads)))
    # CPU tests on the target Ryzen 7 5700G measured a small regression and
    # higher RSS with 8 intra-op threads; a single inter-op worker avoids
    # oversubscribing the 8 physical cores while keeping inference parallel.
    try:torch.set_num_interop_threads(1)
    except RuntimeError:pass  # Torch may already have started an inter-op pool.
    if progress: progress('Lendo os pesos locais do Qwen3-TTS 0.6B…')
    model=Qwen3TTSModel.from_pretrained(str(model_path),device_map='cpu',
        dtype=torch.float32,attn_implementation='eager',local_files_only=True)
    if progress: progress('Pesos carregados; preparando a sessão de narração…')
    return model


def _reference_identity(request: dict) -> str:
    digest=hashlib.sha256()
    with Path(request['reference']).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):
            digest.update(chunk)
    return digest.hexdigest()


def _prompt_key(request: dict) -> str:
    identity={
        'schema':PROMPT_SCHEMA,
        'model':str(request.get('model_fingerprint','')),
        'reference_sha256':_reference_identity(request),
        'reference_window_start':request.get('reference_window_start'),
        'reference_window_duration':request.get('reference_window_duration'),
        'reference_text_sha256':hashlib.sha256(
            str(request.get('reference_text','')).strip().encode('utf-8')).hexdigest(),
        'x_vector_only_mode':not bool(str(request.get('reference_text','')).strip()),
    }
    return hashlib.sha256(json.dumps(identity,sort_keys=True,separators=(',',':'))
                          .encode('utf-8')).hexdigest()


def _cache_path(request: dict) -> Path | None:
    value=request.get('prompt_cache_path')
    return Path(value) if value else None


def _load_cached_prompt(model,request: dict,key: str):
    path=_cache_path(request)
    if path is None or not path.is_file() or path.is_symlink():return None
    try:
        from qwen_tts import VoiceClonePromptItem
        with np.load(path,allow_pickle=False) as archive:
            metadata=json.loads(str(archive['metadata'].item()))
            if (metadata.get('schema')!=PROMPT_SCHEMA or metadata.get('key')!=key or
                    metadata.get('model')!=str(request.get('model_fingerprint',''))):
                return None
            ref_code=np.asarray(archive['ref_code'])
            speaker=np.asarray(archive['speaker_embedding'])
            if not speaker.size or not np.isfinite(speaker).all():return None
            import torch
            code=None if ref_code.size==0 else torch.from_numpy(ref_code.copy())
            embedding=torch.from_numpy(speaker.copy())
            return [VoiceClonePromptItem(
                ref_code=code,ref_spk_embedding=embedding,
                x_vector_only_mode=bool(metadata['x_vector_only_mode']),
                icl_mode=bool(metadata['icl_mode']),
                ref_text=str(request.get('reference_text','')).strip() or None)]
    except (OSError,ValueError,KeyError,TypeError,ImportError):
        return None


def _save_cached_prompt(items,request: dict,key: str):
    path=_cache_path(request)
    if path is None or not items:return
    try:
        import torch
        item=items[0]
        ref_code=(np.empty((0,),dtype=np.int64) if item.ref_code is None else
                  item.ref_code.detach().cpu().numpy())
        speaker=item.ref_spk_embedding.detach().cpu().numpy()
        metadata=json.dumps({'schema':PROMPT_SCHEMA,'key':key,
            'model':str(request.get('model_fingerprint','')),
            'x_vector_only_mode':bool(item.x_vector_only_mode),
            'icl_mode':bool(item.icl_mode)},separators=(',',':'))
        path.parent.mkdir(parents=True,exist_ok=True)
        pending=path.with_name(path.name+'.part')
        with pending.open('wb') as stream:
            np.savez_compressed(stream,metadata=np.asarray(metadata),
                ref_code=ref_code,speaker_embedding=speaker)
            stream.flush();os.fsync(stream.fileno())
        os.replace(pending,path)
    except (OSError,ValueError,AttributeError,TypeError):
        try:path.with_name(path.name+'.part').unlink(missing_ok=True)
        except OSError:pass


def _voice_prompt(model,request: dict,memory_cache: dict):
    started=time.perf_counter()
    reference_text=str(request.get('reference_text','')).strip()
    if reference_text:
        from .audio_reference import validate_reference_transcript
        validate_reference_transcript(reference_text,
            float(request.get('reference_window_duration',30.0)))
    key=_prompt_key(request)
    prompt=memory_cache.get(key)
    if prompt is not None:return prompt,True,time.perf_counter()-started
    prompt=_load_cached_prompt(model,request,key)
    if prompt is not None:
        memory_cache[key]=prompt
        return prompt,True,time.perf_counter()-started
    output=Path(request['output'])
    reference_path=output.with_name('qwen_reference_local.wav')
    reference,prepared=prepare_audio_prompt(request['reference'],reference_path,
        start_seconds=request.get('reference_window_start'),
        duration_seconds=request.get('reference_window_duration'),
        trim_outer_silence=True)
    try:
        prompt=model.create_voice_clone_prompt(ref_audio=reference,
            ref_text=reference_text or None,
            x_vector_only_mode=not bool(reference_text))
    finally:
        if prepared is not None:prepared.unlink(missing_ok=True)
        reference_path.unlink(missing_ok=True)
    memory_cache[key]=prompt
    _save_cached_prompt(prompt,request,key)
    while len(memory_cache)>_MAX_PROMPTS:
        memory_cache.pop(next(iter(memory_cache)))
    return prompt,False,time.perf_counter()-started


def _verify_clone_conditioning(prompt,reference_text: str) -> dict:
    """Fail closed unless the selected reference really reached Qwen Base."""
    if not isinstance(prompt,(list,tuple)) or len(prompt)!=1:
        raise RuntimeError('Qwen3 não preparou exatamente um perfil vocal para esta referência.')
    item=prompt[0]
    embedding=getattr(item,'ref_spk_embedding',None)
    if embedding is None:
        raise RuntimeError('Qwen3 não extraiu o vetor vocal da referência; a clonagem foi cancelada.')
    try:
        if hasattr(embedding,'detach'):
            embedding=embedding.detach().cpu().numpy()
        embedding=np.asarray(embedding)
    except Exception as exc:
        raise RuntimeError('Não foi possível validar o vetor vocal extraído da referência.') from exc
    if not embedding.size or not np.isfinite(embedding).all() or not np.any(embedding):
        raise RuntimeError('O vetor vocal da referência está vazio ou inválido; não será usada voz substituta.')
    expected_text=str(reference_text or '').strip()
    if expected_text:
        codes=getattr(item,'ref_code',None)
        try:
            if codes is not None and hasattr(codes,'detach'):
                codes=codes.detach().cpu().numpy()
            code_count=0 if codes is None else int(np.asarray(codes).size)
        except Exception as exc:
            raise RuntimeError('Não foi possível validar os códigos de áudio da referência.') from exc
        actual_text=str(getattr(item,'ref_text','') or '').strip()
        if (bool(getattr(item,'x_vector_only_mode',True)) or
                not bool(getattr(item,'icl_mode',False)) or code_count==0 or
                actual_text!=expected_text):
            raise RuntimeError(
                'O prompt do Qwen não contém áudio, transcrição e vetor vocal '
                'correspondentes. A clonagem foi cancelada sem fallback de voz.')
        return {'mode':'audio+transcript','icl_mode':True,'x_vector_only_mode':False,
                'reference_audio_code_count':code_count,
                'speaker_embedding_dimensions':list(embedding.shape)}
    if not bool(getattr(item,'x_vector_only_mode',False)):
        raise RuntimeError('O perfil sem transcrição não foi preparado no modo x-vector esperado.')
    return {'mode':'speaker-embedding-only','icl_mode':False,'x_vector_only_mode':True,
            'reference_audio_code_count':0,
            'speaker_embedding_dimensions':list(embedding.shape)}


def _synthesize(model,request: dict,memory_cache: dict) -> dict:
    if not request.get('consent'):
        raise PermissionError('Qwen3-TTS requer autorização expressa para a referência.')
    reference=Path(request['reference'])
    if not reference.is_file():
        raise FileNotFoundError(
            'A gravação de referência não está acessível ao worker local. '
            'Verifique o caminho, os caracteres acentuados e se a unidade está montada.')
    if reference.suffix.lower() not in {'.wav','.mp3','.flac','.ogg','.m4a'}:
        raise ValueError('Use referência WAV, MP3, FLAC, OGG ou M4A.')
    text=str(request['text']).strip()
    if not text:raise ValueError('Digite um texto para narrar.')
    prompt,prompt_cache_hit,profile_prepare_seconds=_voice_prompt(model,request,memory_cache)
    conditioning=_verify_clone_conditioning(prompt,str(request.get('reference_text','')))
    max_tokens=min(2048,max(96,int(len(text)*1.5+48)))
    generation_started=time.perf_counter()
    wavs,rate=model.generate_voice_clone(text=text,language=request['language'],
        voice_clone_prompt=prompt,max_new_tokens=max_tokens)
    generation_seconds=time.perf_counter()-generation_started
    if not wavs or len(wavs[0])==0:
        raise RuntimeError('Qwen3-TTS retornou áudio vazio.')
    audio=np.asarray(wavs[0],dtype=np.float32).reshape(-1)
    if not np.all(np.isfinite(audio)):
        raise RuntimeError('Qwen3-TTS retornou amostras não finitas.')
    pcm=np.clip(audio,-1.,1.)
    output=Path(request['output']);output.parent.mkdir(parents=True,exist_ok=True)
    pending=output.with_suffix('.part.wav')
    wavfile.write(str(pending),int(rate),(pcm*32767).astype(np.int16))
    os.replace(pending,output)
    window_start=request.get('reference_window_start')
    window_duration=request.get('reference_window_duration')
    reference_window=({'start':float(window_start),'duration':float(window_duration)}
        if window_start is not None and window_duration is not None else None)
    return {'duration':len(pcm)/int(rate),'sample_rate':int(rate),
            'bytes':output.stat().st_size,'prompt_cache_hit':prompt_cache_hit,
            'profile_prepare_seconds':profile_prepare_seconds,
            'generation_seconds':generation_seconds,'max_new_tokens':max_tokens,
            'reference_window':reference_window,
            'conditioning_mode':conditioning['mode'],
            'conditioning_verified':True,
            'icl_mode':conditioning['icl_mode'],
            'x_vector_only_mode':conditioning['x_vector_only_mode'],
            'reference_audio_code_count':conditioning['reference_audio_code_count'],
            'speaker_embedding_dimensions':conditioning['speaker_embedding_dimensions'],
            'reference_sha256_prefix':_reference_identity(request)[:12],
            'reference_text_word_count':len(str(request.get('reference_text','')).split())}


def run(request_path: str,result_path: str):
    """One-shot compatibility path used by installer probes and tests."""
    request=json.loads(Path(request_path).read_text(encoding='utf-8'))
    model=_load_model(request['model_path'])
    result=_synthesize(model,request,{})
    Path(result_path).write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')


def serve(model_path: str):
    """JSON-lines protocol; keep the single CPU model and prompt cache warm."""
    protocol=sys.stdout
    model_started=time.perf_counter()
    def report_progress(message):
        protocol.write(json.dumps({'progress':str(message)},ensure_ascii=False)+'\n')
        protocol.flush()
    with redirect_stdout(sys.stderr):
        try:
            model=_load_model(model_path,progress=report_progress)
        except Exception as exc:
            protocol.write(json.dumps({'startup_error':type(exc).__name__,
                'error':str(exc).replace('\r',' ').replace('\n',' ')[:1200]},
                ensure_ascii=False)+'\n')
            protocol.flush()
            raise
    model_load_seconds=time.perf_counter()-model_started
    prompts={}
    protocol.write(json.dumps({'ready':True,'model':'Qwen3-TTS-12Hz-0.6B-Base',
        'model_load_seconds':model_load_seconds})+'\n')
    protocol.flush()
    for line in sys.stdin:
        try:
            request=json.loads(line)
            if request.get('operation')=='shutdown':
                protocol.write('{"ok":true,"shutdown":true}\n');protocol.flush();return
            with redirect_stdout(sys.stderr):
                if request.get('operation')=='prepare':
                    operation_started=time.perf_counter()
                    prompt,hit,profile_prepare_seconds=_voice_prompt(model,request,prompts)
                    response={'ok':True,'prompt_cache_hit':hit,
                              'profile_prepare_seconds':profile_prepare_seconds,
                              'operation_seconds':time.perf_counter()-operation_started,
                              'worker_pid':os.getpid(),'model_load_count':1}
                else:
                    result=_synthesize(model,request,prompts)
                    result.update({'worker_pid':os.getpid(),'model_load_count':1,
                                   'model_load_seconds':model_load_seconds})
                    response={'ok':True,'result':result}
        except Exception as exc:
            response={'ok':False,'error_type':type(exc).__name__,
                      'error':str(exc).replace('\r',' ').replace('\n',' ')[:1200]}
        protocol.write(json.dumps(response,ensure_ascii=False)+'\n');protocol.flush()


if __name__=='__main__':
    try:sys.stdin.reconfigure(encoding='utf-8',errors='strict')
    except (AttributeError,OSError,ValueError):pass
    for stream in (sys.stdout,sys.stderr):
        try:stream.reconfigure(encoding='utf-8',errors='replace')
        except (AttributeError,OSError,ValueError):pass
    try:
        if len(sys.argv)==3 and sys.argv[1]=='--server':
            serve(sys.argv[2])
        elif len(sys.argv)==3:
            run(sys.argv[1],sys.argv[2])
        else:
            raise ValueError('Uso: python -m berofel.services.qwen3_tts_worker --server MODEL_DIR')
    except Exception as exc:
        print(f'Falha Qwen3-TTS local: {type(exc).__name__}: {exc}',file=sys.stderr,flush=True)
        raise SystemExit(1)
