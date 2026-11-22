"""Modelo de timeline nao destrutiva com camadas UNIVERSAIS.

A ordem de ``tracks`` e de cima para baixo. Video e imagens nas faixas
superiores aparecem a frente das inferiores. Audio e sempre mixado, e
nao tem profundidade visual. A mesma trilha aceita diferentes tipos de midia.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict, field, replace
import json
import math
import os
from pathlib import Path
from uuid import uuid4
from berofel.core.motion import slice_keyframes, retime_keyframes


def new_id() -> str:
    return uuid4().hex


@dataclass
class Track:
    name: str = 'Camada'
    id: str = field(default_factory=new_id)
    hidden: bool = False            # afeta APENAS imagem/video/texto
    muted: bool = False             # afeta APENAS audio
    locked: bool = False            # impede edicoes de blocos
    height: int = 70
    volume: float = 1.0             # ganho linear aplicado à faixa de áudio
    pan: float = 0.0                # -1 = esquerda, 0 = centro, +1 = direita
    solo: bool = False             # ouve apenas esta camada de áudio


@dataclass
class Clip:
    source: str
    start: float                    # posicao inicial no ARQUIVO de origem
    end: float                      # posicao final no ARQUIVO de origem
    title: str = ''
    id: str = field(default_factory=new_id)
    track_id: str = ''
    timeline_start: float = 0.0     # posicao na TIMELINE, independente da origem
    kind: str = 'video'             # video, audio, image, text
    text: str = ''
    opacity: float = 1.0
    volume: float = 1.0
    scale: float = 1.0
    pos_x: int = 0                  # deslocamento a partir do centro do canvas
    pos_y: int = 0
    font_size: int = 60
    font_family: str = 'Arial'
    font_color: str = '#FFFFFF'
    stroke_color: str = '#000000'
    stroke_width: int = 3
    include_audio: bool = True
    source_length: float = 0.0       # duracao maxima da fonte para recuperar bordas
    stack_order: int = 0            # z dentro da mesma camada; maior na frente
    speed: float = 1.0              # 0.25 a 10x; fonte continua intacta
    keyframes: dict = field(default_factory=dict)  # t relativo ao playback
    fade_in: float = 0.0            # transição visual de entrada
    fade_out: float = 0.0           # transição visual de saída
    audio_fade_in: float = 0.0
    audio_fade_out: float = 0.0
    rotation: float = 0.0          # graus; também animável
    brightness: float = 0.0        # -1 a 1
    contrast: float = 1.0          # 0 a 2
    saturation: float = 1.0        # 0 a 3
    crop_left: float = 0.0         # fração da dimensão de origem
    crop_right: float = 0.0
    crop_top: float = 0.0
    crop_bottom: float = 0.0
    audio_highpass: int = 0        # 0 = desativado
    audio_lowpass: int = 0
    audio_denoise: bool = False
    preserve_pitch: bool = False   # time-stretch do áudio ao alterar speed
    voice_eq_bass_db: float = 0.0
    voice_eq_mids_db: float = 0.0
    voice_eq_treble_db: float = 0.0
    voice_pitch_semitones: float = 0.0
    voice_dsp_bypass: bool = False
    voice_dsp_preset: str = 'Natural'
    group_id: str = ''
    generated_by: str = ''         # vazio para clips normais; identifica legendas automáticas
    caption_anchor_clip_id: str = ''
    caption_source_start: float | None = None
    caption_source_end: float | None = None
    caption_words: list[dict] = field(default_factory=list)
    caption_generated_text: str = ''
    narration_script_id: str = ''
    narration_line_id: str = ''
    narration_voice_id: str = ''

    @property
    def duration(self) -> float:
        return max(0., self.end - self.start) / max(0.0001,self.speed)

    @property
    def timeline_end(self) -> float:
        return self.timeline_start + self.duration

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Project:
    clips: list[Clip] = field(default_factory=list)
    media: list[str] = field(default_factory=list)
    transcripts: list[dict] = field(default_factory=list)  # palavras com tempos ABSOLUTOS na fonte
    markers: list[dict] = field(default_factory=list)
    ai_coverage: list[dict] = field(default_factory=list)  # trechos transcritos, com fingerprint e modelo
    name: str = 'Sem titulo'
    path: str = ''
    tracks: list[Track] = field(default_factory=lambda: [
        Track(name=f'Camada {n}') for n in (4, 3, 2, 1)
    ])
    width: int = 1280
    height: int = 720
    fps: int = 30
    review_queue: list[dict] = field(default_factory=list)
    review_title: str = ''
    narration_scripts: list[dict] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return max((clip.timeline_end for clip in self.clips), default=0.0)

    def track(self, track_id: str) -> Track | None:
        return next((t for t in self.tracks if t.id == track_id), None)

    def clip(self, clip_id: str) -> Clip | None:
        return next((c for c in self.clips if c.id == clip_id), None)

    def relink_media(self, old_source: str, new_source: str) -> int:
        """Relink one missing source and its transcript references non-destructively.

        Transcript text remains available, but coverage fingerprints tied to
        the old path are invalidated so a different file cannot reuse stale AI.
        """
        old_key=os.path.normcase(str(Path(old_source).resolve()))
        new_path=str(Path(new_source).resolve(strict=True))
        new_key=os.path.normcase(new_path)
        if old_key==new_key:
            return 0
        changed=0
        for clip in self.clips:
            if clip.source and os.path.normcase(str(Path(clip.source).resolve()))==old_key:
                clip.source=new_path
                changed+=1
        media=[]
        seen=set()
        for source in self.media:
            if os.path.normcase(str(Path(source).resolve()))==old_key:
                source=new_path
                changed+=1
            key=os.path.normcase(str(Path(source).resolve()))
            if key not in seen:
                seen.add(key);media.append(source)
        self.media=media
        for word in self.transcripts:
            source=word.get('source')
            if source and os.path.normcase(str(Path(source).resolve()))==old_key:
                word['source']=new_path
                changed+=1
        retained=[]
        for coverage in self.ai_coverage:
            identity=coverage.get('source',{})
            if (isinstance(identity,dict) and identity.get('path')
                    and os.path.normcase(str(Path(identity['path']).resolve()))==old_key):
                continue
            retained.append(coverage)
        self.ai_coverage=retained
        return changed

    def _sync_auto_captions(self, clip: Clip) -> None:
        """Reposiciona legendas editáveis pelo intervalo de fonte do clipe."""
        for caption in list(self.clips):
            if (caption.kind != 'text' or caption.generated_by != 'auto_caption'
                    or caption.caption_anchor_clip_id != clip.id
                    or caption.caption_source_start is None
                    or caption.caption_source_end is None):
                continue
            start=max(clip.start,float(caption.caption_source_start))
            end=min(clip.end,float(caption.caption_source_end))
            generated_text=caption.text == caption.caption_generated_text
            if generated_text and caption.caption_words:
                words=[dict(word) for word in caption.caption_words
                       if clip.start-.005 <= float(word['source_start'])
                       and float(word['source_end']) <= clip.end+.005]
                words.sort(key=lambda word:(float(word['source_start']),
                                            float(word['source_end'])))
                if words:
                    caption.caption_words=words
                    caption.text=' '.join(str(word['text']).strip() for word in words).strip()
                    caption.caption_generated_text=caption.text
                    start=float(words[0]['source_start'])
                    end=float(words[-1]['source_end'])
                else:
                    self.clips.remove(caption)
                    continue
            if end-start < .045:
                if generated_text:
                    self.clips.remove(caption)
                else:
                    # Preserva a revisão manual e deixa de vinculá-la a uma
                    # região de fonte que já não existe no clipe.
                    caption.generated_by='manual_caption'
                    caption.caption_anchor_clip_id=''
                    caption.caption_source_start=None
                    caption.caption_source_end=None
                    caption.caption_words=[]
                continue
            caption.caption_source_start=start
            caption.caption_source_end=end
            caption.start=0.
            caption.end=round((end-start)/clip.speed,5)
            caption.timeline_start=round(
                clip.timeline_start+(start-clip.start)/clip.speed,5)

    def _reanchor_auto_captions(self, original_id: str, pieces: list[Clip]) -> None:
        """Reparte cues originais pelos fragmentos sem alterar revisões manuais."""
        for caption in list(self.clips):
            if (caption.kind != 'text' or caption.generated_by != 'auto_caption'
                    or caption.caption_anchor_clip_id != original_id
                    or caption.caption_source_start is None
                    or caption.caption_source_end is None):
                continue
            if caption.caption_words and caption.text == caption.caption_generated_text:
                groups=[]
                for piece in pieces:
                    words=[word for word in caption.caption_words
                           if piece.start-.005 <= float(word['source_start'])
                           and float(word['source_end']) <= piece.end+.005]
                    words.sort(key=lambda word:(float(word['source_start']),
                                                float(word['source_end'])))
                    if words:
                        groups.append((piece,words))
                if not groups:
                    # Nenhuma palavra do cue sobreviveu; o texto foi gerado pela IA
                    # e continua inalterado, portanto pode sair junto com a fala.
                    self.clips.remove(caption)
                    continue
                template=replace(caption)
                for index,(piece,words) in enumerate(groups):
                    fragment=caption if index==0 else replace(template,id=new_id())
                    text=' '.join(str(word['text']).strip() for word in words).strip()
                    source_start=float(words[0]['source_start'])
                    source_end=float(words[-1]['source_end'])
                    fragment.text=text
                    fragment.caption_generated_text=text
                    fragment.caption_words=[dict(word) for word in words]
                    fragment.caption_anchor_clip_id=piece.id
                    fragment.caption_source_start=source_start
                    fragment.caption_source_end=source_end
                    fragment.start=0.
                    fragment.end=round((source_end-source_start)/piece.speed,5)
                    fragment.timeline_start=round(
                        piece.timeline_start+(source_start-piece.start)/piece.speed,5)
                    if index:
                        self.clips.append(fragment)
                continue
            start=float(caption.caption_source_start)
            end=float(caption.caption_source_end)
            matches=[piece for piece in pieces
                     if piece.start-.001 <= start and end <= piece.end+.001]
            if len(matches)==1:
                caption.caption_anchor_clip_id=matches[0].id
                self._sync_auto_captions(matches[0])
            else:
                # Uma revisão manual pode atravessar o trecho removido. Mantém
                # o overlay e seu texto no projeto, sem referência ao clipe extinto.
                caption.generated_by='manual_caption'
                caption.caption_anchor_clip_id=''
                caption.caption_source_start=None
                caption.caption_source_end=None
                caption.caption_words=[]

    def track_is_editable(self, track_id: str) -> bool:
        track = self.track(track_id)
        return bool(track and not track.locked)

    def can_reflow_narration_script(self, script_id: str, line_clip_id: str,
                                    anchor_start: float, old_end: float) -> bool:
        """Return whether replacing a dialogue line may ripple its script lane.

        Only clips owned by the same narration script participate. Locked tracks
        follow the editor's normal edit policy and prevent a partial ripple.
        """
        script_clips = [clip for clip in self.clips
                        if clip.narration_script_id == script_id]
        target = next((clip for clip in script_clips if clip.id == line_clip_id), None)
        if target is not None and not self.track_is_editable(target.track_id):
            return False
        if target is None:
            script_tracks = {clip.track_id for clip in script_clips}
            if script_tracks and any(not self.track_is_editable(track_id)
                                     for track_id in script_tracks):
                return False
        return all(
            self.track_is_editable(clip.track_id)
            for clip in script_clips
            if clip.id != line_clip_id
            and clip.timeline_start >= old_end - .001
            and clip.timeline_start >= anchor_start
        )

    def narration_script_is_editable(self, script_id: str) -> bool:
        """Whether every clip owned by a narration script can be edited."""
        return all(self.track_is_editable(clip.track_id)
                   for clip in self.clips
                   if clip.narration_script_id == script_id)

    def reflow_narration_script_after_replacement(
            self, script_id: str, line_clip_id: str, anchor_start: float,
            old_end: float, delta: float) -> bool:
        """Shift following clips of one script, leaving all other media intact."""
        if not self.can_reflow_narration_script(
                script_id, line_clip_id, anchor_start, old_end):
            return False
        for clip in self.clips:
            if (clip.narration_script_id == script_id
                    and clip.id != line_clip_id
                    and clip.timeline_start >= old_end - .001
                    and clip.timeline_start >= anchor_start):
                clip.timeline_start = max(0.0, clip.timeline_start + delta)
        return True

    def upsert_narration_line_clip(self, *, script_id: str, line_id: str,
                                   source: str, duration: float, title: str,
                                   track_id: str, timeline_start: float,
                                   voice_id: str) -> tuple[Clip | None, bool]:
        """Insert or refresh one generated dialogue clip without duplicating it.

        Existing timeline position and clip-level DSP settings are preserved.
        Returns ``(clip, created)``; a locked lane returns ``(None, False)``.
        """
        clip = next((item for item in self.clips
                     if item.narration_script_id == script_id
                     and item.narration_line_id == line_id), None)
        target_track = clip.track_id if clip else track_id
        if not self.track_is_editable(target_track):
            return None, False
        if clip is None:
            clip = Clip(source=source, start=0.0, end=duration, title=title,
                        track_id=target_track, timeline_start=max(0.0, timeline_start),
                        kind='audio', include_audio=True, source_length=duration,
                        narration_script_id=script_id, narration_line_id=line_id,
                        narration_voice_id=voice_id)
            self.add_clip(clip)
            return clip, True
        clip.source = source
        clip.start = 0.0
        clip.end = duration
        clip.source_length = duration
        clip.title = title
        clip.narration_voice_id = voice_id
        return clip, False

    def add_track(self, name: str = '', index: int = 0) -> Track:
        track = Track(name=name.strip() or f'Camada {len(self.tracks)+1}')
        self.tracks.insert(max(0, min(len(self.tracks), index)), track)
        return track

    def rename_track(self, track_id: str, name: str) -> bool:
        track = self.track(track_id)
        if not track or not name.strip():
            return False
        track.name = name.strip()
        return True

    def move_track(self, track_id: str, direction: int) -> bool:
        """direction -1 = sobe / frente; +1 = desce / fundo."""
        idx = next((i for i, t in enumerate(self.tracks) if t.id == track_id), None)
        if idx is None or not 0 <= idx + direction < len(self.tracks):
            return False
        self.tracks[idx], self.tracks[idx+direction] = self.tracks[idx+direction], self.tracks[idx]
        return True

    def delete_track(self, track_id: str) -> bool:
        track = self.track(track_id)
        if not track or len(self.tracks) <= 1 or any(c.track_id == track_id for c in self.clips):
            return False
        self.tracks = [t for t in self.tracks if t.id != track_id]
        return True

    def add_clip(self, clip: Clip) -> Clip:
        if not self.track(clip.track_id):
            raise ValueError('Escolha uma camada existente antes de adicionar o bloco.')
        if not self.track_is_editable(clip.track_id):
            raise ValueError('Esta camada esta bloqueada.')
        if clip.timeline_start < 0 or clip.duration <= 0:
            raise ValueError('Posicao ou duracao invalidas.')
        clip.stack_order = max((c.stack_order for c in self.clips if c.track_id == clip.track_id), default=-1)+1
        self.clips.append(clip)
        return clip

    def move_clip(self, clip_id: str, track_id: str, timeline_start: float) -> bool:
        clip = self.clip(clip_id)
        if (clip is None or not self.track_is_editable(clip.track_id)
                or not self.track_is_editable(track_id)):
            return False
        if clip.track_id != track_id:
            clip.stack_order = max((c.stack_order for c in self.clips if c.track_id == track_id), default=-1)+1
        clip.track_id = track_id
        clip.timeline_start = max(0., round(timeline_start, 4))
        self._sync_auto_captions(clip)
        return True

    def split(self, clip_id: str, time_in_clip: float) -> bool:
        clip = self.clip(clip_id)
        if not clip or not self.track_is_editable(clip.track_id):
            return False
        if not .05 < time_in_clip < clip.duration - .05:
            return False
        boundary = clip.start + time_in_clip*clip.speed
        first = replace(clip, id=new_id(), end=boundary, title=clip.title,
                        keyframes=slice_keyframes(clip.keyframes, 0, time_in_clip))
        second = replace(clip, id=new_id(), start=boundary, title=clip.title,
                         keyframes=slice_keyframes(clip.keyframes, time_in_clip, clip.duration),
                         timeline_start=clip.timeline_start+time_in_clip)
        first.fade_out=0.0;first.audio_fade_out=0.0
        second.fade_in=0.0;second.audio_fade_in=0.0
        i = self.clips.index(clip)
        self.clips[i:i+1] = [first, second]
        self._reanchor_auto_captions(clip.id,[first,second])
        return True

    def split_at_timeline(self, ids: set[str], at: float) -> list[str]:
        """Aplica o corte somente nos IDs selecionados que cruzam o cursor."""
        changed = []
        # Um grupo AV/legendas vinculadas precisa ser cortado como unidade.
        # Se uma faixa participante estiver bloqueada, deixa o grupo inteiro
        # intacto em vez de desalinhar áudio ou âncoras de legenda.
        requested=[c for c in self.clips if c.id in ids and
                   c.timeline_start+.05<at<c.timeline_end-.05]
        groups={c.group_id for c in requested if c.group_id}
        blocked_groups={group for group in groups if any(
            not self.track_is_editable(member.track_id)
            for member in self.clips if member.group_id==group and
            member.timeline_start+.05<at<member.timeline_end-.05)}
        # Partes esquerdo/direito ficam vinculadas separadamente. Sem isso,
        # um split de vídeo+áudio faria TODOS os fragmentos se moverem juntos.
        new_group_ids={}
        for c in list(self.clips):
            if (c.id in ids and c.group_id not in blocked_groups and
                    c.timeline_start + .05 < at < c.timeline_end - .05):
                original_group=c.group_id
                if self.split(c.id, at-c.timeline_start):
                    changed.append(c.id)
                    if original_group:
                        left,right=new_group_ids.setdefault(original_group,(new_id(),new_id()))
                        for piece in self.clips:
                            if piece.group_id==original_group and piece.id!=c.id:
                                if abs(piece.timeline_end-at)<1e-5 and abs(piece.timeline_start-c.timeline_start)<1e-5:
                                    piece.group_id=left
                                elif abs(piece.timeline_start-at)<1e-5 and abs(piece.timeline_end-c.timeline_end)<1e-5:
                                    piece.group_id=right
        return changed

    def trim_clip(self, clip_id: str, side: str, new_time: float) -> bool:
        """Apara bordas sem alterar a fonte e mantém pares AV vinculados juntos."""
        c=self.clip(clip_id)
        if not c:return False
        members=(self.linked_av_members(clip_id) if c.kind in ('video','audio') else [c])
        if not members or any(not self.track_is_editable(member.track_id) for member in members):
            return False
        changed=False
        for member in members:
            changed=self._trim_clip_one(member.id,side,new_time) or changed
        return changed

    def _trim_clip_one(self,clip_id: str,side: str,new_time: float) -> bool:
        c=self.clip(clip_id)
        if not c or not self.track_is_editable(c.track_id):return False
        if side == 'left':
            # novo inicio <= antigo fim; nao permite tempo de origem negativo.
            delta = max(-c.start, min(c.duration-.10, new_time-c.timeline_start))
            old_duration = c.duration
            c.start += delta*c.speed
            c.keyframes=slice_keyframes(c.keyframes, max(0,delta),old_duration) if delta>=0 else (
                {name:[{**point,'t':point['t']-delta} for point in pts]
                 for name,pts in c.keyframes.items()})
            c.timeline_start = max(0., c.timeline_start + delta)
            self._sync_auto_captions(c)
            return True
        if side == 'right':
            delta = new_time-c.timeline_end
            new_end = c.end + delta*c.speed
            limit = c.source_length if c.source_length > 0 else max(c.end, new_end)
            c.end = min(limit, max(c.start+.1*c.speed, new_end))
            c.keyframes=slice_keyframes(c.keyframes,0,c.duration)
            self._sync_auto_captions(c)
            return True
        return False

    def roll_edit(self, left_id: str, right_id: str, delta: float) -> list[str]:
        """Move a shared cut while keeping the pair's outer duration unchanged.

        ``delta`` is measured in timeline seconds. Positive values extend the
        left clip and trim the head of the right clip. Linked audio/video pairs
        on matching tracks follow the same timeline change.
        """
        left,right=self.clip(left_id),self.clip(right_id)
        if (left is None or right is None or left.id==right.id or
                left.track_id!=right.track_id or left.kind not in ('video','audio') or
                right.kind not in ('video','audio') or
                not self.track_is_editable(left.track_id)):
            return []
        delta=float(delta)
        if not math.isfinite(delta) or abs(delta)<1e-7:
            return []
        if abs(left.timeline_end-right.timeline_start)>.02:
            return []

        pairs=[(left,right)]
        if left.group_id and right.group_id:
            left_members=[c for c in self.clips if c.group_id==left.group_id and
                          c.source==left.source and c.kind in ('video','audio') and
                          abs(c.timeline_start-left.timeline_start)<.02 and
                          abs(c.timeline_end-left.timeline_end)<.02]
            right_members=[c for c in self.clips if c.group_id==right.group_id and
                           c.source==right.source and c.kind in ('video','audio') and
                           abs(c.timeline_start-right.timeline_start)<.02 and
                           abs(c.timeline_end-right.timeline_end)<.02]
            linked=[]
            for first in left_members:
                for second in right_members:
                    if (first.id!=left.id and second.id!=right.id and
                            first.track_id==second.track_id and first.kind==second.kind):
                        linked.append((first,second))
            pairs.extend(linked)

        # Validate every linked pair before mutating anything, so a locked
        # track or source edge cannot leave video and separated audio apart.
        seen=set()
        for first,second in pairs:
            if (first.id in seen or second.id in seen or
                    not self.track_is_editable(first.track_id) or
                    not self.track_is_editable(second.track_id) or
                    abs(first.timeline_end-second.timeline_start)>.02):
                return []
            seen.update((first.id,second.id))
            new_left_end=first.end+delta*first.speed
            left_limit=first.source_length if first.source_length>0 else first.end
            new_right_start=second.start+delta*second.speed
            if (new_left_end>left_limit+.00001 or
                    new_left_end<first.start+.1*first.speed-.00001 or
                    new_right_start<-.00001 or
                    new_right_start>second.end-.1*second.speed+.00001 or
                    first.timeline_start+first.duration+delta<0):
                return []

        changed=[]
        for first,second in pairs:
            old_right_duration=second.duration
            first.end=round(first.end+delta*first.speed,5)
            first.keyframes=slice_keyframes(first.keyframes,0,first.duration)
            second.start=max(0.,round(second.start+delta*second.speed,5))
            second.timeline_start=max(0.,round(second.timeline_start+delta,5))
            if delta>=0:
                second.keyframes=slice_keyframes(second.keyframes,delta,old_right_duration)
            else:
                second.keyframes={name:[{**point,'t':round(float(point['t'])-delta,5)}
                                         for point in points]
                                  for name,points in second.keyframes.items()}
            second.fade_in=min(second.fade_in,second.duration)
            second.audio_fade_in=min(second.audio_fade_in,second.duration)
            self._sync_auto_captions(first)
            self._sync_auto_captions(second)
            changed.extend((first.id,second.id))
        return changed

    def slip_clip(self, clip_id: str, source_delta: float) -> list[str]:
        """Desloca a janela de origem sem mover ou retimar o clipe na timeline.

        Áudio e vídeo ainda vinculados são deslocados juntos. Legendas geradas
        que passam a descrever outra fala são removidas; legendas revisadas pelo
        usuário são preservadas e desancoradas do intervalo antigo da fonte.
        """
        clip=self.clip(clip_id)
        if (clip is None or clip.kind not in ('video','audio','image')
                or not self.track_is_editable(clip.track_id)):
            return []
        delta=float(source_delta)
        if not math.isfinite(delta):
            raise ValueError('O deslocamento de origem precisa ser um número finito.')
        linked=[clip]
        if clip.group_id:
            linked.extend(other for other in self.clips if other.id!=clip.id
                and other.group_id==clip.group_id and other.source==clip.source
                and other.kind in ('video','audio','image')
                and abs(other.start-clip.start)<.0001 and abs(other.end-clip.end)<.0001
                and abs(other.timeline_start-clip.timeline_start)<.0001
                and self.track_is_editable(other.track_id))
        lower=max(-item.start for item in linked)
        upper=min((item.source_length-item.end) if item.source_length>0 else float('inf')
                  for item in linked)
        delta=max(lower,min(upper,delta))
        if abs(delta)<1e-7:return []
        anchor_ids={item.id for item in linked}
        for item in linked:
            item.start=round(item.start+delta,5)
            item.end=round(item.end+delta,5)
        for caption in list(self.clips):
            if (caption.kind!='text' or caption.generated_by!='auto_caption'
                    or caption.caption_anchor_clip_id not in anchor_ids):
                continue
            if caption.text==caption.caption_generated_text:
                self.clips.remove(caption)
            else:
                # Texto editado é do usuário: mantenha o overlay no mesmo
                # tempo da timeline, sem alegar que ainda corresponde à fonte.
                caption.caption_anchor_clip_id=''
                caption.caption_source_start=None
                caption.caption_source_end=None
                caption.caption_words=[]
        return [item.id for item in linked]

    def slide_clip(self, clip_id: str, timeline_delta: float) -> list[str]:
        """Desloca um clipe entre vizinhos, preservando os limites externos.

        O trecho selecionado mantém fonte e duração. O vizinho anterior cede
        ou ganha mídia no fim, e o seguinte ajusta o início. Quando o clipe é
        um grupo AV, todos os membros e seus vizinhos passam pela mesma
        validação antes de qualquer alteração.
        """
        target=self.clip(clip_id)
        if (target is None or target.kind not in ('video','audio','image')
                or not self.track_is_editable(target.track_id)):
            return []
        delta=float(timeline_delta)
        if not math.isfinite(delta) or abs(delta)<1e-7:
            return []
        members=[target]
        if target.group_id:
            members=[clip for clip in self.clips if clip.group_id==target.group_id and
                     clip.kind in ('video','audio','image') and
                     abs(clip.timeline_start-target.timeline_start)<.001 and
                     abs(clip.timeline_end-target.timeline_end)<.001]
        if not members or any(not self.track_is_editable(clip.track_id) for clip in members):
            return []

        triples=[];used_tracks=set()
        for middle in members:
            if middle.track_id in used_tracks:
                return []
            used_tracks.add(middle.track_id)
            neighbors=[clip for clip in self.clips if clip.id!=middle.id and
                       clip.track_id==middle.track_id and
                       clip.kind in ('video','audio','image')]
            left=[clip for clip in neighbors if abs(clip.timeline_end-middle.timeline_start)<.02]
            right=[clip for clip in neighbors if abs(middle.timeline_end-clip.timeline_start)<.02]
            if len(left)!=1 or len(right)!=1:
                return []
            before,after=left[0],right[0]
            if any(not self.track_is_editable(clip.track_id) for clip in (before,after)):
                return []
            if before.speed<=0 or middle.speed<=0 or after.speed<=0:
                return []
            before_limit=before.source_length if before.source_length>0 else before.end
            before_end=before.end+delta*before.speed
            after_start=after.start+delta*after.speed
            if (middle.timeline_start+delta<0 or
                    before_end<before.start+.05*before.speed-.00001 or
                    before_end>before_limit+.00001 or
                    after_start<-.00001 or
                    after_start>after.end-.05*after.speed+.00001):
                return []
            triples.append((before,middle,after))

        # Não mutar até validar todas as faixas do grupo.
        changed=[]
        for before,middle,after in triples:
            old_after_duration=after.duration
            before.end=round(before.end+delta*before.speed,5)
            if delta<0:
                before.keyframes=slice_keyframes(before.keyframes,0,before.duration)
            middle.timeline_start=round(middle.timeline_start+delta,5)
            after.start=max(0.,round(after.start+delta*after.speed,5))
            after.timeline_start=max(0.,round(after.timeline_start+delta,5))
            if delta>=0:
                after.keyframes=slice_keyframes(after.keyframes,delta,old_after_duration)
            else:
                after.keyframes={name:[{**point,'t':round(float(point['t'])-delta,5)}
                                        for point in points]
                                 for name,points in after.keyframes.items()}
            for clip in (before,middle,after):
                clip.fade_in=min(clip.fade_in,clip.duration)
                clip.fade_out=min(clip.fade_out,clip.duration)
                clip.audio_fade_in=min(clip.audio_fade_in,clip.duration)
                clip.audio_fade_out=min(clip.audio_fade_out,clip.duration)
                self._sync_auto_captions(clip)
                changed.append(clip.id)
        return changed

    def drop_ids(self, ids: set[str]) -> None:
        self.clips = [c for c in self.clips if c.id not in ids or not self.track_is_editable(c.track_id)]

    def cut_intervals(self, clip_id: str,
                      intervals: list[tuple[float, float]]) -> list[Clip]:
        """Remove intervalos de playback sem dessincronizar AV vinculado.

        Se o bloco pertence a um par de vídeo/áudio separado, corta os membros
        equivalentes na mesma transação. Blocos sem vínculo não são movidos e
        os arquivos de origem permanecem intactos.
        """
        clip=self.clip(clip_id)
        if not clip or not self.track_is_editable(clip.track_id):return []
        normalized: list[tuple[float,float]] = []
        for a, b in sorted(intervals):
            a, b = max(0., a), min(clip.duration, b)
            if b-a < .03:
                continue
            if normalized and a <= normalized[-1][1]:
                normalized[-1] = normalized[-1][0], max(normalized[-1][1], b)
            else:
                normalized.append((a,b))
        if not normalized:return [clip]
        members=[clip]
        if clip.kind in ('video','audio') and clip.group_id:
            members=self.linked_av_members(clip_id)
            # Never cut only one side of a linked pair.
            if any(not self.track_is_editable(item.track_id) for item in members):return [clip]

        target_index=members.index(clip)
        survivors_by_member=[]
        for member in members:
            survivors=self._cut_intervals_one(member.id,normalized)
            survivors_by_member.append(survivors)
        if len(survivors_by_member)>1:
            # Each surviving A/V segment gets its own group. Reusing the old
            # group ID for every segment could make later moves drag the whole
            # edited sequence as one block.
            for segment_index in range(min(map(len,survivors_by_member))):
                pieces=[survivors[segment_index] for survivors in survivors_by_member]
                first=pieces[0]
                if all(abs(piece.start-first.start)<.0001 and
                       abs(piece.end-first.end)<.0001 and
                       abs(piece.timeline_start-first.timeline_start)<.0001 and
                       abs(piece.speed-first.speed)<.0001 for piece in pieces[1:]):
                    group=new_id()
                    for piece in pieces:piece.group_id=group
        return survivors_by_member[target_index]

    def _cut_intervals_one(self, clip_id: str,
                           normalized: list[tuple[float,float]]) -> list[Clip]:
        """Aplica intervalos já validados a um único bloco e devolve sobreviventes."""
        clip=self.clip(clip_id)
        if not clip or not self.track_is_editable(clip.track_id):return []
        cursor = 0.0
        output_pos = clip.timeline_start
        survivors = []
        for a,b in normalized + [(clip.duration, clip.duration)]:
            if a-cursor > .04:
                piece = replace(clip, id=new_id(), start=clip.start+cursor*clip.speed,
                                end=clip.start+a*clip.speed, timeline_start=output_pos,
                                keyframes=slice_keyframes(clip.keyframes,cursor,a),
                                fade_in=clip.fade_in if cursor<.001 else 0,
                                fade_out=clip.fade_out if a>=clip.duration-.001 else 0,
                                audio_fade_in=clip.audio_fade_in if cursor<.001 else 0,
                                audio_fade_out=clip.audio_fade_out if a>=clip.duration-.001 else 0)
                output_pos += piece.duration
                survivors.append(piece)
            cursor = max(cursor,b)
        idx = self.clips.index(clip)
        self.clips[idx:idx+1] = survivors
        self._reanchor_auto_captions(clip_id,survivors)
        return survivors

    def group_clips(self, ids: set[str]) -> str:
        clips=[c for c in self.clips if c.id in ids and self.track_is_editable(c.track_id)]
        if len(clips)<2:return ''
        group=new_id()
        for clip in clips:clip.group_id=group
        return group

    def ungroup_clips(self, ids: set[str]) -> int:
        clips=[c for c in self.clips if c.id in ids and self.track_is_editable(c.track_id)]
        groups={c.group_id for c in clips if c.group_id}
        if not groups:return 0
        changed=0
        for c in self.clips:
            if c.group_id in groups and self.track_is_editable(c.track_id):
                c.group_id='';changed+=1
        return changed

    def set_speed(self, clip_id: str, speed: float, preserve_end: bool = False) -> bool:
        clip=self.clip(clip_id)
        if clip is None or not self.track_is_editable(clip.track_id) or clip.kind not in ('video','audio'):
            return False
        speed=float(speed)
        if not .25 <= speed <= 10:
            raise ValueError('A velocidade deve estar entre 0,25× e 10×.')
        linked=self.linked_av_clips(clip_id)
        if all(abs(c.speed-speed)<1e-6 for c in linked):return False
        for target in linked:
            old=target.speed
            old_duration=target.duration
            target.speed=speed
            target.keyframes=retime_keyframes(target.keyframes,old/speed)
            target.fade_in=min(target.fade_in,target.duration)
            target.fade_out=min(target.fade_out,target.duration)
            target.audio_fade_in=min(target.audio_fade_in,target.duration)
            target.audio_fade_out=min(target.audio_fade_out,target.duration)
            if preserve_end:
                target.timeline_start=max(0,target.timeline_start+old_duration-target.duration)
            self._sync_auto_captions(target)
        return True

    def linked_av_clips(self,clip_id: str) -> list[Clip]:
        """Retorna o par AV sincronizado com mesma fonte/trecho e grupo editável."""
        members=self.linked_av_members(clip_id)
        if any(not self.track_is_editable(member.track_id) for member in members):return []
        return members

    def linked_av_members(self,clip_id: str) -> list[Clip]:
        """Todos os membros AV do mesmo trecho, inclusive os bloqueados."""
        clip=self.clip(clip_id)
        if clip is None or clip.kind not in ('video','audio'):
            return []
        linked=[clip]
        if clip.group_id:
            linked.extend(c for c in self.clips if c.id!=clip.id and
                c.group_id==clip.group_id and c.source==clip.source and
                c.kind in ('video','audio') and
                abs(c.start-clip.start)<.0001 and abs(c.end-clip.end)<.0001 and
                abs(c.timeline_start-clip.timeline_start)<.0001 and
                abs(c.speed-clip.speed)<.0001)
        return linked

    def can_edit_linked_av(self,clip_id: str) -> bool:
        """True quando cortar o bloco não deixará um par AV bloqueado para trás."""
        members=self.linked_av_members(clip_id)
        return bool(members) and all(self.track_is_editable(c.track_id) for c in members)

    def set_pitch_preservation(self,clip_id: str,enabled: bool) -> list[str]:
        """Aplica o estado de preservar tom a todo o par AV sincronizado."""
        clip=self.clip(clip_id)
        if clip is None or not self.track_is_editable(clip.track_id):
            return []
        value=bool(enabled)
        changed=[]
        for target in self.linked_av_clips(clip_id):
            if target.preserve_pitch!=value:
                target.preserve_pitch=value
                changed.append(target.id)
        return changed

    def ripple_delete(self, ids: set[str]) -> int:
        """Exclui e fecha buracos somente nas trilhas afetadas; ação EXPLÍCITA."""
        victims=[c for c in self.clips if c.id in ids and self.track_is_editable(c.track_id)]
        if not victims:return 0
        for track_id in set(c.track_id for c in victims):
            rows=sorted((c for c in victims if c.track_id==track_id),key=lambda c:c.timeline_start)
            intervals=[]
            for c in rows:
                a,b=c.timeline_start,c.timeline_end
                if intervals and a<=intervals[-1][1]:
                    intervals[-1]=(intervals[-1][0],max(b,intervals[-1][1]))
                else: intervals.append((a,b))
            # Só desloca os clipes que estavam inteiramente após o intervalo.
            for c in self.clips:
                if c.id in ids or c.track_id!=track_id:continue
                displacement=sum(b-a for a,b in intervals if c.timeline_start >= b - 1e-7)
                if displacement:
                    c.timeline_start=max(0,round(c.timeline_start-displacement,5))
                    self._sync_auto_captions(c)
        self.drop_ids(ids)
        return len(victims)

    def transition_overlap(self, left_id: str, right_id: str, seconds: float, style: str = "dissolve") -> bool:
        """Dissolvência visual e crossfade de áudio em clipes da mesma camada."""
        left,right=self.clip(left_id),self.clip(right_id)
        if (left is None or right is None or left.id==right.id or
            left.track_id!=right.track_id or not self.track_is_editable(left.track_id) or
            left.kind not in ('video','image') or right.kind not in ('video','image')):
            return False
        if style not in ('dissolve','slide','zoom'):
            raise ValueError('Transição desconhecida.')
        seconds=max(.05,min(float(seconds),left.duration*.45,right.duration*.45))
        left_audio=[];right_audio=[]
        if left.group_id:
            left_audio=[clip for clip in self.clips if clip.id!=left.id and
                clip.group_id==left.group_id and clip.source==left.source and
                clip.kind=='audio' and abs(clip.start-left.start)<.0001 and
                abs(clip.end-left.end)<.0001 and
                abs(clip.timeline_start-left.timeline_start)<.0001]
        if right.group_id:
            right_audio=[clip for clip in self.clips if clip.id!=right.id and
                clip.group_id==right.group_id and clip.source==right.source and
                clip.kind=='audio' and abs(clip.start-right.start)<.0001 and
                abs(clip.end-right.end)<.0001 and
                abs(clip.timeline_start-right.timeline_start)<.0001]
        # A separated stem must follow the visual overlap and crossfade. If
        # either linked audio track is locked, reject before touching any clip.
        if any(not self.track_is_editable(clip.track_id)
               for clip in (*left_audio,*right_audio)):
            return False
        # Sobrepõe o começo do próximo ao fim do anterior.
        right.timeline_start=max(0,left.timeline_end-seconds)
        self._sync_auto_captions(right)
        right.fade_in=seconds if style in ('dissolve','zoom') else 0
        if style == 'slide':
            from berofel.core.motion import put_keyframe
            put_keyframe(right,'pos_x',0,right.pos_x+self.width,'ease-out')
            put_keyframe(right,'pos_x',seconds,right.pos_x,'linear')
        elif style == 'zoom':
            from berofel.core.motion import put_keyframe
            put_keyframe(right,'scale',0,max(.05,right.scale*.72),'ease-out')
            put_keyframe(right,'scale',seconds,right.scale,'linear')
        left.audio_fade_out=seconds
        right.audio_fade_in=seconds
        # Áudio separado não passa mais pelo filtro do clipe de vídeo. Espelha
        # o overlap/crossfade nos membros de áudio vinculados, se editáveis.
        for audio_clip in left_audio:
            if self.track_is_editable(audio_clip.track_id):
                audio_clip.audio_fade_out=min(seconds,audio_clip.duration)
                self._sync_auto_captions(audio_clip)
        for audio_clip in right_audio:
            if self.track_is_editable(audio_clip.track_id):
                audio_clip.timeline_start=right.timeline_start
                audio_clip.audio_fade_in=min(seconds,audio_clip.duration)
                self._sync_auto_captions(audio_clip)
        right.stack_order=max(c.stack_order for c in self.clips if c.track_id==right.track_id)+1
        return True

    def add_marker(self, at:float, label:str='Marcador') -> dict:
        record={'id':new_id(),'time':round(max(0.,float(at)),4),'label':label.strip() or 'Marcador'}
        self.markers.append(record)
        self.markers.sort(key=lambda m:m['time'])
        return record

    def save(self, path: str):
        p = Path(path).resolve()
        data = dict(version=3, name=self.name, media=self.media, transcripts=self.transcripts,
                    markers=self.markers,ai_coverage=self.ai_coverage,
                    review_queue=self.review_queue,review_title=self.review_title,
                    narration_scripts=self.narration_scripts,
                    width=self.width, height=self.height, fps=self.fps,
                    tracks=[asdict(t) for t in self.tracks],
                    clips=[c.as_dict() for c in self.clips])
        p.parent.mkdir(parents=True, exist_ok=True)
        temp = p.with_name(p.name+'.tmp')
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(p)
        self.path = str(p)

    @classmethod
    def load(cls, path: str) -> 'Project':
        p = Path(path).resolve()
        data = json.loads(p.read_text(encoding='utf-8'))
        version = data.get('version', 1)
        if version == 1:
            # Migracao sem perda: clips antigos eram concatenados numa faixa.
            project = cls(name=data.get('name',p.stem), media=data.get('media',[]), path=str(p))
            lane = project.tracks[-1]
            position = 0.0
            for record in data.get('clips', []):
                clip = Clip(**record, track_id=lane.id, timeline_start=position, kind='video')
                project.clips.append(clip)
                position += clip.duration
            return project
        if version not in (2, 3):
            raise ValueError(f'Versao de projeto nao suportada: {version}')
        tracks = [Track(**t) for t in data.get('tracks', [])]
        if not tracks:
            raise ValueError('Projeto sem camadas.')
        clips = [Clip(**c) for c in data.get('clips', [])]
        ids = {t.id for t in tracks}
        if any(c.track_id not in ids for c in clips):
            raise ValueError('Projeto contem blocos associados a camadas inexistentes.')
        return cls(clips=clips, media=data.get('media',[]), transcripts=data.get('transcripts',[]),
                   markers=data.get('markers',[]),ai_coverage=data.get('ai_coverage',[]), name=data.get('name',p.stem),
                   path=str(p), tracks=tracks, width=data.get('width',1280),
                   height=data.get('height',720), fps=data.get('fps',30),
                   review_queue=data.get('review_queue',[]),
                   review_title=data.get('review_title',''),
                   narration_scripts=data.get('narration_scripts',[]))
