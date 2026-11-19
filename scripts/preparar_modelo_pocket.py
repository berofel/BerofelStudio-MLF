"""Pré-carrega pesos portugueses e confirma se acesso ao Hugging Face está autorizado."""
from __future__ import annotations
from array import array
import math
from pathlib import Path
import sys
import tempfile
import wave

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from berofel.services.pocket_tts_worker import (activation_failure_message,
    ensure_voice_cloning_weights)


def validate_voice_cloning_pipeline(model):
    """Exercise audio-prompt encoding with a temporary signal, never user audio."""
    if not getattr(model,'has_voice_cloning',False):
        raise RuntimeError('Os pesos carregados permitem somente vozes do catálogo; '
                           'pesos para clonagem ainda não foram autorizados/baixados.')
    sample_rate=24000
    frames=array('h',(int(5000*math.sin(2*math.pi*180*index/sample_rate))
                      for index in range(sample_rate)))
    if sys.byteorder!='little':frames.byteswap()
    with tempfile.TemporaryDirectory(prefix='bfs_voice_clone_check_') as folder:
        prompt=f'{folder}/prompt.wav'
        with wave.open(prompt,'wb') as output:
            output.setnchannels(1);output.setsampwidth(2);output.setframerate(sample_rate)
            output.writeframes(frames.tobytes())
        state=model.get_state_for_audio_prompt(prompt,truncate=True)
        if state is None:
            raise RuntimeError('O encoder Pocket TTS não retornou estado para uma amostra de áudio.')
        return state


def main():
    try:
        from pocket_tts import TTSModel
        print('Carregando Pocket TTS português pela primeira vez (internet necessária)...',flush=True)
        ensure_voice_cloning_weights('portuguese')
        model=TTSModel.load_model(language='portuguese')
        state=validate_voice_cloning_pipeline(model)
        print('[OK] Pocket TTS aceitou uma amostra de áudio e preparou o encoder de clonagem.',flush=True)
        del state, model
        return 0
    except Exception as exc:
        detail=str(exc).strip()
        print(f'[PENDENTE] Ativação do modelo de clonagem não concluída: {type(exc).__name__}: {detail[:1000]}',flush=True)
        if 'recusou o checkpoint' in detail:
            print('Ação: abra https://huggingface.co/kyutai/pocket-tts e aceite os termos; depois use Narração > Preparar clonagem local ou AUTORIZAR_POCKET_TTS.bat.',flush=True)
        elif 'pela rede' in detail:
            print('Ação: verifique conexão, firewall ou proxy e repita Narração > Preparar clonagem local ou AUTORIZAR_POCKET_TTS.bat quando o Hugging Face estiver acessível.',flush=True)
        else:
            print('Ação: confira o erro acima; depois repita Narração > Preparar clonagem local (ou AUTORIZAR_POCKET_TTS.bat) e TESTAR_POCKET_TTS.bat.',flush=True)
        return 2

if __name__=='__main__':
    raise SystemExit(main())
