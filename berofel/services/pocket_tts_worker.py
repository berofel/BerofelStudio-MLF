"""Processo isolado que carrega/descarta Pocket TTS sem afetar memória do Qt."""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys

from .pocket_tts_service import _PRECOMPUTED_VOICE_IDS


def activation_failure_message(exc):
    kind=type(exc).__name__
    response=getattr(exc,'response',None)
    status=getattr(response,'status_code',None)
    detail=str(exc).replace('\n',' ')[:600]
    if kind in {'GatedRepoError','RepositoryNotFoundError'} or status in {401,403}:
        reason=('O Hugging Face recusou o checkpoint de clonagem. Entre na conta usada pelo editor '
                'e aceite os termos de kyutai/pocket-tts; depois repita a ativação.')
    elif kind in {'HfHubConnectionError','ConnectTimeout','ReadTimeout','ConnectionError',
                  'LocalEntryNotFoundError'} or \
            'WinError 10013' in detail or 'Network is unreachable' in detail:
        reason=('Não foi possível acessar o Hugging Face pela rede. Verifique internet/firewall/proxy '
                'e tente novamente; o Pocket TTS pode usar voz de catálogo offline, mas isso não ativa clonagem.')
    else:
        reason='Não foi possível validar/baixar os pesos completos de clonagem.'
    return f'{reason}\nDetalhe: {kind}: {detail}'


def ensure_voice_cloning_weights(language='portuguese'):
    """Fetch the full checkpoint before Pocket TTS can silently use catalog weights."""
    from pocket_tts.utils.config import CONFIGS_DIR, load_config
    from pocket_tts.utils.utils import download_if_necessary

    config=load_config(CONFIGS_DIR/f'{language}.yaml')
    if not config.weights_path:
        raise RuntimeError(f'A configuração Pocket TTS de {language} não declara pesos para clonagem.')
    try:
        return download_if_necessary(config.weights_path)
    except Exception as exc:
        raise RuntimeError(activation_failure_message(exc)) from exc


def require_voice_cloning(model, request: dict) -> None:
    """Fail clearly when HF silently supplied the catalog-only model weights."""
    voice = str(request.get('voice', ''))
    is_precomputed = (Path(voice).suffix.lower() == '.safetensors' or
                      voice == 'rafael' or voice in _PRECOMPUTED_VOICE_IDS)
    # Fail closed when a future/older Pocket TTS API does not expose the
    # capability flag. Do not claim cloning support based on an unknown API.
    if request.get('consent') and not is_precomputed and not bool(
            getattr(model, 'has_voice_cloning', False)):
        raise RuntimeError(
            'Este Pocket TTS está usando pesos somente de catálogo; clonagem de áudio está desativada. '
            'Abra https://huggingface.co/kyutai/pocket-tts, entre na conta e aceite os termos do modelo. '
            'Depois execute AUTORIZAR_POCKET_TTS.bat para baixar/preparar os pesos de clonagem e gere novamente.'
        )


def load_model_for_request(request: dict):
    """Preflight personal-audio checkpoints before loading TTS or its fallback."""
    voice=str(request.get('voice',''))
    is_precomputed=(Path(voice).suffix.lower()=='.safetensors' or voice=='rafael' or
                    voice in _PRECOMPUTED_VOICE_IDS)
    if request.get('consent') and not is_precomputed:
        ensure_voice_cloning_weights(request.get('language','portuguese'))
    from pocket_tts import TTSModel
    model=TTSModel.load_model(language=request['language'],
                              quantize=bool(request.get('quantize',False)))
    require_voice_cloning(model,request)
    return model


def prepare_audio_prompt(voice: str, output_path: str | Path,
                        ffmpeg: str | None = None) -> tuple[str, Path | None]:
    """Normalize user audio for Pocket TTS without touching its source file.

    Pocket TTS reads 16-bit WAV through the standard library; MP3/FLAC/OGG/M4A
    require optional ``soundfile`` support that is not part of our install.
    FFmpeg is already bundled with the editor, so use it to produce a short,
    mono PCM16 WAV. Precomputed .safetensors, Hugging Face voices, and Pocket
    TTS's built-in ``rafael`` speaker ID pass through without filesystem checks.
    """
    # ``rafael`` is Pocket TTS's predefined Portuguese speaker id, not a file.
    # Let TTSModel resolve its cached catalog state just like the UI expects.
    if (voice.startswith('hf://') or voice == 'rafael' or
            voice in _PRECOMPUTED_VOICE_IDS or
            Path(voice).suffix.lower() == '.safetensors'):
        return voice, None
    source = Path(voice)
    if not source.is_file():
        raise FileNotFoundError(f'Amostra da voz não encontrada: {voice}')
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if ffmpeg is None:
        from berofel.services.ffmpeg import ffmpeg_path
        ffmpeg = ffmpeg_path()
    command = [ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
               '-i', str(source), '-map', '0:a:0', '-vn', '-t', '30', '-ac', '1',
               '-ar', '24000', '-c:a', 'pcm_s16le', str(target)]
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                encoding='utf-8', errors='replace',
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode != 0 or not target.is_file() or target.stat().st_size <= 44:
            target.unlink(missing_ok=True)
            detail=(result.stderr or result.stdout or 'FFmpeg não produziu áudio válido.')[-1000:]
            raise RuntimeError(f'Não foi possível preparar a amostra da voz: {detail}')
        return str(target), target
    except Exception:
        target.unlink(missing_ok=True)
        raise


def create_voice_prompt_state(model,voice_prompt):
    """Cap reference-audio embedding work at Pocket TTS's supported 30 s limit."""
    return model.get_state_for_audio_prompt(voice_prompt,truncate=True)


def run(request_path: str, result_path: str):
    request = json.loads(Path(request_path).read_text(encoding='utf-8'))
    from scipy.io import wavfile
    import numpy as np

    model = load_model_for_request(request)
    voice_prompt, prepared = prepare_audio_prompt(
        request['voice'], Path(request['output']).with_name('voice_conditioning.wav'))
    try:
        voice_state = create_voice_prompt_state(model,voice_prompt)
    finally:
        if prepared is not None:
            prepared.unlink(missing_ok=True)
    audio = model.generate_audio(voice_state, request['text'])
    samples = audio.detach().cpu().numpy().reshape(-1)
    if not samples.size:
        raise RuntimeError('Pocket TTS retornou áudio vazio.')
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
    sample_rate = int(model.sample_rate)
    target = Path(request['output'])
    target.parent.mkdir(parents=True, exist_ok=True)
    pending = target.with_suffix('.part.wav')
    wavfile.write(str(pending), sample_rate, pcm)
    os.replace(pending, target)
    result = {'duration':len(pcm) / sample_rate, 'sample_rate':sample_rate, 'bytes':target.stat().st_size}
    result_target = Path(result_path)
    tmp = result_target.with_suffix('.tmp')
    tmp.write_text(json.dumps(result), encoding='utf-8')
    os.replace(tmp, result_target)


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, OSError, ValueError):
            pass
    try:
        if len(sys.argv) != 3:
            raise ValueError('Uso: python -m berofel.services.pocket_tts_worker pedido.json resultado.json')
        run(sys.argv[1], sys.argv[2])
    except Exception as exc:
        print(f'Falha Pocket TTS: {type(exc).__name__}: {exc}',file=sys.stderr)
        raise SystemExit(1)
