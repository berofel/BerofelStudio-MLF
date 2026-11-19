"""Canonical narration API backed exclusively by local Qwen3-TTS Base."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
import time
from typing import Callable

LANGUAGES = (
    ('Português', 'portuguese'), ('English', 'english'),
    ('Español', 'spanish'), ('Français', 'french'),
    ('Italiano', 'italian'), ('Deutsch', 'german'),
)


@dataclass(frozen=True)
class NarrationRequest:
    text: str
    voice: str
    language: str = 'portuguese'
    consent: bool = False
    quantize: bool = False  # Compatibility only; Base runs at the validated CPU precision.
    project_path: str = ''
    title: str = 'Narração'
    engine: str = 'qwen3-tts-local'
    reference_text: str = ''


def persistent_folder(project_path: str = '') -> Path:
    if project_path:
        project = Path(project_path).expanduser().resolve()
        return project.parent / (project.stem + '_arquivos') / 'narracoes'
    return Path.home() / 'Documents' / 'BerofelStudio' / 'Narracoes'


def _process_flags() -> int:
    return getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def validate_request(text: str, voice: str, language: str,
                     consent: bool = False) -> None:
    if not str(text or '').strip():
        raise ValueError('Digite um texto para narrar.')
    if language not in {code for _, code in LANGUAGES}:
        raise ValueError('Idioma não suportado pelo Qwen3-TTS Base.')
    if not voice:
        raise ValueError('Escolha um perfil de voz local.')
    sample=Path(voice).expanduser()
    if sample.suffix.lower() not in {'.wav','.mp3','.flac','.ogg','.m4a'}:
        raise ValueError('A referência precisa ser WAV, MP3, FLAC, OGG ou M4A.')
    if not sample.is_file():
        raise FileNotFoundError('A gravação de referência não foi encontrada.')
    if sample.stat().st_size <= 44:
        raise ValueError('A gravação de referência está vazia ou incompleta.')
    if not consent:
        raise PermissionError('Confirme que possui autorização para usar esta voz.')


def generate_narration(request: NarrationRequest, progress: Callable | None = None,
                       runner: Callable | None = None, control=None,
                       stage=None, audio_chunk: Callable | None = None) -> dict:
    """Generate a non-destructive, local WAV using the sole supported TTS engine."""
    if request.engine == 'qwen3-tts-native-q4':
        from .qwen3_native_tts import generate_native_clone
        return generate_native_clone(request,progress=progress,runner=runner,
                                     control=control,stage=stage,
                                     audio_chunk=audio_chunk)
    if request.engine != 'qwen3-tts-local':
        raise ValueError('O BerofelStudio usa exclusivamente Qwen3-TTS Base para narração.')
    validate_request(request.text,request.voice,request.language,request.consent)
    from .qwen3_tts_local import generate_local_clone
    return generate_local_clone(request,progress=progress,runner=runner,
                                control=control,stage=stage)
