"""Clipador Inteligente: ranking editorial explicável sem nova inferência.

Reutiliza as palavras já salvas no projeto e calcula eventos acústicos em PCM
streaming. Os tempos são sempre segundos absolutos da mídia de origem.
"""
from __future__ import annotations

from dataclasses import dataclass
from bisect import bisect_left
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
from .ffmpeg import ffmpeg_path, media_info

CLIPPER_VERSION = 1
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


@dataclass(frozen=True)
class ClipperOptions:
    min_seconds: float = 15.0
    max_seconds: float = 60.0
    max_candidates: int = 8
    relative_rise_db: float = 6.0

    def __post_init__(self):
        if not 3 <= float(self.min_seconds) <= 300:
            raise ValueError('Duração mínima do Clipador deve ficar entre 3 e 300 s.')
        if not float(self.min_seconds) < float(self.max_seconds) <= 600:
            raise ValueError('A duração máxima precisa ser maior que a mínima e até 600 s.')
        if not 1 <= int(self.max_candidates) <= 50:
            raise ValueError('Escolha entre 1 e 50 candidatos.')
        if not 1 <= float(self.relative_rise_db) <= 24:
            raise ValueError('Sensibilidade de energia precisa ficar entre 1 e 24 dB.')

    def as_dict(self):
        return {'min_seconds': float(self.min_seconds),
                'max_seconds': float(self.max_seconds),
                'max_candidates': int(self.max_candidates),
                'relative_rise_db': float(self.relative_rise_db)}


def clipper_cache_dir() -> Path:
    """Keep derived audio features separate from AI weights and user projects."""
    override = os.environ.get('BEROFEL_CLIPPER_CACHE')
    if override:
        return Path(override).expanduser().resolve()
    local = os.environ.get('LOCALAPPDATA')
    return (Path(local) / 'BFS' / 'cache' / 'clipper' if local else
            Path.home() / '.cache' / 'BerofelStudio' / 'clipper')


def _features_key(source: str, start: float, end: float) -> str:
    return digest({'version': CLIPPER_VERSION, 'source': source_identity(source),
        'start': round(float(start), 4), 'end': round(float(end), 4),
        'stream': 0, 'sample_rate': FEATURE_RATE, 'frame_ms': FEATURE_FRAME_MS})


def _load_features(path: Path, offset_ms: float) -> FrameFeatures | None:
    try:
        with np.load(path, allow_pickle=False) as data:
            rate = int(data['sample_rate'][0])
            frame_ms = float(data['frame_ms'][0])
            rms = data['rms_dbfs'].astype(np.float32, copy=True)
            peak = data['peak_dbfs'].astype(np.float32, copy=True)
            clipped = data['clip_fraction'].astype(np.float32, copy=True)
        times = offset_ms + np.arange(len(rms), dtype=np.float64) * frame_ms
        return FrameFeatures(times, rms, peak, clipped, frame_ms, rate)
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
                clip_fraction=frames.clip_fraction)
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
                   progress=None, cache_dir: Path | None = None
                   ) -> tuple[FrameFeatures | None, bool]:
    """Return real RMS/peak frames and whether they were reused from cache."""
    if end <= start:
        raise ValueError('Intervalo de áudio inválido para o Clipador.')
    try:
        identity = source_identity(source)
    except (OSError, ValueError):
        return None, False
    key = _features_key(source, start, end)
    path = (cache_dir or clipper_cache_dir()) / 'features' / key[:2] / f'{key}.npz'
    cached = _load_features(path, start * 1000.)
    if cached is not None:
        return cached, True
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
    value = text.strip().lower()
    if '?' in value or re.match(r'^(o que|quem|quando|onde|como|por que|qual|quanto)\b', value):
        return 'question'
    if re.search(r'\b(na verdade|descobri|o segredo|o resultado|a conclusão|aconteceu)\b', value):
        return 'reveal'
    if re.search(r'\b(porque|por isso|a resposta|isso significa|quer dizer)\b', value):
        return 'answer'
    if re.search(r'\b(em resumo|para concluir|por fim|no final)\b', value):
        return 'conclusion'
    return 'unspecified'


def _utterances(words: Sequence[Mapping]) -> list[dict]:
    groups=[]; current=[]
    for word in words:
        if current:
            prev=current[-1]
            gap=(float(word['start_ms'])-float(prev['end_ms']))/1000.
            finished=bool(_TERMINAL.search(str(prev['text']).strip()))
            speaker_change=(prev.get('speaker_id') is not None and
                            word.get('speaker_id') is not None and
                            prev.get('speaker_id')!=word.get('speaker_id'))
            if gap >= .9 or finished or speaker_change:
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
        duration=ends[end_index]-start
        if duration<minimum or duration>maximum:
            continue
        # Prefer a natural terminal boundary near target, but never extend past max.
        terminal_indices=[i for i in range(start_index,end_index+1)
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
        candidates.append({'start_ms':int(start),'end_ms':int(end),'text':text,
            'words':subset,'context_score':context,'hook_score':hook,
            'boundary_score':boundary,'text_reasons':reasons})
    return candidates


def _boundary_choices(all_words: Sequence[Mapping], candidate: Mapping,
                      options: ClipperOptions) -> tuple[list[dict],list[dict]]:
    """Offer nearby Whisper word edges while preserving configured duration."""
    start=int(candidate['start_ms']);end=int(candidate['end_ms'])
    minimum=options.min_seconds*1000.;maximum=options.max_seconds*1000.
    start_choices=[];end_choices=[]
    for word in all_words:
        word_start=int(word['start_ms']);word_end=int(word['end_ms'])
        if abs(word_start-start)<=3000 and minimum<=end-word_start<=maximum:
            start_choices.append({'ms':word_start,'word':str(word['text'])})
        if abs(word_end-end)<=3000 and minimum<=word_end-start<=maximum:
            end_choices.append({'ms':word_end,'word':str(word['text'])})
    for choices,value,label in ((start_choices,start,'Início atual'),
                                (end_choices,end,'Fim atual')):
        if not any(item['ms']==value for item in choices):
            choices.append({'ms':value,'word':label})
        choices.sort(key=lambda item:item['ms'])
    return start_choices,end_choices


def _cache_path(cache_dir: Path, key: str) -> Path:
    return cache_dir / 'results' / key[:2] / f'{key}.json'


def analyze_clips(clips, transcript_words: Sequence[Mapping], options: ClipperOptions | None = None,
                  *, control=None, progress=None, stage=None,
                  cache_dir: Path | None = None) -> dict:
    """Rank candidate windows from saved words and optional measured audio.

    This function never calls Whisper/Qwen, renders video, or changes a project.
    """
    opts=options or ClipperOptions()
    opts.__post_init__()
    root=Path(cache_dir or clipper_cache_dir())
    started=time.monotonic()
    results=[];hits=misses=0;decoded_seconds=0.;frames_seen=0
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
        if not words:
            results.append({'clip_id':clip.id,'title':clip.title,'source':source,
                'status':'missing_transcript','candidates':[],'events':[],
                'audio_available':False,'warnings':['Transcreva este bloco antes de usar o Clipador.']})
            if progress:progress(position+1,total)
            continue
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
            if cached.get('schema')==CACHE_SCHEMA and cached.get('key')==result_key:
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
                    progress=audio_progress,cache_dir=root)
                if feature_hit:hits+=1
                elif frames is not None:decoded_seconds+=clip.end-clip.start
            except Exception as exc:
                from .process_control import ProcessCancelled
                if isinstance(exc,ProcessCancelled):raise
                frames=None
                audio_warning=f'Áudio indisponível para análise: {str(exc)[:160]}'
            else:
                audio_warning='' if frames is not None else 'A fonte não contém faixa de áudio decodificável.'
        if control:control.checkpoint()
        frames_seen+=len(frames.times_ms) if frames is not None else 0
        speech_intervals=[(word['start_ms'],word['end_ms']) for word in words]
        events=(detect_energy_events(frames,speech_intervals,
                 relative_rise_db=opts.relative_rise_db) if frames is not None else [])
        turns=_utterances(words)
        events=align_events_to_conversation(events,turns)
        events=[dict(event,clip_id=clip.id,title=clip.title,source=source) for event in events]
        candidates=[]
        for candidate in _candidate_spans(words,opts):
            if control:control.checkpoint()
            ranked=score_clip(candidate,events,frames)
            candidate_events=[event for event in events
                if event['start_ms']<candidate['end_ms'] and
                   event['end_ms']>candidate['start_ms']]
            warnings=list(ranked['warnings'])
            if audio_warning:warnings.append(audio_warning)
            elif frames is not None:
                mask=(frames.times_ms>=candidate['start_ms']) & (frames.times_ms<candidate['end_ms'])
                if np.any(mask) and float(np.mean(frames.rms_dbfs[mask] <= -65.))>.95:
                    warnings.append('Mais de 95% do intervalo ficou abaixo de -65 dBFS.')
            candidate_id=digest({'clip_id':clip.id,'start_ms':candidate['start_ms'],
                                  'end_ms':candidate['end_ms']})[:16]
            start_choices,end_choices=_boundary_choices(words,candidate,opts)
            candidates.append({'id':candidate_id,'clip_id':clip.id,'title':clip.title,
                'source':source,'source_start':candidate['start_ms']/1000.,
                'source_end':candidate['end_ms']/1000.,
                'start_ms':candidate['start_ms'],'end_ms':candidate['end_ms'],
                'duration':(candidate['end_ms']-candidate['start_ms'])/1000.,
                'text':candidate['text'],'score':ranked['score'],
                'score_note':ranked['note'],'reasons':candidate['text_reasons']+ranked['reasons'],
                'warnings':warnings,'events':candidate_events,
                'word_spans':[{'start_ms':int(word['start_ms']),
                    'end_ms':int(word['end_ms']),'text':str(word['text'])}
                    for word in words
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
            'events':events,'audio_available':frames is not None,
            'warnings':[audio_warning] if audio_warning else []}
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
            'feature_frames':frames_seen,'candidate_count':candidate_count,
            'elapsed_seconds':round(time.monotonic()-started,3),'rss_mb':round(rss_mb,2) if rss_mb else None}}
