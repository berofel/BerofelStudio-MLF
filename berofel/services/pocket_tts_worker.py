"""Processo isolado que carrega/descarta Pocket TTS sem afetar memória do Qt."""
from __future__ import annotations
import json
import hashlib
import importlib.metadata
import os
from pathlib import Path
import subprocess
import sys
import re
from contextlib import contextmanager

from .pocket_tts_service import _PRECOMPUTED_VOICE_IDS


def activation_failure_message(exc):
    kind=type(exc).__name__
    response=getattr(exc,'response',None)
    status=getattr(response,'status_code',None)
    detail=str(exc).replace('\n',' ')[:600]
    if kind in {'GatedRepoError','RepositoryNotFoundError'} or status in {401,403}:
        reason=('O Hugging Face recusou o checkpoint de clonagem. Entre na conta usada pelo editor '
                'e aceite os termos de kyutai/pocket-tts; depois repita a ativação.')
    elif kind in {'HfHubConnectionError','ConnectTimeout','ReadTimeout','ConnectionError',
                  'LocalEntryNotFoundError'} or \
            'WinError 10013' in detail or 'Network is unreachable' in detail:
        reason=('Não foi possível acessar o Hugging Face pela rede. Verifique internet/firewall/proxy '
                'e tente novamente; o Pocket TTS pode usar voz de catálogo offline, mas isso não ativa clonagem.')
    else:
        reason='Não foi possível validar/baixar os pesos completos de clonagem.'
    return f'{reason}\nDetalhe: {kind}: {detail}'


def ensure_voice_cloning_weights(language='portuguese'):
    """Download the full checkpoint during the explicit first-time activation only."""
    from pocket_tts.utils.config import CONFIGS_DIR, load_config
    from pocket_tts.utils.utils import download_if_necessary

    config=load_config(CONFIGS_DIR/f'{language}.yaml')
    if not config.weights_path:
        raise RuntimeError(f'A configuração Pocket TTS de {language} não declara pesos para clonagem.')
    try:
        return download_if_necessary(config.weights_path)
    except Exception as exc:
        raise RuntimeError(activation_failure_message(exc)) from exc


def require_local_voice_cloning_weights(language='portuguese'):
    """Verify clone weights already exist locally; synthesis must never fetch them."""
    from huggingface_hub import hf_hub_download
    from pocket_tts.utils.config import CONFIGS_DIR, load_config

    config=load_config(CONFIGS_DIR/f'{language}.yaml')
    source=str(config.weights_path or '')
    if not source.startswith('hf://'):
        path=Path(source).expanduser()
        if path.is_file():return path
        raise RuntimeError('O checkpoint local de clonagem não foi encontrado. '
                           'Execute AUTORIZAR_POCKET_TTS.bat uma vez com internet.')
    address=source[5:]
    address,separator,revision=address.rpartition('@')
    if not separator:
        address=source[5:]
        revision=None
    parts=address.split('/',2)
    if len(parts)!=3 or not parts[0] or not parts[1] or not parts[2]:
        raise RuntimeError(f'Endereço de pesos Pocket TTS inválido: {source}')
    repo_id='/'.join(parts[:2])
    filename=parts[2]
    try:
        return Path(hf_hub_download(repo_id=repo_id,filename=filename,
                                    revision=revision,local_files_only=True))
    except Exception as exc:
        raise RuntimeError(
            'Os pesos completos de clonagem do Pocket TTS ainda não estão neste PC. '
            'A geração normal não acessa a internet. Conecte-se, aceite os termos oficiais '
            'e execute AUTORIZAR_POCKET_TTS.bat para baixar e validar o modelo uma vez. '
            f'Detalhe local: {type(exc).__name__}: {str(exc)[:400]}'
        ) from exc


def require_voice_cloning(model, request: dict) -> None:
    """Fail clearly when HF silently supplied the catalog-only model weights."""
    voice = str(request.get('voice', ''))
    is_precomputed = _is_catalog_voice(voice)
    # Fail closed when a future/older Pocket TTS API does not expose the
    # capability flag. Do not claim cloning support based on an unknown API.
    if request.get('consent') and not is_precomputed and not bool(
            getattr(model, 'has_voice_cloning', False)):
        raise RuntimeError(
            'Este Pocket TTS está usando pesos somente de catálogo; clonagem de áudio está desativada até preparar os pesos oficiais completos. '
            'Eles precisam ser autorizados e baixados uma vez. Depois ficam no PC e a amostra/geração são processadas localmente. '
            'Execute AUTORIZAR_POCKET_TTS.bat para preparar o modelo e tente novamente.'
        )


def _is_catalog_voice(voice: str) -> bool:
    return voice == 'rafael' or voice in _PRECOMPUTED_VOICE_IDS


def load_model_for_request(request: dict):
    """Load from local files only; model downloads belong to explicit setup actions."""
    voice=str(request.get('voice',''))
    is_precomputed=_is_catalog_voice(voice)
    if request.get('consent') and not is_precomputed:
        require_local_voice_cloning_weights(request.get('language','portuguese'))
    from pocket_tts import TTSModel
    model=TTSModel.load_model(language=request['language'],
                              quantize=bool(request.get('quantize',False)))
    require_voice_cloning(model,request)
    return model


@contextmanager
def _offline_model_access():
    """Prevent Hugging Face/network access while serving an inference request."""
    keys=('HF_HUB_OFFLINE','TRANSFORMERS_OFFLINE','HF_HUB_DISABLE_TELEMETRY')
    previous={key:os.environ.get(key) for key in keys}
    os.environ.update({'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1',
                       'HF_HUB_DISABLE_TELEMETRY':'1'})
    try:
        yield
    finally:
        for key,value in previous.items():
            if value is None:os.environ.pop(key,None)
            else:os.environ[key]=value


def prepare_audio_prompt(voice: str, output_path: str | Path,
                        ffmpeg: str | None = None) -> tuple[str, Path | None]:
    """Normalize user audio for Pocket TTS without touching its source file.

    Pocket TTS reads 16-bit WAV through the standard library; MP3/FLAC/OGG/M4A
    require optional ``soundfile`` support that is not part of our install.
    FFmpeg is already bundled with the editor, so use it to produce a short,
    mono PCM16 WAV. Precomputed .safetensors, Hugging Face voices, and Pocket
    TTS's built-in ``rafael`` speaker ID pass through without filesystem checks.
    """
    # ``rafael`` is Pocket TTS's predefined Portuguese speaker id, not a file.
    # Let TTSModel resolve its cached catalog state just like the UI expects.
    if (voice.startswith('hf://') or voice == 'rafael' or
            voice in _PRECOMPUTED_VOICE_IDS or
            Path(voice).suffix.lower() == '.safetensors'):
        return voice, None
    source = Path(voice)
    if not source.is_file():
        raise FileNotFoundError(f'Amostra da voz não encontrada: {voice}')
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if ffmpeg is None:
        from berofel.services.ffmpeg import ffmpeg_path
        ffmpeg = ffmpeg_path()
    command = [ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
               '-i', str(source), '-map', '0:a:0', '-vn', '-t', '30', '-ac', '1',
               '-ar', '24000', '-c:a', 'pcm_s16le', str(target)]
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                encoding='utf-8', errors='replace',
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode != 0 or not target.is_file() or target.stat().st_size <= 44:
            target.unlink(missing_ok=True)
            detail=(result.stderr or result.stdout or 'FFmpeg não produziu áudio válido.')[-1000:]
            raise RuntimeError(f'Não foi possível preparar a amostra da voz: {detail}')
        return str(target), target
    except Exception:
        target.unlink(missing_ok=True)
        raise


def create_voice_prompt_state(model,voice_prompt):
    """Cap reference-audio embedding work at Pocket TTS's supported 30 s limit."""
    return model.get_state_for_audio_prompt(voice_prompt,truncate=True)


def voice_state_cache_dir() -> Path:
    """Private per-user cache; cloned voice embeddings never enter the project."""
    override=os.environ.get('BEROFEL_VOICE_STATE_CACHE')
    if override:
        return Path(override).expanduser().resolve()
    local=os.environ.get('LOCALAPPDATA')
    return (Path(local)/'BFS'/'cache'/'pocket_tts'/'voice_states' if local else
            Path.home()/'.cache'/'BerofelStudio'/'pocket_tts'/'voice_states')


def _model_voice_fingerprint(language: str) -> dict:
    try:
        version=importlib.metadata.version('pocket-tts')
    except importlib.metadata.PackageNotFoundError:
        version='not-installed'
    try:
        from pocket_tts.utils.config import CONFIGS_DIR,load_config
        config=load_config(CONFIGS_DIR/f'{language}.yaml')
        weights=str(config.weights_path or '')
    except Exception:
        weights='unknown'
    return {'package':version,'language':language,'weights':weights}


def _voice_state_key(source: Path,language: str) -> str:
    content=hashlib.sha256()
    with source.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):
            content.update(block)
    identity={'source_sha256':content.hexdigest(),
        'model':_model_voice_fingerprint(language),'truncate_seconds':30,
        'schema':1}
    return hashlib.sha256(json.dumps(identity,sort_keys=True,separators=(',',':'))
        .encode('utf-8')).hexdigest()


def _prune_voice_state_cache(folder: Path,protected: Path | None=None):
    """Bound only our hash-named state files, keeping biometric cache local."""
    try:limit=max(64,int(os.environ.get('BEROFEL_VOICE_STATE_CACHE_MAX_MB','512')))*1024*1024
    except ValueError:limit=512*1024*1024
    if not folder.is_dir() or folder.is_symlink():return
    valid=re.compile(r'^[0-9a-f]{64}\.safetensors$')
    files=[];total=0
    for path in folder.iterdir():
        if path.is_symlink() or not path.is_file() or not valid.fullmatch(path.name):continue
        try:
            stat=path.stat();files.append((path,stat.st_size,stat.st_mtime_ns));total+=stat.st_size
        except OSError:continue
    protected_path=Path(protected).resolve() if protected else None
    for path,size,_mtime in sorted(files,key=lambda item:item[2]):
        if total<=limit:break
        try:
            if protected_path and path.resolve()==protected_path:continue
            path.unlink();total-=size
        except OSError:continue


def create_or_load_voice_state(model,voice: str,language: str):
    """Encode an authorized local reference once, then reuse its local latent state."""
    if _is_catalog_voice(voice) or voice.startswith('hf://'):
        return create_voice_prompt_state(model,voice)
    source=Path(voice)
    if source.suffix.lower()=='.safetensors':
        if not source.is_file():raise FileNotFoundError(f'Perfil vocal não encontrado: {source}')
        return create_voice_prompt_state(model,str(source))
    if not source.is_file():raise FileNotFoundError(f'Amostra da voz não encontrada: {source}')
    folder=voice_state_cache_dir()
    key=_voice_state_key(source,language)
    cached=folder/f'{key}.safetensors'
    if cached.is_file():
        try:return create_voice_prompt_state(model,str(cached))
        except Exception:
            # Only delete this app-owned hash file; the reference remains untouched.
            try:cached.unlink(missing_ok=True)
            except OSError:pass
    voice_prompt,prepared=prepare_audio_prompt(
        str(source),folder/f'{key}.reference.wav')
    try:
        state=create_voice_prompt_state(model,voice_prompt)
        try:
            from pocket_tts import export_model_state
            folder.mkdir(parents=True,exist_ok=True)
            temporary=cached.with_name(cached.name+f'.{os.getpid()}.tmp')
            try:
                export_model_state(state,temporary)
                os.replace(temporary,cached)
                _prune_voice_state_cache(folder,protected=cached)
            finally:
                temporary.unlink(missing_ok=True)
        except Exception:
            # A read-only cache must not prevent this one synthesis from completing.
            pass
        return state
    finally:
        if prepared is not None:prepared.unlink(missing_ok=True)


def run(request_path: str, result_path: str):
    request = json.loads(Path(request_path).read_text(encoding='utf-8'))
    from scipy.io import wavfile
    import numpy as np

    # Inference is local-only. Model acquisition is performed by the explicit
    # installer/authorization flow, never as a hidden side effect of Generate.
    with _offline_model_access():
        model = load_model_for_request(request)
        voice_state = create_or_load_voice_state(model,request['voice'],
                                                 request.get('language','portuguese'))
        audio = model.generate_audio(voice_state, request['text'])
    samples = audio.detach().cpu().numpy().reshape(-1)
    if not samples.size:
        raise RuntimeError('Pocket TTS retornou áudio vazio.')
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
    sample_rate = int(model.sample_rate)
    target = Path(request['output'])
    target.parent.mkdir(parents=True, exist_ok=True)
    pending = target.with_suffix('.part.wav')
    wavfile.write(str(pending), sample_rate, pcm)
    os.replace(pending, target)
    result = {'duration':len(pcm) / sample_rate, 'sample_rate':sample_rate, 'bytes':target.stat().st_size}
    result_target = Path(result_path)
    tmp = result_target.with_suffix('.tmp')
    tmp.write_text(json.dumps(result), encoding='utf-8')
    os.replace(tmp, result_target)


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, OSError, ValueError):
            pass
    try:
        if len(sys.argv) != 3:
            raise ValueError('Uso: python -m berofel.services.pocket_tts_worker pedido.json resultado.json')
        run(sys.argv[1], sys.argv[2])
    except Exception as exc:
        print(f'Falha Pocket TTS: {type(exc).__name__}: {exc}',file=sys.stderr)
        raise SystemExit(1)
