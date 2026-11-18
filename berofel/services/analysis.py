"""Análise somente sob comando e somente para os clips selecionados."""
from berofel.services.ffmpeg import silence_intervals


def analyze_clips(clips, progress=None, control=None, stage=None):
    findings = []
    for i, clip in enumerate(clips):
        if control:control.checkpoint()
        if stage:stage(f'FFmpeg • detectando silêncios no bloco {i+1}/{len(clips)}')
        # Em FFmpeg, SS/TT limitam extração ao trecho do arquivo bruto referido pelo bloco.
        for a, b in silence_intervals(clip.source, clip.start, clip.end, control=control):
            # Guarda margem de segurança para evitar eliminar sílabas nas bordas.
            padding = 0.12
            a, b = a + padding, b - padding
            if b - a >= 0.12:
                findings.append(dict(clip_id=clip.id, title=clip.title, a=a, b=b, checked=True))
        if progress:
            progress(i + 1, len(clips))
    return findings


def repetitions_clips(clips, model_name='base', progress=None):
    """Sugestão por transcrição local; requer download do modelo na primeira utilização."""
    from faster_whisper import WhisperModel
    import tempfile
    from pathlib import Path
    from berofel.services.ffmpeg import run
    import difflib
    # O instalador baixa o modelo para uso offline. Se nao existir, a
    # biblioteca ainda pode busca-lo sob demanda no cache padrao.
    from berofel.services.model_paths import whisper_model_dir
    model_location = str(whisper_model_dir()) if (whisper_model_dir() / 'model.bin').is_file() else model_name
    model = WhisperModel(model_location, device='cpu', compute_type='int8')
    result = []
    for idx, clip in enumerate(clips):
        with tempfile.TemporaryDirectory(prefix='berofel_whisper_') as d:
            path = str(Path(d) / 'audio.wav')
            r = run(['-y', '-ss', str(clip.start), '-t', str(clip.end-clip.start), '-i', clip.source,
                     '-vn', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', path], check=False)
            if r.returncode:
                raise RuntimeError(r.stderr[-700:])
            segments, _ = model.transcribe(path, beam_size=3, vad_filter=True, language='pt')
            spans = [(s.start, s.end, s.text.strip()) for s in segments]
            for earlier, later in zip(spans, spans[1:]):
                score = difflib.SequenceMatcher(None, earlier[2].lower(), later[2].lower()).ratio()
                if len(earlier[2]) >= 12 and score >= .78:
                    result.append(dict(clip_id=clip.id, title=clip.title, a=earlier[0], b=earlier[1],
                                       checked=False, note=f'Possível repetição ({score:.0%}): {earlier[2][:85]}'))
        if progress:
            progress(idx+1, len(clips))
    return result
