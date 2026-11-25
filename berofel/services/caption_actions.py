"""Legendas independentes: texto manual ou transcrição local, em qualquer escopo.

Cada legenda gerada vira um clipe de TEXTO editável na timeline. Nada é
sobreposto sem consentimento, e clipes manuais nunca são apagados.
"""
from __future__ import annotations
from pathlib import Path

from berofel.core.project import Clip
from berofel.services.subtitles import _time_srt


def get_caption_track(project):
    track = next((t for t in project.tracks if t.name == 'Legendas' and not t.locked), None)
    if track is None:
        track = project.add_track('Legendas', 0)
    return track


def create_manual_caption(project, text: str, start: float, end: float):
    text = text.strip()
    if not text:
        raise ValueError('Digite a legenda antes de adicionar.')
    if start < 0 or end <= start or end-start < .05:
        raise ValueError('A legenda precisa de tempos In/Out válidos.')
    track = get_caption_track(project)
    clip = Clip(source='', start=0., end=round(end-start, 5),
                timeline_start=round(start, 5), kind='text',
                title='Legenda manual', text=text, font_size=44,
                pos_y=int(project.height * .34),
                track_id=track.id, include_audio=False,
                generated_by='manual_caption')
    project.add_clip(clip)
    return clip


def _make_cue_entries(words: list[dict], max_words=8, max_seconds=3.5, gap_seconds=.65):
    cues = []
    segment = []
    def flush():
        if segment:
            cues.append((round(segment[0]['start'], 4),
                         round(segment[-1]['end'], 4),
                         ' '.join(w['text'] for w in segment).strip()))
    for word in sorted(words, key=lambda w: (w['start'], w['end'])):
        if segment and (len(segment) >= max_words or
                        word['start'] - segment[-1]['end'] > gap_seconds or
                        word['end'] - segment[0]['start'] > max_seconds or
                        word['start'] < segment[-1]['end'] - .4):
            flush()
            segment = []
        segment.append(word)
    flush()
    return [(a,b,text) for a,b,text in cues if b-a >= .045 and text]


def scoped_cues(project, targets):
    """Somente palavras contidas nos alvos; source->timeline preserva velocidade."""
    cues = []
    seen = set()
    for target in targets:
        clip = project.clip(target.original_id)
        if clip is None or clip.kind not in ('video', 'audio'):
            continue
        source = str(Path(clip.source).resolve())
        words = []
        for w in project.transcripts:
            if w.get('source') != source:
                continue
            a, b = float(w['source_start']), float(w['source_end'])
            # Não extrapolar limites da seleção. Um resíduo pequeno pode surgir
            # por arredondamento dos timestamps do reconhecedor.
            if a < target.source_start-.005 or b > target.source_end+.005 or b <= a:
                continue
            at = target.timeline_start + (a - target.source_start) / clip.speed
            until = target.timeline_start + (b - target.source_start) / clip.speed
            if until-at < .025:
                continue
            signature = (round(at, 3),round(until, 3), w['text'])
            if signature in seen:
                continue
            seen.add(signature)
            words.append({'start':at, 'end':until, 'text':w['text']})
        cues.extend(_make_cue_entries(words))
    # Roteiros com vídeo+áudio separados, mesmo tempo, não criam duas legendas.
    unique = {}
    for a,b,text in cues:
        unique[(round(a,3), round(b,3),text)] = (a,b,text)
    return sorted(unique.values(), key=lambda cue: (cue[0], cue[1], cue[2]))


def create_auto_captions(project, targets):
    """Insere só novas legendas, mantém revisões do usuário e evita duplicações."""
    records=[]
    for target in targets:
        source_clip=project.clip(target.original_id)
        if source_clip is None or source_clip.kind not in ('video','audio'):
            continue
        for start,end,text in scoped_cues(project,[target]):
            source_start=source_clip.start+(start-target.timeline_start)*source_clip.speed
            source_end=source_clip.start+(end-target.timeline_start)*source_clip.speed
            source_path=str(Path(source_clip.source).resolve())
            words=sorted(({'source_start':float(word['source_start']),
                           'source_end':float(word['source_end']),
                           'text':str(word['text'])}
                          for word in project.transcripts
                          if word.get('source')==source_path
                          and float(word['source_start']) >= source_start-.005
                          and float(word['source_end']) <= source_end+.005
                          and float(word['source_end']) > float(word['source_start'])),
                         key=lambda word:(word['source_start'],word['source_end']))
            records.append((source_clip,start,end,text,source_start,source_end,words))
    if not records:
        return []
    existing = {(round(c.timeline_start, 3), round(c.timeline_end, 3), c.text)
                for c in project.clips if c.kind == 'text' and c.generated_by == 'auto_caption'}
    track = get_caption_track(project)
    added = []
    for source_clip,start,end,text,source_start,source_end,words in records:
        signature = (round(start,3),round(end,3),text)
        if signature in existing:
            continue
        overlay = Clip(source='', start=0., end=round(end-start,5),
                       timeline_start=start, kind='text',
                       title='Legenda automática', text=text,
                       font_size=44, pos_y=int(project.height*.34),
                       include_audio=False, track_id=track.id,
                       generated_by='auto_caption',
                       caption_anchor_clip_id=source_clip.id,
                       caption_source_start=round(source_start,5),
                       caption_source_end=round(source_end,5),
                       caption_words=words,caption_generated_text=text)
        project.add_clip(overlay)
        added.append(overlay)
        existing.add(signature)
    return added


def export_scoped_srt(project, targets, filename: str) -> int:
    """Exporta clipes de legenda reais e, na falta deles, palavras transcritas.

    Os textos editados manualmente têm precedência no trecho correspondente.
    """
    windows=[(t.timeline_start,t.timeline_end) for t in targets]
    overlays=[]
    for clip in project.clips:
        if clip.kind!='text' or clip.generated_by not in ('auto_caption','manual_caption'):
            continue
        for left,right in windows:
            a=max(left,clip.timeline_start)
            b=min(right,clip.timeline_end)
            if b-a >= .045 and clip.text.strip():
                overlays.append((round(a,4),round(b,4),clip.text.strip()))
    automatic=scoped_cues(project,targets)
    def covered(cue):
        a,b,text=cue
        # Um texto editável prevalece sobre a transcrição original no mesmo momento.
        return any(max(0.,min(b,v)-max(a,u)) >= (b-a)*.45 for u,v,_ in overlays)
    unique={ (round(a,3),round(b,3),text):(a,b,text)
             for a,b,text in overlays+list(filter(lambda cue:not covered(cue),automatic)) }
    cues=sorted(unique.values(),key=lambda cue:(cue[0],cue[1],cue[2]))
    if not cues:
        raise ValueError('Não há palavras ou legendas manuais neste alcance.')
    lines=[]
    for number,(a,b,text) in enumerate(cues,1):
        lines.append(f'{number}\n{_time_srt(a)} --> {_time_srt(b)}\n{text}\n')
    destination=Path(filename)
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text('\n'.join(lines)+'\n',encoding='utf-8-sig')
    return len(cues)
