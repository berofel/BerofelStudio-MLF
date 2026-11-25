"""Local, reviewable transcript of the exact Qwen voice-reference window."""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from . import audio_reference, ffmpeg

def transcribe_voice_reference(reference: str, *, runner=None, progress=None,
                               control=None, stage=None) -> dict:
    """Transcribe the selected <=30 s reference window with local Parakeet TDT.

    This is only a transcript draft. It is returned to the UI for review and is
    never silently used to alter the source recording or a saved voice profile.
    The same local Parakeet TDT v3 ONNX INT8 runtime used elsewhere is reused.
    """
    source = Path(reference).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError('A gravação de referência não foi encontrada.')
    if source.stat().st_size <= 44:
        raise ValueError('A gravação de referência está vazia ou incompleta.')
    if control:
        control.checkpoint()
    if stage:
        stage('Analisando a gravação inteira para localizar a janela vocal')

    start, duration, active_fraction = audio_reference._reference_window(source)
    if duration <= 0:
        raise ValueError('Não foi possível encontrar uma janela de áudio para transcrever.')

    from .model_paths import parakeet_tdt_model_dir
    model_dir = parakeet_tdt_model_dir()
    if not model_dir.is_dir() or not any(model_dir.glob('*.onnx')):
        raise FileNotFoundError(
            'O Parakeet TDT v3 ONNX INT8 não está instalado. Execute INSTALAR_IA_OPCIONAL.bat '
            'ou digite/revise manualmente a transcrição da referência.'
        )

    with tempfile.TemporaryDirectory(prefix='bfs_voice_ref_asr_') as temp:
        wav_path = Path(temp) / 'reference_window.wav'
        command = [ffmpeg.ffmpeg_path(), '-hide_banner', '-loglevel', 'error',
                   '-nostdin', '-y', '-ss', f'{start:.4f}', '-i', str(source),
                   '-map', '0:a:0', '-vn', '-t', f'{duration:.4f}',
                   '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', str(wav_path)]
        if stage:
            stage('FFmpeg · preparando a janela escolhida para o Parakeet')
        if control:
            completed = control.run(command, timeout=max(120, int(duration * 4)),
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    text=True, encoding='utf-8', errors='replace',
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        else:
            completed = subprocess.run(command, timeout=max(120, int(duration * 4)),
                                       capture_output=True, text=True, encoding='utf-8',
                                       errors='replace',
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if completed.returncode or not wav_path.is_file() or wav_path.stat().st_size <= 44:
            detail = (completed.stderr or completed.stdout or '').strip()[-500:]
            raise RuntimeError('Não foi possível preparar o áudio para transcrição local.' +
                               (f' Detalhe: {detail}' if detail else ''))
        if control:
            control.checkpoint()
        if stage:
            stage('Silero ONNX · encontrando fala na referência')
        if progress:
            progress(0, 1)
        vad_answer=Path(temp)/'vad.json'
        if runner is None:
            from .ai_pipeline import StageRunner
            runner = StageRunner()
        vad_result=runner('vad',{'audio_path':str(wav_path),'threads':1},vad_answer,
                          timeout=max(180,int(duration*4)),control=control)
        vad_result=vad_result.get('result',vad_result)
        payload = {'audio_path': str(wav_path), 'model_path':str(model_dir),
                   'speech_spans':vad_result.get('speech',[]),'threads':4}
        answer = Path(temp) / 'transcript.json'
        if stage:
            stage('Parakeet TDT v3 ONNX INT8/CPU · transcrevendo em português para revisão')
        envelope = runner('parakeet', payload, answer,
                          timeout=max(180, int(duration * 8)), control=control)
        result = envelope.get('result', envelope)
        segments = result.get('segments') or []
        text = ' '.join(str(item.get('text') or '').strip() for item in segments).strip()
        text = ' '.join(text.split())
        if not text:
            raise RuntimeError(
                'O Parakeet não reconheceu fala suficiente nessa janela. Escolha uma '
                'gravação mais limpa ou digite a transcrição exata manualmente.'
            )
        words = result.get('words') or []
        probabilities = []
        for item in words:
            try:
                probabilities.append(float(item.get('probability')))
            except (TypeError, ValueError):
                pass
        confidence = (sum(probabilities) / len(probabilities) if probabilities else None)
        if control:
            control.checkpoint()
        if progress:
            progress(1, 1)
        return {'text': text, 'language_detected': str(result.get('language') or 'multilingual-auto'),
                'reference_window': {'start': float(start), 'duration': float(duration)},
                'active_fraction': float(active_fraction), 'word_count': len(text.split()),
                'mean_word_confidence': confidence, 'review_required': True,
                'model': 'Parakeet TDT v3 ONNX INT8/CPU'}
