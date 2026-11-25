"""Fila de IA selecionável: Silero -> Whisper -> Qwen -> legendas/narração.

Os modelos nunca concorrem entre si: cada etapa usa o runner existente de
subprocessos e cache. A seleção/edição da timeline não é bloqueada por esta fila.
Silero apenas restringe o material enviado ao ASR (pré-processamento virtual):
não modifica o projeto nem aprova cortes automaticamente.
"""
from __future__ import annotations
from dataclasses import dataclass, replace
from typing import Callable
from .ai_pipeline import AIOptions, run_analysis

ACTION_NAMES = ('silence', 'transcribe', 'fillers', 'context', 'subtitles', 'srt', 'narration')


@dataclass(frozen=True)
class EditPlan:
    selected: tuple[str, ...]
    phases: tuple[str, ...]
    use_vad_for_asr: bool


def plan_actions(actions, optimize_silence=True) -> EditPlan:
    """Resolve dependências sem carregar duas vezes o mesmo modelo.

    Legendas, SRT e narração a partir do vídeo exigem texto. A narração por
    texto livre pode ser usada sem transcrever (handled in UI).
    """
    chosen=tuple(dict.fromkeys(actions))
    invalid=set(chosen)-set(ACTION_NAMES)
    if invalid:
        raise ValueError('Ações não reconhecidas: '+', '.join(sorted(invalid)))
    if not chosen:
        raise ValueError('Marque pelo menos uma ação para iniciar a edição.')
    need_text=any(a in chosen for a in ('transcribe','fillers','context','subtitles','srt'))
    # Narração de texto livre não exige transcrição por padrão.
    steps=[]
    if 'silence' in chosen:
        steps.append('silence')
    if need_text:
        steps.append('whisper')
    if 'fillers' in chosen or 'context' in chosen:
        steps.append('qwen')
    if 'subtitles' in chosen:
        steps.append('subtitles')
    if 'srt' in chosen:
        steps.append('srt')
    if 'narration' in chosen:
        steps.append('narration')
    return EditPlan(chosen, tuple(steps), bool('silence' in chosen and need_text and optimize_silence))


def _merge_windows(windows, *, max_gap=0.75):
    merged=[]
    for a,b in sorted(windows):
        if b-a < 0.06:
            continue
        if merged and a - merged[-1][1] <= max_gap:
            merged[-1]=(merged[-1][0],max(merged[-1][1],b))
        else:
            merged.append((a,b))
    return merged


def spoken_clips(clips, vad_reports, pad=0.18, bridge_gap=0.75):
    """Cópias virtuais somente dos intervalos falados, em tempo absoluto da fonte.

    Não altera o vídeo ou as decisões de corte; protege início/fim de cada fala.
    Retorna (clipes virtuais, quantidade de segundos da FONTE enviados ao ASR).
    """
    by_id={r['clip_id']:r for r in vad_reports}
    output=[]
    for clip in clips:
        report=by_id.get(clip.id)
        if report is None:
            output.append(clip)  # nunca descartar sem relatório
            continue
        speech=report.get('speech',[])
        windows=_merge_windows([(max(0.,float(s['start'])-pad),
                                 min(clip.end-clip.start,float(s['end'])+pad))
                                for s in speech],max_gap=bridge_gap)
        for start,end in windows:
            if end-start<.07:
                continue
            output.append(replace(clip, start=round(clip.start+start,5),
                                  end=round(clip.start+end,5),
                                  timeline_start=clip.timeline_start+start/clip.speed))
    return output,sum(c.end-c.start for c in output)


def run_edit_queue(clips, actions, options: AIOptions | None = None,
                   known_words=None, optimize_silence=True,
                   progress=None, control=None, stage=None,
                   analyze: Callable = run_analysis):
    """Executa IA pesada sequencialmente e devolve resultados para ÚNICA revisão.

    O callback de progresso reflete o trabalho concluído, sem estimativa falsa
    durante inferência opaca; o monitor continua responsável pelo tempo decorrido.
    """
    opts=options or AIOptions()
    plan=plan_actions(actions,optimize_silence)
    phases=[name for name in plan.phases if name in ('silence','whisper','qwen')]
    total=max(1,len(phases)*100)
    if progress:progress(0,total)
    all_findings=[]
    reports=[]
    context_reports=[]
    qwen_errors=[]
    accumulated_words={clip.id:list((known_words or {}).get(clip.id,[])) for clip in clips}
    hits=misses=0
    stage_history=[]
    asr_clips=list(clips)
    asr_seconds=sum(c.end-c.start for c in clips)
    def update(index):
        def track(done,count):
            fraction=max(0.,min(1.,float(done)/max(1,float(count))))
            if progress:progress(round((index+fraction)*100),total)
        return track
    for i,name in enumerate(phases):
        if control:control.checkpoint()
        if stage:
            stage(('Silero VAD · detectar pausas, sem modificar a timeline' if name=='silence'
                   else 'Qwen · analisar somente texto e IDs das palavras' if name=='qwen'
                   else 'Faster-Whisper · transcrever somente os trechos necessários'))
        mode=('silence' if name=='silence' else
              'fillers' if name=='qwen' and 'fillers' in plan.selected else
              'context' if name=='qwen' else 'transcribe')
        selected_clips=clips if name in ('silence','qwen') else asr_clips
        # Qwen recebe toda a transcrição dos blocos de origem, incluindo os
        # trechos de fala já condensados pelo VAD. Não recarrega o Whisper.
        words_for_stage=(accumulated_words if name=='qwen' else known_words or {})
        if selected_clips:
            try:
                result=analyze(selected_clips,options=opts,known_words=words_for_stage,
                               progress=update(i),control=control,stage=stage,mode=mode)
            except Exception as exc:
                # Qwen é opcional: uma falha em seu subprocesso não deve
                # descartar transcrição, cortes Silero aprováveis ou legendas.
                if name!='qwen':raise
                if control:control.checkpoint()  # preserva cancelamento do usuário
                qwen_errors.append(str(exc))
                if stage:stage('Qwen falhou · continuando com transcrição e legendas')
                result={'reports':[], 'suggestions':[], 'cache_hits':0,
                        'cache_misses':0,'stages':[]}
        else:
            # O VAD não encontrou voz: não iniciamos Whisper/Qwen à toa.
            result={'reports':[], 'suggestions':[], 'cache_hits':0,
                    'cache_misses':0,'stages':[]}
        hits+=result.get('cache_hits',0)
        misses+=result.get('cache_misses',0)
        stage_history.extend(result.get('stages',[]))
        if name=='silence':
            all_findings.extend(dict(f) for f in result.get('suggestions',[]))
            if plan.use_vad_for_asr:
                asr_clips,asr_seconds=spoken_clips(clips,result.get('reports',[]))
                if stage:stage(f'Silero concluído · {asr_seconds:.1f}s de fala preparados para transcrição')
        elif name=='whisper':
            reports.extend(result.get('reports',[]))
            for report in result.get('reports',[]):
                accumulated_words.setdefault(report['clip_id'],[]).extend(report.get('words',[]))
        elif name=='qwen':
            context_reports.extend(result.get('reports',[]))
            if 'fillers' in plan.selected:
                # As propostas Qwen são relativas à seleção ORIGINAL, mesmo
                # que o Whisper tenha transcrito segmentos virtuais menores.
                original_by_id={c.id:c for c in clips}
                for report in result.get('reports',[]):
                    original=original_by_id.get(report['clip_id'])
                    if original is None:continue
                    offset=float(report['start'])-original.start
                    for f in report.get('suggestions',[]):
                        entry=dict(f)
                        entry['a']=round(float(f['a'])+offset,5)
                        entry['b']=round(float(f['b'])+offset,5)
                        all_findings.append(entry)
        if progress:progress((i+1)*100,total)
    if stage:stage('Preparando revisão de cortes e resultados da fila')
    return {'plan':plan, 'reports':reports,'context_reports':context_reports,
            'suggestions':all_findings,
            'qwen_errors':qwen_errors,
            'cache_hits':hits,'cache_misses':misses,'stages':stage_history,
            'source_seconds':sum(c.end-c.start for c in clips),
            'asr_seconds':asr_seconds,
            'virtual_clips':len(asr_clips)}


def apply_reviewed_cuts(project, targets, findings, on_progress=None, control=None):
    """Corta somente os blocos aprovados e devolve escopos atualizados.

    ``findings`` têm a/b em segundos da FONTE relativos ao clipe ORIGINAL,
    não da timeline. Cada clipe preservado é um novo trecho de fonte; o áudio
    e as legendas podem ser remapeados após compactar estes trechos.
    """
    from .action_scope import ScopeTarget
    by_id={}
    for f in findings:
        if f.get('clip_id') and float(f['b'])-float(f['a']) >= 0.03:
            by_id.setdefault(f['clip_id'],[]).append((float(f['a']),float(f['b'])))
    affected={}
    count=len(by_id)
    for index,(clip_id,ranges) in enumerate(by_id.items(),1):
        if control:control.checkpoint()
        original=project.clip(clip_id)
        if original is None or not project.can_edit_linked_av(clip_id):
            continue
        affected[clip_id]=project.cut_intervals(
            clip_id,[(a/original.speed,b/original.speed) for a,b in ranges])
        if on_progress:on_progress(index,max(1,count))
    remapped=[]
    for target in targets:
        old_pieces=affected.get(target.original_id)
        if old_pieces is None:
            current=project.clip(target.original_id)
            old_pieces=[current] if current is not None else []
        for piece in old_pieces:
            a=max(piece.start,target.source_start)
            b=min(piece.end,target.source_end)
            if b-a<0.045:continue
            start=piece.timeline_start+(a-piece.start)/piece.speed
            end=piece.timeline_start+(b-piece.start)/piece.speed
            remapped.append(ScopeTarget(piece.id,a,b,start,end,piece.track_id))
    return remapped


def _split_timeline_and_remap_targets(project, ids, at, targets):
    """Split clips at one timeline boundary and keep selected scopes current."""
    from .action_scope import ScopeTarget
    before={clip.id:clip for clip in project.clips}
    changed=set(project.split_at_timeline(set(ids),float(at)))
    if not changed:return
    new_ids={clip.id for clip in project.clips}-set(before)
    replacements={}
    for old_id in changed:
        old=before.get(old_id)
        if old is None:continue
        pieces=[project.clip(cid) for cid in new_ids]
        pieces=[piece for piece in pieces if piece is not None and
                piece.source==old.source and piece.track_id==old.track_id and
                piece.kind==old.kind]
        parents=[target for target in targets if target.original_id==old_id]
        for parent in parents:
            children=[]
            for piece in pieces:
                # Uma mídia pode aparecer várias vezes na mesma faixa. Exija
                # sobreposição temporal e de fonte para não remapear um escopo
                # para outra instância do mesmo arquivo.
                if (piece.timeline_end<=parent.timeline_start+.001 or
                        piece.timeline_start>=parent.timeline_end-.001):
                    continue
                start=max(float(parent.source_start),float(piece.start))
                end=min(float(parent.source_end),float(piece.end))
                if end-start<.045:continue
                left=piece.timeline_start+(start-piece.start)/piece.speed
                right=piece.timeline_start+(end-piece.start)/piece.speed
                children.append(ScopeTarget(piece.id,start,end,left,right,piece.track_id))
            if children:replacements[old_id,parent]=children
    if replacements:
        rebuilt=[]
        for target in targets:
            children=replacements.get((target.original_id,target))
            rebuilt.extend(children if children is not None else [target])
        targets[:]=rebuilt


def apply_reviewed_speedups(project, originals, targets, findings, *, default_speed=2.0,
                            control=None):
    """Time-compress reviewed voice-free gameplay spans non-destructively.

    Each accepted source interval is isolated with timeline splits, sped up,
    then downstream clips ripple left by exactly the duration saved. The full
    operation mutates only the supplied project copy and is one UI undo step.
    A locked or ambiguous timeline scope is skipped rather than partially
    desynchronizing tracks.
    """
    from math import isfinite
    import copy
    from .action_scope import ScopeTarget
    applied=[];skipped=[]
    def original_for(finding):
        return originals.get(str(finding.get('clip_id','')))
    def map_order(finding):
        original=original_for(finding)
        if original is None:return -1.0
        try:return original.timeline_start+float(finding['a'])/max(.0001,original.speed)
        except (KeyError,TypeError,ValueError):return -1.0
    speed_findings=sorted((item for item in findings if item.get('type')=='speedup'),
                          key=map_order,reverse=True)
    for finding in speed_findings:
        if control:control.checkpoint()
        original=original_for(finding)
        try:
            relative_start=float(finding['a']);relative_end=float(finding['b'])
            speed=float(finding.get('speed',default_speed))
        except (KeyError,TypeError,ValueError):
            skipped.append('Intervalo ou velocidade inválidos.');continue
        if (original is None or not isfinite(relative_start) or not isfinite(relative_end)
                or not isfinite(speed) or relative_start<0 or relative_end<=relative_start
                or speed<=1.0 or speed>10.0):
            skipped.append('Intervalo ou velocidade fora dos limites.');continue
        source_start=original.start+relative_start
        source_end=min(original.end,original.start+relative_end)
        if source_end-source_start<.15:
            skipped.append('Trecho curto demais para acelerar com segurança.');continue

        candidates=[]
        for target in targets:
            if target.track_id!=original.track_id or target.source_start>source_start+.001 or target.source_end<source_end-.001:
                continue
            clip=project.clip(target.original_id)
            if (clip is not None and clip.source==original.source and clip.kind==original.kind
                    and clip.start<=source_start+.001 and clip.end>=source_end-.001):
                candidates.append((target,clip))
        if len(candidates)!=1:
            skipped.append('O trecho não corresponde a um único bloco selecionado e editável.')
            continue
        target,clip=candidates[0]
        if clip.kind not in ('video','audio') or not project.can_edit_linked_av(clip.id):
            skipped.append('A faixa do trecho ou seu áudio vinculado está bloqueado.')
            continue
        end_time=clip.timeline_start+(source_end-clip.start)/clip.speed
        locked=[item for item in project.clips if not project.track_is_editable(item.track_id) and
                (item.timeline_start>=end_time-.00001 or
                 item.timeline_start+.05<end_time<item.timeline_end-.05)]
        if locked:
            skipped.append('Aceleração ignorada porque o ripple afetaria clipes em faixas bloqueadas.')
            continue

        # A failed boundary split must never leave half an edit in the project.
        project_state=copy.deepcopy(project.__dict__)
        target_state=copy.deepcopy(targets)
        def rollback(reason):
            project.__dict__.clear()
            project.__dict__.update(project_state)
            targets[:]=target_state
            skipped.append(reason)

        # Isolate the target interval, keeping separated A/V linked at each edge.
        linked={item.id for item in project.linked_av_members(clip.id)}
        _split_timeline_and_remap_targets(project,linked,end_time,targets)
        middle_candidates=[item for item in project.clips if item.track_id==clip.track_id and
            item.source==clip.source and item.kind==clip.kind and
            item.start<=source_start+.001 and item.end>=source_end-.001]
        if len(middle_candidates)!=1:
            rollback('Não foi possível isolar o trecho de gameplay na timeline.')
            continue
        middle=middle_candidates[0]
        linked={item.id for item in project.linked_av_members(middle.id)}
        middle_start=middle.timeline_start+(source_start-middle.start)/middle.speed
        _split_timeline_and_remap_targets(project,linked,middle_start,targets)
        middle_candidates=[item for item in project.clips if item.track_id==clip.track_id and
            item.source==clip.source and item.kind==clip.kind and
            abs(item.start-source_start)<=.002 and abs(item.end-source_end)<=.002]
        if len(middle_candidates)!=1:
            rollback('A divisão não produziu um bloco único para a aceleração.')
            continue
        middle=middle_candidates[0]
        old_end=middle.timeline_end
        old_duration=middle.duration
        if speed<=middle.speed+.001 or not project.set_speed(middle.id,speed):
            rollback('O trecho já está nessa velocidade ou não pode ser alterado.')
            continue
        saved=old_duration-middle.duration
        if saved<=.001:
            rollback('A alteração não reduziria a duração do trecho.')
            continue

        # Split every editable crossing clip at the old boundary before the
        # ripple, so overlays and separate audio move in sync with the picture.
        crossing=[item.id for item in project.clips if item.timeline_start+.05<old_end<item.timeline_end-.05]
        _split_timeline_and_remap_targets(project,crossing,old_end,targets)
        moved=[]
        for item in project.clips:
            if item.timeline_start>=old_end-.00001 and item.generated_by!='auto_caption':
                item.timeline_start=max(0.,round(item.timeline_start-saved,5))
                project._sync_auto_captions(item)
                moved.append(item.id)
        # Keep the supplied review scopes aligned to the new timeline.
        for index,current in enumerate(targets):
            updated=project.clip(current.original_id)
            if updated is not None:
                targets[index]=ScopeTarget(current.original_id,current.source_start,
                    current.source_end,updated.timeline_start+
                    (current.source_start-updated.start)/updated.speed,
                    updated.timeline_start+(current.source_end-updated.start)/updated.speed,
                    current.track_id)
        applied.append({'clip_id':original.id,'a':relative_start,'b':relative_end,
                        'speed':speed,'saved_seconds':round(saved,5),
                        'changed_ids':list(linked)+moved})
    return {'applied':applied,'skipped':skipped}
