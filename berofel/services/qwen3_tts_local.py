"""Optional local Qwen3-TTS voice-cloning backend in an isolated environment."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from .ai_cache import cache_root, source_identity, digest, write_json
from .pocket_tts_service import NarrationRequest, persistent_folder, _process_flags

MODEL_ID='Qwen/Qwen3-TTS-12Hz-0.6B-Base'
MODEL_REVISION='main'
QWEN_TTS_VERSION='0.1.1'
LANGUAGES={'portuguese':'Portuguese','english':'English','spanish':'Spanish',
           'french':'French','italian':'Italian','german':'German'}
REQUIRED_MODEL_FILES=('config.json','model.safetensors','preprocessor_config.json',
    'tokenizer_config.json','vocab.json','merges.txt','speech_tokenizer/config.json',
    'speech_tokenizer/configuration.json','speech_tokenizer/model.safetensors',
    'speech_tokenizer/preprocessor_config.json')


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
    key=digest({'engine':'qwen3-tts-local','voice':_voice_fingerprint(reference),
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
        if stage:stage('Qwen3-TTS local • clonando e gerando no CPU')
        job=directory/'request.json';result_file=directory/'worker_result.json'
        job.unlink(missing_ok=True);result_file.unlink(missing_ok=True)
        write_json(job,{'text':request.text.strip(),'reference':str(reference),
            'reference_text':request.reference_text.strip(),
            'language':LANGUAGES[request.language],'model_path':str(model),
            'output':str(wav),'consent':True})
        try:
            if runner is not None:runner(job,result_file)
            else:
                env=os.environ.copy()
                cmd=[str(python_path()),'-m','berofel.services.qwen3_tts_worker',
                     str(job),str(result_file)]
                if control:
                    proc=control.run(cmd,cwd=str(Path(__file__).resolve().parents[2]),
                        env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,
                        encoding='utf-8',errors='replace',timeout=3600,
                        creationflags=_process_flags())
                else:
                    proc=subprocess.run(cmd,cwd=str(Path(__file__).resolve().parents[2]),
                        env=env,capture_output=True,text=True,encoding='utf-8',
                        errors='replace',timeout=3600,creationflags=_process_flags())
                if proc.returncode!=0:
                    raise RuntimeError('Qwen3-TTS local: '+(proc.stderr or proc.stdout)[-1800:])
            if not wav.is_file() or wav.stat().st_size<=44 or not result_file.is_file():
                raise RuntimeError('Qwen3-TTS local não entregou um WAV válido.')
            result=json.loads(result_file.read_text(encoding='utf-8'))
            duration=float(result['duration'])
            if not .01<duration<24*3600:raise RuntimeError('Duração de voz Qwen inválida.')
            write_json(metadata,{'key':key,'duration':duration,'engine':'qwen3-tts-local'})
        finally:
            job.unlink(missing_ok=True);result_file.unlink(missing_ok=True)
    else:
        duration=float(data['duration']);os.utime(metadata,None)
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
        'voice':request.voice,'language':request.language,'title':request.title,
        'engine':'qwen3-tts-local'}
