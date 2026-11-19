"""Offline real-inference smoke test for the BerofelStudio Qwen Base worker.

Without --reference this uses a synthetic reference signal to test the actual
model/worker/audio pipeline, not voice identity. Pass an authorized recording
and its exact transcript to exercise personal voice cloning.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import wave

import numpy as np
import psutil
from scipy.io import wavfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def _synthetic_reference(path: Path) -> Path:
    rate=24000
    duration=3.2
    t=np.arange(round(rate*duration),dtype=np.float64)/rate
    # A bounded multi-formant-like test tone, never represented as a real voice.
    fundamental=np.where(t<1.05,132.,np.where(t<2.1,165.,147.))
    phase=2*np.pi*np.cumsum(fundamental)/rate
    envelope=np.minimum(1.,np.minimum(t/.12,(duration-t)/.12))
    signal=envelope*(.22*np.sin(phase)+.11*np.sin(2*phase)+.055*np.sin(3*phase))
    wavfile.write(str(path),rate,np.clip(signal*32767,-32768,32767).astype('<i2'))
    return path


def _sample_process_memory(stop: threading.Event, peak: list[int]):
    process=psutil.Process()
    while not stop.is_set():
        try:
            total=process.memory_info().rss
            for child in process.children(recursive=True):
                try:total+=child.memory_info().rss
                except (psutil.NoSuchProcess,psutil.AccessDenied):pass
            peak[0]=max(peak[0],total)
        except (psutil.NoSuchProcess,psutil.AccessDenied):
            pass
        stop.wait(.2)


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference',type=Path,
        help='áudio de referência autorizado; sem isso, usa sinal sintético')
    parser.add_argument('--saved-reference',action='store_true',
        help='usa localmente a amostra e a transcrição já guardadas no painel Narração')
    parser.add_argument('--reference-text',default='',
        help='transcrição exata da gravação (recomendado pelo modo ICL oficial)')
    parser.add_argument('--text',default='Olá, esta é uma validação local da narração em português.')
    parser.add_argument('--language',default='portuguese',choices=('portuguese','english','spanish','french','german','italian'))
    parser.add_argument('--timeout',type=int,default=1800)
    args=parser.parse_args(argv)
    if args.reference and args.saved_reference:
        raise ValueError('Use --reference ou --saved-reference, não ambos.')
    if args.reference and not args.reference.is_file():
        raise FileNotFoundError('O arquivo de referência informado não existe.')
    if not args.text.strip():raise ValueError('Informe um texto para gerar.')

    os.environ.update({'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1',
                       'HF_HUB_DISABLE_TELEMETRY':'1'})
    from berofel.services.narration_service import NarrationRequest
    from berofel.services.qwen3_tts_local import generate_local_clone
    reference_text=args.reference_text.strip()
    if args.saved_reference:
        from PySide6.QtCore import QSettings
        settings=QSettings(QSettings.Format.IniFormat,QSettings.Scope.UserScope,
                           'Berofel','BerofelStudio')
        saved=Path(str(settings.value('narration/sample_path','') or '')).expanduser()
        if not saved.is_file():
            raise FileNotFoundError('Não há amostra válida configurada no painel Narração.')
        reference=saved.resolve()
        if not reference_text:
            reference_text=str(settings.value('narration/reference_text','') or '').strip()
        if not reference_text:
            raise ValueError('A amostra salva não tem transcrição. Use --reference-text para fornecer o texto exato.')
    else:
        reference=args.reference.resolve() if args.reference else None

    with tempfile.TemporaryDirectory(prefix='bfs_qwen3_smoke_') as temp:
        folder=Path(temp)
        if reference is None:reference=_synthetic_reference(folder/'synthetic_reference.wav')
        request=NarrationRequest(text=args.text.strip(),voice=str(reference),
            language=args.language,consent=True,project_path=str(folder/'smoke.bfs'),
            title='Qwen3 offline validation',engine='qwen3-tts-local',
            reference_text=reference_text)
        outcome={};failure={}
        def run():
            try:outcome['result']=generate_local_clone(request)
            except BaseException as exc:failure['exception']=exc
        stop=threading.Event();peak=[0]
        monitor=threading.Thread(target=_sample_process_memory,args=(stop,peak),daemon=True)
        monitor.start();started=time.perf_counter()
        worker=threading.Thread(target=run,name='Qwen3OfflineSmoke')
        worker.start();worker.join(max(1,args.timeout));
        if worker.is_alive():
            raise TimeoutError(f'Qwen3 não concluiu em {args.timeout} s; o worker continua ativo nesta validação.')
        elapsed=time.perf_counter()-started;stop.set();monitor.join(timeout=2)
        if failure:raise failure['exception']
        result=outcome['result'];audio_path=Path(result['path'])
        sample_rate,samples=wavfile.read(str(audio_path))
        data=np.asarray(samples,dtype=np.float64)
        if data.ndim>1:data=data.mean(axis=1)
        if not data.size or not np.isfinite(data).all():raise RuntimeError('WAV vazio ou com amostras inválidas.')
        peak_value=float(np.max(np.abs(data)))
        rms=float(np.sqrt(np.mean(data*data)))
        duration=len(data)/float(sample_rate)
        if peak_value<=0 or rms<=0:raise RuntimeError('O WAV não contém sinal de áudio audível.')
        print('[PASSOU] Worker real Qwen3-TTS Base concluiu em modo offline.')
        print(f'Validação: {"gravação configurada no editor" if args.saved_reference else "gravação informada" if args.reference else "referência sintética (não valida identidade)"}; transcrição: {bool(reference_text)}')
        print(f'WAV: {duration:.2f}s, {sample_rate} Hz, RMS={rms:.2f}, pico={peak_value:.2f}')
        print(f'Tempo total: {elapsed:.1f}s; memória agregada máxima amostrada: {peak[0]/(1024**3):.2f} GiB')
        print(f'Cache do WAV: {result["cache_hit"]}; prompt de voz: {result["prompt_cache_hit"]}; carregamentos do modelo: {result["model_load_count"]}')
    return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as exc:
        print(f'[FALHOU] {type(exc).__name__}: {exc}',flush=True)
        raise SystemExit(1)
