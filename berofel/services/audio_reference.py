"""Shared, non-destructive audio-reference normalization for local models."""
from __future__ import annotations

from pathlib import Path
from functools import lru_cache
import re
import tempfile
import subprocess
import threading
from bisect import bisect_right

import numpy as np
from scipy.io import wavfile

_PROMPT_MAX_SECONDS = 30.0
REFERENCE_PREPARATION_VERSION = 2
_SILENCE_THRESHOLD_DB = -38
_SILENCE_MIN_SECONDS = .35
_REFERENCE_SCAN_LOCK=threading.RLock()


@lru_cache(maxsize=32)
def _best_reference_window(path: str, size: int, mtime_ns: int) -> tuple[float, float, float]:
    """Scan the full source for quiet gaps and choose its cleanest 30 s window.

    This is an acoustic activity scan, not voice recognition: background music
    may count as activity. It deliberately does not load the whole recording
    into RAM or pass a long recording to Qwen.
    """
    source = Path(path)
    from .ffmpeg import ffmpeg_path, media_info
    binary = ffmpeg_path()
    duration, _has_video, has_audio = media_info(str(source))
    if not has_audio or duration <= 0:
        raise ValueError('A referência não contém uma faixa de áudio válida.')
    duration = float(duration)
    lengths = sorted({min(duration, candidate) for candidate in
                      (_PROMPT_MAX_SECONDS, 20.0, 15.0, 10.0, 6.0, 3.0)
                      if min(duration, candidate) > 0}, reverse=True)
    speech_regions=_silero_speech_regions(source,binary,duration)
    if speech_regions:
        active_regions=speech_regions
    else:
        command = [binary, '-hide_banner', '-nostdin', '-i', str(source), '-vn',
            '-af', f'silencedetect=noise={_SILENCE_THRESHOLD_DB}dB:d={_SILENCE_MIN_SECONDS}',
            '-f', 'null', '-']
        try:
            result = subprocess.run(command, capture_output=True, text=True,
                encoding='utf-8', errors='replace', timeout=max(120, int(duration * 2)),
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError('A análise acústica da referência excedeu o tempo limite.') from exc
        if result.returncode and 'silence_' not in result.stderr:
            raise RuntimeError('Não foi possível analisar o áudio da referência: ' + result.stderr[-500:])
        silences: list[tuple[float, float]] = []
        opened: float | None = None
        for line in result.stderr.splitlines():
            start_match = re.search(r'silence_start:\s*(-?[\d.]+)', line)
            end_match = re.search(r'silence_end:\s*(-?[\d.]+)', line)
            if start_match:opened = max(0.0, float(start_match.group(1)))
            if end_match and opened is not None:
                end = min(float(duration), float(end_match.group(1)))
                if end > opened:silences.append((opened, end))
                opened = None
        if opened is not None:silences.append((opened, float(duration)))
        cursor=0.0;active_regions=[]
        for silent_start,silent_end in silences:
            if silent_start>cursor:active_regions.append((cursor,silent_start))
            cursor=max(cursor,silent_end)
        if cursor<duration:active_regions.append((cursor,duration))
    merged=[]
    for start,end in sorted(active_regions):
        if end<=start:continue
        if merged and start<=merged[-1][1]:
            merged[-1]=(merged[-1][0],max(merged[-1][1],end))
        else:merged.append((start,end))
    active_regions=merged
    region_starts=[start for start,_end in active_regions]
    candidates: set[tuple[float, float]] = set()
    for length in lengths:
        candidates.update(((0.0, length), (max(0.0, duration - length), length)))
    for start, end in active_regions:
        for length in lengths:
            candidates.update((max(0.0, min(duration - length, point)), length)
                              for point in (start, end, start - length, end - length))

    def active_seconds(window_start: float, length: float) -> float:
        window_end = window_start + length
        index=max(0,bisect_right(region_starts,window_start)-1)
        total=0.0
        while index<len(active_regions):
            start,end=active_regions[index]
            if start>=window_end:break
            total+=max(0.0,min(window_end,end)-max(window_start,start))
            index+=1
        return min(length,total)

    chosen, length = max(candidates, key=lambda item: (
        active_seconds(*item), active_seconds(*item) / item[1], item[1], -item[0]))
    return chosen, length, active_seconds(chosen, length) / length


def _reference_window(source: Path) -> tuple[float, float, float]:
    stat = source.stat()
    with _REFERENCE_SCAN_LOCK:
        return _best_reference_window(str(source.resolve()), stat.st_size, stat.st_mtime_ns)


def _silero_speech_regions(source: Path, binary: str, duration: float):
    """Use the already-installed Silero VAD in bounded chunks when available."""
    try:
        from faster_whisper.vad import VadOptions, get_speech_timestamps
        options=VadOptions(threshold=.5,min_speech_duration_ms=250,
                           min_silence_duration_ms=350,speech_pad_ms=120)
    except ImportError:
        return None
    rate=16000;chunk_samples=rate*30;regions=[];process=None;offset=0
    command=[binary,'-hide_banner','-loglevel','error','-nostdin','-i',str(source),
        '-map','0:a:0','-vn','-ac','1','-ar',str(rate),'-f','f32le','-acodec','pcm_f32le','-']
    try:
        process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        while True:
            raw=process.stdout.read(chunk_samples*4)
            if not raw:break
            audio=np.frombuffer(raw[:len(raw)//4*4],dtype='<f4').copy()
            if audio.size:
                for span in get_speech_timestamps(audio,vad_options=options,sampling_rate=rate):
                    start=offset+int(span['start']);end=offset+int(span['end'])
                    if end>start:regions.append((start/rate,min(duration,end/rate)))
            offset+=len(audio)
        process.communicate(timeout=30)
        if process.returncode:raise RuntimeError('Silero não conseguiu analisar a referência.')
    except Exception:
        if process is not None and process.poll() is None:
            process.kill();process.communicate()
        return None
    return regions


def voice_reference_warnings(report: dict) -> list[str]:
    """Return actionable, non-blocking guidance for a voice sample report.

    The UI has historically surfaced a note at 30% near-silence while the
    audio analyzer's stronger warning began above 50%. Keep those paths
    consistent without rejecting or modifying the user's reference.
    """
    warnings=[str(item) for item in (report.get('warnings') or ())]
    try:
        silence_fraction=float(report.get('silence_fraction',0.0))
    except (TypeError,ValueError):
        silence_fraction=0.0
    if silence_fraction>=.30 and not any('silenc' in item.casefold()
                                         for item in warnings):
        warnings.append('Parte significativa da amostra está quase silenciosa; prefira uma fala mais contínua para uma clonagem mais estável.')
    return warnings


def prepare_audio_prompt(voice: str,output_path: str | Path,
                        ffmpeg: str | None=None, *, start_seconds: float | None=None,
                        duration_seconds: float | None=None) -> tuple[str,Path | None]:
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
    if start_seconds is None:
        start, length, _active_fraction = _reference_window(source)
    else:
        from .ffmpeg import media_info
        source_duration=float(media_info(str(source))[0])
        start=max(0.0,min(float(start_seconds),max(0.0,source_duration-.01)))
        length=min(float(duration_seconds or _PROMPT_MAX_SECONDS),
                   _PROMPT_MAX_SECONDS,source_duration-start)
        if length<=0:raise ValueError('A janela de referência selecionada está fora do arquivo.')
    command=[ffmpeg,'-hide_banner','-loglevel','error','-nostdin','-y',
        '-ss',f'{start:.3f}','-i',str(source),'-map','0:a:0','-vn','-t',f'{length:.3f}','-ac','1','-ar','24000',
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
        quiet=np.abs(signal)<.005
        silence=float(np.mean(quiet))
        audible_signal_seconds=float(np.count_nonzero(~quiet)/float(rate))
        warnings=[]
        if duration<3: warnings.append('Amostra curta; grave ao menos 3 segundos de fala contínua.')
        selected_start, _window_length, active_fraction = _reference_window(source)
        from .ffmpeg import media_info
        source_duration = float(media_info(str(source))[0])
        if source_duration > _PROMPT_MAX_SECONDS:
            warnings.append('O arquivo inteiro foi analisado para localizar uma janela de até 30 segundos com menos silêncio; o Qwen condiciona a voz nessa janela, não aprende com o arquivo inteiro.')
        if rms_dbfs<-35: warnings.append('Nível muito baixo; aumente o volume da gravação antes de clonar.')
        if clipped>.01: warnings.append('Há clipping perceptível; reduza o ganho e grave novamente se possível.')
        if silence>.50: warnings.append('Mais de 50% do trecho está quase silencioso; escolha uma fala mais contínua ou grave uma amostra com menos pausas.')
        return {'duration':duration,'source_duration':source_duration,
                'selected_start':float(selected_start),'active_fraction':float(active_fraction),
                'sample_rate':int(rate),'rms_dbfs':float(rms_dbfs),
                'audible_signal_seconds':audible_signal_seconds,
                'peak_dbfs':float(20*np.log10(max(peak,1e-12))),
                'clipped_fraction':clipped,'silence_fraction':silence,
                'warnings':warnings}
