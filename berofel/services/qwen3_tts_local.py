"""Optional local Qwen3-TTS voice-cloning backend in an isolated environment."""
from __future__ import annotations

import hashlib
import atexit
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time

from .ai_cache import cache_root, source_identity, digest, write_json
from .narration_service import (NarrationRequest, persistent_folder,
                                _process_flags, validate_clone_conditioning)

MODEL_ID='Qwen/Qwen3-TTS-12Hz-0.6B-Base'
MODEL_REVISION='main'
QWEN_TTS_VERSION='0.1.1'
LANGUAGES={'portuguese':'Portuguese','english':'English','spanish':'Spanish',
           'french':'French','italian':'Italian','german':'German'}
REQUIRED_MODEL_FILES=('config.json','model.safetensors','preprocessor_config.json',
    'tokenizer_config.json','vocab.json','merges.txt','speech_tokenizer/config.json',
    'speech_tokenizer/configuration.json','speech_tokenizer/model.safetensors',
    'speech_tokenizer/preprocessor_config.json')

_WORKER_LOCK=threading.RLock()
_WORKER_PROCESS=None
_WORKER_MODEL_KEY=''
_WORKER_LOAD_SECONDS=0.0


def runtime_root() -> Path:
    local=os.environ.get('LOCALAPPDATA')
    return (Path(local)/'BFS'/'qwen3_tts' if local else
            Path.home()/'.local'/'share'/'BerofelStudio'/'qwen3_tts')


def model_path() -> Path:
    override=os.environ.get('BEROFEL_QWEN3_TTS_MODEL')
    return Path(override).expanduser().resolve() if override else runtime_root()/'model'


def python_path() -> Path:
    override=os.environ.get('BEROFEL_QWEN3_TTS_PYTHON')
    return Path(override).expanduser().resolve() if override else runtime_root()/'venv'/'Scripts'/'python.exe'


def is_ready() -> bool:
    model=model_path()
    return python_path().is_file() and all((model/name).is_file()
                                           for name in REQUIRED_MODEL_FILES)


def _voice_fingerprint(path: Path) -> dict:
    info=source_identity(str(path))
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):
            h.update(chunk)
    info['sha256']=h.hexdigest()
    return info


def _model_fingerprint(folder: Path) -> dict:
    files=[]
    for name in REQUIRED_MODEL_FILES:
        path=folder/name
        try:
            stat=path.stat();files.append((name,stat.st_size,stat.st_mtime_ns))
        except OSError:files.append((name,None,None))
    return {'id':MODEL_ID,'revision':MODEL_REVISION,'files':files,
            'qwen_tts':QWEN_TTS_VERSION}


def _prompt_cache_file(reference: Path,reference_text: str,model: Path,
                       reference_window: tuple[float,float] | None=None) -> Path:
    model_id=digest(_model_fingerprint(model))
    text_hash=hashlib.sha256(reference_text.strip().encode('utf-8')).hexdigest()
    key_data={'schema':5,'model':model_id,
        'reference_sha256':_voice_fingerprint(reference)['sha256'],
        'reference_text_sha256':text_hash,
        'reference_window':reference_window,
        'x_vector_only_mode':not bool(reference_text.strip())}
    key=hashlib.sha256(json.dumps(key_data,sort_keys=True,separators=(',',':'))
                       .encode('utf-8')).hexdigest()
    cache_override=os.environ.get('BEROFEL_QWEN3_PROMPT_CACHE','')
    root=Path(cache_override).expanduser() if cache_override else runtime_root()/'cache'/'voice_prompts'
    return root/f'{key}.npz'


def stop_local_worker():
    """Stop the isolated warm model when the editor exits or a request cancels."""
    global _WORKER_PROCESS,_WORKER_MODEL_KEY,_WORKER_LOAD_SECONDS
    with _WORKER_LOCK:
        process=_WORKER_PROCESS
        _WORKER_PROCESS=None;_WORKER_MODEL_KEY='';_WORKER_LOAD_SECONDS=0.0
        if process is None:return
        try:
            if process.poll() is None:
                try:
                    process.stdin.write(json.dumps({'operation':'shutdown'})+'\n')
                    process.stdin.flush()
                except (OSError,ValueError,AttributeError):pass
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:process.terminate()
                except OSError:pass
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        except (OSError,subprocess.TimeoutExpired):
            try:process.kill()
            except OSError:pass
            try:process.wait(timeout=5)
            except (OSError,subprocess.TimeoutExpired):pass
        finally:
            # Popen keeps three pipe wrappers alive even after the child exits.
            # Close them explicitly so repeated editor sessions do not leak
            # Windows handles or emit ResourceWarning during shutdown.
            for name in ('stdin','stdout','stderr'):
                stream=getattr(process,name,None)
                if stream is not None:
                    try:stream.close()
                    except (OSError,ValueError):pass


atexit.register(stop_local_worker)


def _read_worker_line(process, timeout, control=None, stage=None):
    deadline=time.monotonic()+timeout
    while True:
        lines=queue.Queue(maxsize=1)
        def read():
            try:lines.put((True,process.stdout.readline()))
            except Exception as exc:lines.put((False,exc))
        threading.Thread(target=read,name='QwenWorkerReply',daemon=True).start()
        while True:
            if control and control.cancelled:
                stop_local_worker();control.checkpoint()
            remaining=deadline-time.monotonic()
            if remaining<=0:
                stop_local_worker()
                raise TimeoutError(f'Qwen3-TTS excedeu o limite local de {timeout}s.')
            try:ok,value=lines.get(timeout=min(.2,remaining))
            except queue.Empty:
                if process.poll() is not None:
                    stop_local_worker()
                    raise RuntimeError('O worker Qwen3 encerrou antes de responder.')
                continue
            if not ok:raise RuntimeError(f'Falha lendo resposta do worker Qwen3: {value}')
            if not value:
                stop_local_worker()
                raise RuntimeError('O worker Qwen3 fechou o canal de resposta.')
            try:response=json.loads(value)
            except ValueError as exc:
                stop_local_worker()
                raise RuntimeError('O worker Qwen3 retornou resposta inválida.') from exc
            break
        if isinstance(response,dict) and response.get('progress'):
            if stage:
                stage('Qwen3-TTS Base • ' + str(response['progress'])[:160])
            continue
        return response


def _ensure_worker(model: Path, control=None, stage=None):
    global _WORKER_PROCESS,_WORKER_MODEL_KEY,_WORKER_LOAD_SECONDS
    model_key=digest(_model_fingerprint(model))
    if (_WORKER_PROCESS is not None and _WORKER_PROCESS.poll() is None and
            _WORKER_MODEL_KEY==model_key):
        return _WORKER_PROCESS
    stop_local_worker()
    env=os.environ.copy()
    env.update({'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1',
                'HF_HUB_DISABLE_TELEMETRY':'1'})
    configured=str(Path(__file__).resolve().parents[2])
    python=str(python_path())
    command=[python,'-u','-m','berofel.services.qwen3_tts_worker','--server',str(model)]
    process=subprocess.Popen(command,cwd=configured,env=env,stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',
        errors='replace',bufsize=1,creationflags=_process_flags())
    _WORKER_PROCESS=process;_WORKER_MODEL_KEY=model_key
    response=_read_worker_line(process,timeout=900,control=control,stage=stage)
    if response.get('startup_error'):
        detail=str(response.get('error',''))
        for secret_path in (str(model), str(Path.home()),
                            os.environ.get('LOCALAPPDATA','')):
            if secret_path:
                detail=detail.replace(secret_path,'<dados locais>')
                detail=detail.replace(secret_path.replace('\\','/'),'<dados locais>')
        stop_local_worker()
        raise RuntimeError(f"Falha ao iniciar Qwen3-TTS ({response['startup_error']}): {detail[:1000]}")
    if not response.get('ready'):
        stop_local_worker()
        raise RuntimeError('O worker Qwen3 não confirmou o carregamento do modelo Base.')
    try:_WORKER_LOAD_SECONDS=max(0.0,float(response.get('model_load_seconds',0.0)))
    except (TypeError,ValueError):_WORKER_LOAD_SECONDS=0.0
    return process


def _runtime_request(request_data: dict,model: Path,control=None,stage=None) -> dict:
    global _WORKER_PROCESS
    timeout_value=os.environ.get('BEROFEL_QWEN3_REQUEST_TIMEOUT','1800')
    try:timeout=max(60,min(3600,int(timeout_value)))
    except ValueError:timeout=1800
    with _WORKER_LOCK:
        model_key=digest(_model_fingerprint(model))
        was_warm=(_WORKER_PROCESS is not None and _WORKER_PROCESS.poll() is None and
                  _WORKER_MODEL_KEY==model_key)
        process=_ensure_worker(model,control,stage)
        try:
            process.stdin.write(json.dumps(request_data,ensure_ascii=False)+'\n')
            process.stdin.flush()
        except (OSError,ValueError) as exc:
            stop_local_worker()
            raise RuntimeError('Não foi possível enviar a tarefa ao worker Qwen3 local.') from exc
        response=_read_worker_line(process,timeout=timeout,control=control,stage=stage)
        if not response.get('ok'):
            kind=str(response.get('error_type','RuntimeError'))
            detail=str(response.get('error','falha sem detalhe'))
            raise RuntimeError(f'Qwen3-TTS {kind}: {detail}')
        request_load_seconds=0.0 if was_warm else _WORKER_LOAD_SECONDS
        response['model_load_seconds']=request_load_seconds
        result=response.get('result')
        if isinstance(result,dict):
            result['worker_model_load_seconds']=float(result.pop('model_load_seconds',0.0))
            result['model_load_seconds']=request_load_seconds
        return response


def prepare_local_voice_prompt(reference: str,reference_text: str,*,
        progress=None,control=None,stage=None) -> dict:
    """Prepare/cache a profile; blank text uses Qwen's x-vector-only mode."""
    path=Path(reference)
    if not path.is_file():raise FileNotFoundError('A gravação de referência não foi encontrada.')
    text=str(reference_text or '').strip()
    if not is_ready():raise RuntimeError('O modelo Qwen3-TTS Base não está instalado. Use INSTALAR_QWEN3_TTS_LOCAL.bat.')
    model=model_path()
    from .audio_reference import _reference_window
    window_start,window_duration,_activity=_reference_window(path)
    if text:
        from .audio_reference import validate_reference_transcript
        validate_reference_transcript(text,window_duration)
    prompt_file=_prompt_cache_file(path,text,model,(window_start,window_duration))
    data={'operation':'prepare','consent':True,'reference':str(path.resolve()),
        'reference_text':text,'language':'Portuguese','model_path':str(model),
        'reference_window_start':window_start,'reference_window_duration':window_duration,
        'model_fingerprint':digest(_model_fingerprint(model)),
        'prompt_cache_path':str(prompt_file),
        'output':str(prompt_file.with_suffix('.wav'))}
    if stage:stage('Qwen3-TTS Base • preparando perfil de referência')
    if progress:progress(0,1)
    response=_runtime_request(data,model,control,stage)
    if progress:progress(1,1)
    return {'prepared':True,'prompt_cache_hit':bool(response.get('prompt_cache_hit')),
            'worker_pid':response.get('worker_pid'),
            'model_load_count':response.get('model_load_count'),
            'model_load_seconds':float(response.get('model_load_seconds',0.0)),
            'profile_prepare_seconds':float(response.get('profile_prepare_seconds',0.0)),
            'operation_seconds':float(response.get('operation_seconds',0.0))}


def _prune_cache(folder: Path,keep: Path,max_mb: int=2048):
    """Only remove app-owned cache entries with a complete metadata marker."""
    if not folder.is_dir() or folder.is_symlink():return
    items=[];total=0
    for marker in folder.rglob('result.json'):
        entry=marker.parent
        if entry.is_symlink() or not entry.is_dir() or len(entry.name)!=32:continue
        try:metadata=json.loads((entry/'result.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):continue
        if metadata.get('engine')!='qwen3-tts-local' or metadata.get('key')!=entry.name:continue
        size=sum(file.stat().st_size for file in entry.iterdir()
                 if file.is_file() and not file.is_symlink())
        total+=size
        items.append((entry.stat().st_mtime_ns,entry,size))
    protected=keep.resolve()
    for _mtime,entry,size in sorted(items):
        if total<=max_mb*1024*1024:break
        try:
            if entry.resolve()==protected:continue
            shutil.rmtree(entry);total-=size
        except OSError:continue


def generate_local_clone(request: NarrationRequest, progress=None, runner=None,
                         control=None, stage=None) -> dict:
    """Run voice cloning on CPU in the optional, isolated Qwen3-TTS environment."""
    validate_clone_conditioning(request)
    if not request.text.strip():raise ValueError('Digite um texto para narrar.')
    if not request.consent:
        raise PermissionError('Confirme autorização expressa para clonar a gravação selecionada.')
    reference=Path(request.voice)
    if not reference.is_file():raise FileNotFoundError(f'Amostra da voz não encontrada: {reference}')
    if reference.suffix.lower() not in {'.wav','.mp3','.flac','.ogg','.m4a'}:
        raise ValueError('O motor Qwen3 local aceita amostras de áudio; escolha WAV, MP3, FLAC, OGG ou M4A.')
    if request.language not in LANGUAGES:
        raise ValueError('O Qwen3-TTS local não oferece este idioma neste perfil.')
    if not is_ready():
        raise RuntimeError('O motor local de clonagem ainda não foi instalado. Use INSTALAR_QWEN3_TTS_LOCAL.bat; são baixados aproximadamente 2,5 GB de modelo público. Nenhum download ocorre ao gerar a narração.')
    if control:control.checkpoint()
    if stage:stage('Qwen3-TTS local • preparando a amostra')
    if progress:progress(0,3)
    model=model_path()
    from .audio_reference import REFERENCE_PREPARATION_VERSION,_reference_window
    window_start,window_duration,_activity=_reference_window(reference)
    if request.reference_text.strip():
        from .audio_reference import validate_reference_transcript
        validate_reference_transcript(request.reference_text,window_duration)
    key=digest({'engine':'qwen3-tts-local','reference_preparation':REFERENCE_PREPARATION_VERSION,
        'reference_window':(window_start,window_duration),
        'voice':_voice_fingerprint(reference),
        'model':_model_fingerprint(model),'text':request.text.strip(),
        'language':LANGUAGES[request.language],
        'reference_text':request.reference_text.strip(),
        'consent':bool(request.consent)})
    root=cache_root().parent/'qwen3_tts'
    directory=root/key[:2]/key
    directory.mkdir(parents=True,exist_ok=True)
    wav=directory/'audio.wav';metadata=directory/'result.json';cache_hit=False
    if wav.is_file() and wav.stat().st_size>44 and metadata.is_file():
        try:
            data=json.loads(metadata.read_text(encoding='utf-8'))
            cache_hit=data.get('key')==key and data.get('duration',0)>0
        except (OSError,ValueError):pass
    if not cache_hit:
        if control:control.checkpoint()
        if _WORKER_PROCESS is None or _WORKER_PROCESS.poll() is not None:
            if stage:stage('Qwen3-TTS Base • carregando modelo CPU nesta sessão')
        elif stage:
            stage('Qwen3-TTS Base • usando modelo carregado e perfil local')
        job=directory/'request.json';result_file=directory/'worker_result.json'
        prompt_file=_prompt_cache_file(reference,request.reference_text,model,
                                       (window_start,window_duration))
        prompt_file.parent.mkdir(parents=True,exist_ok=True)
        job.unlink(missing_ok=True);result_file.unlink(missing_ok=True)
        write_json(job,{'text':request.text.strip(),'reference':str(reference),
            'reference_text':request.reference_text.strip(),
            'reference_window_start':window_start,
            'reference_window_duration':window_duration,
            'language':LANGUAGES[request.language],'model_path':str(model),
            'model_fingerprint':digest(_model_fingerprint(model)),
            'prompt_cache_path':str(prompt_file),
            'output':str(wav),'consent':True})
        try:
            if runner is not None:runner(job,result_file)
            else:
                response=_runtime_request(json.loads(job.read_text(encoding='utf-8')),
                                          model,control,stage)
                write_json(result_file,response['result'])
            if not wav.is_file() or wav.stat().st_size<=44 or not result_file.is_file():
                raise RuntimeError('Qwen3-TTS local não entregou um WAV válido.')
            result=json.loads(result_file.read_text(encoding='utf-8'))
            duration=float(result['duration'])
            if not .01<duration<24*3600:raise RuntimeError('Duração de voz Qwen inválida.')
            if request.language=='portuguese' and request.reference_text.strip():
                if (result.get('conditioning_verified') is not True or
                        result.get('conditioning_mode')!='audio+transcript' or
                        result.get('icl_mode') is not True or
                        result.get('x_vector_only_mode') is not False):
                    wav.unlink(missing_ok=True)
                    raise RuntimeError(
                        'O Qwen não confirmou clonagem PT-BR com áudio e transcrição '
                        'da referência. A geração foi descartada; nenhuma voz padrão '
                        'será usada como substituta.')
            prompt_cache_hit=bool(result.get('prompt_cache_hit'))
            write_json(metadata,{'key':key,'duration':duration,
                'engine':'qwen3-tts-local','prompt_cache_hit':prompt_cache_hit,
                'reference_window':result.get('reference_window'),
                'conditioning_mode':result.get('conditioning_mode'),
                'conditioning_verified':result.get('conditioning_verified',False),
                'icl_mode':result.get('icl_mode',False),
                'x_vector_only_mode':result.get('x_vector_only_mode',True),
                'reference_audio_code_count':result.get('reference_audio_code_count',0),
                'speaker_embedding_dimensions':result.get('speaker_embedding_dimensions',[]),
                'reference_sha256_prefix':result.get('reference_sha256_prefix'),
                'reference_text_word_count':result.get('reference_text_word_count'),
                'worker_pid':result.get('worker_pid'),
                'model_load_count':result.get('model_load_count'),
                'model_load_seconds':result.get('model_load_seconds',0.0),
                'worker_model_load_seconds':result.get('worker_model_load_seconds',0.0),
                'profile_prepare_seconds':result.get('profile_prepare_seconds',0.0),
                'generation_seconds':result.get('generation_seconds',0.0)})
        finally:
            job.unlink(missing_ok=True);result_file.unlink(missing_ok=True)
    else:
        duration=float(data['duration'])
        if request.language=='portuguese' and request.reference_text.strip() and (
                data.get('conditioning_verified') is not True or
                data.get('conditioning_mode')!='audio+transcript'):
            wav.unlink(missing_ok=True);metadata.unlink(missing_ok=True)
            raise RuntimeError(
                'O cache encontrado não comprova clonagem PT-BR com a referência. '
                'Ele foi invalidado para impedir reprodução de uma voz substituta.')
        prompt_cache_hit=bool(data.get('prompt_cache_hit'))
        result=data
        os.utime(metadata,None)
        if stage:stage('Qwen3-TTS local • áudio recuperado do cache')
    if control:control.checkpoint()
    if progress:progress(2,3)
    dest=persistent_folder(request.project_path);dest.mkdir(parents=True,exist_ok=True)
    safe=''.join(c if c.isalnum() or c in '-_' else '_' for c in request.title.strip())[:48] or 'Narracao'
    output=dest/f'{safe}_{time.strftime("%Y%m%d_%H%M%S")}_{key[:8]}.wav';counter=1
    while output.exists():
        output=dest/f'{safe}_{time.strftime("%Y%m%d_%H%M%S")}_{key[:8]}_{counter}.wav';counter+=1
    shutil.copy2(wav,output)
    if control and control.cancelled:
        output.unlink(missing_ok=True);control.checkpoint()
    try:_prune_cache(root,directory)
    except OSError:pass
    if progress:progress(3,3)
    return {'path':str(output),'duration':duration,'cache_hit':cache_hit,
        'prompt_cache_hit':prompt_cache_hit,
        'reference_window':data.get('reference_window') if cache_hit else result.get('reference_window'),
        'conditioning_mode':data.get('conditioning_mode') if cache_hit else result.get('conditioning_mode'),
        'conditioning_verified':data.get('conditioning_verified',False) if cache_hit else result.get('conditioning_verified',False),
        'reference_sha256_prefix':data.get('reference_sha256_prefix') if cache_hit else result.get('reference_sha256_prefix'),
        'reference_text_word_count':data.get('reference_text_word_count') if cache_hit else result.get('reference_text_word_count'),
        'worker_pid':(data.get('worker_pid') if cache_hit else result.get('worker_pid')),
        'model_load_count':(data.get('model_load_count') if cache_hit else result.get('model_load_count')),
        'model_load_seconds':float(data.get('model_load_seconds',0.0) if cache_hit else result.get('model_load_seconds',0.0)),
        'worker_model_load_seconds':float(data.get('worker_model_load_seconds',0.0) if cache_hit else result.get('worker_model_load_seconds',0.0)),
        'profile_prepare_seconds':float(data.get('profile_prepare_seconds',0.0) if cache_hit else result.get('profile_prepare_seconds',0.0)),
        'generation_seconds':float(data.get('generation_seconds',0.0) if cache_hit else result.get('generation_seconds',0.0)),
        'voice':request.voice,'language':request.language,'title':request.title,
        'engine':'qwen3-tts-local'}
