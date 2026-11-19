"""Shared, non-destructive audio-reference normalization for local models."""
from __future__ import annotations

from pathlib import Path
import subprocess


def prepare_audio_prompt(voice: str,output_path: str | Path,
                        ffmpeg: str | None=None) -> tuple[str,Path | None]:
    """Convert an audio file to a short mono PCM16/24 kHz WAV for local TTS."""
    source=Path(voice)
    if not source.is_file():
        raise FileNotFoundError('A gravação de referência não foi encontrada.')
    if source.suffix.lower() not in {'.wav','.mp3','.flac','.ogg','.m4a'}:
        raise ValueError('Use WAV, MP3, FLAC, OGG ou M4A como referência de voz.')
    target=Path(output_path);target.parent.mkdir(parents=True,exist_ok=True)
    if ffmpeg is None:
        from .ffmpeg import ffmpeg_path
        ffmpeg=ffmpeg_path()
    command=[ffmpeg,'-hide_banner','-loglevel','error','-nostdin','-y',
        '-i',str(source),'-map','0:a:0','-vn','-t','30','-ac','1','-ar','24000',
        '-c:a','pcm_s16le',str(target)]
    try:
        result=subprocess.run(command,capture_output=True,text=True,
            encoding='utf-8',errors='replace',
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode or not target.is_file() or target.stat().st_size<=44:
            target.unlink(missing_ok=True)
            raise RuntimeError('Não foi possível converter a referência de voz para WAV PCM.')
        return str(target),target
    except Exception:
        target.unlink(missing_ok=True)
        raise
