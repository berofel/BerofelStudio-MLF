"""Autoteste do pacote e teste opcional de geração real com Pocket TTS."""
import argparse
import sys
import tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--real',action='store_true')
    parser.add_argument('--offline',action='store_true',
                        help='não consulta a rede para obter pesos ou vozes')
    args=parser.parse_args()
    from pocket_tts import TTSModel
    import torch
    from scipy.io import wavfile
    print('[OK] pocket-tts importável; PyTorch:',torch.__version__,flush=True)
    if args.real:
        import os
        from berofel.services.pocket_tts_service import NarrationRequest, generate_narration
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            old_cache=os.environ.get('BEROFEL_AI_CACHE')
            old_offline=os.environ.get('HF_HUB_OFFLINE')
            os.environ['BEROFEL_AI_CACHE']=str(root/'cache'/'ai')
            if args.offline:os.environ['HF_HUB_OFFLINE']='1'
            try:
                request=NarrationRequest(text='Olá! Este é um teste do BerofelStudio.',
                    voice='rafael',language='portuguese',
                    project_path=str(root/'Projeto_teste.bfs'),title='Teste Pocket TTS')
                first=generate_narration(request)
                second=generate_narration(request)
                for result in (first,second):
                    path=Path(result['path'])
                    assert path.is_file() and path.stat().st_size>44
                    assert result['duration']>0
                assert not first['cache_hit'] and second['cache_hit']
                print('[OK] WAV real gerado; %.2fs; segunda chamada reaproveitou o cache.' %
                      first['duration'],flush=True)
            finally:
                if old_cache is None:os.environ.pop('BEROFEL_AI_CACHE',None)
                else:os.environ['BEROFEL_AI_CACHE']=old_cache
                if old_offline is None:os.environ.pop('HF_HUB_OFFLINE',None)
                else:os.environ['HF_HUB_OFFLINE']=old_offline
    return 0

if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as exc:
        print('[ERRO]',type(exc).__name__,':',exc,flush=True)
        raise SystemExit(1)
