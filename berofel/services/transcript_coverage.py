"""Reutilização segura de transcrições entre blocos divididos ou faixas inteiras.

Não confunde 'não há palavras' com 'não foi transcrito': a cobertura inclui
intervalos de silêncio e a identidade de arquivo. Funciona com velocidade 10x.
"""
from __future__ import annotations
from pathlib import Path
from .ai_cache import source_identity


def _revision(source: str):
    try:
        return source_identity(source)
    except (OSError, ValueError):
        return None


def record_coverage(project, reports, model='base', language='pt') -> int:
    saved=0
    existing=project.ai_coverage
    for report in reports:
        revision=_revision(report['source'])
        if revision is None:continue
        entry={'source':revision, 'start':round(float(report['start']),5),
               'end':round(float(report['end']),5),
               'model':model,'language':language}
        if entry['end']<=entry['start']+.045:continue
        if entry not in existing:
            existing.append(entry)
            saved+=1
    return saved


def has_coverage(project, clip, model='base', language='pt') -> bool:
    revision=_revision(clip.source)
    if revision is None:return False
    spans=sorted((float(entry['start']),float(entry['end']))
                  for entry in project.ai_coverage
                  if entry.get('source')==revision and entry.get('model')==model
                  and entry.get('language')==language)
    cursor=clip.start
    for a,b in spans:
        if a > cursor+.02:
            return False
        cursor=max(cursor,b)
        if cursor >= clip.end-.02:return True
    return False


def words_in_clip(project, clip) -> list[dict]:
    source=str(Path(clip.source).resolve())
    return [dict(w) for w in project.transcripts
            if w.get('source')==source
            and float(w.get('source_start',-1))>=clip.start-.005
            and float(w.get('source_end',1e20))<=clip.end+.005]
