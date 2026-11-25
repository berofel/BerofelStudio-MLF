"""FFmpeg local instalado pelo bootstrap; imageio-ffmpeg serve de reserva."""
import os
import re
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path


def ffmpeg_path():
    bundled = Path(__file__).resolve().parents[2] / 'tools' / 'ffmpeg' / 'ffmpeg.exe'
    if os.name == 'nt' and bundled.is_file():
        return str(bundled)
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        from shutil import which
        binary = which('ffmpeg')
        if binary:
            return binary
        raise RuntimeError('FFmpeg não foi encontrado no pacote, no PATH nem em imageio-ffmpeg.')


@lru_cache(maxsize=24)
def supports_filter(name: str, executable: str | None = None) -> bool:
    """Check the actual FFmpeg binary for an audio/video filter once per name."""
    binary=executable or ffmpeg_path()
    if not re.fullmatch(r'[A-Za-z0-9_]+',str(name)):return False
    try:
        result=subprocess.run([binary,'-hide_banner','-filters'],capture_output=True,
            text=True,errors='replace',timeout=15,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    except (OSError,subprocess.TimeoutExpired):
        return False
    listing=result.stdout+'\n'+result.stderr
    return bool(result.returncode==0 and re.search(
        rf'^\s*[A-Z. ]{{3}}\s+{re.escape(name)}\s',listing,re.MULTILINE))


@lru_cache(maxsize=12)
def _supports_legacy_filter_script(executable: str) -> bool:
    """Detecta opção realmente exposta pelo FFmpeg instalado (uma vez por binário).

    FFmpeg 9 removeu -filter_complex_script em favor de -/filter_complex.
    Versões antigas aceitam a primeira opção; algumas não reconhecem a nova.
    A consulta é leve, não decodifica vídeo e não altera o projeto.
    """
    try:
        info = subprocess.run(
            [executable, '-hide_banner', '-h', 'full'],
            capture_output=True, text=True, errors='replace', timeout=15,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        # Preferir sintaxe atual; falhas reais de FFmpeg permanecem visíveis.
        return False
    if info.returncode != 0:
        return False
    return bool(re.search(r'^\s*-filter_complex_script(?:\s|$)', info.stdout,
                          flags=re.MULTILINE))


def filter_complex_file_args(graph_file: str | Path, executable: str | None = None) -> list[str]:
    """Lê um filtergraph de arquivo em FFmpeg antigo ou novo.

    Não passa o conteúdo inline: evita limite de comando do Windows para
    timelines com centenas de blocos, além de preservar escaping dos filtros.
    """
    binary = executable or ffmpeg_path()
    option = ('-filter_complex_script' if _supports_legacy_filter_script(binary)
              else '-/filter_complex')
    return [option, str(graph_file)]


def ffprobe_path():
    bundled = Path(__file__).resolve().parents[2] / 'tools' / 'ffmpeg' / 'ffprobe.exe'
    if os.name == 'nt' and bundled.is_file():
        return str(bundled)
    from shutil import which
    return which('ffprobe')


def run(args, check=True):
    return subprocess.run([ffmpeg_path(), '-hide_banner', '-nostdin', *args], capture_output=True, text=True, errors='replace', check=check, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))


def media_info(path: str):
    """Cache de metadados por fonte (e versão do arquivo).

    Após 300 cortes o mesmo MP4 deve ser inspecionado UMA vez, não 600.
    Mudanças no arquivo invalidam a chave pelo tamanho/mtime.
    """
    try:
        stat = Path(path).stat()
        key = (str(Path(path).resolve()), stat.st_size, stat.st_mtime_ns)
    except OSError:
        key = (str(path), -1, -1)
    return _media_info_cached(*key)


@lru_cache(maxsize=256)
def _media_info_cached(path: str, _size: int, _mtime_ns: int):
    # FFprobe retorna duracao e fluxos com maior robustez que parsear stderr.
    probe = ffprobe_path()
    if probe:
        import json
        try:
            proc = subprocess.run([probe, '-v', 'error', '-show_entries',
                                   'format=duration:stream=codec_type',
                                   '-of', 'json', path], capture_output=True, text=True,
                                  errors='replace', timeout=30,
                                  creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if proc.returncode == 0:
                data = json.loads(proc.stdout)
                types = {stream.get('codec_type') for stream in data.get('streams', [])}
                duration = float(data.get('format', {}).get('duration') or 0)
                return duration, 'video' in types, 'audio' in types
        except (ValueError, OSError, subprocess.TimeoutExpired):
            pass
    result = run(['-i', path], check=False)  # Consulta metadados sem processar o vídeo inteiro
    log = result.stderr
    m = re.search(r'Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)', log)
    duration = int(m[1])*3600 + int(m[2])*60 + float(m[3]) if m else 0.
    has_video = bool(re.search(r'Stream #.*Video:', log))
    has_audio = bool(re.search(r'Stream #.*Audio:', log))
    return duration, has_video, has_audio


def silence_intervals(source: str, start: float, end: float, threshold_db=-35, min_sec=0.55, control=None):
    """Detecta baixo nível acústico, NÃO detecção semântica de fala."""
    length = end - start
    if length <= 0:
        return []
    args = ['-ss', f'{start:.6f}', '-t', f'{length:.6f}', '-i', source,
            '-vn', '-af', f'silencedetect=noise={threshold_db}dB:d={min_sec}', '-f', 'null', '-']
    if control:
        control.checkpoint()
        result=control.run([ffmpeg_path(),'-hide_banner','-nostdin',*args],
                           stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,
                           errors='replace',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    else:
        result=run(args,check=False)
    if result.returncode != 0 and 'silence_start'  not in result.stderr:
        raise RuntimeError(result.stderr[-900:] or 'Falha ao analisar áudio.')
    times = []
    open_start = None
    for line in result.stderr.splitlines():
        st = re.search(r'silence_start:\s*(-?[\d.]+)', line)
        en = re.search(r'silence_end:\s*(-?[\d.]+)', line)
        if st:
            open_start = max(0, float(st[1]))
        if en and open_start is not None:
            b = min(length, float(en[1]))
            if b > open_start:
                times.append((open_start, b))
            open_start = None
    if open_start is not None and length > open_start:
        times.append((open_start, length))
    return times


def make_export(clips, destination: str, on_progress=None):
    """Exportação inicial: clipes de vídeo em sequência em 720p/30fps.
    Cada segmento é normalizado para compatibilidade entre fontes.
    """
    if not clips:
        raise ValueError('A timeline está vazia.')
    with tempfile.TemporaryDirectory(prefix='berofel_export_') as d:
        manifest = []
        for i, clip in enumerate(clips):
            _, video, audio = media_info(clip.source)
            if not video:
                raise ValueError('Esta versão exporta apenas blocos de vídeo. Remova blocos somente de áudio.')
            segment = str(Path(d) / f'part_{i:05d}.mp4')
            args = ['-y', '-ss', f'{clip.start:.6f}', '-t', f'{clip.duration:.6f}', '-i', clip.source]
            if not audio:
                args += ['-f', 'lavfi', '-t', f'{clip.duration:.6f}', '-i', 'anullsrc=channel_layout=stereo:sample_rate=48000']
            args += ['-map', '0:v:0', '-map', '0:a:0' if audio else '1:a:0',
                     '-vf', 'scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30',
                     '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '22', '-pix_fmt', 'yuv420p',
                     '-c:a', 'aac', '-ar', '48000', '-ac', '2', '-b:a', '160k', '-shortest', segment]
            r = run(args, check=False)
            if r.returncode:
                raise RuntimeError(f'Erro no bloco {i+1}: {r.stderr[-1200:]}')
            manifest.append(segment)
            if on_progress:
                on_progress(i+1, len(clips)+1)
        concat_path = Path(d) / 'concat.txt'
        concat_path.write_text(''.join("file '" + p.replace("'", "'\\''") + "'\n" for p in manifest), encoding='utf-8')
        result = run(['-y', '-f', 'concat', '-safe', '0', '-i', str(concat_path), '-c', 'copy', destination], check=False)
        if result.returncode:
            raise RuntimeError(result.stderr[-1200:])
        if on_progress:
            on_progress(len(clips)+1, len(clips)+1)
