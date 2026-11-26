"""Opt-in Windows Pure C backend for Qwen3-TTS Base mixed CPU inference.

The official PyTorch backend remains the default. This adapter runs an
independent local HTTP server and keeps one authorized x-vector profile loaded
per server session. A profile switch restarts the server because the upstream
Pure C API does not accept a per-request clone embedding.
"""
from __future__ import annotations

import atexit
import hashlib
import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
import uuid
import wave
from functools import lru_cache

import numpy as np

from .ai_cache import digest, file_sha256
from .narration_service import (LANGUAGES, NarrationRequest, persistent_folder,
                                _process_flags, validate_request,
                                validate_clone_conditioning)

ENGINE_ID = 'qwen3-tts-purec-mixed'
ENGINE_INT8_ID = 'qwen3-tts-purec-int8'
PUREC_ENGINES = (ENGINE_ID, ENGINE_INT8_ID)
_LANGUAGES = {'portuguese': 'Portuguese', 'english': 'English',
              'spanish': 'Spanish', 'french': 'French',
              'italian': 'Italian', 'german': 'German'}
_LOCK = threading.RLock()
_PROCESS: subprocess.Popen | None = None
_PROCESS_KEY = ''
_PORT = 0
_MODEL_LOAD_SECONDS = 0.0
_PROFILE_SECONDS = 0.0
_SERVER_STATE = 'STOPPED'
_ACTIVE_PROFILE_FINGERPRINT = ''
_ACTIVE_STYLE_FINGERPRINT = ''
_ACTIVE_PROFILE_PATH = ''
_ACTIVE_STYLE_PATH = ''
_ACTIVE_STYLE_TEXT = ''
_ACTIVE_ENGINE = ''
_ACTIVE_THREADS = 0
_SERVER_LOG_HANDLE = None
_SERVER_LOG_PATH = ''


def runtime_root() -> Path:
    override = os.environ.get('BEROFEL_QWEN3_PUREC_HOME', '').strip()
    if override:
        return Path(override).expanduser().resolve()
    local = os.environ.get('LOCALAPPDATA')
    base = Path(local) if local else Path.home() / '.local' / 'share'
    return base / 'BFS' / 'qwen3_tts' / 'purec'


def _layout() -> tuple[Path, Path, list[Path]]:
    root = runtime_root()
    exe = Path(os.environ.get('BEROFEL_QWEN3_PUREC_EXE', '') or
               root / 'bin' / 'qwen_tts.exe').expanduser().resolve()
    model = Path(os.environ.get('BEROFEL_QWEN3_PUREC_MODEL', '') or
                 (Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) /
                  'BFS' / 'qwen3_tts' / 'model')).expanduser().resolve()
    extra = os.environ.get('BEROFEL_QWEN3_PUREC_RUNTIME_PATHS', '')
    paths = [Path(value).expanduser().resolve() for value in extra.split(os.pathsep) if value]
    paths.insert(0, exe.parent)
    return exe, model, paths


def is_ready() -> bool:
    exe, model, paths = _layout()
    return (exe.is_file() and (model / 'config.json').is_file() and
            (model / 'model.safetensors').is_file() and
            (model / 'speech_tokenizer' / 'model.safetensors').is_file() and
            all(path.is_dir() for path in paths))


@lru_cache(maxsize=8)
def _emotion_by_example_capability(binary: str, size: int, mtime_ns: int) -> bool:
    """Cache CLI capability detection by concrete executable metadata."""
    del size, mtime_ns  # They intentionally form part of this cache key.
    try:
        from .voice_intelligence.capabilities import inspect_purec_capabilities
        manifest = inspect_purec_capabilities(binary, timeout=1.5)
        cli = manifest.get('cli', {})
        return bool(cli.get('emotion_by_example_advertised') and
                    cli.get('emotion_by_example_needs_transcript') and
                    cli.get('emotion_by_example_wav_constraints') == '24khz mono')
    except (OSError, RuntimeError, ValueError):
        return False


def supports_emotion_by_example() -> bool:
    """Return whether the installed Pure C binary advertises the exact route.

    This only probes ``--help``/``--caps`` (no weights or model load) and is
    cached until the executable's size or modification time changes.
    """
    executable, _model, _paths = _layout()
    try:
        stat = executable.stat()
    except OSError:
        return False
    return _emotion_by_example_capability(
        str(executable), stat.st_size, stat.st_mtime_ns)


def _environment(exe: Path, paths: list[Path], thread_count: int | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env['PATH'] = os.pathsep.join(map(str, paths)) + os.pathsep + env.get('PATH', '')
    env['OMP_NUM_THREADS'] = str(threads_for_engine(thread_count))
    # The Pure C server owns the request-level thread pool. Prevent a separate
    # OpenBLAS pool from expanding to the host-wide default (often all cores).
    env['OPENBLAS_NUM_THREADS'] = '1'
    return env


def threads_for_engine(thread_count: int | None = None) -> int:
    if thread_count is not None:
        try:
            return max(2, min(8, int(thread_count)))
        except (TypeError, ValueError):
            return 6
    try:
        return max(2, min(8, int(os.environ.get('BEROFEL_QWEN3_PUREC_THREADS', '6'))))
    except (TypeError, ValueError):
        return 6


def _profile_cache_root() -> Path:
    override = os.environ.get('BEROFEL_QWEN3_PUREC_PROFILE_CACHE', '').strip()
    if override:
        return Path(override).expanduser().resolve()
    return runtime_root() / 'cache' / 'profiles'


def _prepare_emotion_reference(reference: str, reference_text: str) -> tuple[Path, str]:
    """Prepare and cache the opt-in Pure C 0.6B emotion-by-example WAV.

    Pure C's installed CLI expects a mono 24 kHz WAV and its exact transcript.
    The user's source remains untouched; only the best reference window is
    converted and stored in the private local profile cache.
    """
    source = Path(reference).expanduser().resolve()
    transcript = ' '.join(str(reference_text or '').split())
    if not transcript:
        raise ValueError('A transferência de estilo exige a transcrição revisada da referência.')
    from .audio_reference import _reference_window, REFERENCE_PREPARATION_VERSION
    start, duration, _ = _reference_window(source)
    source_hash = file_sha256(source)
    cache_key = digest({'schema': 1, 'kind': 'purec-emotion-reference',
                        'source_sha256': source_hash, 'transcript': transcript,
                        'window_start': round(start, 3), 'window_duration': round(duration, 3),
                        'reference_preparation': REFERENCE_PREPARATION_VERSION})
    destination = _profile_cache_root() / 'emotion_refs' / f'{cache_key}.wav'
    if destination.is_file():
        try:
            with wave.open(str(destination), 'rb') as wav:
                if (wav.getnchannels() == 1 and wav.getframerate() == 24000 and
                        wav.getsampwidth() == 2 and wav.getnframes() > 0):
                    return destination, cache_key
        except (OSError, wave.Error):
            pass
        destination.unlink(missing_ok=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    pending = destination.with_name(destination.stem + f'.{uuid.uuid4().hex}.pending.wav')
    try:
        from .audio_reference import prepare_audio_prompt
        prepare_audio_prompt(str(source), pending, start_seconds=start,
                             duration_seconds=duration)
        with wave.open(str(pending), 'rb') as wav:
            if (wav.getnchannels() != 1 or wav.getframerate() != 24000 or
                    wav.getsampwidth() != 2 or wav.getnframes() <= 0):
                raise RuntimeError('A referência de estilo não está em WAV mono 24 kHz válido.')
        os.replace(pending, destination)
    except Exception:
        pending.unlink(missing_ok=True)
        raise
    return destination, cache_key


def _server_log_destination() -> Path:
    override = os.environ.get('BEROFEL_QWEN3_PUREC_LOG', '').strip()
    if override:
        path = Path(override).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    folder = runtime_root() / 'logs'
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f'purec-server-{time.strftime("%Y%m%d-%H%M%S")}-{uuid.uuid4().hex[:8]}.log'


def _server_log_tail(path: str, limit: int = 2400) -> str:
    if not path:
        return ''
    try:
        with Path(path).open('rb') as source:
            source.seek(max(0, Path(path).stat().st_size - limit))
            return source.read().decode('utf-8', 'replace').strip()
    except OSError:
        return ''


def server_status() -> dict:
    """Return a safe snapshot of the serialized local server state."""
    with _LOCK:
        if _PROCESS is not None and _PROCESS.poll() is not None:
            _stop_server_locked()
        return {'state': _SERVER_STATE,
                'pid': _PROCESS.pid if _PROCESS is not None else None,
                'engine': _ACTIVE_ENGINE,
                'threads': _ACTIVE_THREADS,
                'emotion_by_example': bool(_ACTIVE_STYLE_FINGERPRINT),
                'profile_fingerprint': _ACTIVE_PROFILE_FINGERPRINT,
                'log_path': _SERVER_LOG_PATH}


def _model_key(exe: Path, model: Path) -> str:
    files = (exe, model / 'config.json', model / 'model.safetensors',
             model / 'speech_tokenizer' / 'model.safetensors')
    return digest({'engine': ENGINE_ID, 'files': [
        (str(path), path.stat().st_size, path.stat().st_mtime_ns) for path in files]})


def _valid_profile(path: Path) -> bool:
    try:
        if path.stat().st_size != 1024 * 4:
            return False
        vector = np.fromfile(path, dtype='<f4')
        return vector.size == 1024 and bool(np.isfinite(vector).all()) and float(np.linalg.norm(vector)) > 1e-6
    except (OSError, ValueError):
        return False


def _quantization_flag(engine: str) -> list[str]:
    if engine == ENGINE_ID:
        return ['--quant-mixed-cpu']
    if engine == ENGINE_INT8_ID:
        return ['--int8']
    raise ValueError(f'Perfil de execução Pure C inválido: {engine}')


def prepare_voice_profile(reference: str, reference_text: str = '',
                          consent: bool = False, control=None,
                          stage=None, engine: str = ENGINE_ID,
                          thread_count: int | None = None,
                          emotion_reference_path: str | Path | None = None,
                          emotion_reference_text: str = '') -> dict:
    """Prepare and securely cache a reusable Pure C x-vector for local TTS."""
    source = Path(reference).expanduser().resolve()
    validate_request('preparar voz', str(source), 'portuguese', consent)
    if not is_ready():
        raise RuntimeError('Pure C não está instalado. Configure o executável, o runtime MSYS2 e o modelo Qwen3 Base local.')
    _quantization_flag(engine)
    exe, model, paths = _layout()
    emotion_path = Path(emotion_reference_path).expanduser().resolve() if emotion_reference_path else None
    if emotion_path is not None:
        if not emotion_path.is_file() or not str(emotion_reference_text or '').strip():
            raise ValueError('A referência de estilo Pure C precisa de WAV e transcrição revisada.')
        with wave.open(str(emotion_path), 'rb') as emotion_wav:
            if (emotion_wav.getnchannels() != 1 or emotion_wav.getframerate() != 24000 or
                    emotion_wav.getsampwidth() != 2 or emotion_wav.getnframes() <= 0):
                raise ValueError('A referência de estilo Pure C deve ser WAV mono PCM16 de 24 kHz.')
    source_hash = file_sha256(source)
    from .audio_reference import REFERENCE_PREPARATION_VERSION
    key = digest({'schema': 2, 'reference_preparation': REFERENCE_PREPARATION_VERSION,
                  'voice_sha256': source_hash,
                  'model': _model_key(exe, model), 'profile': 'xvector-1024-f32'})
    cache = _profile_cache_root()
    destination = cache / (key + '.bin')
    cache.mkdir(parents=True, exist_ok=True)
    # Profile extraction itself loads Qwen weights in a short-lived process.
    # Keep it under the same lock as inference and evict a resident server first
    # so a cache miss never has two 0.6B copies consuming RAM simultaneously.
    with _LOCK:
        if _valid_profile(destination):
            _, model_load = _start_server(destination, control, engine, thread_count,
                emotion_reference_path=emotion_path,
                emotion_reference_text=emotion_reference_text)
            return {'path': str(destination), 'cache_hit': True,
                    'profile_prepare_seconds': 0.0, 'model_load_seconds': model_load,
                    'engine': engine,
                    'emotion_by_example': emotion_path is not None}
        if stage:
            stage('Pure C • preparando perfil vocal local reutilizável')
        started = time.perf_counter()
        _stop_server_locked()
        with tempfile.TemporaryDirectory(prefix='bfs_purec_profile_') as work:
            normalized = Path(work) / 'reference.wav'
            pending = cache / (key + '.bin.part')
            from .audio_reference import prepare_audio_prompt
            prepare_audio_prompt(str(source), normalized)
            command = [str(exe), '-d', str(model), '--ref-audio', str(normalized),
                       '--xvector-only', '--save-voice', str(pending),
                       '-j', str(threads_for_engine(thread_count))]
            process = subprocess.Popen(command, cwd=str(exe.parent), env=_environment(exe, paths, thread_count),
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       creationflags=_process_flags())
            timeout = max(30, min(900, float(os.environ.get('BEROFEL_QWEN3_PUREC_PROFILE_TIMEOUT', '300'))))
            deadline = time.monotonic() + timeout
            while process.poll() is None:
                if control and control.cancelled:
                    process.kill(); process.communicate(timeout=5)
                    pending.unlink(missing_ok=True)
                    if control: control.checkpoint()
                if time.monotonic() >= deadline:
                    process.kill(); out, err = process.communicate(timeout=5)
                    pending.unlink(missing_ok=True)
                    raise TimeoutError(f'Preparar referência Pure C excedeu {timeout:.0f}s: {(err or out)[-500:].decode("utf-8", "replace")}')
                time.sleep(.1)
            out, err = process.communicate()
            if process.returncode or not _valid_profile(pending):
                pending.unlink(missing_ok=True)
                detail = (err or out)[-700:].decode('utf-8', 'replace').strip()
                raise RuntimeError('Pure C não criou um perfil x-vector válido.' + (f' Detalhe: {detail}' if detail else ''))
            if control: control.checkpoint()
            os.replace(pending, destination)
        elapsed = time.perf_counter() - started
        # Keep the expensive model resident so the next voice generation can stream
        # immediately. The server holds the selected profile until a profile switch.
        _, model_load = _start_server(destination, control, engine, thread_count,
            emotion_reference_path=emotion_path,
            emotion_reference_text=emotion_reference_text)
    return {'path': str(destination), 'cache_hit': False,
            'profile_prepare_seconds': elapsed, 'model_load_seconds': model_load,
            'engine': engine,
            'emotion_by_example': emotion_path is not None}


def compare_generated_voice_identity(reference: str, generated: str, *,
                                     consent: bool = False, engine: str = ENGINE_INT8_ID,
                                     thread_count: int | None = None,
                                     control=None, stage=None) -> dict:
    """Compare cached Pure C speaker vectors as an explicit, slower diagnostic.

    At most one Qwen server is resident. The helper serializes both profile
    extractions and restores the previously active voice/style server (or stops
    the temporary server if none was active). The resulting cosine is heuristic
    and intentionally has no pass/fail threshold.
    """
    reference_path = Path(reference).expanduser().resolve()
    generated_path = Path(generated).expanduser().resolve()
    if not reference_path.is_file() or not generated_path.is_file():
        raise FileNotFoundError('A referência e o WAV gerado precisam existir.')
    from .voice_intelligence.speaker_fingerprint import (
        VECTOR_FORMAT, cosine_similarity, read_purec_xvector,
    )

    with _LOCK:
        was_running = _PROCESS is not None and _PROCESS.poll() is None
        previous = {
            'profile': _ACTIVE_PROFILE_PATH,
            'style_path': _ACTIVE_STYLE_PATH,
            'style_text': _ACTIVE_STYLE_TEXT,
            'engine': _ACTIVE_ENGINE,
            'threads': _ACTIVE_THREADS,
        } if was_running else None
        try:
            if stage:
                stage('Pure C · extraindo impressão vocal da narração')
            generated_profile = prepare_voice_profile(
                str(generated_path), consent=consent, control=control,
                engine=engine, thread_count=thread_count, stage=stage)
            if control:
                control.checkpoint()
            if stage:
                stage('Pure C · comparando com a referência autorizada')
            reference_profile = prepare_voice_profile(
                str(reference_path), consent=consent, control=control,
                engine=engine, thread_count=thread_count, stage=stage)
            generated_vector = read_purec_xvector(generated_profile['path'])
            reference_vector = read_purec_xvector(reference_profile['path'])
            score = cosine_similarity(reference_vector, generated_vector)
            return {
                'cosine_similarity': score,
                'vector_format': VECTOR_FORMAT,
                'encoder': 'Qwen3-TTS Pure C x-vector 1024-f32',
                'engine': engine,
                'reference_cache_hit': bool(reference_profile['cache_hit']),
                'generated_cache_hit': bool(generated_profile['cache_hit']),
                'review_required': True,
                'calibrated': False,
                'metric_note': ('Diagnóstico heurístico do encoder do próprio Qwen; '
                                'sem limiar calibrado, não comprova identidade nem '
                                'substitui audição humana.'),
            }
        finally:
            # This function may have restarted the resident server twice. Restore
            # its exact voice/style configuration to avoid the generated voice
            # becoming the active identity for the next narration.
            if previous and previous['profile'] and Path(previous['profile']).is_file():
                _stop_server_locked()
                try:
                    _start_server(
                        Path(previous['profile']), engine=previous['engine'],
                        thread_count=previous['threads'],
                        emotion_reference_path=(Path(previous['style_path'])
                                                if previous['style_path'] else None),
                        emotion_reference_text=previous['style_text'])
                except Exception:
                    _stop_server_locked()
                    raise RuntimeError(
                        'A comparação terminou, mas não foi possível restaurar o servidor Pure C anterior.')
            else:
                _stop_server_locked()


def _stop_server_locked() -> None:
    global _PROCESS, _PROCESS_KEY, _PORT, _MODEL_LOAD_SECONDS, _PROFILE_SECONDS
    global _SERVER_STATE, _ACTIVE_PROFILE_FINGERPRINT, _ACTIVE_STYLE_FINGERPRINT
    global _ACTIVE_PROFILE_PATH, _ACTIVE_STYLE_PATH, _ACTIVE_STYLE_TEXT
    global _ACTIVE_ENGINE, _ACTIVE_THREADS
    global _SERVER_LOG_HANDLE, _SERVER_LOG_PATH
    process = _PROCESS
    if process is not None:
        _SERVER_STATE = 'STOPPING'
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=5)
    _PROCESS = None; _PROCESS_KEY = ''; _PORT = 0
    _MODEL_LOAD_SECONDS = 0.0; _PROFILE_SECONDS = 0.0
    _ACTIVE_PROFILE_FINGERPRINT = ''; _ACTIVE_STYLE_FINGERPRINT = ''
    _ACTIVE_PROFILE_PATH = ''; _ACTIVE_STYLE_PATH = ''; _ACTIVE_STYLE_TEXT = ''
    _ACTIVE_ENGINE = ''; _ACTIVE_THREADS = 0
    log_handle = _SERVER_LOG_HANDLE
    _SERVER_LOG_HANDLE = None; _SERVER_LOG_PATH = ''
    if log_handle is not None:
        try:
            log_handle.flush()
            log_handle.close()
        except OSError:
            pass
    _SERVER_STATE = 'STOPPED'


def stop_purec_worker() -> None:
    with _LOCK:
        _stop_server_locked()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return int(sock.getsockname()[1])


def _start_server(profile: Path, control=None,
                  engine: str = ENGINE_ID,
                  thread_count: int | None = None,
                  emotion_reference_path: Path | None = None,
                  emotion_reference_text: str = '') -> tuple[int, float]:
    global _PROCESS, _PROCESS_KEY, _PORT, _MODEL_LOAD_SECONDS, _PROFILE_SECONDS
    global _SERVER_STATE, _ACTIVE_PROFILE_FINGERPRINT, _ACTIVE_STYLE_FINGERPRINT
    global _ACTIVE_PROFILE_PATH, _ACTIVE_STYLE_PATH, _ACTIVE_STYLE_TEXT
    global _ACTIVE_ENGINE, _ACTIVE_THREADS
    global _SERVER_LOG_HANDLE, _SERVER_LOG_PATH
    exe, model, paths = _layout()
    quantization = _quantization_flag(engine)
    profile_fingerprint = file_sha256(profile)
    style_fingerprint = ''
    emotion_args: list[str] = []
    if emotion_reference_path is not None:
        emotion_reference_path = Path(emotion_reference_path).expanduser().resolve()
        transcript = ' '.join(str(emotion_reference_text or '').split())
        if not emotion_reference_path.is_file() or not transcript:
            raise ValueError('A configuração Pure C exige uma referência de estilo e sua transcrição.')
        with wave.open(str(emotion_reference_path), 'rb') as emotion_wav:
            if (emotion_wav.getnchannels() != 1 or emotion_wav.getframerate() != 24000 or
                    emotion_wav.getsampwidth() != 2 or emotion_wav.getnframes() <= 0):
                raise ValueError('A referência de estilo Pure C deve ser WAV mono PCM16 de 24 kHz.')
        style_fingerprint = digest({'wav_sha256': file_sha256(emotion_reference_path),
                                    'transcript': transcript})
        emotion_args = ['--emo-ref', str(emotion_reference_path),
                        '--emo-ref-text', transcript]
    key = digest({'model': _model_key(exe, model), 'profile': profile_fingerprint,
                  'threads': threads_for_engine(thread_count), 'precision': engine,
                  'style': style_fingerprint})
    if _PROCESS is not None and _PROCESS.poll() is None and _PROCESS_KEY == key:
        # This value is per request: a resident server incurs no new model load.
        _SERVER_STATE = 'READY'
        return _PORT, 0.0
    _stop_server_locked()
    _SERVER_STATE = 'STARTING'
    port = _free_port()
    command = [str(exe), '-d', str(model), '--load-voice', str(profile),
               '--xvector-only', *quantization, '-j', str(threads_for_engine(thread_count)),
               '--max-request-seconds', '600', *emotion_args, '--serve', str(port)]
    started = time.perf_counter()
    log_path = _server_log_destination()
    log_handle = log_path.open('ab', buffering=0)
    process = None
    try:
        process = subprocess.Popen(command, cwd=str(exe.parent), env=_environment(exe, paths, thread_count),
                                   stdin=subprocess.DEVNULL, stdout=log_handle,
                                   stderr=subprocess.STDOUT, creationflags=_process_flags())
        _PROCESS = process
        _SERVER_LOG_HANDLE = log_handle
        _SERVER_LOG_PATH = str(log_path)
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            if control and control.cancelled:
                _stop_server_locked()
                control.checkpoint()
            if process.poll() is not None:
                detail = _server_log_tail(str(log_path))
                _stop_server_locked()
                suffix = f' Detalhe do servidor: {detail}' if detail else f' Consulte o log local: {log_path}'
                raise RuntimeError('Servidor Pure C encerrou durante a inicialização do modelo ou voz.' + suffix)
            try:
                conn = http.client.HTTPConnection('127.0.0.1', port, timeout=1)
                try:
                    conn.request('GET', '/v1/health')
                    response = conn.getresponse(); body = response.read()
                finally:
                    conn.close()
                if response.status == 200 and json.loads(body).get('status') == 'ok':
                    _PROCESS_KEY = key; _PORT = port
                    _ACTIVE_PROFILE_FINGERPRINT = profile_fingerprint
                    _ACTIVE_STYLE_FINGERPRINT = style_fingerprint
                    _ACTIVE_PROFILE_PATH = str(Path(profile).resolve())
                    _ACTIVE_STYLE_PATH = (str(emotion_reference_path.resolve())
                                          if emotion_reference_path is not None else '')
                    _ACTIVE_STYLE_TEXT = (' '.join(str(emotion_reference_text or '').split())
                                          if emotion_reference_path is not None else '')
                    _ACTIVE_ENGINE = engine
                    _ACTIVE_THREADS = threads_for_engine(thread_count)
                    _SERVER_STATE = 'READY'
                    _MODEL_LOAD_SECONDS = time.perf_counter() - started
                    return port, _MODEL_LOAD_SECONDS
            except (OSError, ValueError, TimeoutError):
                pass
            time.sleep(.2)
        detail = _server_log_tail(str(log_path))
        _stop_server_locked()
        suffix = f' Detalhe do servidor: {detail}' if detail else f' Consulte o log local: {log_path}'
        raise TimeoutError('Servidor Pure C não respondeu ao health check em 180 segundos.' + suffix)
    except Exception:
        if _PROCESS is process and process is not None:
            _stop_server_locked()
        else:
            if process is not None and process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            try:
                log_handle.close()
            except OSError:
                pass
            _SERVER_STATE = 'STOPPED'
        raise


def generate_purec_clone(request: NarrationRequest, progress=None, runner=None,
                         control=None, stage=None, audio_chunk=None) -> dict:
    global _SERVER_STATE
    validate_clone_conditioning(request)
    validate_request(request.text, request.voice, request.language, request.consent)
    if request.engine not in PUREC_ENGINES:
        raise ValueError('Selecione um modo de execução Pure C reconhecido.')
    if request.language not in _LANGUAGES:
        raise ValueError('Idioma não suportado pelo Pure C Qwen3 Base.')
    if not is_ready():
        raise RuntimeError('Pure C não está configurado; selecione Original ou Q4 no editor.')
    if request.emotion_by_example and not supports_emotion_by_example():
        raise RuntimeError(
            'Este executável Pure C não anuncia referência de estilo por exemplo '
            '(`--emo-ref`/`--emo-ref-text` para WAV mono 24 kHz). Atualize o runtime '
            'ou desative a opção experimental; nenhuma síntese foi iniciada.')
    if control: control.checkpoint()
    emotion_reference_path = None
    emotion_style_fingerprint = ''
    if request.emotion_by_example:
        emotion_reference_path, emotion_style_fingerprint = _prepare_emotion_reference(
            request.voice, request.reference_text)
    profile = prepare_voice_profile(request.voice, request.reference_text,
                                    request.consent, control, stage,
                                    engine=request.engine,
                                    thread_count=request.thread_count,
                                    emotion_reference_path=emotion_reference_path,
                                    emotion_reference_text=(request.reference_text
                                        if request.emotion_by_example else ''))
    folder = persistent_folder(request.project_path)
    folder.mkdir(parents=True, exist_ok=True)
    base = (''.join(ch if ch.isalnum() or ch in '-_ ' else '_' for ch in request.title).strip() or 'Narração')[:80]
    output = folder / f'{base}_purec_{uuid.uuid4().hex[:8]}.wav'
    pending = output.with_suffix('.pending.wav')
    stream_stats = {'first_audio_chunk_seconds': None, 'streamed_pcm_bytes': 0, 'streamed_chunk_count': 0}
    stage_seconds = {
        'payload_prepare_seconds': 0.0,
        'http_headers_seconds': 0.0,
        'stream_read_seconds': 0.0,
        'wav_write_seconds': 0.0,
        'pcm_analysis_seconds': 0.0,
        'pcm_to_float_seconds': 0.0,
        'audio_callback_seconds': 0.0,
        'wav_close_seconds': 0.0,
        'wav_replace_seconds': 0.0,
    }
    with _LOCK:
        port, model_load = _start_server(Path(profile['path']), control,
                                         request.engine, request.thread_count,
                                         emotion_reference_path=emotion_reference_path,
                                         emotion_reference_text=(request.reference_text
                                             if request.emotion_by_example else ''))
        expected_profile_fingerprint = file_sha256(Path(profile['path']))
        expected_style_fingerprint = (digest({
            'wav_sha256': file_sha256(emotion_reference_path),
            'transcript': ' '.join(request.reference_text.split())})
            if emotion_reference_path is not None else '')
        if (_ACTIVE_PROFILE_FINGERPRINT != expected_profile_fingerprint or
                _ACTIVE_STYLE_FINGERPRINT != expected_style_fingerprint or
                _ACTIVE_ENGINE != request.engine or
                _ACTIVE_THREADS != threads_for_engine(request.thread_count) or
                _PROCESS is None or _PROCESS.poll() is not None):
            raise RuntimeError('O servidor Pure C pronto não corresponde ao perfil vocal, estilo de referência, backend ou threads solicitados; nenhuma síntese foi enviada.')
        # A cache miss starts the resident model while preparing its profile;
        # preserve that measured cost in this request's telemetry. Cache hits
        # on an already running server correctly report zero incremental load.
        if model_load <= 0:
            model_load = float(profile.get('model_load_seconds', 0.0))
        start = time.perf_counter()
        conn = http.client.HTTPConnection('127.0.0.1', port, timeout=1800)
        payload_started = time.perf_counter()
        normalized_text = request.text.strip()
        payload = json.dumps({'text': normalized_text, 'language': _LANGUAGES[request.language],
                              'temperature': .5, 'top_k': 50, 'top_p': 1.0,
                              'rep_penalty': 1.05}, ensure_ascii=False).encode('utf-8')
        stage_seconds['payload_prepare_seconds'] = time.perf_counter() - payload_started
        try:
            _SERVER_STATE = 'GENERATING'
            headers_started = time.perf_counter()
            conn.request('POST', '/v1/tts/stream', body=payload,
                         headers={'Content-Type': 'application/json'})
            response = conn.getresponse()
            stage_seconds['http_headers_seconds'] = time.perf_counter() - headers_started
            if response.status != 200:
                detail = response.read(1200).decode('utf-8', 'replace')
                raise RuntimeError(f'Pure C recusou a narração (HTTP {response.status}): {detail}')
            carry = b''; frames = 0; peak = 0; first = None
            wav = wave.open(str(pending), 'wb')
            try:
                wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(24000)
                while True:
                    if control: control.checkpoint()
                    read_started = time.perf_counter()
                    block = response.read(4096)
                    stage_seconds['stream_read_seconds'] += time.perf_counter() - read_started
                    if not block: break
                    if first is None:
                        first = time.perf_counter() - start
                        stream_stats['first_audio_chunk_seconds'] = first
                    block = carry + block
                    usable = len(block) - (len(block) % 2)
                    carry = block[usable:]
                    if not usable: continue
                    pcm = block[:usable]
                    write_started = time.perf_counter()
                    wav.writeframesraw(pcm)
                    stage_seconds['wav_write_seconds'] += time.perf_counter() - write_started
                    frames += usable // 2
                    analysis_started = time.perf_counter()
                    values = np.frombuffer(pcm, dtype='<i2')
                    peak = max(peak, int(np.max(np.abs(values.astype(np.int32)))))
                    stage_seconds['pcm_analysis_seconds'] += time.perf_counter() - analysis_started
                    if audio_chunk:
                        conversion_started = time.perf_counter()
                        floats = (values.astype('<f4') / 32768.0).tobytes()
                        stage_seconds['pcm_to_float_seconds'] += time.perf_counter() - conversion_started
                        callback_started = time.perf_counter()
                        audio_chunk(floats)
                        stage_seconds['audio_callback_seconds'] += time.perf_counter() - callback_started
                    stream_stats['streamed_pcm_bytes'] += usable
                    stream_stats['streamed_chunk_count'] += 1
                if carry:
                    raise RuntimeError('Pure C encerrou a stream com amostra PCM incompleta.')
            finally:
                close_started = time.perf_counter()
                wav.close()
                stage_seconds['wav_close_seconds'] += time.perf_counter() - close_started
            response.close()
            if frames <= 0 or peak == 0:
                raise RuntimeError('Pure C retornou áudio vazio ou silencioso.')
            if control: control.checkpoint()
            replace_started = time.perf_counter()
            os.replace(pending, output)
            stage_seconds['wav_replace_seconds'] = time.perf_counter() - replace_started
        except Exception:
            try: conn.close()
            except OSError: pass
            pending.unlink(missing_ok=True)
            raise
        finally:
            try: conn.close()
            except OSError: pass
            if _PROCESS is not None and _PROCESS.poll() is None:
                _SERVER_STATE = 'READY'
            else:
                _stop_server_locked()
    duration = frames / 24000.0
    generation = time.perf_counter() - start
    quantization = ('Talker INT8 + Code Predictor INT4'
                    if request.engine == ENGINE_ID else 'Talker INT8 + Code Predictor INT8')
    execution_profile = ('Turbo Pure C mixed CPU'
                         if request.engine == ENGINE_ID else 'Equilibrado Pure C INT8')
    return {'path': str(output), 'duration': duration, 'title': request.title,
            'engine': request.engine, 'threads': threads_for_engine(request.thread_count),
            'execution_profile': execution_profile,
            'precision': quantization,
            'emotion_by_example': bool(request.emotion_by_example),
            'emotion_style_cache_key': emotion_style_fingerprint,
            'cache_hit': False, 'profile_cache_hit': bool(profile['cache_hit']),
            'conditioning_mode': 'speaker-embedding-only',
            'profile_prepare_seconds': float(profile['profile_prepare_seconds']),
            'model_load_seconds': float(model_load), 'generation_seconds': generation,
            'first_audio_chunk_seconds': stream_stats['first_audio_chunk_seconds'],
            'streamed_pcm_bytes': stream_stats['streamed_pcm_bytes'],
            'streamed_chunk_count': stream_stats['streamed_chunk_count'],
            **stage_seconds,
            'sample_rate': 24000, 'peak': peak / 32768.0}


atexit.register(stop_purec_worker)
