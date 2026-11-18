"""Autoteste do pacote e teste opcional de geração real com Pocket TTS."""
import argparse
import sys
import tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))


def create_synthetic_voice_reference(path, wavfile):
    """Create a short local test voice signal; never read or upload user media."""
    import numpy as np
    rate=24000
    t=np.arange(int(rate*1.2),dtype=np.float64)/rate
    signal=(.30*np.sin(2*np.pi*180*t)+.16*np.sin(2*np.pi*360*t)+
            .08*np.sin(2*np.pi*540*t))
    pcm=np.clip(signal*32767,-32768,32767).astype('<i2')
    wavfile.write(str(path),rate,pcm)
    return path


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--real',action='store_true')
    parser.add_argument('--clone',action='store_true',
                        help='sintetiza com referência de voz sintética; requer pesos completos autorizados')
    parser.add_argument('--offline',action='store_true',
                        help='não consulta a rede para obter pesos ou vozes')
    args=parser.parse_args()
    if args.clone:
        args.real=True
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
                if args.clone:
                    reference=create_synthetic_voice_reference(
                        root/'referencia_clone_sintetica.wav',wavfile)
                    voice=str(reference)
                    consent=True
                else:
                    voice='rafael'
                    consent=False
                request=NarrationRequest(text='Olá! Este é um teste do BerofelStudio.',
                    voice=voice,language='portuguese',consent=consent,
                    project_path=str(root/'Projeto_teste.bfs'),title='Teste Pocket TTS')
                first=generate_narration(request)
                second=generate_narration(request)
                for result in (first,second):
                    path=Path(result['path'])
                    assert path.is_file() and path.stat().st_size>44
                    assert result['duration']>0
                assert not first['cache_hit'] and second['cache_hit']
                if args.clone:
                    print('[OK] Clonagem Pocket TTS validada com referência sintética; '
                          '%.2fs; cache confirmado.' % first['duration'],flush=True)
                else:
                    print('[OK] WAV real gerado; %.2fs; segunda chamada reaproveitou o cache.' %
                          first['duration'],flush=True)
            finally:
                if old_cache is None:os.environ.pop('BEROFEL_AI_CACHE',None)
                else:os.environ['BEROFEL_AI_CACHE']=old_cache
                if old_offline is None:os.environ.pop('HF_HUB_OFFLINE',None)
                else:os.environ['HF_HUB_OFFLINE']=old_offline
    return 0

if __name__=='__main__':
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, OSError, ValueError):
            pass
    try:raise SystemExit(main())
    except Exception as exc:
        print('[ERRO]',type(exc).__name__,':',exc,flush=True)
        raise SystemExit(1)
