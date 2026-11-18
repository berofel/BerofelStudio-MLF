"""Autoteste opcional de transcrição REAL do modelo local (sem download)."""
from pathlib import Path
import math
import os
import sys
import tempfile
import wave
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))

from berofel.services.ai_worker import _load_whisper, _whisper


def main():
    print('[1/2] Carregando o modelo Whisper Base já instalado...', flush=True)
    with tempfile.TemporaryDirectory(prefix='bfs_whisper_teste_') as folder:
        wav=Path(folder)/'teste.wav'
        # 2 segundos de áudio PCM16 mono/16k: não importa se há fala.
        frames=bytearray()
        for i in range(32000):
            value=int(900 * math.sin(2 * math.pi * 220 * i / 16000))
            frames.extend(value.to_bytes(2,'little',signed=True))
        with wave.open(str(wav),'wb') as file:
            file.setnchannels(1)
            file.setsampwidth(2)
            file.setframerate(16000)
            file.writeframes(bytes(frames))
        opts={'audio_path':str(wav),'model':'base','language':'pt',
              'offline_only':True,'compute_type':'int8','device':'cpu'}
        model=_load_whisper(opts)
        print('[2/2] Transcrevendo WAV de teste sem PyAV...', flush=True)
        result=_whisper(opts,model=model)
        assert isinstance(result['words'],list)
        print('[OK] Whisper real executou; duração: %.2f s; palavras: %d' %
              (result['duration'],len(result['words'])),flush=True)


if __name__=='__main__':
    main()
