"""Proxy H.264 opcional para prévia fluida: exportação usa SEMPRE o original.

Sem limite fixo de RAM/CPU. O usuário solicita a geração; resultados ficam
persistentes por caminho, tamanho e data de modificação do arquivo original.
"""
from __future__ import annotations
from hashlib import sha256
import os
from pathlib import Path
import subprocess
from uuid import uuid4

from berofel.services.ffmpeg import ffmpeg_path, media_info


def proxy_dir():
    local=os.getenv('LOCALAPPDATA')
    return (Path(local)/'BFS'/'cache'/'proxies') if local else (Path.home()/'.cache'/'berofelstudio'/'proxies')


def proxy_path(source, folder=None):
    p=Path(source).resolve()
    stat=p.stat()
    key=f'{p}|{stat.st_size}|{stat.st_mtime_ns}'
    digest=sha256(key.encode('utf-8')).hexdigest()[:24]
    root=Path(folder or proxy_dir())
    return root/(digest+'.mp4')


def find_proxy(source, folder=None):
    try:
        file=proxy_path(source,folder)
        return str(file) if file.is_file() and file.stat().st_size>200 else None
    except OSError:return None


def remove_proxy(source, folder=None):
    try:
        path=proxy_path(source,folder)
        path.unlink(missing_ok=True)
        return True
    except OSError:return False


def create_proxy(source, on_progress=None, control=None, stage=None, folder=None, max_width=960):
    """Cria proxy em arquivo temporário, com progresso/cancelamento atômicos."""
    original=Path(source).resolve()
    if not original.is_file():raise FileNotFoundError(source)
    destination=proxy_path(source,folder)
    if destination.is_file() and destination.stat().st_size>200:
        if on_progress:on_progress(1,1)
        return str(destination)
    duration,has_video,has_audio=media_info(source)
    if not has_video:raise ValueError('Proxy de vídeo exige uma fonte com imagem.')
    if control:control.checkpoint()
    destination.parent.mkdir(parents=True,exist_ok=True)
    temporary=destination.with_name('.'+destination.stem+'.'+uuid4().hex+'.tmp.mp4')
    if stage:stage(f'FFmpeg • gerando proxy {max_width}px: {original.name}')
    unit=max(1,int(duration*100))
    if on_progress:on_progress(0,unit)
    args=[ffmpeg_path(),'-hide_banner','-nostdin','-loglevel','error','-y',
          '-i',str(original),'-map','0:v:0']
    if has_audio:args+=['-map','0:a:0?']
    args+=['-vf',f"scale=w='min(iw,{max(160,int(max_width))})':h=-2",
           '-c:v','libx264','-preset','veryfast','-crf','27','-pix_fmt','yuv420p']
    if has_audio:args+=['-c:a','aac','-b:a','96k']
    else:args+=['-an']
    args+=['-movflags','+faststart','-progress','pipe:2',str(temporary)]
    launcher=control.popen if control else subprocess.Popen
    proc=launcher(args,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,text=True,errors='replace',
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    errors=[]
    try:
        for line in proc.stderr:
            if control:control.checkpoint()
            line=line.strip()
            if line.startswith('out_time_ms='):
                try:
                    sec=int(line.split('=',1)[1])/1e6
                    if on_progress:on_progress(min(unit,int(sec*100)),unit)
                except ValueError:pass
            elif line and not line.startswith(('frame=','fps=','stream_','bitrate=',
                                              'total_size=','out_time=','speed=',
                                              'dup_frames=','drop_frames=','progress=')):
                errors.append(line)
                if len(errors)>25:errors.pop(0)
        code=proc.wait()
        if control:control.checkpoint()
        if code:
            raise RuntimeError('Falha ao gerar proxy FFmpeg: '+'\n'.join(errors)[-1500:])
        if not temporary.is_file() or temporary.stat().st_size<200:
            raise RuntimeError('O proxy resultou vazio.')
        os.replace(temporary,destination)
        if on_progress:on_progress(unit,unit)
        return str(destination)
    finally:
        if temporary.exists():temporary.unlink(missing_ok=True)
        if proc.stderr:proc.stderr.close()
        if proc.poll() is None:
            if control:control._kill(proc)
            else:proc.kill()
            proc.wait()
        if control:control.release(proc)
