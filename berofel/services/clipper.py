"""Clipador Inteligente: ranking editorial explicável sem nova inferência.

Reutiliza as palavras já salvas no projeto e calcula eventos acústicos em PCM
streaming. Os tempos são sempre segundos absolutos da mídia de origem.
"""
from __future__ import annotations

from dataclasses import dataclass
from bisect import bisect_left, bisect_right
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Callable, Iterable, Mapping, Sequence

import numpy as np

from .ai_cache import digest, source_identity
from .clip_audio_signals import (FrameFeatures, align_events_to_conversation,
    detect_energy_events, extract_frames_from_chunks, score_clip,
    select_diverse_clips)
from .discourse_features import (analyze_discourse, content_terms, discourse_role,
    text_tiling_boundaries)
from .clip_visual_signals import (read_cached_visual_signals,
    score_cached_visual_interval, detect_cached_visual_events)
from .ffmpeg import ffmpeg_path, media_info

CLIPPER_VERSION = 8
# Keep the persisted v5 feature keys compatible: the PCM/waveform extraction
# format and algorithm did not change. Bump this independently only when they do.
FEATURE_EXTRACTOR_VERSION = 5
FEATURE_RATE = 16_000
FEATURE_FRAME_MS = 20
CACHE_SCHEMA = 1
DEFAULT_CACHE_MB = 512
_PRUNE_EVERY_SAVES = 12
_feature_saves = 0
_TERMINAL = re.compile(r"[.!?…][\"'”’)}\]]*$")
_HOOK_PATTERNS = tuple(re.compile(pattern, re.I) for pattern in (
    r"\bpor que\b", r"\bcomo (?:eu|n[oó]s|voc[eê])\b", r"\bna verdade\b",
    r"\bo segredo\b", r"\bdescobri\b", r"\bresultado\b", r"\bningu[eé]m\b",
    r"\bprimeira vez\b", r"\bmudou tudo\b", r"\bo que aconteceu\b",
    r"\baten[cç][aã]o\b", r"\brepara\b", r"\bpor isso\b", r"\bafinal\b"))
_DEPENDENT_OPENERS = {'e', 'mas', 'porque', 'que', 'quando', 'então', 'entao',
    'isso', 'ele', 'ela', 'eles', 'elas', 'aí', 'ai', 'também', 'tambem',
    'daí', 'dai', 'porém', 'porem', 'só', 'so', 'depois'}
_INCOMPLETE_ENDINGS = {'e', 'mas', 'porque', 'que', 'de', 'do', 'da', 'para',
    'com', 'se', 'quando', 'então', 'entao', 'porém', 'porem', 'ou'}
_ANSWER_CUES = re.compile(
    r"^(?:porque|por isso|a resposta|isso significa|quer dizer|o motivo|"
    r"a razão|a raz[aã]o|acontece que|é que|e é por isso|basicamente|"
    r"na prática|funciona assim|o que ocorre|sim|não|depende)\b", re.I)


@dataclass(frozen=True)
class ClipperOptions:
    min_seconds: float = 15.0
    max_seconds: float = 60.0
    max_candidates: int = 8
    relative_rise_db: float = 6.0
    profile: str = 'Geral'
    mode: str = 'Equilibrado'
    analyze_visual: bool = False
    score_weights: Mapping[str, float] | None = None

    def __post_init__(self):
        if not 3 <= float(self.min_seconds) <= 300:
            raise ValueError('Duração mínima do Clipador deve ficar entre 3 e 300 s.')
        if not float(self.min_seconds) < float(self.max_seconds) <= 600:
            raise ValueError('A duração máxima precisa ser maior que a mínima e até 600 s.')
        if not 1 <= int(self.max_candidates) <= 50:
            raise ValueError('Escolha entre 1 e 50 candidatos.')
        if not 1 <= float(self.relative_rise_db) <= 24:
            raise ValueError('Sensibilidade de energia precisa ficar entre 1 e 24 dB.')
        from .clip_audio_signals import CLIP_SCORE_PROFILES
        if self.profile not in CLIP_SCORE_PROFILES:
            raise ValueError('Perfil do Clipador desconhecido.')
        if self.mode not in ('Rápido','Equilibrado','Avançado'):
            raise ValueError('Modo do Clipador desconhecido.')
        if self.score_weights is not None:
            allowed=set(CLIP_SCORE_PROFILES['Geral'])
            weights={str(key):float(value) for key,value in self.score_weights.items()}
            if (not weights or set(weights)-allowed or
                    any(not np.isfinite(value) or value < 0. or value > 1.
                        for value in weights.values()) or not any(weights.values())):
                raise ValueError('Pesos personalizados devem ser valores finitos entre 0 e 1, com soma positiva.')

    def as_dict(self):
        return {'min_seconds': float(self.min_seconds),
                'max_seconds': float(self.max_seconds),
                'max_candidates': int(self.max_candidates),
                'relative_rise_db': float(self.relative_rise_db),
                'profile': self.profile,'mode':self.mode,
                'analyze_visual':bool(self.analyze_visual),
                'score_weights':({str(key):float(value) for key,value in
                    sorted(self.score_weights.items())}
                    if self.score_weights is not None else None)}


def clipper_cache_dir() -> Path:
    """Keep derived audio features separate from AI weights and user projects."""
    override = os.environ.get('BEROFEL_CLIPPER_CACHE')
    if override:
        return Path(override).expanduser().resolve()
    local = os.environ.get('LOCALAPPDATA')
    return (Path(local) / 'BFS' / 'cache' / 'clipper' if local else
            Path.home() / '.cache' / 'BerofelStudio' / 'clipper')


def _features_key(source: str, start: float, end: float, mode: str = 'pcm') -> str:
    return digest({'version': FEATURE_EXTRACTOR_VERSION, 'source': source_identity(source),
        'start': round(float(start), 4), 'end': round(float(end), 4),
        'stream': 0, 'sample_rate': FEATURE_RATE, 'frame_ms': FEATURE_FRAME_MS,
        'mode': mode})


def _load_features(path: Path, offset_ms: float) -> FrameFeatures | None:
    try:
        with np.load(path, allow_pickle=False) as data:
            rate = int(data['sample_rate'][0])
            frame_ms = float(data['frame_ms'][0])
            rms = data['rms_dbfs'].astype(np.float32, copy=True)
            peak = data['peak_dbfs'].astype(np.float32, copy=True)
            clipped = data['clip_fraction'].astype(np.float32, copy=True)
            level_kind = str(data['level_kind'].item()) if 'level_kind' in data else 'pcm_rms'
        times = offset_ms + np.arange(len(rms), dtype=np.float64) * frame_ms
        return FrameFeatures(times, rms, peak, clipped, frame_ms, rate, level_kind)
    except (OSError, ValueError, KeyError, EOFError):
        return None


def _save_features(path: Path, frames: FrameFeatures, offset_ms: float):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f'.{os.getpid()}.tmp')
    try:
        with temporary.open('wb') as stream:
            np.savez_compressed(stream, sample_rate=np.asarray([frames.sample_rate], np.int32),
                frame_ms=np.asarray([frames.frame_ms], np.float32),
                offset_ms=np.asarray([offset_ms], np.float64),
                rms_dbfs=frames.rms_dbfs, peak_dbfs=frames.peak_dbfs,
                clip_fraction=frames.clip_fraction,
                level_kind=np.asarray(frames.level_kind))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    global _feature_saves
    _feature_saves += 1
    if _feature_saves % _PRUNE_EVERY_SAVES == 0:
        _prune_feature_cache(path.parents[2])


def _prune_feature_cache(folder: Path, max_megabytes: int | None = None):
    """Bound only generated compressed frames; never touch other user files."""
    if max_megabytes is None:
        try:
            max_megabytes=max(64,int(os.environ.get('BEROFEL_CLIPPER_CACHE_MAX_MB',
                                                    str(DEFAULT_CACHE_MB))))
        except ValueError:
            max_megabytes=DEFAULT_CACHE_MB
    pattern=re.compile(r'^[0-9a-f]{32}\.npz$')
    files=[];total=0
    for path in folder.rglob('*.npz'):
        if not pattern.fullmatch(path.name):continue
        try:
            stat=path.stat();files.append((path,stat.st_size,stat.st_mtime_ns))
            total+=stat.st_size
        except OSError:continue
    limit=int(max_megabytes)*1024*1024
    for path,size,_mtime in sorted(files,key=lambda item:item[2]):
        if total<=limit:break
        try:path.unlink();total-=size
        except OSError:pass


def _audio_pcm_chunks(source: str, start: float, duration: float, control=None,
                      progress: Callable[[float, float], None] | None = None
                      ) -> Iterable[np.ndarray]:
    """Decode mono float PCM through a bounded pipe; never buffer the whole media."""
    if duration <= 0:
        return
    command = [ffmpeg_path(), '-hide_banner', '-loglevel', 'error', '-nostdin',
        '-threads', '1', '-ss', f'{max(0., start):.6f}', '-t', f'{duration:.6f}',
        '-i', source, '-map', '0:a:0', '-vn', '-sn', '-dn', '-ac', '1',
        '-ar', str(FEATURE_RATE), '-f', 'f32le', '-acodec', 'pcm_f32le', 'pipe:1']
    launcher = control.popen if control is not None else subprocess.Popen
    proc = launcher(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    expected_bytes = max(1, int(duration * FEATURE_RATE * 4))
    received = 0
    started = control.elapsed() if control is not None else time.monotonic()
    remainder = b''
    try:
        while True:
            raw = proc.stdout.read(64 * 1024)
            if not raw:
                break
            if control is not None:
                control.checkpoint()
                if control.elapsed() - started > max(180., duration * 3.0 + 60.):
                    control._kill(proc)
                    raise TimeoutError('A decodificação PCM do Clipador excedeu o limite de segurança.')
            received += len(raw)
            data = remainder + raw
            aligned = len(data) - len(data) % 4
            remainder = data[aligned:]
            if aligned:
                yield np.frombuffer(data[:aligned], dtype='<f4').copy()
            if progress is not None and received % (2 * 1024 * 1024) < len(raw):
                progress(min(99., received * 100. / expected_bytes), 100.)
        if remainder:
            raise RuntimeError('O FFmpeg devolveu um frame PCM incompleto.')
        proc.wait(timeout=10)
        if proc.returncode != 0:
            raise RuntimeError('FFmpeg não conseguiu decodificar o áudio para análise do Clipador.')
        if progress is not None:
            progress(100., 100.)
    finally:
        if proc.poll() is None:
            if control is not None:
                control._kill(proc)
            else:
                proc.kill()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        if proc.stdout:
            proc.stdout.close()
        if control is not None:
            control.release(proc)


def audio_features(source: str, start: float, end: float, *, control=None,
                   progress=None, cache_dir: Path | None = None,
                   waveform_provider=None, waveform_only: bool = False
                   ) -> tuple[FrameFeatures | None, bool]:
    """Return cached waveform or PCM frames and whether they were reused.

    In waveform-only mode, use the timeline's existing 100 ms peak envelope;
    never decode the media again. Those values are explicitly labeled as a
    peak proxy and are not treated as RMS or clipping measurements.
    """
    if end <= start:
        raise ValueError('Intervalo de áudio inválido para o Clipador.')
    try:
        identity = source_identity(source)
    except (OSError, ValueError):
        return None, False
    mode='waveform' if waveform_only else 'pcm'
    key = _features_key(source, start, end, mode)
    path = (cache_dir or clipper_cache_dir()) / 'features' / key[:2] / f'{key}.npz'
    cached = _load_features(path, start * 1000.)
    if cached is not None:
        return cached, True
    if waveform_only:
        frames=_features_from_cached_waveform(source,start,end,waveform_provider)
        if frames is None:
            return None,False
        _save_features(path,frames,start*1000.)
        return frames,True
    _duration, _has_video, has_audio = media_info(source)
    if not has_audio:
        return None, False
    chunks = _audio_pcm_chunks(source, start, end - start, control, progress)
    frames = extract_frames_from_chunks(chunks, FEATURE_RATE, FEATURE_FRAME_MS)
    if not len(frames.times_ms):
        return None, False
    frames.times_ms += start * 1000.
    _save_features(path, frames, start * 1000.)
    return frames, False


def _features_from_cached_waveform(source: str, start: float, end: float,
                                   provider) -> FrameFeatures | None:
    """Adapt complete cached timeline peak tiles without launching FFmpeg."""
    if provider is None or not hasattr(provider,'get_wave') or end <= start:
        return None
    first=int(start//60)*60
    last=int((end-1e-9)//60)*60
    timestamps=[];levels=[]
    for tile in range(first,last+1,60):
        try:
            data=provider.get_wave(source,tile,request=False)
            offset=float(data['offset']);step=float(data['step'])
            peaks=np.asarray(data['peaks'],dtype=np.float32)
        except (AttributeError,KeyError,TypeError,ValueError):
            return None
        if step<=0 or peaks.ndim!=1 or not len(peaks) or not np.isfinite(peaks).all():
            return None
        if abs(offset-tile)>.05:
            return None
        times=offset+np.arange(len(peaks),dtype=np.float64)*step
        expected_start=max(start,offset)
        expected_end=min(end,offset+60.)
        tile_times=times[(times>=expected_start)&(times<expected_end)]
        if not len(tile_times) or tile_times[0]>expected_start+step*1.5 or \
                tile_times[-1]+step<expected_end-step*1.5:
            return None
        keep=(times>=start)&(times<end)&(times>=offset)&(times<offset+60.)
        if np.any(keep):
            timestamps.extend(times[keep].tolist())
            levels.extend(peaks[keep].tolist())
    if not timestamps:
        return None
    order=np.argsort(np.asarray(timestamps,dtype=np.float64),kind='stable')
    times=np.asarray(timestamps,dtype=np.float64)[order]*1000.
    peak=np.asarray(levels,dtype=np.float32)[order]
    db=(20.*np.log10(np.maximum(peak,1e-9))).astype(np.float32)
    frame_ms=float(np.median(np.diff(times))) if len(times)>1 else 100.
    return FrameFeatures(times,db.copy(),db,np.zeros(len(db),dtype=np.float32),
                         max(.01,frame_ms),4000,'waveform_peak_proxy')


def _normalise_words(clip, words: Sequence[Mapping]) -> list[dict]:
    source = str(Path(clip.source).resolve())
    result = []
    for index, word in enumerate(words):
        try:
            if str(Path(word.get('source', source)).resolve()) != source:
                continue
            start, end = float(word['source_start']), float(word['source_end'])
            text = str(word.get('text', '')).strip()
        except (KeyError, TypeError, ValueError, OSError):
            continue
        if not text or not np.isfinite(start + end) or end <= start:
            continue
        if start < clip.start - .005 or end > clip.end + .005:
            continue
        result.append({'id': str(word.get('id') or f'{clip.id}_word_{index}'),
            'start_ms': round(start * 1000.), 'end_ms': round(end * 1000.),
            'text': text, 'speaker_id': word.get('speaker_id')})
    result.sort(key=lambda item: (item['start_ms'], item['end_ms']))
    return result


def _role(text: str) -> str:
    return discourse_role(text)


def _utterances(words: Sequence[Mapping]) -> list[dict]:
    groups=[]; current=[]
    for word in words:
        if current:
            prev=current[-1]
            gap=(float(word['start_ms'])-float(prev['end_ms']))/1000.
            finished=bool(_TERMINAL.search(str(prev['text']).strip()))
            question_pause=False
            if gap>=.7 and len(current)>=3:
                current_text=' '.join(str(item['text']) for item in current)
                last_token=re.sub(r'^\W+|\W+$','',str(prev['text']).casefold())
                question_pause=(_role(current_text)=='question' and
                    last_token not in _INCOMPLETE_ENDINGS)
            speaker_change=(prev.get('speaker_id') is not None and
                            word.get('speaker_id') is not None and
                            prev.get('speaker_id')!=word.get('speaker_id'))
            if gap >= .9 or finished or speaker_change or question_pause:
                groups.append(current);current=[]
        current.append(word)
    if current:groups.append(current)
    result=[]
    for group in groups:
        text=' '.join(str(w['text']) for w in group).strip()
        result.append({'start_ms':int(group[0]['start_ms']),'end_ms':int(group[-1]['end_ms']),
            'text':text,'words':list(group),'role':_role(text),
            'speaker_id':group[0].get('speaker_id')})
    return result


def _text_scores(text: str, words: Sequence[Mapping], utterance_start: bool,
                 terminal: bool, gap_before: float, gap_after: float) -> tuple[float,float,float,list[str]]:
    normalized=text.lower()
    tokens=[re.sub(r'^\W+|\W+$','',str(w['text']).lower()) for w in words]
    tokens=[token for token in tokens if token]
    first=tokens[0] if tokens else ''
    last=tokens[-1] if tokens else ''
    dependent=first in _DEPENDENT_OPENERS and not utterance_start
    incomplete=last in _INCOMPLETE_ENDINGS and not terminal
    context=.54 + (.16 if terminal else 0.) + (.08 if gap_before>=.35 else 0.)
    if len(tokens)>=18:context+=.08
    if dependent:context-=.24
    if incomplete:context-=.22
    context=float(np.clip(context,.05,.96))
    hook=.34
    matches=[pattern.pattern for pattern in _HOOK_PATTERNS if pattern.search(normalized)]
    hook+=min(.36,.14*len(matches))
    if '?' in text:hook+=.12
    if any(any(ch.isdigit() for ch in token) for token in tokens):hook+=.08
    if _role(text) in ('reveal','conclusion'):hook+=.08
    hook=float(np.clip(hook,.05,.96))
    boundary=.5 + (.18 if utterance_start else 0.) + (.15 if terminal else 0.)
    boundary+=.08 if gap_before>=.35 else 0.
    boundary+=.08 if gap_after>=.35 else 0.
    if dependent:boundary-=.2
    if incomplete:boundary-=.2
    boundary=float(np.clip(boundary,.05,.98))
    reasons=[]
    if terminal:reasons.append('Fecha em limite de frase')
    if gap_before>=.35:reasons.append('Começa após pausa natural')
    if gap_after>=.35:reasons.append('Termina antes de pausa natural')
    if matches:reasons.append('Gancho textual detectado: '+matches[0].replace(r'\b','').replace('\\',''))
    if _role(text)!='unspecified':reasons.append('Bloco classificado como '+_role(text))
    if dependent:reasons.append('Início pode depender do contexto anterior')
    if incomplete:reasons.append('Final pode deixar uma frase incompleta')
    return context,hook,boundary,reasons


def suggest_title(text: object, max_chars: int = 72) -> str:
    """Choose an existing transcript sentence as a deterministic title cue.

    This is extractive, not generative: title text always comes from the ASR
    transcript, and the caller retains the complete transcript separately.
    """
    raw=' '.join(str(text or '').split())
    sentences=[part.strip(' \t\r\n\"“”\'') for part in
               re.split(r'(?<=[.!?])\s+|\s+(?=[—–])',raw) if part.strip()]
    if not sentences:
        return ''
    ranked=[]
    for index,sentence in enumerate(sentences):
        terms=content_terms(sentence)
        role=discourse_role(sentence)
        score=min(1.,len(terms)/9.)*.42
        if any(pattern.search(sentence.casefold()) for pattern in _HOOK_PATTERNS):
            score+=.20
        if role in ('reveal','conclusion','answer'):
            score+=.18
        elif role=='question':
            score+=.12
        if 4<=len(terms)<=12:
            score+=.12
        if len(terms)<3:
            score-=.2
        ranked.append((score,-index,sentence))
    chosen=max(ranked)[2].strip(' .!?—–')
    if len(chosen)>max_chars:
        shortened=chosen[:max_chars-1].rsplit(' ',1)[0].rstrip(' ,:;-')
        chosen=(shortened or chosen[:max_chars-1]).rstrip()+'…'
    return chosen


def _local_textrank_salience(words: Sequence[Mapping], max_neighbors: int = 8,
                             iterations: int = 12) -> float | None:
    """Small sparse TextRank pass over turns inside one candidate only."""
    turns=_utterances(words)
    if len(turns)<2:
        return None
    vectors=[content_terms(turn.get('text','')) for turn in turns]
    count=len(vectors)
    outgoing=[[] for _ in range(count)]
    for left in range(count):
        for right in range(max(0,left-max_neighbors),min(count,left+max_neighbors+1)):
            if left==right:
                continue
            a,b=vectors[left],vectors[right]
            denominator=sum(max(a.get(term,0),b.get(term,0)) for term in a.keys()|b.keys())
            if denominator:
                overlap=sum(min(a.get(term,0),b.get(term,0)) for term in a.keys()&b.keys())
                weight=overlap/denominator
                if weight>0:
                    outgoing[left].append((right,weight))
    scores=np.full(count,1./count,dtype=np.float64)
    damping=.85
    for _ in range(max(1,iterations)):
        updated=np.full(count,(1.-damping)/count,dtype=np.float64)
        for source,neighbors in enumerate(outgoing):
            total=sum(weight for _target,weight in neighbors)
            if total:
                for target,weight in neighbors:
                    updated[target]+=damping*scores[source]*weight/total
            else:
                updated+=damping*scores[source]/count
        if np.max(np.abs(updated-scores))<1e-6:
            scores=updated
            break
        scores=updated
    # Relative to a uniform rank: 1.0 means clearly central, 0.5 means flat.
    return float(np.clip(float(np.max(scores))/(2./count),0.,1.))


def _editorial_dimensions(text: str, words: Sequence[Mapping],
                          start_ms: int, end_ms: int,
                          advanced: bool=False) -> tuple[float,float,float,float|None]:
    """Estimate lexical value, narrative payoff and spoken-time density.

    These are deterministic ranking cues, not calibrated relevance probabilities.
    The speech-density calculation unions word intervals to avoid double counting.
    """
    tokens = re.findall(r"[\wÀ-ÿ]+", text.casefold(), flags=re.UNICODE)
    terms = content_terms(text)
    content_count = sum(terms.values())
    lexical_density = content_count / max(1, len(tokens))
    unique_ratio = len(terms) / max(1, content_count)
    information = float(np.clip(.4*min(1., lexical_density/.45) +
                                .6*min(1., unique_ratio/.72), 0., 1.))
    text_rank=_local_textrank_salience(words) if advanced else None
    if text_rank is not None:
        information=float(np.clip(.75*information+.25*text_rank,0.,1.))

    role = discourse_role(text)
    ending = str(words[-1].get('text','')).strip() if words else ''
    normalized = text.casefold()
    has_resolution = bool(re.search(
        r"\b(?:no final|por isso|o resultado|conclus[aã]o|resumindo|"
        r"foi assim|deu certo|a resposta|aprendi)\b", normalized))
    payoff = .88 if role in ('answer','reveal','conclusion') else .68 if has_resolution else .52
    if _TERMINAL.search(ending):
        payoff = min(1., payoff+.08)

    intervals = sorted((max(start_ms,int(float(w['start_ms']))),
                        min(end_ms,int(float(w['end_ms'])))) for w in words)
    active = 0
    current_start = current_end = None
    for left,right in intervals:
        if right <= left:
            continue
        if current_start is None:
            current_start,current_end=left,right
        elif left <= current_end:
            current_end=max(current_end,right)
        else:
            active += current_end-current_start
            current_start,current_end=left,right
    if current_start is not None:
        active += current_end-current_start
    span=max(1,end_ms-start_ms)
    density=active/span
    rhythm=float(np.clip(density/.78,0.,1.))
    return information,float(payoff),rhythm,text_rank


def _dialogue_context_index(words: Sequence[Mapping]):
    """Build reusable word-to-turn indexes once for the candidate scan."""
    turns = _utterances(words)
    by_first = {id(turn['words'][0]): index for index, turn in enumerate(turns)}
    by_last = {id(turn['words'][-1]): index for index, turn in enumerate(turns)}
    word_positions = {id(word): index for index, word in enumerate(words)}
    return turns, by_first, by_last, word_positions


def _answers_question(question: Mapping, answer: Mapping,
                      speaker_changed: bool = False) -> bool:
    """Conservatively link an adjacent answer to a question.

    Parakeet may have no speaker labels and some transcripts omit answer
    connectives. In that case, a small content-word overlap can support the
    link. This is a local editorial cue, never a semantic-equivalence claim.
    """
    if question.get('role') != 'question':
        return False
    answer_text = str(answer.get('text', '')).strip()
    if (answer.get('role') == 'answer' or
            _ANSWER_CUES.match(answer_text)):
        return True
    if speaker_changed:
        return True
    question_terms = content_terms(question.get('text', ''))
    answer_terms = content_terms(answer_text)
    if not question_terms or not answer_terms:
        return False
    shared = question_terms.keys() & answer_terms.keys()
    # Compare the smaller content vocabulary so a concise question can link to
    # a more detailed answer. Require a majority of that vocabulary to overlap
    # so one incidental shared noun does not join unrelated turns.
    smaller = min(sum(question_terms.values()), sum(answer_terms.values()))
    overlap = sum(min(question_terms[token], answer_terms[token])
                  for token in shared)
    return overlap > 0 and overlap / max(1, smaller) >= .55


def _dialogue_context_bounds(words: Sequence[Mapping], start_index: int,
                             end_index: int, max_duration_ms: float,
                             turn_index=None) -> tuple[int, int, bool, bool]:
    """Keep a nearby question and its answer in the same candidate when safe.

    This is a local deterministic boundary adjustment. It uses only existing
    transcript word timestamps and speaker labels; it does not infer missing
    words or extend beyond the configured candidate duration.
    """
    if not words or not (0 <= start_index <= end_index < len(words)):
        return start_index, end_index, False, False
    turns, by_first, by_last, word_positions = (
        turn_index if turn_index is not None else _dialogue_context_index(words))
    if len(turns) < 2:
        return start_index, end_index, False, False
    start_turn = by_first.get(id(words[start_index]))
    end_turn = by_last.get(id(words[end_index]))
    if start_turn is None or end_turn is None:
        return start_index, end_index, False, False

    linked_start = linked_end = False
    start_ms = float(words[start_index]['start_ms'])
    end_ms = float(words[end_index]['end_ms'])
    if start_turn > 0:
        previous = turns[start_turn - 1]
        current = turns[start_turn]
        previous_end = float(previous['end_ms'])
        current_start = float(current['start_ms'])
        previous_words = previous['words']
        current_words = current['words']
        changed_speaker = (previous.get('speaker_id') is not None and
            current.get('speaker_id') is not None and
            previous.get('speaker_id') != current.get('speaker_id'))
        current_first = re.sub(r'^\W+|\W+$', '',
                               str(current_words[0]['text']).lower())
        dependent_start = current_first in _DEPENDENT_OPENERS
        joins_question = (_answers_question(previous, current, changed_speaker) or
                          (previous.get('role') == 'question' and dependent_start))
        combined = end_ms - float(previous_words[0]['start_ms'])
        if joins_question and current_start - previous_end <= 1800 and \
                combined <= max_duration_ms:
            start_index = word_positions[id(previous_words[0])]
            start_ms = float(words[start_index]['start_ms'])
            linked_start = True

    if end_turn + 1 < len(turns):
        current = turns[end_turn]
        following = turns[end_turn + 1]
        current_end = float(current['end_ms'])
        following_start = float(following['start_ms'])
        changed_speaker = (current.get('speaker_id') is not None and
            following.get('speaker_id') is not None and
            current.get('speaker_id') != following.get('speaker_id'))
        linked_answer = _answers_question(current, following, changed_speaker)
        if current.get('role') == 'question' and \
                linked_answer and \
                following_start - current_end <= 1800:
            following_words = following['words']
            proposed_end = float(following_words[-1]['end_ms'])
            if proposed_end - start_ms <= max_duration_ms:
                end_index = word_positions[id(following_words[-1])]
                end_ms = proposed_end
                linked_end = True
    return start_index, end_index, linked_start, linked_end


def _candidate_spans(words: Sequence[Mapping], options: ClipperOptions) -> list[dict]:
    if not words:return []
    minimum=options.min_seconds*1000.;maximum=options.max_seconds*1000.
    target=(minimum+maximum)/2.
    stride=max(minimum*.65,min(target*.48,15000.))
    starts=[0]
    next_allowed=0
    for i in range(1,len(words)):
        prev=words[i-1];word=words[i]
        gap=float(word['start_ms'])-float(prev['end_ms'])
        sentence=bool(_TERMINAL.search(str(prev['text']).strip()))
        speaker_change=(prev.get('speaker_id') is not None and
                        word.get('speaker_id') is not None and
                        prev.get('speaker_id')!=word.get('speaker_id'))
        elapsed=float(word['start_ms'])-float(words[next_allowed]['start_ms'])
        if (gap>=.35 or sentence or speaker_change) and elapsed>=stride:
            starts.append(i);next_allowed=i
        elif elapsed>=stride:
            starts.append(i);next_allowed=i
    ends=[float(word['end_ms']) for word in words]
    turns,by_first,by_last,_word_positions=_dialogue_context_index(words)
    word_to_turn={id(word):turn_index for turn_index,turn in enumerate(turns)
                  for word in turn['words']}
    topic_shift_scores=text_tiling_boundaries(turns)
    topic_shift_keys=sorted(topic_shift_scores)
    candidates=[];seen=set()
    for start_index in starts:
        start=float(words[start_index]['start_ms'])
        target_index=bisect_left(ends,start+target,start_index)
        max_index=bisect_left(ends,start+maximum,start_index)
        if target_index>=len(words):
            continue
        end_index=min(target_index,len(words)-1)
        if ends[end_index]-start>maximum and end_index>start_index:
            end_index-=1
        if ends[end_index]-start<minimum:
            # Search the largest whole-word end that still stays inside max.
            end_index=max_index-1
        if end_index<start_index or end_index>=len(words):
            continue
        start_index,end_index,dialogue_start,dialogue_end=_dialogue_context_bounds(
            words,start_index,end_index,maximum,
            turn_index=(turns,by_first,by_last,_word_positions))
        start=float(words[start_index]['start_ms'])
        duration=ends[end_index]-start
        if duration<minimum or duration>maximum:
            continue
        # Prefer a natural terminal boundary near target, but never extend past max.
        terminal_indices=[] if dialogue_end else [i for i in range(start_index,end_index+1)
                          if _TERMINAL.search(str(words[i]['text']).strip())]
        if terminal_indices:
            best=min(terminal_indices,key=lambda i:abs(ends[i]-(start+target)))
            if ends[best]-start>=minimum*.75:
                end_index=best
        subset=list(words[start_index:end_index+1])
        end=float(subset[-1]['end_ms'])
        key=(int(start),int(end))
        if key in seen:continue
        seen.add(key)
        text=' '.join(str(word['text']) for word in subset).strip()
        utterance_start=(start_index==0 or
            float(words[start_index]['start_ms'])-float(words[start_index-1]['end_ms'])>=.35 or
            bool(_TERMINAL.search(str(words[start_index-1]['text']).strip())))
        terminal=bool(_TERMINAL.search(str(subset[-1]['text']).strip()))
        gap_before=(float(words[start_index]['start_ms'])-
                    float(words[start_index-1]['end_ms']))/1000. if start_index else 1.
        gap_after=(float(words[end_index+1]['start_ms'])-end)/1000. if end_index+1<len(words) else 1.
        context,hook,boundary,reasons=_text_scores(text,subset,utterance_start,
            terminal,gap_before,gap_after)
        # Candidate windows may start/end inside an utterance; map every word
        # to its turn instead of treating non-boundary words as missing context.
        start_turn=word_to_turn.get(id(words[start_index]))
        end_turn=word_to_turn.get(id(words[end_index]))
        entry_shift=(topic_shift_scores.get(start_turn,0.) if start_turn is not None else 0.)
        exit_shift=(topic_shift_scores.get(end_turn+1,0.) if end_turn is not None else 0.)
        if entry_shift>=.52:
            context=min(.96,context+.06)
            boundary=min(.98,boundary+.04)
            reasons.append(f'Início próximo a uma possível mudança de assunto ({entry_shift:.0%})')
        if exit_shift>=.52:
            boundary=min(.98,boundary+.04)
            reasons.append(f'Fim próximo a uma possível mudança de assunto ({exit_shift:.0%})')
        if start_turn is not None and end_turn is not None:
            first_internal=bisect_left(topic_shift_keys,start_turn+1)
            after_internal=bisect_left(topic_shift_keys,end_turn+1)
            internal_scores=[topic_shift_scores[index]
                for index in topic_shift_keys[first_internal:after_internal]]
        else:
            internal_scores=[]
        internal_shifts=sum(score>=.50 for score in internal_scores)
        if internal_shifts:
            context=max(.05,context-min(.10,.04*internal_shifts))
            if internal_shifts>=2:
                reasons.append('Janela atravessa várias mudanças de tópico; revisar coerência')

        previous_text=''
        following_text=''
        previous_speaker=None
        following_speaker=None
        candidate_speakers={word.get('speaker_id') for word in subset
                            if word.get('speaker_id') is not None}
        speaker_id=next(iter(candidate_speakers)) if len(candidate_speakers)==1 else None
        if start_turn is not None and start_turn>0:
            previous_turn=turns[start_turn-1]
            if start/1000.-float(previous_turn['end_ms'])/1000.<=4.0:
                previous_text=previous_turn['text']
                previous_speaker=previous_turn.get('speaker_id')
        if end_turn is not None and end_turn+1<len(turns):
            following_turn=turns[end_turn+1]
            if float(following_turn['start_ms'])/1000.-end/1000.<=4.0:
                following_text=following_turn['text']
                following_speaker=following_turn.get('speaker_id')
        discourse=analyze_discourse(text,previous=previous_text,following=following_text,
            speaker_id=speaker_id,previous_speaker=previous_speaker,
            following_speaker=following_speaker)
        irony=discourse['irony']
        if irony['suspected']:
            reasons.append('Possíveis sinais de ironia/contraste: '
                           + '; '.join(irony['evidence'][:3]))
        existing_cues=set(irony['evidence'])
        reasons.extend(cue for cue in discourse['cues'] if cue not in existing_cues)
        if discourse['speaker_context_excluded']:
            reasons.append('Contexto de locutor diferente conhecido foi excluído da comparação')
        figurative_score=(float(irony['score']) if irony['suspected'] else 0.)
        if dialogue_start or dialogue_end:
            reasons.append('Pergunta e resposta próximas mantidas no mesmo clipe')
        information_score,payoff_score,rhythm_score,text_rank_score=_editorial_dimensions(
            text,subset,int(start),int(end),advanced=options.mode=='Avançado')
        candidates.append({'start_ms':int(start),'end_ms':int(end),'text':text,
            'words':subset,'context_score':context,'hook_score':hook,
            'boundary_score':boundary,'figurative_score':figurative_score,
            'information_score':information_score,'payoff_score':payoff_score,
            'rhythm_score':rhythm_score,'text_rank_score':text_rank_score,
            'discourse_score':float(discourse['editorial_score']),
            'discourse_cues':list(discourse['cues']),
            'irony_suspected':bool(irony['suspected']),
            'irony_score':float(irony['score']),
            'irony_evidence':list(irony['evidence']),
            'topic_shift_before':entry_shift,'topic_shift_after':exit_shift,
            'topic_shift_internal':max(internal_scores,default=0.),
            'text_reasons':reasons})
    return candidates


def _boundary_choices(all_words: Sequence[Mapping], candidate: Mapping,
                      options: ClipperOptions) -> tuple[list[dict],list[dict]]:
    """Offer nearby ASR word edges while preserving configured duration."""
    start=int(candidate['start_ms']);end=int(candidate['end_ms'])
    minimum=options.min_seconds*1000.;maximum=options.max_seconds*1000.
    start_choices=[];end_choices=[]
    key=lambda word:int(word['start_ms'])
    left=bisect_left(all_words,start-3000,key=key)
    right=bisect_right(all_words,start+3000,key=key)
    for word in all_words[left:right]:
        word_start=int(word['start_ms']);word_end=int(word['end_ms'])
        if minimum<=end-word_start<=maximum:
            start_choices.append({'ms':word_start,'word':str(word['text'])})
    left=bisect_left(all_words,end-3000,key=key)
    right=bisect_right(all_words,end+3000,key=key)
    for word in all_words[left:right]:
        word_end=int(word['end_ms'])
        if abs(word_end-end)<=3000 and minimum<=word_end-start<=maximum:
            end_choices.append({'ms':word_end,'word':str(word['text'])})
    for choices,value,label in ((start_choices,start,'Início atual'),
                                (end_choices,end,'Fim atual')):
        if not any(item['ms']==value for item in choices):
            choices.append({'ms':value,'word':label})
        choices.sort(key=lambda item:item['ms'])
    return start_choices,end_choices


def _event_only_spans(clip, audio_events: Sequence[Mapping],
                      visual_events: Sequence[Mapping],
                      options: ClipperOptions) -> list[dict]:
    """Build cautious candidates around measured events when no transcript exists.

    The result is explicitly non-semantic: an energy burst or a cached-frame
    change is only a review cue, never a claim that an action/reaction occurred.
    """
    minimum = options.min_seconds * 1000.
    maximum = options.max_seconds * 1000.
    available = max(0., (float(clip.end) - float(clip.start)) * 1000.)
    if available < minimum:
        return []
    duration = min(maximum, available, max(minimum, (minimum + maximum) / 2.))
    left_limit, right_limit = float(clip.start) * 1000., float(clip.end) * 1000.
    anchors=[]
    for event in audio_events:
        strength=float(event.get('strength',0.))
        if strength >= .05:
            anchors.append((float(event['start_ms']),dict(event)))
    for event in visual_events:
        strength=float(event.get('strength',0.))
        if strength >= .05:
            anchors.append((float(event['start_ms']),dict(event)))
    if not anchors:
        return []

    anchors.sort(key=lambda item:item[0])
    groups=[]
    for at,event in anchors:
        if groups and at-groups[-1][-1][0] <= min(duration*.45,12000.):
            groups[-1].append((at,event))
        else:
            groups.append([(at,event)])
    candidates=[]
    for group in groups:
        strength_sum=sum(max(.01,float(event.get('strength',0.)))
                         for _at,event in group)
        center=sum(at*max(.01,float(event.get('strength',0.)))
                   for at,event in group)/strength_sum
        start=max(left_limit,min(center-duration/2.,right_limit-duration))
        end=start+duration
        if not left_limit <= start < end <= right_limit:
            continue
        group_events=[event for _at,event in group]
        kinds={event.get('kind') for event in group_events}
        cues=[]
        if any('energy' in str(kind) or 'waveform' in str(kind) for kind in kinds):
            cues.append('mudança de energia relativa')
        if 'cached_thumbnail_change' in kinds:
            cues.append('mudança visual em miniatura já armazenada')
        if not cues:
            continue
        reasons=['Sem transcrição persistida; candidato baseado somente em sinais observados: '
                 + ', '.join(cues),
                 'Mudanças acústicas/visuais não identificam ação nem relevância semântica']
        candidates.append({'start_ms':int(round(start)),'end_ms':int(round(end)),
            'duration_ms':int(round(duration)),'text':'','words':[],
            'event_only':True,'event_cues':cues,'events':group_events,
            'text_reasons':reasons,'visual_score':None})
    return candidates


def _transcript_gaps(clip, words: Sequence[Mapping],
                     guard_ms: float = 350.) -> list[tuple[float, float]]:
    """Return source-time gaps not covered by word timestamps.

    A guard around each word avoids treating uncertain word boundaries as
    evidence of a truly speech-free moment. A gap means only that the saved
    transcript has no timed words there; it does not prove silence.
    """
    left = float(clip.start) * 1000.
    right = float(clip.end) * 1000.
    if not np.isfinite(left + right) or right <= left:
        return []
    spans = []
    for word in words:
        try:
            start = max(left, float(word['start_ms']) - guard_ms)
            end = min(right, float(word['end_ms']) + guard_ms)
        except (KeyError, TypeError, ValueError):
            continue
        if np.isfinite(start + end) and end > start:
            spans.append((start, end))
    spans.sort()
    gaps = []
    cursor = left
    for start, end in spans:
        if start > cursor:
            gaps.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < right:
        gaps.append((cursor, right))
    return gaps


def _events_in_transcript_gaps(events: Sequence[Mapping],
                               gaps: Sequence[tuple[float, float]]) -> list[dict]:
    """Keep observed event cues whose centers fall outside timed speech."""
    gap_starts = [left for left, _right in gaps]
    result = []
    for event in events:
        try:
            start, end = float(event['start_ms']), float(event['end_ms'])
            strength = float(event.get('strength', 0.))
        except (KeyError, TypeError, ValueError):
            continue
        center = (start + end) / 2.
        if not (np.isfinite(start + end + strength) and end > start and strength >= .05):
            continue
        gap_index = bisect_right(gap_starts, center) - 1
        if gap_index < 0 or center > gaps[gap_index][1]:
            continue
        item = dict(event)
        item['speech_verified'] = False
        item['meaning'] = ('relative audio event outside Parakeet word timestamps; '
                           'not a speech or semantic classification')
        result.append(item)
    return result


def _event_only_spans_in_gaps(clip, events: Sequence[Mapping],
                              gaps: Sequence[tuple[float, float]],
                              options: ClipperOptions) -> list[dict]:
    """Build review-only candidates for measured events in long transcript gaps."""
    minimum = float(options.min_seconds) * 1000.
    maximum = float(options.max_seconds) * 1000.
    preferred = min(maximum, max(minimum, (minimum + maximum) / 2.))
    candidates = []
    anchors = []
    for event in events:
        try:
            center = (float(event['start_ms']) + float(event['end_ms'])) / 2.
            strength = float(event.get('strength', 0.))
        except (KeyError, TypeError, ValueError):
            continue
        if np.isfinite(center + strength) and strength >= .05:
            anchors.append((center, dict(event)))
    anchors.sort(key=lambda item: item[0])
    anchor_times = [at for at, _event in anchors]
    for gap_start, gap_end in gaps:
        gap_duration = gap_end - gap_start
        duration = min(preferred, maximum, gap_duration)
        if duration < minimum:
            continue
        left = bisect_left(anchor_times, gap_start)
        right = bisect_right(anchor_times, gap_end)
        gap_anchors = anchors[left:right]
        groups = []
        for anchor in gap_anchors:
            if groups and anchor[0] - groups[-1][-1][0] <= min(duration * .45, 12000.):
                groups[-1].append(anchor)
            else:
                groups.append([anchor])
        for group in groups:
            weights = [max(.01, float(event.get('strength', 0.)))
                       for _at, event in group]
            center = sum(at * weight for (at, _event), weight
                         in zip(group, weights)) / sum(weights)
            start = max(gap_start, min(center - duration / 2., gap_end - duration))
            end = start + duration
            if not gap_start <= start < end <= gap_end:
                continue
            group_events = [event for _at, event in group]
            kinds = {event.get('kind') for event in group_events}
            cues = []
            if any('energy' in str(kind) or 'waveform' in str(kind) for kind in kinds):
                cues.append('mudança de energia relativa')
            if 'cached_thumbnail_change' in kinds:
                cues.append('mudança visual em miniatura já armazenada')
            if not cues:
                continue
            candidates.append({
                'start_ms': int(round(start)), 'end_ms': int(round(end)),
                'duration_ms': int(round(duration)), 'text': '', 'words': [],
                'event_only': True, 'transcript_present': True,
                'event_cues': cues, 'events': group_events,
                'allowed_start_ms': int(round(gap_start)),
                'allowed_end_ms': int(round(gap_end)),
                'text_reasons': [
                    'Sem palavras do Parakeet nesta janela; candidato baseado em sinais medidos.',
                    'Ausência de timestamps não comprova silêncio, ação ou relevância; confirme no áudio/vídeo.',
                ],
                'visual_score': None,
            })
    return candidates


def _score_event_only(candidate: Mapping, profile: str,
                      weights_override: Mapping[str,float] | None = None) -> dict:
    """Rank only measured event dimensions; semantic dimensions stay absent."""
    from .clip_audio_signals import CLIP_SCORE_PROFILES
    weights=dict(CLIP_SCORE_PROFILES.get(profile,CLIP_SCORE_PROFILES['Geral']))
    if weights_override is not None:
        weights.update({str(key):float(value) for key,value in weights_override.items()})
        total=sum(weights.values())
        if total>0:weights={key:value/total for key,value in weights.items()}
    audio_events=[event for event in candidate.get('events',[])
                  if 'energy' in str(event.get('kind','')) or
                     'waveform' in str(event.get('kind',''))]
    visual_events=[event for event in candidate.get('events',[])
                   if event.get('kind')=='cached_thumbnail_change']
    dimensions={
        'audio':max((float(event.get('strength',0.)) for event in audio_events),default=None),
        'visual':max((float(event.get('strength',0.)) for event in visual_events),default=None),
    }
    total_weight=sum(weights.get(key,0.) for key,value in dimensions.items()
                     if value is not None and weights.get(key,0.)>0.)
    if (total_weight<=0 and weights_override is None and
            any(value is not None for value in dimensions.values())):
        # Event-only review is an explicitly opt-in fallback path. If the
        # selected editorial profile excludes the only observed dimension,
        # retain a low-coverage cue rather than silently hiding it.
        weights.update({'audio':.65,'visual':.35})
        total_weight=sum(weights[key] for key,value in dimensions.items()
                         if value is not None and weights.get(key,0.)>0.)
    if total_weight<=0:
        return {'score':None,'components':{'audio':None,'visual':None},
                'evidence_coverage':0.,'reasons':[],'warnings':[],
                'profile':profile,'audio_score':None,'audio_available':False,
                'note':'Sem dimensões de evento disponíveis.'}
    raw=sum(weights[key]*float(value) for key,value in dimensions.items()
            if value is not None and weights.get(key,0.)>0.)/total_weight
    coverage=sum(weights.get(key,0.) for key,value in dimensions.items()
                 if value is not None and weights.get(key,0.)>0.)
    reasons=['Ranking parcial de eventos; não mede contexto, gancho ou conclusão']
    if dimensions['audio'] is not None:
        reasons.append('Sinal de energia relativo à própria gravação')
    if dimensions['visual'] is not None:
        reasons.append('Mudança visual relativa em miniaturas; sem reconhecimento de conteúdo')
    raw=float(np.clip(raw,0.,1.))
    # Shrink a high single-signal score toward neutral according to the
    # profile's evidence coverage. This makes a lone visual cut visibly
    # lower-confidence than a multimodal candidate with transcript context.
    coverage_adjusted=.5+(raw-.5)*float(np.clip(coverage,0.,1.))
    return {'score':round(100.*float(np.clip(coverage_adjusted,0.,1.)),1),
        'components':{key:(round(float(value),3) if value is not None else None)
                      for key,value in dimensions.items()},
        'evidence_coverage':round(float(coverage),3),'reasons':reasons,'warnings':[],
        'profile':profile,
        'audio_score':(round(float(dimensions['audio']),3)
                       if dimensions['audio'] is not None else None),
        'audio_available':dimensions['audio'] is not None,
        'note':'Ranking parcial de eventos observáveis; não avalia conteúdo semântico.'}


def _event_boundary_choices(clip, candidate: Mapping,
                            options: ClipperOptions) -> tuple[list[dict],list[dict]]:
    """Offer small second-based trims when no transcript word edges exist."""
    minimum=options.min_seconds*1000.;maximum=options.max_seconds*1000.
    low=max(float(clip.start)*1000.,float(candidate.get(
        'allowed_start_ms',float(clip.start)*1000.)))
    high=min(float(clip.end)*1000.,float(candidate.get(
        'allowed_end_ms',float(clip.end)*1000.)))
    start=int(candidate['start_ms']);end=int(candidate['end_ms'])
    offsets=(-2000,-1000,0,1000,2000)
    starts=[{'ms':at,'word':'evento ± tempo'} for delta in offsets
            if low <= (at:=start+delta) < end and minimum<=end-at<=maximum]
    ends=[{'ms':at,'word':'evento ± tempo'} for delta in offsets
          if start < (at:=end+delta) <= high and minimum<=at-start<=maximum]
    return starts,ends


def _cache_path(cache_dir: Path, key: str) -> Path:
    return cache_dir / 'results' / key[:2] / f'{key}.json'


def analyze_clips(clips, transcript_words: Sequence[Mapping], options: ClipperOptions | None = None,
                  *, control=None, progress=None, stage=None,
                  cache_dir: Path | None = None, waveform_provider=None,
                  visual_provider=None) -> dict:
    """Rank candidate windows from saved words and optional measured audio.

    This function never calls a language model, renders video, or changes a project.
    """
    opts=options or ClipperOptions()
    opts.__post_init__()
    root=Path(cache_dir or clipper_cache_dir())
    started=time.monotonic()
    results=[];hits=misses=0;decoded_seconds=0.;frames_seen=0
    visual_frames_reused=visual_cache_hits=0
    path_words={}
    for word in transcript_words:
        try:key=str(Path(word.get('source','')).resolve())
        except (OSError,ValueError):continue
        path_words.setdefault(key,[]).append(word)
    total=max(1,len(clips))
    for position,clip in enumerate(clips):
        if control:control.checkpoint()
        source=str(Path(clip.source).resolve())
        words=_normalise_words(clip,path_words.get(source,[]))
        try:
            identity=source_identity(source)
        except (OSError,ValueError):
            identity={'path':source,'missing':True}
        result_key=digest({'schema':CACHE_SCHEMA,'version':CLIPPER_VERSION,
            'source':identity,'start':round(clip.start,4),
            'end':round(clip.end,4),'words':words,'options':opts.as_dict(),
            'timebase':'absolute-source-ms'})
        result_path=_cache_path(root,result_key)
        try:
            cached=json.loads(result_path.read_text(encoding='utf-8'))
            # The rank key intentionally stays cheap. When visual analysis is
            # enabled, re-read the thumbnail manifest and feature cache before
            # reusing results, so newly generated/replaced thumbnails cannot
            # leave a stale visual score in the result cache.
            if (not opts.analyze_visual and cached.get('schema')==CACHE_SCHEMA
                    and cached.get('key')==result_key):
                cached_result=cached['result']
                cached_result['clip_id']=clip.id;cached_result['title']=clip.title
                for item in cached_result.get('candidates',[]):
                    item['clip_id']=clip.id;item['title']=clip.title
                    for event in item.get('events',[]):
                        event['clip_id']=clip.id;event['title']=clip.title
                for event in cached_result.get('events',[]):
                    event['clip_id']=clip.id;event['title']=clip.title
                results.append(cached_result);hits+=1
                if progress:progress(position+1,total)
                continue
        except (OSError,ValueError,KeyError,TypeError):
            pass
        misses+=1
        if stage:stage(f'Clipador • sinais matemáticos · {position+1}/{total}')
        if clip.kind not in ('audio','video') or not getattr(clip,'include_audio',True):
            frames=None
            audio_warning='Este bloco não inclui áudio; ranking segue somente pelo texto.'
        else:
            try:
                def audio_progress(done,total_value):
                    if progress:
                        fraction=max(0.,min(1.,float(done)/max(1.,float(total_value))))
                        progress(position+.9*fraction,total)
                frames,feature_hit=audio_features(source,clip.start,clip.end,control=control,
                    progress=audio_progress,cache_dir=root,waveform_provider=waveform_provider,
                    waveform_only=opts.mode=='Rápido')
                if feature_hit:hits+=1
                elif frames is not None:decoded_seconds+=clip.end-clip.start
            except Exception as exc:
                from .process_control import ProcessCancelled
                if isinstance(exc,ProcessCancelled):raise
                frames=None
                audio_warning=f'Áudio indisponível para análise: {str(exc)[:160]}'
            else:
                audio_warning=(
                    'Sinal acústico aproximado pela waveform de pico da timeline (100 ms); sem RMS/FFT.'
                    if frames is not None and frames.level_kind!='pcm_rms' else ''
                ) if frames is not None else (
                    ('Modo rápido: não havia waveform da timeline em cache; ranking segue pelas evidências restantes.'
                     if words else 'Modo rápido: sem waveform em cache; não há evidência acústica para pontuar.')
                    if opts.mode=='Rápido' else
                    'A fonte não contém faixa de áudio decodificável.')
        if control:control.checkpoint()
        frames_seen+=len(frames.times_ms) if frames is not None else 0
        # With no saved transcript, energy events are exploratory only. The
        # detector receives None (unknown speech mask), never an empty mask
        # that would falsely mean confirmed silence.
        speech_intervals=([(word['start_ms'],word['end_ms']) for word in words]
                          if words else None)
        events=(detect_energy_events(frames,speech_intervals,
                 relative_rise_db=opts.relative_rise_db) if frames is not None else [])
        gaps = _transcript_gaps(clip, words) if words else []
        gap_audio_events = []
        if words and frames is not None:
            # A second, cheap pass over the already computed frame arrays finds
            # out-of-speech bursts (e.g. gameplay events). It decodes no audio;
            # these cues remain explicitly unverified and never affect the
            # transcript-backed candidate scores.
            exploratory = detect_energy_events(
                frames, None, relative_rise_db=opts.relative_rise_db)
            gap_audio_events = _events_in_transcript_gaps(exploratory, gaps)
        turns=_utterances(words)
        events=align_events_to_conversation(events,turns)
        events=[dict(event,clip_id=clip.id,title=clip.title,source=source) for event in events]
        visual_signals=None
        visual_events=[]
        if opts.analyze_visual and visual_provider is not None:
            if stage:stage(f'Clipador • miniaturas em cache · {position+1}/{total}')
            visual_signals=read_cached_visual_signals(
                source,clip.start,clip.end,visual_provider,cache_dir=root,
                control=control)
            if visual_signals is not None:
                visual_frames_reused+=visual_signals.frame_count
                visual_cache_hits+=int(visual_signals.cache_hit)
                visual_events=detect_cached_visual_events(visual_signals)
                visual_events=[dict(event,clip_id=clip.id,title=clip.title,
                    source=source) for event in visual_events]
        candidates=[]
        word_starts=[int(word['start_ms']) for word in words]
        if words:
            gap_events = gap_audio_events + _events_in_transcript_gaps(visual_events, gaps)
            proposals = _candidate_spans(words,opts)
            proposals.extend(_event_only_spans_in_gaps(clip,gap_events,gaps,opts))
        else:
            gap_events = []
            proposals = _event_only_spans(clip,events,visual_events,opts)
        for candidate in proposals:
            if control:control.checkpoint()
            visual=(score_cached_visual_interval(visual_signals,
                candidate['start_ms'],candidate['end_ms'])
                if opts.analyze_visual else {'score':None,'coverage':0.,
                    'frames':0,'reason':''})
            if visual.get('score') is not None:
                candidate['visual_score']=visual['score']
                candidate['text_reasons'].append(
                    f"{visual['reason']} ({visual['coverage']:.0%} de cobertura)")
            if candidate.get('event_only'):
                candidate['events']=list(candidate.get('events',[]))
                ranked=_score_event_only(candidate,opts.profile,opts.score_weights)
                candidate_events=candidate['events']
            else:
                ranked=score_clip(candidate,events,frames,opts.profile,
                    weights_override=opts.score_weights)
                candidate_events=[event for event in events
                    if event['start_ms']<candidate['end_ms'] and
                       event['end_ms']>candidate['start_ms']]
            if ranked.get('score') is None:
                continue
            warnings=list(ranked['warnings'])
            if candidate.get('event_only'):
                warnings.append(
                    'Sem palavras do Parakeet no intervalo: isso não comprova ausência de fala; '
                    'confirme o áudio e os limites manualmente.' if words else
                    'Sem transcrição salva: revisar o acontecimento e os limites manualmente.')
            if opts.analyze_visual and visual.get('score') is None:
                warnings.append(visual.get('reason') or
                    'Análise visual solicitada, mas nenhum cache visual utilizável foi fornecido.')
            if audio_warning:warnings.append(audio_warning)
            elif frames is not None and frames.level_kind=='pcm_rms':
                left=int(np.searchsorted(frames.times_ms,candidate['start_ms'],side='left'))
                right=int(np.searchsorted(frames.times_ms,candidate['end_ms'],side='left'))
                if right>left and float(np.mean(frames.rms_dbfs[left:right] <= -65.))>.95:
                    warnings.append('Mais de 95% do intervalo ficou abaixo de -65 dBFS.')
            candidate_id=digest({'clip_id':clip.id,'start_ms':candidate['start_ms'],
                                  'end_ms':candidate['end_ms'],
                                  'event_only':bool(candidate.get('event_only'))})[:16]
            start_choices,end_choices=_boundary_choices(words,candidate,opts)
            if candidate.get('event_only'):
                start_choices,end_choices=_event_boundary_choices(clip,candidate,opts)
            span_left=bisect_left(word_starts,candidate['start_ms']-3000)
            span_right=bisect_right(word_starts,candidate['end_ms']+3000)
            local_words=words[span_left:span_right]
            candidates.append({'id':candidate_id,'clip_id':clip.id,'title':clip.title,
                'suggested_title':(suggest_title(candidate['text']) if candidate['text']
                    else ('Mudança acústica e visual' if candidate.get('event_only') and
                          any(event.get('kind')=='cached_thumbnail_change' for event in candidate_events)
                          and any('energy' in str(event.get('kind','')) or 'waveform' in str(event.get('kind',''))
                                  for event in candidate_events)
                          else 'Mudança visual detectada' if candidate.get('event_only') and
                          any(event.get('kind')=='cached_thumbnail_change' for event in candidate_events)
                          else 'Pico acústico para revisão')),
                'source':source,'source_start':candidate['start_ms']/1000.,
                'source_end':candidate['end_ms']/1000.,
                'start_ms':candidate['start_ms'],'end_ms':candidate['end_ms'],
                'duration':(candidate['end_ms']-candidate['start_ms'])/1000.,
                'text':candidate['text'],'transcript_available':not bool(candidate.get('event_only')),
                'transcript_present':bool(words),
                'score':ranked['score'],
                'score_note':ranked.get('note','Ranking parcial de eventos observáveis; não avalia conteúdo semântico.'),
                'reasons':candidate['text_reasons']+ranked['reasons'],
                'score_profile':ranked['profile'],'score_components':ranked['components'],
                'evidence_coverage':ranked['evidence_coverage'],
                'text_rank_score':candidate.get('text_rank_score'),
                'visual_score':(ranked['components'].get('visual')
                    if candidate.get('event_only') else visual.get('score')),
                'visual_coverage':visual.get('coverage',0.),
                'visual_frames':visual.get('frames',0),
                'audio_level_source':frames.level_kind if frames is not None else None,
                'warnings':warnings,'events':candidate_events,
                'irony_suspected':bool(candidate.get('irony_suspected',False)),
                'irony_score':float(candidate.get('irony_score',0.)),
                'irony_evidence':list(candidate.get('irony_evidence',[])),
                'discourse_score':float(candidate.get('discourse_score',0.)),
                'discourse_cues':list(candidate.get('discourse_cues',[])),
                'topic_shift_before':float(candidate.get('topic_shift_before',0.)),
                'topic_shift_after':float(candidate.get('topic_shift_after',0.)),
                'topic_shift_internal':float(candidate.get('topic_shift_internal',0.)),
                'word_spans':[{'start_ms':int(word['start_ms']),
                    'end_ms':int(word['end_ms']),'text':str(word['text'])}
                    for word in local_words
                    if int(word['start_ms'])>=candidate['start_ms']-3000 and
                       int(word['end_ms'])<=candidate['end_ms']+3000],
                'start_choices':start_choices,'end_choices':end_choices,
                'min_duration_ms':int(opts.min_seconds*1000),
                'max_duration_ms':int(opts.max_seconds*1000),
                'audio_score':ranked['audio_score'],'audio_available':ranked['audio_available'],
                'checked':False})
        selected=select_diverse_clips(candidates,opts.max_candidates)
        result={'clip_id':clip.id,'title':clip.title,'source':source,
            'status':'ready' if selected else 'no_candidates','candidates':selected,
            'events':events+gap_audio_events+visual_events,'audio_available':frames is not None,
            'warnings':(([audio_warning] if audio_warning else [])+
                (['Sem transcrição salva: somente sinais acústicos/visuais observáveis podem gerar candidatos.']
                 if not words else []))}
        result_path.parent.mkdir(parents=True,exist_ok=True)
        temporary=result_path.with_name(result_path.name+f'.{os.getpid()}.tmp')
        try:
            temporary.write_text(json.dumps({'schema':CACHE_SCHEMA,'key':result_key,
                'result':result},ensure_ascii=False),encoding='utf-8')
            os.replace(temporary,result_path)
        finally:
            temporary.unlink(missing_ok=True)
        results.append(result)
        if progress:progress(position+1,total)
    candidate_count=sum(len(item['candidates']) for item in results)
    try:
        import psutil
        rss_mb=psutil.Process(os.getpid()).memory_info().rss/(1024*1024)
    except (ImportError,OSError):
        rss_mb=None
    return {'clips':results,'candidates':[c for item in results for c in item['candidates']],
        'events':[event for item in results for event in item['events']],
        'stats':{'cache_hits':hits,'cache_misses':misses,'decoded_seconds':round(decoded_seconds,3),
            'profile':opts.profile,'mode':opts.mode,
            'feature_frames':frames_seen,'candidate_count':candidate_count,
            'visual_frames_reused':visual_frames_reused,
            'visual_cache_hits':visual_cache_hits,
            'transcript_gap_candidates':sum(
                bool(c.get('transcript_present')) and not bool(c.get('transcript_available'))
                for item in results for c in item['candidates']),
            'irony_candidates':sum(bool(c.get('irony_suspected')) for item in results for c in item['candidates']),
            'topic_boundary_candidates':sum(
                float(c.get('topic_shift_before',0.))>=.52 or
                float(c.get('topic_shift_after',0.))>=.52 or
                float(c.get('topic_shift_internal',0.))>=.52
                for item in results for c in item['candidates']),
            'elapsed_seconds':round(time.monotonic()-started,3),'rss_mb':round(rss_mb,2) if rss_mb else None}}
