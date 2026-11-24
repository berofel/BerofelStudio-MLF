"""Canonical narration API backed exclusively by local Qwen3-TTS Base."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
import time
from typing import Callable

LANGUAGES = (
    # Qwen3-TTS exposes the language token Portuguese (no dialect-specific
    # PT-BR token); the selected reference voice supplies the regional accent.
    ('Português brasileiro (PT-BR)', 'portuguese'), ('English', 'english'),
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
    reference_text_reviewed: bool = False
    thread_count: int | None = None


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


def validate_clone_conditioning(request: NarrationRequest) -> None:
    """Validate the conditioning required by the explicitly selected backend.

    Qwen3 exposes only the generic ``Portuguese`` language token. Regional
    accent is therefore anchored by the reference speech and its transcript.
    Pure C is an explicit speed path: it accepts only an x-vector. Original
    uses the full audio+transcript conditioning. Native Q4 remains blocked for
    PT-BR until its language/accent behavior is separately validated.
    """
    if request.language != 'portuguese':
        return
    if request.engine in ('qwen3-tts-purec-mixed', 'qwen3-tts-purec-int8'):
        return
    if request.engine != 'qwen3-tts-local':
        raise ValueError(
            'Este backend ainda não foi validado para clonagem PT-BR. Selecione '
            'Original Qwen3-TTS Base ou um perfil Pure C explicitamente identificado.'
        )
    if not str(request.reference_text or '').strip():
        raise ValueError(
            'A clonagem PT-BR precisa da transcrição exata da janela de referência. '
            'Use “Transcrever referência”, revise o texto e tente novamente. Sem a '
            'transcrição, o Qwen usa apenas o vetor vocal e pode gerar pronúncia genérica.'
        )
    if not request.reference_text_reviewed:
        raise ValueError(
            'A transcrição PT-BR ainda não foi confirmada. Confira o texto da janela '
            'vocal e marque “Conferi que a transcrição corresponde à janela vocal '
            'selecionada” antes de gerar ou salvar o perfil.'
        )


def generate_narration(request: NarrationRequest, progress: Callable | None = None,
                       runner: Callable | None = None, control=None,
                       stage=None, audio_chunk: Callable | None = None) -> dict:
    """Generate a non-destructive, local WAV using the sole supported TTS engine."""
    if request.engine in ('qwen3-tts-native-q4','qwen3-tts-native-q4-balanced'):
        from .qwen3_native_tts import generate_native_clone
        return generate_native_clone(request,progress=progress,runner=runner,
                                     control=control,stage=stage,
                                     audio_chunk=audio_chunk)
    if request.engine in ('qwen3-tts-purec-mixed','qwen3-tts-purec-int8'):
        from .qwen3_purec_tts import generate_purec_clone
        return generate_purec_clone(request,progress=progress,runner=runner,
                                    control=control,stage=stage,
                                    audio_chunk=audio_chunk)
    if request.engine != 'qwen3-tts-local':
        raise ValueError('O BerofelStudio usa exclusivamente Qwen3-TTS Base para narração.')
    validate_clone_conditioning(request)
    validate_request(request.text,request.voice,request.language,request.consent)
    from .qwen3_tts_local import generate_local_clone
    return generate_local_clone(request,progress=progress,runner=runner,
                                control=control,stage=stage)
