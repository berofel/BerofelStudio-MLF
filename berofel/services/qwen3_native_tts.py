"""Experimental Windows CPU adapter for a locally installed Qwen3-TTS.cpp build.

This backend is opt-in. The official Python/PyTorch Base backend remains the
default and fallback. It uses the same 0.6B Base speaker x-vector, cached by the
official worker, then synthesizes with a persistent native Q4_0 server.
"""
from __future__ import annotations

import atexit
import hashlib
import json
import os
from pathlib import Path
import queue
import shutil
import struct
import subprocess
import threading
import tempfile
import time
import wave
import uuid
from collections.abc import Mapping, Sequence

import numpy as np

from .ai_cache import cache_root, digest, write_json
from .narration_service import (LANGUAGES, NarrationRequest, persistent_folder,
                                _process_flags, validate_request)

ENGINE_ID='qwen3-tts-native-q4'
BALANCED_ENGINE_ID='qwen3-tts-native-q4-balanced'
ENGINE_IDS=(ENGINE_ID,BALANCED_ENGINE_ID)
_LANGUAGES={'portuguese':'portuguese','english':'english','spanish':'spanish',
            'french':'french','italian':'italian','german':'german'}
def _stream_chunk_frames()->int:
    try:return max(1,min(12,int(os.environ.get('BEROFEL_QWEN3_NATIVE_STREAM_CHUNK_FRAMES','6'))))
    except (TypeError,ValueError):return 6

def _thread_count(variable:str,default:int,legacy:str='') -> int:
    try:
        value=os.environ.get(variable)
        if value is None and legacy:value=os.environ.get('BEROFEL_QWEN3_NATIVE_THREADS')
        return max(1,min(8,int(value if value is not None else default)))
    except (TypeError, ValueError):
        return default


def threads_for_engine(engine:str)->int:
    if engine==BALANCED_ENGINE_ID:
        return _thread_count('BEROFEL_QWEN3_NATIVE_BALANCED_THREADS',8)
    return _thread_count('BEROFEL_QWEN3_NATIVE_TURBO_THREADS',6,'legacy')
_LOCK=threading.RLock()
_PROCESS=None
_PROCESS_KEY=''
_MODEL_LOAD_SECONDS=0.0


def runtime_root() -> Path:
    override=os.environ.get('BEROFEL_QWEN3_NATIVE_HOME','').strip()
    if override:return Path(override).expanduser().resolve()
    local=os.environ.get('LOCALAPPDATA')
    base=Path(local) if local else Path.home()/'.local'/'share'
    return base/'BFS'/'qwen3_tts'/'native_turbo'


def _layout() -> tuple[Path,Path,Path]:
    root=runtime_root()
    exe=Path(os.environ.get('BEROFEL_QWEN3_NATIVE_EXE','') or root/'bin'/'qwen3-tts-cli.exe')
    model=Path(os.environ.get('BEROFEL_QWEN3_NATIVE_MODEL','') or root/'models'/'qwen3-tts-0.6b-q4_0.gguf')
    tokenizer=Path(os.environ.get('BEROFEL_QWEN3_NATIVE_TOKENIZER','') or root/'models'/'qwen3-tts-tokenizer-f16-f32.gguf')
    if not model.is_file() and not os.environ.get('BEROFEL_QWEN3_NATIVE_MODEL'):
        model=root/'models'/'qwen3-tts-0.6b-q4_0-exp.gguf'
    return exe.expanduser().resolve(),model.expanduser().resolve(),tokenizer.expanduser().resolve()


def is_ready() -> bool:
    exe,model,tokenizer=_layout()
    return exe.is_file() and model.is_file() and tokenizer.is_file()


def _fingerprint(exe: Path,model: Path,tokenizer: Path) -> str:
    def identity(path: Path):
        stat=path.stat()
        return {'name':path.name,'size':stat.st_size,'mtime_ns':stat.st_mtime_ns}
    return digest({'engine':'qwen3-tts-native-q4','exe':identity(exe),
                   'model':identity(model),'tokenizer':identity(tokenizer)})


def _stop_locked():
    global _PROCESS,_PROCESS_KEY,_MODEL_LOAD_SECONDS
    process=_PROCESS
    _PROCESS=None;_PROCESS_KEY='';_MODEL_LOAD_SECONDS=0.0
    if process is None:return
    try:
        if process.poll() is None:
            # The upstream JSON-line server does not define a shutdown
            # operation. EOF is its graceful idle exit; avoid waiting for an
            # unrecognized JSON request to time out on every profile switch.
            try:process.stdin.close()
            except (OSError,ValueError,AttributeError):pass
            try:process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    try:process.wait(timeout=2)
                    except subprocess.TimeoutExpired:pass
    except OSError:
        try:process.kill()
        except OSError:pass
    finally:
        for stream in (process.stdin,process.stdout,process.stderr):
            if stream is not None:
                try:stream.close()
                except OSError:pass


def stop_native_worker():
    with _LOCK:_stop_locked()


atexit.register(stop_native_worker)


def _start_server(exe: Path,model: Path,tokenizer: Path,control=None,threads:int=6):
    global _PROCESS,_PROCESS_KEY,_MODEL_LOAD_SECONDS
    key=digest({'model':_fingerprint(exe,model,tokenizer),'threads':threads})
    if _PROCESS is not None and _PROCESS.poll() is None and _PROCESS_KEY==key:
        return _PROCESS,0.0
    _stop_locked()
    env=os.environ.copy()
    env['PATH']=str(exe.parent)+os.pathsep+env.get('PATH','')
    env['OMP_NUM_THREADS']=str(threads)
    command=[str(exe),'-m',str(model),'--tokenizer',str(tokenizer),
             '-j',str(threads),'--server']
    started=time.perf_counter()
    process=subprocess.Popen(command,cwd=str(exe.parent),env=env,stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',
        errors='replace',bufsize=1,creationflags=_process_flags())
    stderr_lines=queue.Queue()
    def drain_stderr():
        try:
            for line in process.stderr:stderr_lines.put(line.rstrip())
        except (OSError,ValueError):pass
    threading.Thread(target=drain_stderr,name='QwenNativeStderr',daemon=True).start()
    deadline=time.monotonic()+900
    while time.monotonic()<deadline:
        if control and control.cancelled:
            process.kill();process.wait(timeout=5)
            if control:control.checkpoint()
        if process.poll() is not None:
            tail=[]
            while not stderr_lines.empty():tail.append(stderr_lines.get_nowait())
            raise RuntimeError('Backend nativo Qwen3 não iniciou: '+(' | '.join(tail[-5:]) or 'processo encerrou sem diagnóstico.'))
        try:line=stderr_lines.get(timeout=.2)
        except queue.Empty:continue
        if 'Server mode: ready.' in line:
            _PROCESS=process;_PROCESS_KEY=key
            _MODEL_LOAD_SECONDS=time.perf_counter()-started
            return process,_MODEL_LOAD_SECONDS
    process.kill();process.wait(timeout=5)
    raise TimeoutError('O modelo Qwen3 Turbo não ficou pronto em 15 minutos.')


def _read_reply(process,timeout: float,control=None,stream_file=None,
                audio_chunk=None,stream_stats=None,stream_started=None):
    replies=queue.Queue(maxsize=1)
    def read_line():
        try:replies.put((True,process.stdout.readline()))
        except Exception as exc:replies.put((False,exc))
    threading.Thread(target=read_line,name='QwenNativeReply',daemon=True).start()
    deadline=time.monotonic()+timeout
    stream_offset=0
    while time.monotonic()<deadline:
        if stream_file is not None and audio_chunk is not None:
            stream_offset=_emit_stream_delta(stream_file,stream_offset,audio_chunk,
                stream_stats,stream_started)
        if control and control.cancelled:
            _stop_locked()
            control.checkpoint()
        if process.poll() is not None:
            _stop_locked();raise RuntimeError('Servidor Qwen3 Turbo encerrou durante a narração.')
        try:ok,value=replies.get(timeout=min(.05,max(.01,deadline-time.monotonic())))
        except queue.Empty:continue
        if not ok:raise RuntimeError(f'Falha lendo resposta do Qwen3 Turbo: {value}')
        if not value:
            _stop_locked();raise RuntimeError('Servidor Qwen3 Turbo fechou o canal de resposta.')
        try:
            response=json.loads(value)
            if stream_file is not None and audio_chunk is not None:
                _emit_stream_delta(stream_file,stream_offset,audio_chunk,
                    stream_stats,stream_started)
            return response
        except ValueError as exc:
            _stop_locked();raise RuntimeError('Servidor Qwen3 Turbo retornou JSON inválido.') from exc
    _stop_locked()
    raise TimeoutError(f'Qwen3 Turbo excedeu o limite local de {timeout:.0f}s.')


def _native_embedding(reference: Path,reference_text: str,model: Path,control=None,
                      stage=None,threads:int=6):
    """Prepare one native x-vector per authorized recording and model build.

    Native and Python prompt embeddings are not interchangeable for every
    tested precision, so this cache is generated by the exact Turbo encoder.
    """
    exe,_,tokenizer=_layout()
    destination=_native_embedding_cache_path(reference,model,exe,tokenizer)
    embeddings=destination.parent

    if _valid_native_embedding(destination):return destination,True,0.0
    # The encoder CLI loads the same weights. Release a resident synthesis
    # worker before extracting an uncached profile to avoid overlapping copies.
    with _LOCK:
        if _PROCESS is not None and _PROCESS.poll() is None:
            _stop_locked()
    if destination.exists():destination.unlink(missing_ok=True)
    embeddings.mkdir(parents=True,exist_ok=True)
    if stage:stage('Qwen Turbo • preparando cache vocal nativo (uma vez por perfil)')
    started=time.perf_counter()
    from .audio_reference import prepare_audio_prompt
    env=os.environ.copy()
    env['PATH']=str(exe.parent)+os.pathsep+env.get('PATH','')
    try:timeout=max(30,min(900,float(os.environ.get('BEROFEL_QWEN3_NATIVE_PROFILE_TIMEOUT','300'))))
    except ValueError:timeout=300.0
    pending=destination.with_suffix('.bin.part')
    try:
        with tempfile.TemporaryDirectory(prefix='bfs_qwen_native_profile_') as folder:
            normalized=Path(folder)/'reference.wav'
            prepare_audio_prompt(str(reference),normalized)
            if control:control.checkpoint()
            result=subprocess.run([str(exe),'-m',str(model),'--tokenizer',str(tokenizer),
                '-r',str(normalized),'--embedding-out',str(pending),'-j',str(threads)],
                cwd=str(exe.parent),env=env,capture_output=True,text=True,
                encoding='utf-8',errors='replace',timeout=timeout,
                creationflags=_process_flags())
            if result.returncode or not _valid_native_embedding(pending):
                detail=(result.stderr or result.stdout or '').replace(str(normalized),'[áudio local]')
                raise RuntimeError('Não foi possível preparar o perfil vocal no Qwen Turbo: '+
                    (detail[-700:].strip() or 'o vetor nativo retornou inválido.'))
        if control:control.checkpoint()
        os.replace(pending,destination)
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f'A preparação nativa da referência excedeu {timeout:.0f}s.') from exc
    finally:pending.unlink(missing_ok=True)
    return destination,False,time.perf_counter()-started


def _native_embedding_cache_path(reference: Path,model: Path,exe: Path | None = None,
                                 tokenizer: Path | None = None) -> Path:
    if exe is None or tokenizer is None:
        exe,_,tokenizer=_layout()
    source_hash=hashlib.sha256()
    with reference.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):
            source_hash.update(chunk)
    identity=digest({'voice_sha256':source_hash.hexdigest(),
        'native_model':_fingerprint(exe,model,tokenizer),
        'format':'qwen3-tts.cpp-xvector-v1'})
    return runtime_root()/'cache'/'speaker_embeddings'/f'{identity}.bin'



def _valid_native_embedding(path: Path) -> bool:
    try:
        if path.stat().st_size!=4100:return False
        with path.open('rb') as stream:
            count=struct.unpack('<I',stream.read(4))[0]
            vector=np.frombuffer(stream.read(),dtype='<f4')
        return count==1024 and vector.size==1024 and bool(np.isfinite(vector).all())
    except (OSError,ValueError,struct.error):return False


def prepare_native_voice_profiles(profiles: Sequence[Mapping], *,
        engine: str = ENGINE_ID, control=None, progress=None, stage=None) -> dict:
    """Prepare all unique voice embeddings before warming one resident worker.

    Preparing missing embeddings starts the encoder CLI, which loads weights
    independently. If any cache is missing, stop a resident synthesis worker
    first, prepare embeddings serially, then load the server once for the batch.
    This avoids overlapping model copies during multi-character preparation.
    """
    if engine not in ENGINE_IDS:
        raise ValueError('Perfil Native Qwen3 desconhecido.')
    if not is_ready():
        raise RuntimeError('O backend nativo Qwen3 não está instalado localmente.')
    exe, model, tokenizer = _layout()
    threads = threads_for_engine(engine)
    unique: dict[Path, tuple[Path, str]] = {}
    for profile in profiles:
        reference = Path(str(profile.get('sample_path', ''))).expanduser().resolve()
        if not reference.is_file():
            raise FileNotFoundError('A gravação de um perfil vocal do roteiro não foi encontrada.')
        cache_file = _native_embedding_cache_path(reference, model, exe, tokenizer)
        unique.setdefault(cache_file, (reference, str(profile.get('reference_text', '') or '')))
    if not unique:
        raise ValueError('Selecione ao menos um perfil vocal para preparar.')
    prepare_started = time.perf_counter()
    cache_hits = 0
    with _LOCK:
        missing = any(not _valid_native_embedding(cache_file) for cache_file in unique)
        if missing and _PROCESS is not None and _PROCESS.poll() is None:
            _stop_locked()
        for index, (reference, reference_text) in enumerate(unique.values(), 1):
            if control:
                control.checkpoint()
            if stage:
                stage(f'Preparando embedding vocal nativo {index}/{len(unique)}')
            _embedding, cache_hit, _seconds = _native_embedding(
                reference, reference_text.strip(), model, control, stage, threads)
            cache_hits += int(cache_hit)
            if progress:
                progress(index, len(unique) + 1)
        if control:
            control.checkpoint()
        if stage:
            stage('Carregando Qwen Turbo Q4 para manter uma instância durante os lotes')
        _process, model_load_seconds = _start_server(
            exe, model, tokenizer, control, threads)
    if progress:
        progress(len(unique) + 1, len(unique) + 1)
    return {
        'prepared': True,
        'profile_count': len(unique),
        'embedding_cache_hits': cache_hits,
        'profile_prepare_seconds': max(0.0, time.perf_counter() - prepare_started - model_load_seconds),
        'model_load_seconds': float(model_load_seconds),
        'engine': engine,
        'threads': threads,
    }


def prepare_native_voice_profile(reference: str, reference_text: str = '', *,
        engine: str = ENGINE_ID, control=None, progress=None, stage=None) -> dict:
    """Prepare one native x-vector and leave its selected worker resident.

    ``reference_text`` is accepted for a common UI contract; native Q4 is
    x-vector conditioned and does not use that text in its speaker embedding.
    """
    result = prepare_native_voice_profiles(
        [{'sample_path': reference, 'reference_text': reference_text}],
        engine=engine, control=control, progress=progress, stage=stage)
    return {
        'prepared': bool(result['prepared']),
        'embedding_cache_hit': result['embedding_cache_hits'] == 1,
        'profile_prepare_seconds': result['profile_prepare_seconds'],
        'model_load_seconds': result['model_load_seconds'],
        'engine': result['engine'],
        'threads': result['threads'],
    }

def _wav_info(path: Path) -> tuple[float,int,int]:
    with wave.open(str(path),'rb') as stream:
        channels=stream.getnchannels();rate=stream.getframerate();frames=stream.getnframes()
        width=stream.getsampwidth()
        if channels not in (1,2) or rate<8000 or frames<=0 or width not in (2,3,4):
            raise ValueError('O backend Turbo produziu WAV com formato inválido.')
        raw=stream.readframes(frames)
    if len(raw)<frames*channels*width:
        raise ValueError('O WAV do backend Turbo foi gravado incompleto.')
    sample_peak=max((abs(value) for (value,) in __import__('struct').iter_unpack('<h',raw[:len(raw)//2*2])),default=0) if width==2 else 1
    if sample_peak==0:raise ValueError('O backend Turbo produziu áudio silencioso.')
    return frames/rate,rate,frames


def _emit_stream_delta(path:Path,offset:int,callback,stats=None,started=None)->int:
    """Forward complete float32 PCM appended by the native decoder."""
    try:
        ready=path.stat().st_size
        ready-=ready%4
        if ready<=offset:return offset
        with path.open('rb') as stream:
            stream.seek(offset);data=stream.read(ready-offset)
        data=data[:len(data)-(len(data)%4)]
        if not data:return offset
        if stats is not None:
            stats['bytes']=stats.get('bytes',0)+len(data)
            stats['chunks']=stats.get('chunks',0)+1
            if stats.get('first_chunk_seconds') is None and started is not None:
                stats['first_chunk_seconds']=time.perf_counter()-started
        try:callback(data)
        except Exception:
            # Preview output is best effort; it must not fail synthesis.
            if stats is not None:stats['callback_failed']=True
        return offset+len(data)
    except (OSError,ValueError):
        return offset


def generate_native_clone(request: NarrationRequest,progress=None,runner=None,
        control=None,stage=None,audio_chunk=None) -> dict:
    """Generate with the selected cached Base x-vector/Q4 native execution profile."""
    validate_request(request.text,request.voice,request.language,request.consent)
    if request.engine not in ENGINE_IDS:
        raise ValueError('Perfil de execução Qwen Turbo desconhecido.')
    threads=threads_for_engine(request.engine)
    if not is_ready():
        raise RuntimeError('O runtime experimental Qwen Turbo não está instalado. O modo original continua disponível.')
    exe,model,tokenizer=_layout();reference=Path(request.voice).expanduser().resolve()
    if control:control.checkpoint()
    if progress:progress(0,3)
    # Serialize profile cache creation with inference: the CLI encoder loads
    # the same model files and concurrent requests must not duplicate work.
    with _LOCK:
        embedding,embedding_hit,embedding_seconds=_native_embedding(reference,
            request.reference_text.strip(),model,control,stage,threads)
    if stage:stage('Qwen Turbo Q4 • usando modelo nativo já carregado')
    voice_hash=hashlib.sha256(reference.read_bytes()).hexdigest()
    key=digest({'engine':request.engine,'voice_sha256':voice_hash,'text':request.text.strip(),
        'language':request.language,'model':_fingerprint(exe,model,tokenizer),
        'threads':threads,
        'embedding':embedding.name})
    root=cache_root().parent/'qwen3_native_tts';directory=root/key[:2]/key
    directory.mkdir(parents=True,exist_ok=True)
    output=directory/'audio.wav';metadata=directory/'result.json';cache_hit=False
    if output.is_file() and metadata.is_file():
        try:
            info=json.loads(metadata.read_text(encoding='utf-8'))
            cache_hit=info.get('key')==key and _wav_info(output)[0]>0
        except (OSError,ValueError,wave.Error):cache_hit=False
    result={}
    stream_stats={'bytes':0,'chunks':0,'first_chunk_seconds':None}
    if not cache_hit:
        if control:control.checkpoint()
        temporary=directory/'audio.pending.wav';temporary.unlink(missing_ok=True)
        stream_file=directory/f'audio_{uuid.uuid4().hex}.stream.f32' if audio_chunk else None
        with _LOCK:
            process,model_load_seconds=_start_server(exe,model,tokenizer,control,threads)
            payload={'text':request.text.strip(),'output':str(temporary),
                'language':_LANGUAGES[request.language],'max_tokens':2048,
                'embedding_in':str(embedding)}
            if stream_file is not None:
                stream_file.unlink(missing_ok=True)
                payload.update({'stream_file':str(stream_file),
                                'chunk_frames':_stream_chunk_frames()})
            started=time.perf_counter()
            try:
                process.stdin.write(json.dumps(payload,ensure_ascii=False)+'\n')
                process.stdin.flush()
                result=_read_reply(process,timeout=float(os.environ.get(
                    'BEROFEL_QWEN3_NATIVE_TIMEOUT','1800')),control=control,
                    stream_file=stream_file,audio_chunk=audio_chunk,
                    stream_stats=stream_stats,stream_started=started)
                generation_seconds=time.perf_counter()-started
            finally:
                if stream_file is not None:stream_file.unlink(missing_ok=True)
        if not result.get('success') or not temporary.is_file():
            temporary.unlink(missing_ok=True)
            raise RuntimeError('Qwen3 Turbo não concluiu a geração do áudio.')
        duration,rate,frames=_wav_info(temporary)
        os.replace(temporary,output)
        result={'key':key,'duration':duration,'sample_rate':rate,'frames':frames,
            'engine':request.engine,'threads':threads,
            'model_load_seconds':model_load_seconds,
            'generation_seconds':generation_seconds,
            'engine_reported_ms':result.get('t_total_ms'),
            'profile_embedding_cache_hit':embedding_hit,
            'profile_embedding_prepare_seconds':embedding_seconds}
        write_json(metadata,result)
    else:
        result=info
        try:os.utime(metadata,None)
        except OSError:pass
    if control:control.checkpoint()
    if progress:progress(2,3)
    destination=persistent_folder(request.project_path);destination.mkdir(parents=True,exist_ok=True)
    title=''.join(ch if ch.isalnum() or ch in '-_' else '_' for ch in request.title.strip())[:48] or 'Narracao'
    target=destination/f'{title}_{time.strftime("%Y%m%d_%H%M%S")}_{key[:8]}.wav';suffix=1
    while target.exists():
        target=destination/f'{title}_{time.strftime("%Y%m%d_%H%M%S")}_{key[:8]}_{suffix}.wav';suffix+=1
    shutil.copy2(output,target)
    if control and control.cancelled:
        target.unlink(missing_ok=True);control.checkpoint()
    if progress:progress(3,3)
    return {'path':str(target),'duration':float(result['duration']),
        'cache_hit':cache_hit,'prompt_cache_hit':embedding_hit,
        'profile_prepare_seconds':float(result.get('profile_embedding_prepare_seconds',embedding_seconds)),
        'model_load_seconds':float(result.get('model_load_seconds',0.0)),
        'generation_seconds':float(result.get('generation_seconds',0.0)),
        'first_audio_chunk_seconds':stream_stats['first_chunk_seconds'] if not cache_hit else None,
        'first_audio_request_seconds':(
            float(result.get('profile_embedding_prepare_seconds',embedding_seconds))+
            float(result.get('model_load_seconds',0.0))+
            float(stream_stats['first_chunk_seconds'] or 0.0)
            if not cache_hit and stream_stats['first_chunk_seconds'] is not None else None),
        'streamed_pcm_bytes':stream_stats['bytes'] if not cache_hit else 0,
        'streamed_chunk_count':stream_stats['chunks'] if not cache_hit else 0,
        'voice':request.voice,'language':request.language,'title':request.title,
        'engine':request.engine,'threads':threads,
        'execution_profile':'Turbo' if request.engine==ENGINE_ID else 'Equilibrado',
        'precision':'Q4_0 mixed; sensitive tensors retained in F16'}
