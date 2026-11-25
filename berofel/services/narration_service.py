"""Canonical narration API backed exclusively by local Qwen3-TTS Base."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import re
import subprocess
import tempfile
import time
import wave
from typing import Callable

from .ai_cache import digest
from .voice_intelligence.text_normalizer import NORMALIZER_VERSION, normalize_pt_br
from .voice_intelligence.narrative_interpreter import plan_narrative_interpretation
from .voice_intelligence.pronunciation_dictionary import (
    PronunciationDictionary, apply_pronunciations,
)

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
    # Experimental Pure C 0.6B voice-style transfer. The reference must be
    # authorized and its exact transcript reviewed; normal TTS stays unchanged.
    emotion_by_example: bool = False


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
    purec_engines = ('qwen3-tts-purec-mixed', 'qwen3-tts-purec-int8')
    if request.emotion_by_example:
        if request.engine not in purec_engines:
            raise ValueError('A transferência de estilo por referência exige um perfil Pure C 0.6B.')
        if not str(request.reference_text or '').strip():
            raise ValueError('Transcreva a referência de estilo com Parakeet e revise o texto antes de usar este modo experimental.')
        if not request.reference_text_reviewed:
            raise ValueError('Confirme que a transcrição corresponde ao áudio da referência de estilo.')
    if request.language != 'portuguese':
        return
    if request.engine in purec_engines:
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


# Pure C's packaged HTTP endpoint does not expose max_new_tokens. Keep its
# requests below the observed endpoint budget. The official and native APIs do
# expose a token budget, so they can accept much longer single requests.
_TEXT_CHUNK_CHARS = {
    'qwen3-tts-purec-mixed': 1200,
    'qwen3-tts-purec-int8': 1200,
    'qwen3-tts-local': 4800,
    'qwen3-tts-native-q4': 4800,
    'qwen3-tts-native-q4-balanced': 4800,
}


def qwen_output_token_budget(text: str) -> int:
    """Estimate a bounded output-token budget; never restore the old 2048 cap."""
    return min(8192, max(96, int(len(str(text or '').strip()) * 1.5 + 64)))


def _split_narration_text(text: str, limit: int) -> list[str]:
    """Split long narration at sentence/word boundaries, never mid-word."""
    text = str(text or '').strip()
    if len(text) <= limit:
        return [text]
    sentences = re.split(r'(?<=[.!?…])\s+|\n+', text)
    chunks: list[str] = []
    current = ''
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        while len(sentence) > limit:
            # Prefer punctuation inside an unusually long sentence, then the
            # nearest whitespace before the limit. Never split a token.
            punctuation = max((sentence.rfind(mark, 0, limit + 1)
                               for mark in (',', ';', ':')), default=-1)
            if punctuation >= limit // 2:
                boundary = punctuation + 1  # Keep punctuation with the preceding phrase.
            else:
                boundary = sentence.rfind(' ', 0, limit + 1)
                if boundary <= 0:
                    boundary = sentence.find(' ', limit)
            if boundary <= 0:
                raise ValueError('Não foi possível dividir o texto em um limite seguro de palavra.')
            piece, sentence = sentence[:boundary].strip(), sentence[boundary:].strip()
            if piece:
                if current:
                    chunks.append(current)
                    current = ''
                chunks.append(piece)
        candidate = f'{current} {sentence}'.strip() if current else sentence
        if len(candidate) <= limit:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = sentence
    if current:
        chunks.append(current)
    return chunks


def _merge_narration_wavs(paths: list[str], destination: Path, control=None) -> float:
    """Join generated chunks into one continuous WAV without loading it all in RAM."""
    if not paths:
        raise RuntimeError('A geração longa não produziu nenhum trecho de áudio.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    pending = destination.with_name(destination.stem + '.pending.wav')
    duration = 0.0
    try:
        with wave.open(paths[0], 'rb') as first:
            params = first.getparams()
            if params.nframes <= 0:
                raise RuntimeError('Um trecho de narração está vazio.')
            with wave.open(str(pending), 'wb') as output:
                output.setparams(params)
                for path in paths:
                    if control:
                        control.checkpoint()
                    with wave.open(path, 'rb') as part:
                        actual = part.getparams()
                        if (actual.nchannels, actual.sampwidth, actual.framerate,
                                actual.comptype) != (params.nchannels, params.sampwidth,
                                                     params.framerate, params.comptype):
                            raise RuntimeError('Os trechos foram gerados em formatos WAV incompatíveis; o áudio original foi preservado.')
                        while True:
                            if control:
                                control.checkpoint()
                            frames = part.readframes(65536)
                            if not frames:
                                break
                            output.writeframesraw(frames)
                        duration += actual.nframes / actual.framerate
        os.replace(pending, destination)
    except Exception:
        pending.unlink(missing_ok=True)
        raise
    if duration <= 0 or destination.stat().st_size <= 44:
        destination.unlink(missing_ok=True)
        raise RuntimeError('O WAV consolidado está vazio ou inválido.')
    return duration


def _generate_long_narration(request: NarrationRequest, chunks: list[str],
                             progress=None, runner=None, control=None,
                             stage=None, audio_chunk=None) -> dict:
    """Generate bounded requests sequentially and return one reusable WAV."""
    from dataclasses import replace
    destination_folder = persistent_folder(request.project_path)
    destination_folder.mkdir(parents=True, exist_ok=True)
    generated: list[str] = []
    results: list[dict] = []
    with tempfile.TemporaryDirectory(prefix='bfs_narration_parts_') as scratch:
        for index, text in enumerate(chunks, 1):
            if control:
                control.checkpoint()
            if stage:
                stage(f'Narração longa · trecho {index}/{len(chunks)} · mesmo perfil vocal')
            part_request = replace(request, text=text, title=f'{request.title}_parte_{index:04d}',
                                   project_path=str(Path(scratch) / f'part_{index:04d}.bfs'))
            def part_progress(done, total, *, part=index):
                if progress and total:
                    progress((part - 1) * total + done, len(chunks) * total)
            part = generate_narration(part_request, progress=part_progress,
                runner=runner, control=control, stage=stage, audio_chunk=audio_chunk,
                _prepared_text=True)
            path = str(part.get('path', ''))
            if not path or not Path(path).is_file():
                raise RuntimeError(f'A síntese do trecho {index}/{len(chunks)} não criou um WAV válido.')
            generated.append(path)
            results.append(part)
        stamp = time.strftime('%Y%m%d_%H%M%S')
        suffix = digest({'text': request.text.strip(), 'voice': request.voice,
                         'engine': request.engine, 'language': request.language})[:8]
        safe_title = ''.join(ch if ch.isalnum() or ch in '-_' else '_'
                             for ch in request.title.strip())[:48] or 'Narracao'
        destination = destination_folder / f'{safe_title}_{stamp}_{suffix}_completa.wav'
        duplicate = 1
        while destination.exists():
            destination = destination_folder / f'{safe_title}_{stamp}_{suffix}_completa_{duplicate}.wav'
            duplicate += 1
        duration = _merge_narration_wavs(generated, destination, control)
    return {'path': str(destination), 'duration': duration,
        'cache_hit': all(bool(item.get('cache_hit')) for item in results),
        'prompt_cache_hit': all(bool(item.get('prompt_cache_hit')) for item in results),
        'conditioning_mode': results[0].get('conditioning_mode'),
        'engine': request.engine, 'threads': request.thread_count,
        'title': request.title, 'voice': request.voice, 'language': request.language,
        'emotion_by_example': bool(request.emotion_by_example),
        'chunk_count': len(chunks), 'continuous_wav': True,
        'generation_seconds': sum(float(item.get('generation_seconds', 0.0)) for item in results)}


def generate_narration(request: NarrationRequest, progress: Callable | None = None,
                       runner: Callable | None = None, control=None,
                       stage=None, audio_chunk: Callable | None = None,
                       _prepared_text: bool = False) -> dict:
    """Generate a non-destructive, local WAV using the sole supported TTS engine."""
    if request.engine not in _TEXT_CHUNK_CHARS:
        raise ValueError('O BerofelStudio usa exclusivamente Qwen3-TTS Base para narração.')
    source_text = request.text
    # Long narration recursively enters this function once per bounded Qwen
    # request. The whole-script interpretation is attached by the outer call;
    # repeating the deterministic linguistic pass for every chunk wastes CPU
    # and can produce inconsistent per-chunk metadata.
    interpretation = (plan_narrative_interpretation(source_text)
                      if request.language == 'portuguese' and not _prepared_text
                      else None)
    pronunciation_terms: tuple[str, ...] = ()
    if _prepared_text:
        # Long narration already normalized the full source before splitting;
        # applying pronunciation rules again to each chunk can cascade aliases.
        speech_text = source_text
    else:
        pronunciation_text = source_text
        if (request.language == 'portuguese' and request.voice and
                Path(request.voice).expanduser().is_file()):
            dictionary = PronunciationDictionary(request.voice)
            entries = dictionary.load()
            pronunciation_text, pronunciation_terms = apply_pronunciations(
                source_text, entries, language=request.language)
        speech_text = (normalize_pt_br(pronunciation_text).spoken
                       if request.language == 'portuguese' else source_text.strip())
    if speech_text != request.text:
        from dataclasses import replace
        request = replace(request, text=speech_text)
    chunks = _split_narration_text(request.text, _TEXT_CHUNK_CHARS[request.engine])
    if len(chunks) > 1:
        validate_clone_conditioning(request)
        validate_request(request.text, request.voice, request.language, request.consent)
        result = _generate_long_narration(request, chunks, progress, runner,
                                          control, stage, audio_chunk)
        result.update({'source_text': source_text, 'spoken_text': speech_text,
                       'pronunciation_terms_applied': pronunciation_terms,
                       'text_normalizer_version': NORMALIZER_VERSION,
                       'narrative_interpretation': interpretation})
        return result
    if request.engine in ('qwen3-tts-native-q4','qwen3-tts-native-q4-balanced'):
        from .qwen3_native_tts import generate_native_clone
        result = generate_native_clone(request,progress=progress,runner=runner,
                                       control=control,stage=stage,
                                       audio_chunk=audio_chunk)
    elif request.engine in ('qwen3-tts-purec-mixed','qwen3-tts-purec-int8'):
        from .qwen3_purec_tts import generate_purec_clone
        result = generate_purec_clone(request,progress=progress,runner=runner,
                                      control=control,stage=stage,
                                      audio_chunk=audio_chunk)
    else:
        validate_clone_conditioning(request)
        validate_request(request.text,request.voice,request.language,request.consent)
        from .qwen3_tts_local import generate_local_clone
        result = generate_local_clone(request,progress=progress,runner=runner,
                                      control=control,stage=stage)
    result.update({'source_text': source_text, 'spoken_text': speech_text,
                   'pronunciation_terms_applied': pronunciation_terms,
                   'text_normalizer_version': NORMALIZER_VERSION,
                   'narrative_interpretation': interpretation})
    return result
