"""Dispatch de narração do editor e adaptador legado de Pocket TTS.

Novos pedidos usam Qwen3-TTS Base e são roteados ao worker local persistente.
O código Pocket abaixo é mantido apenas para compatibilidade explícita com
requisições antigas; não é exibido nem instalado pelo fluxo padrão. Este módulo
não importa torch nem pocket_tts no processo Qt.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from importlib.metadata import PackageNotFoundError, version as package_version
import math
from pathlib import Path
import json
import os
import re
import shutil
import subprocess
import sys
import time
from typing import Callable

from .ai_cache import cache_root, digest, source_identity, write_json

ROOT = Path(__file__).resolve().parents[2]
VOICE_DIR = ROOT / 'assets' / 'voices'

# Todas as amostras da coleção voice-zero são CC0 segundo kyutai/tts-voices.
# Os arquivos reais serão obtidos na instalação; sem conexão há fallback hf://.
VOICE_PRESETS = (
    {'id': 'bill_boerst', 'name': 'Bill Boerst · CC0', 'language': 'english', 'filename': 'bill_boerst.wav', 'license': 'CC0'},
    {'id': 'caro_davy', 'name': 'Caro Davy · CC0', 'language': 'english', 'filename': 'caro_davy.wav', 'license': 'CC0'},
    {'id': 'peter_yearsley', 'name': 'Peter Yearsley · CC0', 'language': 'english', 'filename': 'peter_yearsley.wav', 'license': 'CC0'},
    {'id': 'stuart_bell', 'name': 'Stuart Bell · CC0', 'language': 'english', 'filename': 'stuart_bell.wav', 'license': 'CC0'},
)
_PRECOMPUTED_VOICE_IDS = frozenset(voice['id'] for voice in VOICE_PRESETS)
LANGUAGES = (
    ('Português', 'portuguese'), ('English', 'english'),
    ('Español', 'spanish'), ('Français', 'french'),
    ('Italiano', 'italian'), ('Deutsch', 'german'),
)


def preset_voice(preset_id: str) -> str:
    if preset_id == 'rafael':
        # Voz disponível oficialmente para português; não redistribuímos esta amostra.
        return 'rafael'
    if preset_id not in _PRECOMPUTED_VOICE_IDS:
        raise ValueError('Voz predefinida não reconhecida.')
    # Pocket TTS has precomputed states for these public voices. Passing a WAV
    # would require the gated audio-prompt encoder even though these presets do
    # not: the model can resolve the ID with catalog-only weights.
    return preset_id


def _voice_identity(voice: str) -> dict:
    # Se o arquivo de clonagem mudar, invalida automaticamente o cache.
    if voice.startswith('hf://') or voice == 'rafael' or voice in _PRECOMPUTED_VOICE_IDS:
        return {'catalog': voice}
    if not Path(voice).is_file():
        raise FileNotFoundError(f'Amostra da voz não encontrada: {voice}')
    identity=source_identity(voice)
    content=hashlib.sha256()
    with Path(voice).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):
            content.update(block)
    identity['content_sha256']=content.hexdigest()
    return identity


def _model_version() -> str:
    try:
        return package_version('pocket-tts')
    except PackageNotFoundError:
        return 'not-installed'


def _tts_cache_limit_bytes() -> int:
    """Bound synthesized WAV storage; set BEROFEL_TTS_CACHE_MAX_MB to override."""
    try:
        megabytes=float(os.environ.get('BEROFEL_TTS_CACHE_MAX_MB','2048'))
    except (TypeError,ValueError):
        megabytes=2048.
    if not math.isfinite(megabytes):megabytes=2048.
    return max(0,int(megabytes*1024*1024))


def _is_cache_digest(value: str, length: int) -> bool:
    return len(value)==length and all(char in '0123456789abcdef' for char in value)


def _directory_size(path: Path) -> int:
    total=0
    for base,_dirs,files in os.walk(path,followlinks=False):
        for name in files:
            candidate=Path(base)/name
            try:
                if not candidate.is_symlink():total+=candidate.stat().st_size
            except OSError:
                continue
    return total


def _prune_tts_cache(root: Path, protected: Path | None=None,
                     max_bytes: int | None=None) -> int:
    """Evict oldest owned TTS entries without traversing/deleting unknown paths."""
    root=Path(root)
    if not root.is_dir() or root.is_symlink():return 0
    limit=_tts_cache_limit_bytes() if max_bytes is None else max(0,int(max_bytes))
    protected_path=Path(protected).resolve() if protected is not None else None
    candidates=[];total=0
    for prefix in root.iterdir():
        if (prefix.is_symlink() or not prefix.is_dir() or
                not _is_cache_digest(prefix.name,2)):
            continue
        for entry in prefix.iterdir():
            if (entry.is_symlink() or not entry.is_dir() or
                    not _is_cache_digest(entry.name,32)):
                continue
            # An extant request marks an entry currently being synthesized.
            active=(entry/'request.json').exists()
            try:
                marker=json.loads((entry/'result.json').read_text(encoding='utf-8'))
                owned=(marker.get('engine')=='pocket-tts' and marker.get('key')==entry.name)
            except (OSError,ValueError,AttributeError):
                owned=False
            if not owned and not active:continue
            for partial in entry.glob('*.part.wav'):
                try:
                    if time.time()-partial.stat().st_mtime>24*3600:
                        partial.unlink(missing_ok=True)
                except OSError:
                    pass
            size=_directory_size(entry)
            total+=size
            try:
                used=(entry/'result.json').stat().st_mtime_ns
            except OSError:
                try:used=entry.stat().st_mtime_ns
                except OSError:used=0
            if not active and owned:candidates.append((used,entry,size))
    for _used,entry,size in sorted(candidates,key=lambda record:record[0]):
        if total<=limit:break
        try:
            if protected_path is not None and entry.resolve()==protected_path:continue
            # A second synthesis process may have started after discovery.
            if (entry/'request.json').exists():continue
            shutil.rmtree(entry)
            total-=size
        except OSError:
            continue
    return total


def validate_request(text: str, voice: str, language: str, consent: bool = False) -> None:
    if not text or not text.strip():
        raise ValueError('Digite um texto para narrar.')
    if language not in {code for _, code in LANGUAGES}:
        raise ValueError('Idioma não suportado.')
    if not voice:
        raise ValueError('Escolha uma voz.')
    if not (voice.startswith('hf://') or voice == 'rafael' or
            voice in _PRECOMPUTED_VOICE_IDS):
        path = Path(voice)
        if not path.is_file():
            raise FileNotFoundError(f'Amostra da voz não encontrada: {voice}')
        allowed = {'.wav', '.mp3', '.flac', '.ogg', '.m4a', '.safetensors'}
        if path.suffix.lower() not in allowed:
            raise ValueError('Selecione WAV, MP3, FLAC, OGG, M4A ou safetensors.')
        preset_path = VOICE_DIR.resolve()
        try:
            is_catalog = path.resolve().is_relative_to(preset_path)
        except ValueError:
            is_catalog = False
        if not is_catalog and not consent:
            raise PermissionError('Para clonar uma voz, confirme que possui autorização expressa do titular.')


def persistent_folder(project_path: str = '') -> Path:
    if project_path:
        project = Path(project_path).expanduser().resolve()
        return project.parent / (project.stem + '_arquivos') / 'narracoes'
    # Não guarda material de projeto em pasta temporária que o sistema pode apagar.
    return Path.home() / 'Documents' / 'BerofelStudio' / 'Narracoes'


@dataclass(frozen=True)
class NarrationRequest:
    text: str
    voice: str
    language: str = 'portuguese'
    consent: bool = False
    quantize: bool = False
    project_path: str = ''
    title: str = 'Narração'
    # Legacy Pocket remains available only for old callers/projects. New
    # narration requests use Qwen3-TTS Base and an explicit voice reference.
    engine: str = 'qwen3-tts-local'
    reference_text: str = ''


def _process_flags() -> int:
    return getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def generate_narration(request: NarrationRequest, progress: Callable | None = None,
                       runner: Callable | None = None, control=None, stage=None) -> dict:
    """Entrega WAV durável. O modelo roda em um processo-filho, encerrado após gerar.

    runner é injetável nos testes; a produção usa sys.executable do venv do editor.
    """
    if request.engine=='qwen3-tts-local':
        from .qwen3_tts_local import generate_local_clone
        return generate_local_clone(request,progress=progress,runner=runner,
                                    control=control,stage=stage)
    if control:control.checkpoint()
    if stage:stage('Pocket TTS • preparando texto e voz')
    validate_request(request.text, request.voice, request.language, request.consent)
    if progress: progress(0, 3)
    identity = _voice_identity(request.voice)
    key = digest({'engine':'pocket-tts','api':2,'model_version':_model_version(),
                  'voice':identity,
                  'language':request.language,'quantize':request.quantize,
                  'text':request.text.strip()})
    directory = cache_root().parent / 'pocket_tts' / key[:2] / key
    directory.mkdir(parents=True, exist_ok=True)
    wav = directory / 'audio.wav'
    metadata = directory / 'result.json'
    cache_hit = False
    if wav.is_file() and wav.stat().st_size > 44 and metadata.is_file():
        try:
            payload = json.loads(metadata.read_text(encoding='utf-8'))
            cache_hit = payload.get('key') == key and payload.get('duration', 0) > 0
        except (OSError, ValueError):
            pass
    if not cache_hit:
        if control:control.checkpoint()
        if stage:stage('Pocket TTS • sintetizando áudio (duração variável)')
        job_file = directory / 'request.json'
        result_file = directory / 'worker_result.json'
        job_file.unlink(missing_ok=True)
        result_file.unlink(missing_ok=True)
        write_json(job_file, {'text':request.text.strip(), 'voice':request.voice,
                              'language':request.language, 'quantize':request.quantize,
                              'consent':request.consent,
                              'output':str(wav)})
        try:
            if runner is not None:
                runner(job_file, result_file)
            else:
                env = os.environ.copy()
                env['PYTHONPATH'] = str(ROOT) + os.pathsep + env.get('PYTHONPATH', '')
                cmd=[sys.executable, '-m', 'berofel.services.pocket_tts_worker',
                     str(job_file), str(result_file)]
                if control:
                    proc=control.run(cmd,cwd=str(ROOT),env=env,stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE,text=True,encoding='utf-8',
                                     errors='replace',timeout=3600,creationflags=_process_flags())
                else:
                    proc=subprocess.run(cmd,cwd=str(ROOT),env=env,capture_output=True,text=True,
                                        encoding='utf-8',errors='replace',timeout=3600,
                                        creationflags=_process_flags())
                if proc.returncode != 0:
                    raise RuntimeError('Pocket TTS: ' + (proc.stderr or proc.stdout)[-1500:])
            if not wav.is_file() or wav.stat().st_size <= 44 or not result_file.is_file():
                raise RuntimeError('O processo Pocket TTS não entregou um WAV válido.')
            result = json.loads(result_file.read_text(encoding='utf-8'))
            duration = float(result['duration'])
            if not .01 < duration < 24 * 3600:
                raise RuntimeError('Duração de áudio retornada inválida.')
            write_json(metadata, {'key':key,'duration':duration,'engine':'pocket-tts'})
        finally:
            job_file.unlink(missing_ok=True)
            result_file.unlink(missing_ok=True)
    else:
        duration = float(payload['duration'])
        os.utime(metadata,None)  # touch only our metadata to retain LRU order
        if stage:stage('Pocket TTS • resultado recuperado do cache')
    if control:control.checkpoint()
    if stage:stage('Pocket TTS • salvando áudio no projeto')
    if progress:progress(2, 3)
    dest = persistent_folder(request.project_path)
    dest.mkdir(parents=True, exist_ok=True)
    safe_title = re.sub(r'[^\w\-]+', '_', request.title.strip(), flags=re.UNICODE).strip('_')[:48] or 'Narracao'
    # Cada geração tem seu próprio WAV na mídia do projeto; assim não se substitui
    # uma narração anterior quando o texto ou a voz mudarem.
    now = time.strftime('%Y%m%d_%H%M%S')
    output = dest / f'{safe_title}_{now}_{key[:8]}.wav'
    counter = 1
    while output.exists():
        output = dest / f'{safe_title}_{now}_{key[:8]}_{counter}.wav'
        counter += 1
    shutil.copy2(wav, output)
    if control and control.cancelled:
        output.unlink(missing_ok=True)
        control.checkpoint()
    try:
        _prune_tts_cache(directory.parents[1],protected=directory)
    except OSError:
        # Cache maintenance must not invalidate the durable WAV just written.
        pass
    if progress:progress(3, 3)
    return {'path':str(output), 'duration':duration, 'cache_hit':cache_hit,
            'voice':request.voice, 'language':request.language, 'title':request.title}
