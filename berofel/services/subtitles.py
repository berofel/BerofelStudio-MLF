"""Legendas sincronizadas a partir de coordenadas de origem (sem nova transcrição).

Mapeamento: tempo_timeline = clip.timeline_start + (palavra_na_fonte - clip.start).
Cada novo corte cria referências de fonte; após cortar a legenda segue a fonte.
"""
from __future__ import annotations
from pathlib import Path


def merge_reports(project, reports):
    existing = {(w['source'],round(float(w['source_start']),3),
                 round(float(w['source_end']),3),w['text'])
                for w in project.transcripts}
    count=0
    for report in reports:
        for word in report.get('words',[]):
            key=(word['source'],round(float(word['source_start']),3),
                 round(float(word['source_end']),3),word['text'])
            if key in existing: continue
            project.transcripts.append(dict(word))
            existing.add(key);count+=1
    return count


def timeline_words(project):
    out=[];seen=set()
    for clip in project.clips:
        if clip.kind not in ('video','audio') or not clip.include_audio and clip.kind == 'video':
            continue
        source=str(Path(clip.source).resolve())
        for w in project.transcripts:
            if w.get('source') != source: continue
            start=max(clip.start, float(w['source_start']))
            end=min(clip.end,float(w['source_end']))
            if end-start < .045 or end-start < (float(w['source_end'])-float(w['source_start']))*.50:
                continue
            at=clip.timeline_start+(start-clip.start)/clip.speed
            until=clip.timeline_start+(end-clip.start)/clip.speed
            key=(round(at,3),round(until,3),w['text'])
            if key in seen:continue
            seen.add(key)
            out.append({'start':at,'end':until,'text':w['text'],'id':w.get('id',''),
                        'source':source,'clip_id':clip.id})
    return sorted(out,key=lambda x:(x['start'],x['end']))


def build_cues(project, max_words=8, max_seconds=3.5, gap_seconds=.65):
    words=timeline_words(project)
    if not words:return []
    cues=[];current=[]
    def flush():
        if not current:return
        text=' '.join(item['text'] for item in current).strip()
        cues.append((round(current[0]['start'],3),round(current[-1]['end'],3),text))
    for w in words:
        if current and (len(current)>=max_words or
                        w['start']-current[-1]['end']>gap_seconds or
                        w['end']-current[0]['start']>max_seconds or
                        w['start']<current[-1]['start']):
            flush();current=[]
        current.append(w)
    flush()
    return cues


def _time_srt(s):
    milliseconds=max(0,round(float(s)*1000))
    h,ms=divmod(milliseconds,3600000)
    m,ms=divmod(ms,60000)
    sec,ms=divmod(ms,1000)
    return f'{h:02d}:{m:02d}:{sec:02d},{ms:03d}'


def export_srt(project, filename):
    cues=build_cues(project)
    if not cues:raise ValueError('Não há palavras transcritas nos trechos atualmente presentes na timeline.')
    rows=[]
    for i,(start,end,text) in enumerate(cues,1):
        if end<=start:continue
        rows.append(f'{i}\n{_time_srt(start)} --> {_time_srt(end)}\n{text}\n')
    Path(filename).write_text('\n'.join(rows)+'\n',encoding='utf-8-sig')
    return len(rows)
