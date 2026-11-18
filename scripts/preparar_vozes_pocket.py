"""Pré-cache estados de vozes Voice-Zero para o modelo português, sem WAVs."""
from __future__ import annotations
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from berofel.services.pocket_tts_service import VOICE_PRESETS


def prepare_precomputed_voice_states(language='portuguese', resolver=None, log=print):
    """Cache the model's small public speaker states; do not fetch source WAVs."""
    if resolver is None:
        from pocket_tts.utils.utils import download_if_necessary, get_predefined_voice
        resolver=lambda lang,name: download_if_necessary(
            get_predefined_voice(language=lang,name=name))
    cached=[];failed=[]
    for index,voice in enumerate(VOICE_PRESETS):
        try:
            path=Path(resolver(language,voice['id']))
            if not path.is_file() or path.stat().st_size<=44:
                raise RuntimeError('estado precomputado ausente ou vazio')
            cached.append(voice['id'])
            log(f'[OK] Estado {language}/{voice["id"]} pronto.')
        except Exception as exc:
            failed.append(voice['id'])
            log(f'[AVISO] Estado {language}/{voice["id"]} não preparado: {exc}')
            detail=str(exc)
            if (type(exc).__name__ in {'HfHubConnectionError','ConnectTimeout',
                    'ReadTimeout','ConnectionError','LocalEntryNotFoundError',
                    'OfflineModeIsEnabled','ProxyError'} or
                    'WinError 10013' in detail or 'Network is unreachable' in detail):
                remaining=[item['id'] for item in VOICE_PRESETS[index+1:]]
                failed.extend(remaining)
                if remaining:
                    log('[AVISO] Acesso ao Hugging Face indisponível; sem novas tentativas nesta instalação.')
                break
    if failed:
        log('[AVISO] O editor continua instalável; estes estados serão tentados no primeiro uso: '
            + ', '.join(failed))
    return {'cached':cached,'failed':failed}


def main():
    result=prepare_precomputed_voice_states()
    if result['cached']:
        print('[OK] Presets usam estados precomputados; nenhum WAV de referência foi baixado.')
    else:
        print('[AVISO] Não foi possível pré-carregar estados de voz; arquivos WAV locais antigos foram preservados.')
    return 0

if __name__=='__main__':
    raise SystemExit(main())
