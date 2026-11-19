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

import numpy as np

from .ai_cache import digest
from .narration_service import (LANGUAGES, NarrationRequest, persistent_folder,
                                _process_flags, validate_request)

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


def _environment(exe: Path, paths: list[Path]) -> dict[str, str]:
    env = os.environ.copy()
    env['PATH'] = os.pathsep.join(map(str, paths)) + os.pathsep + env.get('PATH', '')
    env['OMP_NUM_THREADS'] = str(threads_for_engine())
    # The Pure C server owns the request-level thread pool. Prevent a separate
    # OpenBLAS pool from expanding to the host-wide default (often all cores).
    env['OPENBLAS_NUM_THREADS'] = '1'
    return env


def threads_for_engine() -> int:
    try:
        return max(2, min(8, int(os.environ.get('BEROFEL_QWEN3_PUREC_THREADS', '6'))))
    except (TypeError, ValueError):
        return 6


def _profile_cache_root() -> Path:
    override = os.environ.get('BEROFEL_QWEN3_PUREC_PROFILE_CACHE', '').strip()
    if override:
        return Path(override).expanduser().resolve()
    return runtime_root() / 'cache' / 'profiles'


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
                          stage=None, engine: str = ENGINE_ID) -> dict:
    """Prepare and securely cache a reusable Pure C x-vector for local TTS."""
    source = Path(reference).expanduser().resolve()
    validate_request('preparar voz', str(source), 'portuguese', consent)
    if not is_ready():
        raise RuntimeError('Pure C não está instalado. Configure o executável, o runtime MSYS2 e o modelo Qwen3 Base local.')
    _quantization_flag(engine)
    exe, model, paths = _layout()
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    key = digest({'schema': 1, 'voice_sha256': source_hash,
                  'model': _model_key(exe, model), 'profile': 'xvector-1024-f32'})
    cache = _profile_cache_root()
    destination = cache / (key + '.bin')
    if _valid_profile(destination):
        with _LOCK:
            _, model_load = _start_server(destination, control, engine)
        return {'path': str(destination), 'cache_hit': True,
                'profile_prepare_seconds': 0.0, 'model_load_seconds': model_load,
                'engine': engine}
    cache.mkdir(parents=True, exist_ok=True)
    if stage:
        stage('Pure C • preparando perfil vocal local reutilizável')
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix='bfs_purec_profile_') as work:
        normalized = Path(work) / 'reference.wav'
        pending = cache / (key + '.bin.part')
        from .audio_reference import prepare_audio_prompt
        prepare_audio_prompt(str(source), normalized)
        command = [str(exe), '-d', str(model), '--ref-audio', str(normalized),
                   '--xvector-only', '--save-voice', str(pending),
                   '-j', str(threads_for_engine())]
        process = subprocess.Popen(command, cwd=str(exe.parent), env=_environment(exe, paths),
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
    with _LOCK:
        _, model_load = _start_server(destination, control, engine)
    return {'path': str(destination), 'cache_hit': False,
            'profile_prepare_seconds': elapsed, 'model_load_seconds': model_load,
            'engine': engine}


def _stop_server_locked() -> None:
    global _PROCESS, _PROCESS_KEY, _PORT, _MODEL_LOAD_SECONDS, _PROFILE_SECONDS
    process = _PROCESS
    _PROCESS = None; _PROCESS_KEY = ''; _PORT = 0
    _MODEL_LOAD_SECONDS = 0.0; _PROFILE_SECONDS = 0.0
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill(); process.wait(timeout=5)


def stop_purec_worker() -> None:
    with _LOCK:
        _stop_server_locked()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return int(sock.getsockname()[1])


def _start_server(profile: Path, control=None,
                  engine: str = ENGINE_ID) -> tuple[int, float]:
    global _PROCESS, _PROCESS_KEY, _PORT, _MODEL_LOAD_SECONDS, _PROFILE_SECONDS
    exe, model, paths = _layout()
    quantization = _quantization_flag(engine)
    key = digest({'model': _model_key(exe, model), 'profile': hashlib.sha256(profile.read_bytes()).hexdigest(),
                  'threads': threads_for_engine(), 'precision': engine})
    if _PROCESS is not None and _PROCESS.poll() is None and _PROCESS_KEY == key:
        # This value is per request: a resident server incurs no new model load.
        return _PORT, 0.0
    _stop_server_locked()
    port = _free_port()
    command = [str(exe), '-d', str(model), '--load-voice', str(profile),
               '--xvector-only', *quantization, '-j', str(threads_for_engine()),
               '--max-request-seconds', '600', '--serve', str(port)]
    started = time.perf_counter()
    process = subprocess.Popen(command, cwd=str(exe.parent), env=_environment(exe, paths),
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, creationflags=_process_flags())
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        if control and control.cancelled:
            process.kill(); process.wait(timeout=5)
            if control: control.checkpoint()
        if process.poll() is not None:
            raise RuntimeError('Servidor Pure C encerrou ao carregar Qwen3 Base e o perfil vocal.')
        try:
            conn = http.client.HTTPConnection('127.0.0.1', port, timeout=1)
            try:
                conn.request('GET', '/v1/health')
                response = conn.getresponse(); body = response.read()
            finally:
                conn.close()
            if response.status == 200 and json.loads(body).get('status') == 'ok':
                _PROCESS = process; _PROCESS_KEY = key; _PORT = port
                _MODEL_LOAD_SECONDS = time.perf_counter() - started
                return port, _MODEL_LOAD_SECONDS
        except (OSError, ValueError, TimeoutError):
            pass
        time.sleep(.2)
    process.kill(); process.wait(timeout=5)
    raise TimeoutError('Servidor Pure C não ficou pronto em 180 segundos.')


def generate_purec_clone(request: NarrationRequest, progress=None, runner=None,
                         control=None, stage=None, audio_chunk=None) -> dict:
    validate_request(request.text, request.voice, request.language, request.consent)
    if request.engine not in PUREC_ENGINES:
        raise ValueError('Selecione um modo de execução Pure C reconhecido.')
    if request.language not in _LANGUAGES:
        raise ValueError('Idioma não suportado pelo Pure C Qwen3 Base.')
    if not is_ready():
        raise RuntimeError('Pure C não está configurado; selecione Original ou Q4 no editor.')
    if control: control.checkpoint()
    profile = prepare_voice_profile(request.voice, request.reference_text,
                                    request.consent, control, stage,
                                    engine=request.engine)
    folder = persistent_folder(request.project_path)
    folder.mkdir(parents=True, exist_ok=True)
    base = (''.join(ch if ch.isalnum() or ch in '-_ ' else '_' for ch in request.title).strip() or 'Narração')[:80]
    output = folder / f'{base}_purec_{uuid.uuid4().hex[:8]}.wav'
    pending = output.with_suffix('.pending.wav')
    stream_stats = {'first_audio_chunk_seconds': None, 'streamed_pcm_bytes': 0, 'streamed_chunk_count': 0}
    with _LOCK:
        port, model_load = _start_server(Path(profile['path']), control,
                                         request.engine)
        # A cache miss starts the resident model while preparing its profile;
        # preserve that measured cost in this request's telemetry. Cache hits
        # on an already running server correctly report zero incremental load.
        if model_load <= 0:
            model_load = float(profile.get('model_load_seconds', 0.0))
        start = time.perf_counter()
        conn = http.client.HTTPConnection('127.0.0.1', port, timeout=1800)
        payload = json.dumps({'text': request.text.strip(), 'language': _LANGUAGES[request.language],
                              'temperature': .5, 'top_k': 50, 'top_p': 1.0,
                              'rep_penalty': 1.05}, ensure_ascii=False).encode('utf-8')
        try:
            conn.request('POST', '/v1/tts/stream', body=payload,
                         headers={'Content-Type': 'application/json'})
            response = conn.getresponse()
            if response.status != 200:
                detail = response.read(1200).decode('utf-8', 'replace')
                raise RuntimeError(f'Pure C recusou a narração (HTTP {response.status}): {detail}')
            carry = b''; frames = 0; peak = 0; first = None
            with wave.open(str(pending), 'wb') as wav:
                wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(24000)
                while True:
                    if control: control.checkpoint()
                    block = response.read(4096)
                    if not block: break
                    if first is None:
                        first = time.perf_counter() - start
                        stream_stats['first_audio_chunk_seconds'] = first
                    block = carry + block
                    usable = len(block) - (len(block) % 2)
                    carry = block[usable:]
                    if not usable: continue
                    pcm = block[:usable]
                    wav.writeframesraw(pcm); frames += usable // 2
                    values = np.frombuffer(pcm, dtype='<i2')
                    peak = max(peak, int(np.max(np.abs(values.astype(np.int32)))))
                    if audio_chunk:
                        floats = (values.astype('<f4') / 32768.0).tobytes()
                        audio_chunk(floats)
                    stream_stats['streamed_pcm_bytes'] += usable
                    stream_stats['streamed_chunk_count'] += 1
                if carry:
                    raise RuntimeError('Pure C encerrou a stream com amostra PCM incompleta.')
            response.close()
            if frames <= 0 or peak == 0:
                raise RuntimeError('Pure C retornou áudio vazio ou silencioso.')
            if control: control.checkpoint()
            os.replace(pending, output)
        except Exception:
            try: conn.close()
            except OSError: pass
            pending.unlink(missing_ok=True)
            raise
        finally:
            try: conn.close()
            except OSError: pass
    duration = frames / 24000.0
    generation = time.perf_counter() - start
    quantization = ('Talker INT8 + Code Predictor INT4'
                    if request.engine == ENGINE_ID else 'Talker INT8 + Code Predictor INT8')
    execution_profile = ('Turbo Pure C mixed CPU'
                         if request.engine == ENGINE_ID else 'Equilibrado Pure C INT8')
    return {'path': str(output), 'duration': duration, 'title': request.title,
            'engine': request.engine, 'threads': threads_for_engine(),
            'execution_profile': execution_profile,
            'precision': quantization,
            'cache_hit': False, 'profile_cache_hit': bool(profile['cache_hit']),
            'profile_prepare_seconds': float(profile['profile_prepare_seconds']),
            'model_load_seconds': float(model_load), 'generation_seconds': generation,
            'first_audio_chunk_seconds': stream_stats['first_audio_chunk_seconds'],
            'streamed_pcm_bytes': stream_stats['streamed_pcm_bytes'],
            'streamed_chunk_count': stream_stats['streamed_chunk_count'],
            'sample_rate': 24000, 'peak': peak / 32768.0}


atexit.register(stop_purec_worker)
