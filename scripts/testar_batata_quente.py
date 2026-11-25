"""Autoteste local de subprocessos com WAV não-falado; verifica cache e tempos.

Não mede qualidade de transcrição nem contexto (requer fala humana real).
"""
import sys, tempfile, time
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from berofel.core.project import Clip
from berofel.services.ffmpeg import run
from berofel.services.ai_cache import CacheStore
from berofel.services.ai_pipeline import AIOptions,Pipeline


def main():
    with tempfile.TemporaryDirectory(prefix='bfs_ai_test_') as dir:
        source=Path(dir)/'video.mp4'
        p=run(['-y','-f','lavfi','-i','color=c=navy:s=320x180:r=24:d=8',
               '-f','lavfi','-i','sine=frequency=440:duration=8',
               '-c:v','mpeg4','-c:a','aac','-shortest',str(source)],check=False)
        if p.returncode:raise RuntimeError('Não foi possível gerar o teste: '+p.stderr[-350:])
        selected=Clip(source=str(source),start=1,end=7,track_id='test',kind='video',title='Selecionado')
        cache=CacheStore(Path(dir)/'cache')
        print('Primeira análise (Silero VAD + Parakeet TDT v3 INT8; mídia sintética sem fala):',flush=True)
        started=time.monotonic()
        first=Pipeline(cache).analyze([selected],AIOptions(),progress=lambda x,y:print(f'Etapas: {x}/{y}',flush=True))
        print('Cache primeira vez:',first['cache_hits'],'reusos,',first['cache_misses'],'processadas',flush=True)
        second=Pipeline(cache).analyze([selected],AIOptions())
        assert first['cache_misses']==3 and second['cache_hits']==3
        assert first['reports'][0]['clip_id']==selected.id
        print('[OK] Processos independentes encerraram; 3/3 etapas foram reaproveitadas do cache.',flush=True)
        print('Duração teste:',round(time.monotonic()-started,1),'segundos',flush=True)
        print('Obs.: o teste usa um tom, não uma gravação de voz. Teste português com fala real no editor.')


if __name__=='__main__':
    try:main()
    except Exception as error:
        print('[ERRO]',type(error).__name__+':',error,flush=True)
        sys.exit(1)
