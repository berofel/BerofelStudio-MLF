"""Shared, non-destructive audio-reference normalization for local models."""
from __future__ import annotations

from pathlib import Path
import tempfile
import subprocess

import numpy as np
from scipy.io import wavfile


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


def inspect_voice_reference(voice: str | Path) -> dict:
    """Measure a local reference sample before cloning, without changing it."""
    source=Path(voice).expanduser()
    if not source.is_file():
        raise FileNotFoundError('A gravação de referência não foi encontrada.')
    with tempfile.TemporaryDirectory(prefix='bfs_voice_check_') as folder:
        normalized,_=prepare_audio_prompt(source,Path(folder)/'reference.wav')
        rate,pcm=wavfile.read(normalized)
        data=np.asarray(pcm,dtype=np.float64).reshape(-1)
        if data.size==0 or not np.isfinite(data).all():
            raise ValueError('A gravação não contém áudio PCM válido.')
        if np.issubdtype(pcm.dtype,np.integer):
            scale=float(max(abs(np.iinfo(pcm.dtype).min),np.iinfo(pcm.dtype).max))
            signal=data/scale
        else:
            signal=data
        duration=len(signal)/float(rate)
        peak=float(np.max(np.abs(signal)))
        rms=float(np.sqrt(np.mean(signal*signal)))
        rms_dbfs=20*np.log10(max(rms,1e-12))
        clipped=float(np.mean(np.abs(signal)>=.999))
        silence=float(np.mean(np.abs(signal)<.005))
        warnings=[]
        if duration<3: warnings.append('Amostra curta; grave ao menos 3 segundos de fala contínua.')
        if duration>30: warnings.append('A preparação usa no máximo os primeiros 30 segundos.')
        if rms_dbfs<-35: warnings.append('Nível muito baixo; aumente o volume da gravação antes de clonar.')
        if clipped>.01: warnings.append('Há clipping perceptível; reduza o ganho e grave novamente se possível.')
        if silence>.50: warnings.append('Mais de 50% do trecho está quase silencioso; escolha uma fala mais contínua ou grave uma amostra com menos pausas.')
        return {'duration':duration,'sample_rate':int(rate),'rms_dbfs':float(rms_dbfs),
                'peak_dbfs':float(20*np.log10(max(peak,1e-12))),
                'clipped_fraction':clipped,'silence_fraction':silence,
                'warnings':warnings}
