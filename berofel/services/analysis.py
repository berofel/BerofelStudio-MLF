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
    """Suggest adjacent repeated spans using the editor's cached Parakeet transcript."""
    import difflib
    from .ai_pipeline import AIOptions, run_analysis
    result = []
    report=run_analysis(clips,options=AIOptions(),mode='transcribe',progress=progress)
    by_id={clip.id:clip for clip in clips}
    for row in report.get('reports',[]):
        clip=by_id.get(row.get('clip_id'))
        if clip is None:continue
        spans=sorted(row.get('segments',[]),key=lambda s:float(s.get('start',0)))
        for earlier,later in zip(spans,spans[1:]):
            left=str(earlier.get('text','')).strip();right=str(later.get('text','')).strip()
            score=difflib.SequenceMatcher(None,left.casefold(),right.casefold()).ratio()
            if len(left)>=12 and score>=.78:
                result.append(dict(clip_id=clip.id,title=clip.title,
                    a=clip.start+float(earlier['start']),b=clip.start+float(earlier['end']),
                    checked=False,note=f'Possível repetição ({score:.0%}): {left[:85]}'))
    return result
