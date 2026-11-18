"""Ferramentas puras de precisão: snapping sem interferir em IA nem FFmpeg."""
from __future__ import annotations


def snap_time(project, value, moving_id=None, *, threshold=.15, extra=(), also_end=None):
    """Retorna posição alinhada ao corte/marcador/cursor mais próximo.

    Se also_end for passado, alinha também a BORDA DIREITA da peça móvel.
    """
    value=max(0.,float(value))
    targets=[0.]+[float(m['time']) for m in project.markers]
    targets.extend(float(e) for e in extra)
    for clip in project.clips:
        if clip.id != moving_id:
            targets.extend((clip.timeline_start,clip.timeline_end))
    matches=[]
    for target in targets:
        if abs(value-target)<=threshold:
            matches.append((abs(value-target),target))
        if also_end is not None and abs(value+also_end-target)<=threshold:
            matches.append((abs(value+also_end-target),target-also_end))
    return max(0.,min(matches)[1]) if matches else value


def select_next_clip(project, selected_ids, forward=True):
    ordered=sorted(project.clips,key=lambda c:(c.timeline_start,c.track_id,c.id))
    if not ordered:return None
    if not selected_ids:return ordered[0].id
    selected=[i for i,c in enumerate(ordered) if c.id in selected_ids]
    if not selected:return ordered[0].id
    index=(max(selected)+1 if forward else min(selected)-1) % len(ordered)
    return ordered[index].id
