"""Escopos explícitos para ações independentes do BerofelStudio 0.8.

Resolução SEM tocar no projeto. Os intervalos são da timeline (playback),
mas os limites de análise são preservados nas coordenadas da fonte.
"""
from __future__ import annotations
from dataclasses import dataclass, replace
from typing import Iterable

AUDIO_KINDS = frozenset({'audio', 'video'})
SCOPES = ('one', 'selected', 'track', 'interval', 'track_interval', 'project')


@dataclass(frozen=True)
class ScopeSpec:
    mode: str = 'selected'
    selected_ids: tuple[str, ...] = ()
    track_id: str = ''
    in_time: float = 0.0
    out_time: float = 0.0


@dataclass(frozen=True)
class ScopeTarget:
    original_id: str
    source_start: float
    source_end: float
    timeline_start: float
    timeline_end: float
    track_id: str

    @property
    def playback_seconds(self) -> float:
        return self.timeline_end - self.timeline_start


def resolve_scope(project, spec: ScopeSpec, kinds: Iterable[str] = AUDIO_KINDS):
    """Retorna (copies dos blocos para processamento, metadados de cada recorte).

    - ``one`` exige exatamente um bloco selecionado e elegível;
    - ``selected`` usa vários blocos (não inclui outros);
    - ``track`` usa TODOS os blocos elegíveis da faixa indicada;
    - ``interval`` recorta pelas marcas In/Out em qualquer faixa;
    - ``track_interval`` aplica In/Out somente na faixa escolhida;
    - ``project`` contempla todos os blocos elegíveis do projeto.

    O ID da cópia permanece o ID original, pois a revisão deve atingir o
    mesmo bloco (não um ID virtual). ``start/end`` são tempos de FONTE.
    """
    if spec.mode not in SCOPES:
        raise ValueError('Alcance desconhecido: '+str(spec.mode))
    accepted = frozenset(kinds)
    selected = set(spec.selected_ids)
    candidates = [c for c in project.clips if c.kind in accepted and c.duration > 0.045]
    if spec.mode in ('one', 'selected'):
        candidates = [c for c in candidates if c.id in selected]
        if spec.mode == 'one' and len(candidates) != 1:
            raise ValueError('Selecione exatamente um bloco compatível para este alcance.')
    elif spec.mode in ('track','track_interval'):
        if not project.track(spec.track_id):
            raise ValueError('Escolha uma faixa existente.')
        candidates = [c for c in candidates if c.track_id == spec.track_id]
    if spec.mode in ('interval','track_interval'):
        if spec.out_time <= spec.in_time or spec.in_time < 0:
            raise ValueError('Marque um intervalo In/Out válido: Saída deve ser maior que Entrada.')
    order = {t.id: i for i, t in enumerate(project.tracks)}
    candidates.sort(key=lambda c: (c.timeline_start, order.get(c.track_id, 0), c.id))
    copied, targets = [], []
    seen_linked_av=set()
    for clip in candidates:
        left, right = clip.timeline_start, clip.timeline_end
        if spec.mode in ('interval','track_interval'):
            left = max(left, spec.in_time)
            right = min(right, spec.out_time)
        if right - left < .045:
            continue
        if clip.group_id and clip.kind in ('audio','video'):
            linked_key=(clip.group_id,clip.source,round(clip.start,5),round(clip.end,5),
                        round(clip.timeline_start,5),round(clip.speed,5),
                        round(left,5),round(right,5))
            if linked_key in seen_linked_av:
                continue
            seen_linked_av.add(linked_key)
        # Um clipe em 2x toca dois segundos de fonte por segundo de timeline.
        source_start = clip.start + (left - clip.timeline_start) * clip.speed
        source_end = clip.start + (right - clip.timeline_start) * clip.speed
        source_start = max(clip.start, min(clip.end, source_start))
        source_end = max(source_start, min(clip.end, source_end))
        copied.append(replace(clip, start=source_start, end=source_end,
                              timeline_start=left))
        targets.append(ScopeTarget(clip.id, source_start, source_end,
                                   left, right, clip.track_id))
    return copied, targets


def scope_summary(targets) -> tuple[int, float]:
    return len(targets), sum(t.playback_seconds for t in targets)


def proposal_to_original(proposal: dict, target: ScopeTarget) -> dict:
    """Converte intervalo local de fonte para intervalo relativo ao bloco original."""
    entry = dict(proposal)
    shift = target.source_start  # leitura da IA é relativa ao início do recorte
    # A decisão de corte usa segundos da FONTE relativos ao bloco original.
    # original.start é fornecido separadamente na chamada abaixo.
    entry['scope_source_start'] = shift
    return entry


def local_to_original_proposal(proposal: dict, target: ScopeTarget, original) -> dict:
    entry = dict(proposal)
    delta = target.source_start - original.start
    entry['a'] = round(max(0., float(proposal['a']) + delta), 5)
    entry['b'] = round(min(original.end - original.start,
                            float(proposal['b']) + delta), 5)
    entry['clip_id'] = original.id
    return entry


def scope_is_still_valid(project, originals, targets) -> bool:
    """Não aplica resultado obsoleto se algum bloco-alvo mudou enquanto IA rodava."""
    for target in targets:
        old = originals.get(target.original_id)
        current = project.clip(target.original_id)
        if old is None or current is None:
            return False
        for prop in ('source', 'start', 'end', 'speed', 'timeline_start', 'track_id'):
            if getattr(current, prop) != getattr(old, prop):
                return False
    return True
