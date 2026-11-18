"""Teste de integração de FFmpeg + filtros de vídeo/áudio no computador instalado.

É executado na instalação base. Os arquivos de vídeo são sintetizados em um
TemporaryDirectory: não toca em arquivos do usuário nem precisa de GPU, câmera
ou conexão. Valida os mesmos comandos de pipe usados pelo Preview Qt.
"""
from __future__ import annotations
import argparse
from array import array
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from berofel.core.project import Project, Clip
from berofel.services.ffmpeg import ffmpeg_path
from berofel.services.preview_pipeline import prepare_commands


def run(command,timeout=35):
    result=subprocess.run(command, stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                          timeout=timeout,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode:
        raise RuntimeError('FFmpeg falhou: '+result.stderr.decode('utf-8',errors='replace')[-1400:])
    return result.stdout


def check():
    ffmpeg=ffmpeg_path()
    with tempfile.TemporaryDirectory(prefix='bfs_motor_test_') as folder:
        root=Path(folder)
        samples=[]
        for name,color,freq in [('red','red',370),('blue','blue',740)]:
            file=root/(name+'.mp4')
            run([ffmpeg,'-hide_banner','-loglevel','error','-nostdin','-y',
                 '-f','lavfi','-i',f'color=c={color}:s=160x90:r=12:d=0.7',
                 '-f','lavfi','-i',f'sine=frequency={freq}:duration=0.7',
                 '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(file)])
            samples.append(file)
        p=Project(width=160,height=90,fps=12)
        p.add_clip(Clip(source=str(samples[0]),start=0,end=.7,track_id=p.tracks[-1].id,
                        kind='video',timeline_start=0))
        p.add_clip(Clip(source=str(samples[1]),start=0,end=.7,track_id=p.tracks[0].id,
                        kind='video',timeline_start=0))
        cmds=prepare_commands(p,0,root/'live',160,12)
        picture=run(cmds.video)
        sound=run(cmds.audio)
        frame_size=160*90*4
        if len(picture)<frame_size*7:
            raise RuntimeError(f'Quadros da prévia incompletos: {len(picture)} bytes')
        mid=(45*160+80)*4
        blue,green,red,alpha = picture[mid:mid+4]
        if not blue>red+90:
            raise RuntimeError('Composição visual incorreta: a camada superior deveria ser azul.')
        if len(sound)<48000*4*.55:
            raise RuntimeError('Audio da prévia muito curto.')
        samples=array('h');samples.frombytes(sound[:192000])
        peak=max(abs(v) for v in samples)
        if peak<100:
            raise RuntimeError('Áudio misturado está silencioso.')
        # A segunda camada tem vídeo E som. A primeira não deve ser descartada.
        print('[OK] Dois vídeos em camadas simultâneas (azul sobre vermelho)')
        print(f'[OK] Áudio da composição recebido: {len(sound)} bytes; pico {peak}')
        print(f'[OK] Quadros BGRA recebidos: {len(picture)//frame_size}')
    return 0


if __name__=='__main__':
    try: sys.exit(check())
    except Exception as exc:
        print('[FALHOU] Autoteste do motor: '+str(exc),file=sys.stderr)
        sys.exit(1)
