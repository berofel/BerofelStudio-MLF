"""Shared, non-destructive audio-reference normalization for local models."""
from __future__ import annotations

from pathlib import Path
from functools import lru_cache
from array import array
import math
import re
import sys
import tempfile
import subprocess
import threading
from bisect import bisect_right

_PROMPT_MAX_SECONDS = 30.0
REFERENCE_PREPARATION_VERSION = 5
_SILENCE_THRESHOLD_DB = -38
_SILENCE_MIN_SECONDS = .35
_REFERENCE_SCAN_LOCK=threading.RLock()


def _candidate_acoustic_metrics(source: Path, binary: str,
                                start: float, duration: float) -> dict | None:
    """Measure a bounded candidate window without retaining the whole source."""
    command = [binary, '-hide_banner', '-loglevel', 'error', '-nostdin',
        '-ss', f'{start:.3f}', '-i', str(source), '-map', '0:a:0', '-vn',
        '-t', f'{duration:.3f}', '-ac', '1', '-ar', '16000', '-f', 'f32le',
        '-acodec', 'pcm_f32le', 'pipe:1']
    try:
        result = subprocess.run(command, capture_output=True, timeout=max(30, int(duration * 3)),
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.TimeoutExpired):
        return None
    # A few test/platform runners may not expose captured stdout. Acoustic
    # ranking is an optional refinement, so missing PCM must fall back to the
    # VAD ordering rather than fail voice preparation.
    pcm = getattr(result, 'stdout', b'') or b''
    if result.returncode or len(pcm) < 16000 * 4:
        return None
    usable = len(pcm) - len(pcm) % 4
    samples = array('f')
    samples.frombytes(pcm[:usable])
    if not samples:
        return None
    if sys.byteorder != 'little':
        samples.byteswap()
    square_sum = 0.0
    peak = 0.0
    quiet = clipped = 0
    for sample in samples:
        value = float(sample)
        if not math.isfinite(value):
            return None
        absolute = abs(value)
        square_sum += value * value
        peak = max(peak, absolute)
        quiet += absolute < .005
        clipped += absolute >= .999
    rms = math.sqrt(square_sum / len(samples))
    return {'rms_dbfs': 20 * math.log10(max(rms, 1e-12)),
            'peak_dbfs': 20 * math.log10(max(peak, 1e-12)),
            'near_silence_fraction': quiet / len(samples),
            'clipped_fraction': clipped / len(samples),
            'sample_count': len(samples)}


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

    candidate_records = [{'start': start, 'duration': length,
        'active_seconds': active_seconds(start, length),
        'active_fraction': active_seconds(start, length) / length}
        for start, length in candidates]
    # Cheap VAD-only rank narrows acoustic scans to a few locations in a long
    # file. The final rank uses RMS, clipping and near-silence as well, so a
    # noisy 30-second window cannot win merely by being long.
    from .voice_intelligence.reference_selector import rank_reference_candidates
    preliminary = rank_reference_candidates(candidate_records)
    shortlist = preliminary[:8]
    acoustics = {}
    for item in shortlist:
        metrics = _candidate_acoustic_metrics(source, binary, item.start, item.duration)
        if metrics is not None:
            acoustics[(item.start, item.duration)] = metrics
    # Only compare acoustic scores on candidates actually measured; otherwise
    # unmeasured windows would receive an artificial advantage from absent
    # penalty terms. If every PCM scan failed, retain the VAD-only ranking.
    ranked = rank_reference_candidates(shortlist, acoustics) if acoustics else preliminary
    selected = ranked[0]
    return selected.start, selected.duration, selected.active_fraction


def _reference_window(source: Path) -> tuple[float, float, float]:
    stat = source.stat()
    with _REFERENCE_SCAN_LOCK:
        return _best_reference_window(str(source.resolve()), stat.st_size, stat.st_mtime_ns)


def validate_reference_transcript(text: str, duration_seconds: float) -> None:
    """Reject obvious full-recording transcripts paired with a short crop."""
    words=re.findall(r"[\wÀ-ÿ]+",str(text or ''),flags=re.UNICODE)
    if not words:return
    maximum=max(24,int(float(duration_seconds)*8+12))
    if len(words)>maximum:
        raise ValueError(
            f'A transcrição tem {len(words)} palavras, mas a janela escolhida tem '
            f'{float(duration_seconds):.1f} s. Para evitar condicionar a voz com texto '
            'de outro trecho, informe a transcrição exata dessa janela ou deixe o campo vazio para usar x-vector-only.')


def _silero_speech_regions(source: Path, binary: str, duration: float):
    """Use the already-installed Silero VAD in bounded chunks when available."""
    try:
        import numpy as np
        from .parakeet_asr import detect_speech, load_vad
        vad=load_vad(threads=1)
    except (ImportError,FileNotFoundError,RuntimeError):
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
                for span in detect_speech(audio,vad=vad,min_speech_ms=250,
                        min_silence_ms=350,speech_pad_ms=120,
                        max_speech_seconds=20):
                    start=offset+float(span['start']);end=offset+float(span['end'])
                    if end>start:regions.append((start,min(duration,end)))
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
                        duration_seconds: float | None=None,
                        trim_outer_silence: bool=False) -> tuple[str,Path | None]:
    """Convert an audio file to mono PCM16/24 kHz for local voice conditioning.

    ``trim_outer_silence`` is reserved for the Qwen prompt copy. It removes
    quiet lead-in/tail from that temporary copy while preserving the user's
    source and all internal pauses. Inspection keeps the untrimmed signal so
    its silence measurements remain truthful.
    """
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
        '-ss',f'{start:.3f}','-i',str(source),'-map','0:a:0','-vn']
    if trim_outer_silence:
        # Keep word boundaries safe: only remove leading/trailing low-level
        # silence; retain every internal pause and the entire spoken content.
        trim_leading=('silenceremove=start_periods=1:start_duration=0:'
                      'start_threshold=-48dB:start_silence=0.12')
        # silenceremove's stop_periods=1 terminates at the FIRST internal gap.
        # Reverse, trim that now-leading tail, then reverse back so both spoken
        # sentences and their original pause remain in the conditioning audio.
        command += ['-af',
            trim_leading+',areverse,'+trim_leading+',areverse']
    command += ['-t',f'{length:.3f}','-ac','1','-ar','24000',
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
        import numpy as np
        from scipy.io import wavfile
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
        from .voice_intelligence.reference_selector import score_reference_candidate
        quality = score_reference_candidate({
            'start': float(selected_start), 'duration': duration,
            'active_fraction': float(active_fraction),
            'active_seconds': duration * float(active_fraction)}, {
                'rms_dbfs': rms_dbfs, 'clipped_fraction': clipped,
                'near_silence_fraction': silence})
        return {'duration':duration,'source_duration':source_duration,
                'selected_start':float(selected_start),'active_fraction':float(active_fraction),
                'sample_rate':int(rate),'rms_dbfs':float(rms_dbfs),
                'audible_signal_seconds':audible_signal_seconds,
                'peak_dbfs':float(20*np.log10(max(peak,1e-12))),
                'clipped_fraction':clipped,'silence_fraction':silence,
                'reference_quality_score':round(quality.score,4),
                'reference_quality_confidence':quality.confidence,
                'reference_quality_components':quality.components,
                'warnings':warnings}
