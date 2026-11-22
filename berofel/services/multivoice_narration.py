"""Deterministic Berofel Script V1 parsing and multivoice synthesis queue.

Dialogues are persisted as versioned JSON in the project model. This module
contains no UI code and never sends a whole script to the TTS engine.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
from typing import Callable, Iterable, Mapping
import uuid
import wave

from .ai_cache import digest
from .narration_service import NarrationRequest, persistent_folder, generate_narration
from .process_control import ProcessCancelled

SCRIPT_FORMAT = 'Berofel Script V1'
SCRIPT_SCHEMA_VERSION = 1
MAX_VOICES = 10
DEFAULT_PAUSE_MS = 200
MODEL_ID = 'Qwen/Qwen3-TTS-12Hz-0.6B-Base'
GENERATION_CACHE_SCHEMA = 1
_VOICE_IDS = tuple(f'V{i}' for i in range(1, MAX_VOICES + 1))
_HEADER = re.compile(
    r'^\[(?P<number>\d+)\s*\|\s*(?P<voice>V(?:10|[1-9]))'
    r'(?:\s*\|\s*(?P<name>[^\]\r\n]+))?\]$'
)
_ID = re.compile(r'^[0-9a-f]{32}$')


class ScriptValidationError(ValueError):
    """A script error with stable, user-readable location details."""


@dataclass(frozen=True)
class VoiceAssignment:
    voice_id: str
    profile_id: str
    display_name: str = ''


@dataclass
class DialogueLine:
    id: str
    number: int
    voice_id: str
    text: str
    character_name: str = ''
    status: str = 'pending'
    audio_path: str = ''
    duration: float = 0.0
    clip_id: str = ''
    cache_key: str = ''
    error: str = ''
    generation_seconds: float = 0.0
    model_load_seconds: float = 0.0
    profile_prepare_seconds: float = 0.0
    first_audio_seconds: float = 0.0
    cache_hit: bool = False


@dataclass
class MultiVoiceScript:
    id: str
    title: str
    engine_id: str
    pause_ms: int
    voices: dict[str, dict[str, str]]
    lines: list[DialogueLine]
    timeline_start: float = 0.0
    track_id: str = ''
    schema_version: int = SCRIPT_SCHEMA_VERSION
    format: str = SCRIPT_FORMAT
    checkpoint_path: str = ''
    total_seconds: float = 0.0
    first_audio_ready_seconds: float = 0.0

    def to_dict(self) -> dict:
        return {
            'schema_version': self.schema_version,
            'format': self.format,
            'id': self.id,
            'title': self.title,
            'engine_id': self.engine_id,
            'pause_ms': self.pause_ms,
            'timeline_start': self.timeline_start,
            'track_id': self.track_id,
            'checkpoint_path': self.checkpoint_path,
            'total_seconds': self.total_seconds,
            'first_audio_ready_seconds': self.first_audio_ready_seconds,
            'voices': {key: dict(value) for key, value in self.voices.items()},
            'lines': [asdict(line) for line in self.lines],
        }

    @classmethod
    def from_dict(cls, data: Mapping) -> 'MultiVoiceScript':
        if not isinstance(data, Mapping) or data.get('schema_version') != SCRIPT_SCHEMA_VERSION:
            raise ScriptValidationError('Versão do roteiro multivozes não suportada.')
        try:
            script = cls(
                id=str(data['id']), title=str(data.get('title', 'Roteiro')),
                engine_id=str(data['engine_id']), pause_ms=int(data.get('pause_ms', DEFAULT_PAUSE_MS)),
                voices={str(k): dict(v) for k, v in data['voices'].items()},
                lines=[DialogueLine(**line) for line in data['lines']],
                timeline_start=float(data.get('timeline_start', 0.0)),
                track_id=str(data.get('track_id', '')), format=str(data.get('format', SCRIPT_FORMAT)),
                checkpoint_path=str(data.get('checkpoint_path', '')),
                total_seconds=float(data.get('total_seconds', 0.0)),
                first_audio_ready_seconds=float(data.get('first_audio_ready_seconds', 0.0)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ScriptValidationError(f'Dados do roteiro inválidos: {exc}') from exc
        validate_script(script)
        return script


def parse_berofel_script(text: str) -> list[DialogueLine]:
    """Parse `[001 | V1]` blocks without an LLM; preserve punctuation/newlines."""
    if not isinstance(text, str) or not text.strip():
        raise ScriptValidationError('Cole ou digite um roteiro Berofel Script V1.')
    lines: list[DialogueLine] = []
    active: tuple[int, str, str, int] | None = None
    body: list[str] = []
    seen: dict[int, int] = {}

    def finish(end_line: int) -> None:
        nonlocal active, body
        if active is None:
            return
        number, voice_id, name, header_line = active
        spoken = '\n'.join(body).strip()
        if not spoken:
            raise ScriptValidationError(
                f'A fala {number:03d} (linha {header_line}) está vazia; adicione o texto antes do próximo cabeçalho.')
        lines.append(DialogueLine(id=uuid.uuid4().hex, number=number,
                                  voice_id=voice_id, text=spoken,
                                  character_name=name))
        active = None
        body = []

    for line_no, raw in enumerate(text.splitlines(), 1):
        stripped = raw.strip()
        if not stripped:
            if active is not None:
                body.append('')
            continue
        if stripped.casefold() == SCRIPT_FORMAT.casefold() and active is None and not lines:
            continue
        if stripped.startswith('['):
            match = _HEADER.fullmatch(stripped)
            if match is None:
                raise ScriptValidationError(
                    f'Cabeçalho inválido na linha {line_no}: {stripped[:100]}')
            finish(line_no)
            number = int(match.group('number'))
            if number <= 0:
                raise ScriptValidationError(f'O número da fala na linha {line_no} precisa ser positivo.')
            if number in seen:
                raise ScriptValidationError(
                    f'Número de fala duplicado {number:03d} nas linhas {seen[number]} e {line_no}.')
            seen[number] = line_no
            active = (number, match.group('voice'), (match.group('name') or '').strip(), line_no)
            continue
        if active is None:
            raise ScriptValidationError(
                f'Texto fora de um bloco de fala na linha {line_no}; use [001 | V1] antes do texto.')
        body.append(raw.rstrip())
    finish(len(text.splitlines()) + 1)
    if not lines:
        raise ScriptValidationError('O roteiro não contém falas.')
    return lines


def validate_assignments(assignments: Mapping[str, VoiceAssignment | Mapping[str, str]],
                         required_voice_ids: Iterable[str]) -> dict[str, dict[str, str]]:
    normalized: dict[str, dict[str, str]] = {}
    for voice_id, value in assignments.items():
        voice_id = str(voice_id).upper()
        if voice_id not in _VOICE_IDS:
            raise ScriptValidationError(f'Identificador de voz inválido: {voice_id}. Use V1 a V10.')
        if isinstance(value, VoiceAssignment):
            record = {'profile_id': value.profile_id, 'display_name': value.display_name}
        elif isinstance(value, Mapping):
            record = {'profile_id': str(value.get('profile_id', '')).strip(),
                      'display_name': str(value.get('display_name', '')).strip()}
        else:
            raise ScriptValidationError(f'A voz {voice_id} não tem um perfil vocal válido.')
        if not record['profile_id']:
            raise ScriptValidationError(f'Selecione um perfil vocal salvo para {voice_id}.')
        normalized[voice_id] = record
    missing = sorted(set(required_voice_ids) - normalized.keys(), key=_voice_order)
    if missing:
        raise ScriptValidationError('Associe um perfil vocal salvo a: ' + ', '.join(missing) + '.')
    if len(normalized) > MAX_VOICES:
        raise ScriptValidationError(f'O máximo é {MAX_VOICES} personagens por roteiro.')
    return normalized


def create_script(text: str, assignments: Mapping[str, VoiceAssignment | Mapping[str, str]],
                  engine_id: str, title: str = 'Roteiro multivozes',
                  pause_ms: int = DEFAULT_PAUSE_MS, script_id: str | None = None,
                  timeline_start: float = 0.0) -> MultiVoiceScript:
    parsed = parse_berofel_script(text)
    voices = validate_assignments(assignments, {line.voice_id for line in parsed})
    script = MultiVoiceScript(
        id=script_id or uuid.uuid4().hex, title=title.strip() or 'Roteiro multivozes',
        engine_id=engine_id, pause_ms=int(pause_ms), voices=voices, lines=parsed,
        timeline_start=max(0.0, float(timeline_start)))
    validate_script(script)
    return script


def validate_script(script: MultiVoiceScript) -> None:
    if script.schema_version != SCRIPT_SCHEMA_VERSION or script.format != SCRIPT_FORMAT:
        raise ScriptValidationError('Formato ou versão de roteiro não suportados.')
    if not _ID.fullmatch(script.id):
        raise ScriptValidationError('ID interno de roteiro inválido.')
    if not script.engine_id:
        raise ScriptValidationError('Selecione o motor de narração.')
    if not 0 <= script.pause_ms <= 60_000:
        raise ScriptValidationError('A pausa entre falas deve ficar entre 0 e 60.000 ms.')
    if script.timeline_start < 0:
        raise ScriptValidationError('A posição inicial da timeline não pode ser negativa.')
    if not script.lines:
        raise ScriptValidationError('O roteiro não contém falas.')
    identifiers: set[str] = set()
    numbers: set[int] = set()
    used_voices: set[str] = set()
    for line in script.lines:
        if not _ID.fullmatch(line.id) or line.id in identifiers:
            raise ScriptValidationError('O roteiro contém IDs de fala ausentes ou duplicados.')
        identifiers.add(line.id)
        if line.number <= 0 or line.number in numbers:
            raise ScriptValidationError(f'Número de fala inválido ou duplicado: {line.number}.')
        numbers.add(line.number)
        if line.voice_id not in _VOICE_IDS:
            raise ScriptValidationError(f'Identificador de voz inválido na fala {line.number:03d}.')
        if not line.text.strip():
            raise ScriptValidationError(f'A fala {line.number:03d} está vazia.')
        if line.status not in {'pending', 'generating', 'generated', 'error'}:
            raise ScriptValidationError(f'Estado inválido na fala {line.number:03d}.')
        if line.status == 'generated' and (not line.audio_path or line.duration <= 0):
            raise ScriptValidationError(f'A fala {line.number:03d} está marcada como pronta sem WAV válido.')
        used_voices.add(line.voice_id)
    voices = validate_assignments(script.voices, used_voices)
    script.voices = voices


def group_lines_by_voice(lines: Iterable[DialogueLine]) -> list[tuple[str, list[DialogueLine]]]:
    groups: dict[str, list[DialogueLine]] = {}
    for line in sorted(lines, key=lambda item: item.number):
        groups.setdefault(line.voice_id, []).append(line)
    return [(voice_id, groups[voice_id]) for voice_id in sorted(groups, key=_voice_order)]


def group_script_lines_by_profile(script: MultiVoiceScript) -> list[tuple[str, list[DialogueLine]]]:
    """Batch characters that share a saved voice profile to avoid needless switches."""
    groups: dict[str, list[DialogueLine]] = {}
    for line in sorted(script.lines, key=lambda item: item.number):
        profile_id = script.voices[line.voice_id]['profile_id']
        groups.setdefault(profile_id, []).append(line)
    order = {profile_id: min(_voice_order(line.voice_id) for line in lines)
             for profile_id, lines in groups.items()}
    return [(profile_id, groups[profile_id])
            for profile_id in sorted(groups, key=lambda item: order[item])]


def profile_ids_used_by_script(script: MultiVoiceScript) -> set[str]:
    """Return only profiles needed for actual lines, excluding unused slots."""
    validate_script(script)
    return {script.voices[line.voice_id]['profile_id'] for line in script.lines}


def reorder_lines(script: MultiVoiceScript, ordered_ids: Iterable[str]) -> None:
    ordered = list(ordered_ids)
    by_id = {line.id: line for line in script.lines}
    if len(ordered) != len(by_id) or set(ordered) != set(by_id):
        raise ScriptValidationError('A nova ordem deve conter todas as falas exatamente uma vez.')
    script.lines = [by_id[line_id] for line_id in ordered]
    for number, line in enumerate(script.lines, 1):
        line.number = number


def update_line_text(script: MultiVoiceScript, line_id: str, text: str) -> DialogueLine:
    line = next((item for item in script.lines if item.id == line_id), None)
    clean = str(text or '').strip()
    if line is None:
        raise KeyError(line_id)
    if not clean:
        raise ScriptValidationError(f'A fala {line.number:03d} não pode ficar vazia.')
    line.text = clean
    line.status = 'pending'
    # Keep the approved clip/WAV available until a replacement is generated
    # and committed to the timeline. Its cache key will naturally differ.
    line.error = ''
    return line


def profile_fingerprint(profile: Mapping) -> str:
    sample = Path(str(profile.get('sample_path', '') or '')).expanduser()
    if not sample.is_file():
        raise FileNotFoundError('A gravação de referência do perfil salvo não foi encontrada.')
    hasher = hashlib.sha256()
    with sample.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            hasher.update(chunk)
    return digest({'profile_id': str(profile.get('id', '')),
                   'sample_sha256': hasher.hexdigest(),
                   'reference_text': str(profile.get('reference_text', '')),
                   'model': MODEL_ID})


def script_generation_fingerprint(script: MultiVoiceScript) -> str:
    """Identify synthesis inputs so stale asynchronous results cannot replace edits."""
    used_voice_ids = {line.voice_id for line in script.lines}
    return digest({
        'id': script.id,
        'engine': script.engine_id,
        'pause_ms': script.pause_ms,
        'voices': {key: dict(script.voices[key])
                   for key in sorted(used_voice_ids) if key in script.voices},
        'lines': [{'id': line.id, 'number': line.number, 'voice_id': line.voice_id,
                   'character_name': line.character_name, 'text': line.text}
                  for line in sorted(script.lines, key=lambda item: item.number)],
    })


def synthesis_cache_key(line: DialogueLine, profile: Mapping, engine_id: str,
                        thread_count: int, engine_fingerprint: str = '',
                        voice_fingerprint: str = '') -> str:
    return digest({'schema': GENERATION_CACHE_SCHEMA, 'model': MODEL_ID,
                   'text': line.text, 'voice': voice_fingerprint or profile_fingerprint(profile),
                   'voice_id': line.voice_id, 'engine': engine_id,
                   'threads': int(thread_count), 'engine_fingerprint': engine_fingerprint,
                   'sampling': {'temperature': 0.5, 'top_k': 50, 'top_p': 1.0,
                                'rep_penalty': 1.05}})


def engine_cache_fingerprint(engine_id: str) -> str:
    """Cheap invalidation key for installed runtime/model binaries."""
    if engine_id in ('qwen3-tts-purec-mixed', 'qwen3-tts-purec-int8'):
        from .qwen3_purec_tts import _layout
        exe, model, _paths = _layout()
        candidates = (exe, model / 'config.json', model / 'model.safetensors',
                      model / 'speech_tokenizer' / 'model.safetensors')
    elif engine_id in ('qwen3-tts-native-q4', 'qwen3-tts-native-q4-balanced'):
        from .qwen3_native_tts import _layout
        candidates = _layout()
    elif engine_id == 'qwen3-tts-local':
        from .qwen3_tts_local import model_path, python_path, REQUIRED_MODEL_FILES
        model = model_path()
        candidates = (python_path(), *(model / name for name in REQUIRED_MODEL_FILES))
    else:
        candidates = ()
    identity = []
    for path in candidates:
        try:
            stat = Path(path).stat()
            identity.append((Path(path).name, stat.st_size, stat.st_mtime_ns))
        except OSError:
            identity.append((Path(path).name, None, None))
    return digest({'engine': engine_id, 'runtime': identity})


def _voice_order(voice_id: str) -> int:
    return int(str(voice_id)[1:])


def _wav_measure(path: Path) -> tuple[float, bool]:
    with wave.open(str(path), 'rb') as wav:
        rate, channels, width, frames = (wav.getframerate(), wav.getnchannels(),
                                         wav.getsampwidth(), wav.getnframes())
        if rate < 8_000 or channels < 1 or width not in (1, 2, 3, 4) or frames <= 0:
            raise ValueError('O backend produziu um WAV inválido ou vazio.')
        audible = False
        while not audible:
            block = wav.readframes(65_536)
            if not block:
                break
            if width == 1:
                audible = any(value != 128 for value in block)
            elif width == 2:
                audible = any(block[index] or block[index + 1]
                              for index in range(0, len(block) - 1, 2))
            else:
                audible = any(block)
        if not audible:
            raise ValueError('O backend produziu áudio silencioso; a fala não foi marcada como concluída.')
        return frames / rate, audible


def _cached_wav_valid(path: Path) -> tuple[float, bool]:
    try:
        return _wav_measure(path)
    except (OSError, EOFError, wave.Error, ValueError):
        return 0.0, False


def split_dialogue_text(text: str, max_chars: int = 800) -> list[str]:
    """Split oversized dialogue at sentence/word boundaries, keeping punctuation."""
    clean = str(text or '').strip()
    if len(clean) <= max_chars:
        return [clean] if clean else []
    sentences = re.split(r'(?<=[.!?;:])\s+', clean)
    chunks: list[str] = []
    current = ''
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        while len(sentence) > max_chars:
            cut = sentence.rfind(' ', 0, max_chars + 1)
            if cut <= 0:
                raise ScriptValidationError(
                    f'Um trecho de fala excede {max_chars} caracteres sem espaço para dividir com segurança.')
            part, sentence = sentence[:cut].strip(), sentence[cut:].strip()
            if current:
                chunks.append(current)
                current = ''
            chunks.append(part)
        candidate = f'{current} {sentence}'.strip() if current else sentence
        if len(candidate) > max_chars:
            if current:
                chunks.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def _merge_wavs(paths: list[Path], destination: Path, control=None) -> float:
    if not paths:
        raise ValueError('Não há partes de áudio para unir.')
    readers = [wave.open(str(path), 'rb') for path in paths]
    try:
        params = readers[0].getparams()
        if any((reader.getnchannels(), reader.getsampwidth(), reader.getframerate()) !=
               (params.nchannels, params.sampwidth, params.framerate) for reader in readers):
            raise ValueError('As partes da fala usam formatos WAV incompatíveis.')
        destination.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(destination), 'wb') as output:
            output.setparams(params)
            silence = b'\0' * (params.nchannels * params.sampwidth *
                                max(1, int(params.framerate * .06)))
            frames = 0
            for index, reader in enumerate(readers):
                if control:
                    control.checkpoint()
                block = reader.readframes(reader.getnframes())
                expected = reader.getnframes() * params.nchannels * params.sampwidth
                if len(block) != expected:
                    raise ValueError('Uma parte WAV ficou incompleta e não foi unida.')
                output.writeframes(block)
                frames += reader.getnframes()
                if index + 1 < len(readers):
                    output.writeframes(silence)
                    frames += len(silence) // (params.nchannels * params.sampwidth)
        return frames / params.framerate
    finally:
        for reader in readers:
            reader.close()


def _write_checkpoint(script: MultiVoiceScript, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.json.pending')
    temp.write_text(json.dumps(script.to_dict(), ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, path)


def save_script_checkpoint(script: MultiVoiceScript, project_path: str) -> Path:
    """Persist the current project-authored script as the canonical checkpoint."""
    root = persistent_folder(project_path) / 'roteiros' / script.id
    path = root / 'roteiro.json'
    script.checkpoint_path = str(path)
    _write_checkpoint(script, path)
    return path


def load_script_checkpoint(project_path: str, script_id: str,
                           expected_script: MultiVoiceScript | None = None) -> MultiVoiceScript | None:
    root = persistent_folder(project_path) / 'roteiros' / script_id
    canonical = root / 'roteiro.json'
    candidates = [canonical]
    if expected_script is not None:
        candidates.extend((root / 'runs').glob('*.json'))
    valid: list[tuple[int, Path, MultiVoiceScript]] = []
    expected_fingerprint = (script_generation_fingerprint(expected_script)
                            if expected_script is not None else '')
    for path in candidates:
        try:
            if not path.is_file():
                continue
            checkpoint = MultiVoiceScript.from_dict(
                json.loads(path.read_text(encoding='utf-8')))
            if checkpoint.id != script_id:
                continue
            if (expected_script is not None and
                    script_generation_fingerprint(checkpoint) != expected_fingerprint):
                continue
            valid.append((path.stat().st_mtime_ns, path, checkpoint))
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            continue
    restored = None
    if expected_script is not None:
        # Keep project-authored edits such as timeline position, title, and
        # unused profile slots; checkpoints contribute generated-state only.
        import copy
        restored = copy.deepcopy(expected_script)
        for line in restored.lines:
            if line.status != 'generated':
                continue
            saved_audio = Path(line.audio_path) if line.audio_path else None
            if saved_audio is None or not _cached_wav_valid(saved_audio)[1]:
                line.status = 'pending'
                line.audio_path = ''
                line.duration = 0.0
                line.error = 'O WAV salvo não existe ou está inválido; gere esta fala novamente.'
    if not valid:
        return restored
    _modified, path, checkpoint = max(valid, key=lambda item: item[0])
    if expected_script is not None:
        saved_lines = {line.id: line for line in checkpoint.lines}
        for line in restored.lines:
            saved = saved_lines.get(line.id)
            if saved is None:
                continue
            if saved.status == 'generated':
                saved_audio = Path(saved.audio_path) if saved.audio_path else None
                if saved_audio is None or not _cached_wav_valid(saved_audio)[1]:
                    # Keep any still-valid approved audio already in the project
                    # if a newer temporary run points to a damaged WAV.
                    continue
            for attribute in ('status', 'audio_path', 'duration', 'clip_id', 'cache_key',
                              'error', 'generation_seconds', 'model_load_seconds',
                              'profile_prepare_seconds', 'first_audio_seconds', 'cache_hit'):
                setattr(line, attribute, getattr(saved, attribute))
            if saved.status == 'generating':
                line.status = 'pending'
                line.error = 'A fila foi interrompida; retome o roteiro para continuar.'
        restored.total_seconds = checkpoint.total_seconds
        restored.first_audio_ready_seconds = checkpoint.first_audio_ready_seconds
        restored.checkpoint_path = str(canonical)
        return restored
    checkpoint.checkpoint_path = str(path)
    return checkpoint


def generate_script_audio(script: MultiVoiceScript, profiles: Mapping[str, Mapping],
                          project_path: str, control=None,
                          progress: Callable[[int, int], None] | None = None,
                          stage: Callable[[str], None] | None = None,
                          generator: Callable = generate_narration,
                          engine_fingerprint: str = '',
                          checkpoint_path: str | None = None) -> MultiVoiceScript:
    """Generate one independent WAV per line, grouped by voice, serially.

    The Pure C serving API pins a clone embedding at server startup. Lines in a
    voice group therefore share its warmed server; switching to the next voice
    is serialized by the existing singleton worker and may reload its model.
    This avoids simultaneous Qwen copies and per-line profile switches.
    """
    validate_script(script)
    configured: dict[str, Mapping] = {}
    used_voice_ids = {line.voice_id for line in script.lines}
    for voice_id, assignment in script.voices.items():
        if voice_id not in used_voice_ids:
            continue
        profile = profiles.get(assignment['profile_id'])
        if profile is None:
            raise ScriptValidationError(f'O perfil associado a {voice_id} não está disponível.')
        if not profile.get('authorized'):
            raise PermissionError(f'O perfil de {voice_id} precisa ter autorização de clonagem registrada.')
        if not Path(str(profile.get('sample_path', ''))).is_file():
            raise FileNotFoundError(f'A gravação do perfil de {voice_id} não foi encontrada.')
        configured[voice_id] = profile
    voice_fingerprints = {profile_id: profile_fingerprint(profile)
                          for profile_id, profile in {
                              script.voices[voice_id]['profile_id']: profile
                              for voice_id, profile in configured.items()}.items()}
    engine_fingerprint = engine_fingerprint or engine_cache_fingerprint(script.engine_id)

    output_root = persistent_folder(project_path) / 'roteiros' / script.id
    output_root.mkdir(parents=True, exist_ok=True)
    canonical_checkpoint = output_root / 'roteiro.json'
    selected_checkpoint = Path(checkpoint_path) if checkpoint_path else canonical_checkpoint
    try:
        selected_checkpoint.resolve().relative_to(output_root.resolve())
    except ValueError as exc:
        raise ValueError('O checkpoint do roteiro precisa ficar na pasta privada do próprio roteiro.') from exc
    script.checkpoint_path = str(selected_checkpoint)
    _write_checkpoint(script, Path(script.checkpoint_path))
    total = len(script.lines)
    started = time.perf_counter()
    script.total_seconds = 0.0
    script.first_audio_ready_seconds = 0.0
    done = 0
    by_id = {line.id: line for line in script.lines}
    original_order = [line.id for line in sorted(script.lines, key=lambda item: item.number)]
    for profile_id, voice_lines in group_script_lines_by_profile(script):
        voice_ids = sorted({line.voice_id for line in voice_lines}, key=_voice_order)
        if stage:
            stage(f'Lote {"/".join(voice_ids)} · {len(voice_lines)} fala(s)')
        voice_id = voice_ids[0]
        profile = configured[voice_id]
        assignment = script.voices[voice_id]
        if assignment['profile_id'] != profile_id:
            raise ScriptValidationError(f'O lote de voz associado a {voice_id} está inconsistente.')
        if str(profile.get('id', '')) != assignment['profile_id']:
            # Profile managers return IDs, but reject stale/mismatched maps instead
            # of silently generating with a similarly named voice.
            raise ScriptValidationError(f'O perfil de voz atribuído a {voice_id} não corresponde à seleção salva.')
        for line in voice_lines:
            if control:
                control.checkpoint()
            line.status = 'generating'
            line.error = ''
            thread_count = 6 if script.engine_id in ('qwen3-tts-purec-mixed',
                                                       'qwen3-tts-purec-int8') else 0
            cache_key = synthesis_cache_key(line, profile, script.engine_id,
                                            thread_count or 6, engine_fingerprint,
                                            voice_fingerprints[assignment['profile_id']])
            target = output_root / f'{line.id}_{cache_key[:16]}.wav'
            duration, valid = _cached_wav_valid(target)
            line.cache_hit = valid
            if not valid:
                target.unlink(missing_ok=True)
                segments = split_dialogue_text(line.text)
                chunk_root = output_root / 'chunks'
                chunk_root.mkdir(parents=True, exist_ok=True)
                chunk_paths: list[Path] = []
                all_chunk_hits = True
                line.generation_seconds = 0.0
                line.model_load_seconds = 0.0
                line.profile_prepare_seconds = 0.0
                line.first_audio_seconds = 0.0
                try:
                    for chunk_index, chunk_text in enumerate(segments, 1):
                        if control:
                            control.checkpoint()
                        segment_line = DialogueLine(id=line.id, number=line.number,
                                                    voice_id=line.voice_id, text=chunk_text)
                        segment_key = synthesis_cache_key(
                            segment_line, profile, script.engine_id, thread_count or 6,
                            engine_fingerprint, voice_fingerprints[assignment['profile_id']])
                        segment_path = chunk_root / f'{line.id}_{segment_key[:16]}.wav'
                        _segment_duration, segment_valid = _cached_wav_valid(segment_path)
                        if not segment_valid:
                            all_chunk_hits = False
                            segment_path.unlink(missing_ok=True)
                            if stage and len(segments) > 1:
                                stage(f'Fala {line.number:03d} · parte {chunk_index}/{len(segments)}')
                            request = NarrationRequest(
                                text=chunk_text, voice=str(profile['sample_path']),
                                language=str(profile.get('language', 'portuguese')),
                                consent=True, project_path=project_path,
                                title=f'{script.id[:8]}_{line.number:04d}_{line.id[:8]}_p{chunk_index:03d}',
                                engine=script.engine_id,
                                reference_text=str(profile.get('reference_text', '') or ''),
                                thread_count=(6 if script.engine_id in ('qwen3-tts-purec-mixed',
                                                                         'qwen3-tts-purec-int8') else None))
                            result = generator(request, control=control, stage=stage)
                            line.generation_seconds += max(0.0, float(result.get('generation_seconds', 0.0) or 0.0))
                            line.model_load_seconds += max(0.0, float(result.get('model_load_seconds', 0.0) or 0.0))
                            line.profile_prepare_seconds += max(0.0, float(result.get('profile_prepare_seconds', 0.0) or 0.0))
                            first_audio = float(result.get('first_audio_chunk_seconds',
                                                           result.get('first_audio_seconds', 0.0)) or 0.0)
                            if line.first_audio_seconds <= 0 and first_audio > 0:
                                line.first_audio_seconds = first_audio
                            source = Path(result['path'])
                            _source_duration, source_valid = _cached_wav_valid(source)
                            if not source_valid:
                                raise ValueError(f'A parte {chunk_index} da fala {line.number:03d} não produziu WAV válido.')
                            temp = segment_path.with_suffix('.pending.wav')
                            try:
                                shutil.copyfile(source, temp)
                                _wav_measure(temp)
                                os.replace(temp, segment_path)
                            finally:
                                temp.unlink(missing_ok=True)
                            if not result.get('cache_hit') and source.resolve() != segment_path.resolve():
                                source.unlink(missing_ok=True)
                        chunk_paths.append(segment_path)
                        _write_checkpoint(script, Path(script.checkpoint_path))
                    line.cache_hit = all_chunk_hits
                    if len(chunk_paths) == 1:
                        shutil.copyfile(chunk_paths[0], target)
                    else:
                        _merge_wavs(chunk_paths, target, control=control)
                    duration, valid = _cached_wav_valid(target)
                    if not valid:
                        raise ValueError(f'A fala {line.number:03d} falhou na validação após unir as partes.')
                except Exception as exc:
                    line.status = 'pending' if control and control.cancelled else 'error'
                    line.error = str(exc)[:1000]
                    _write_checkpoint(script, Path(script.checkpoint_path))
                    raise
            line.status = 'generated'
            line.audio_path = str(target)
            line.duration = duration
            line.cache_key = cache_key
            line.error = ''
            done += 1
            if script.first_audio_ready_seconds <= 0:
                script.first_audio_ready_seconds = time.perf_counter() - started
            if progress:
                progress(done, total)
            _write_checkpoint(script, Path(script.checkpoint_path))
    script.lines = [by_id[line_id] for line_id in original_order]
    script.total_seconds = time.perf_counter() - started
    validate_script(script)
    _write_checkpoint(script, Path(script.checkpoint_path))
    return script

