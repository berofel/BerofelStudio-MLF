"""Local, reversible automatic cleanup using the editor's Silero/Whisper cache.

All proposed intervals are clip-source-relative seconds. No generative model is
used here; transcript words always keep timestamps supplied by Faster-Whisper
or already persisted by the project.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from collections import Counter
from difflib import SequenceMatcher
from functools import lru_cache
import re
import threading
import time
from typing import Callable

from .ai_pipeline import AIOptions, run_analysis


@dataclass(frozen=True)
class EditOptions:
    remove_silences: bool = False
    remove_fillers: bool = False
    analyze_context: bool = False

    @property
    def empty(self) -> bool:
        return not (self.remove_silences or self.remove_fillers or self.analyze_context)


@dataclass(frozen=True)
class TranscriptWord:
    text: str
    start: float  # original source time
    end: float
    probability: float = 1.0


@dataclass(frozen=True)
class CutCandidate:
    clip_id: str
    start: float  # relative to original clip source in/out
    end: float
    reason: str
    evidence: tuple[str, ...]
    score: float
    source_module: str
    id: str

    def as_finding(self, title: str) -> dict:
        modules=set(self.source_module.split('+'))
        kind = ('silencio' if modules=={'silence'} else 'filler' if modules=={'filler'}
                else 'contexto' if modules=={'context'} else 'misto')
        return {'clip_id': self.clip_id, 'title': title, 'a': self.start, 'b': self.end,
                'type': kind, 'score': round(self.score), 'note': self.reason,
                'evidence': list(self.evidence), 'source_module': self.source_module,
                'candidate_id': self.id, 'checked': False}


@dataclass
class EditPlan:
    options: EditOptions
    candidates: list[CutCandidate] = field(default_factory=list)
    reports: list[dict] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    stats: dict = field(default_factory=dict)


_WORD_RE = re.compile(r"[\wÀ-ÿ]+(?:['’][\wÀ-ÿ]+)?", re.UNICODE)
_STOP = frozenset('a o os as um uma uns umas de do da dos das em no na nos nas por para com e ou que se ao aos à às eu você voces nós eles elas ele ela isso isto aquele aquela hoje vídeo hoje como'.split())
_NEGATION = frozenset({'não', 'nunca', 'jamais', 'sem', 'nem', 'nenhum', 'nenhuma'})
_CUES = ('quer dizer', 'ou melhor', 'na verdade', 'vamos de novo', 'pera', 'não,')
_CONTINUATION = frozenset({'e', 'mas', 'porque', 'pois', 'então', 'quando', 'que', 'com'})
_FILLERS = frozenset({'ahn', 'hum', 'hmm', 'ããã', 'ééé', 'éh'})
_NUMBER_WORDS = frozenset('zero um uma dois duas tres três quatro cinco seis sete oito nove dez onze doze treze catorze quatorze quinze dezesseis dezassete dezessete dezoito dezenove vinte'.split())


class _ProcessMemorySampler:
    """Optional RSS sampler across the UI worker and its AI subprocesses."""
    def __init__(self):
        self.peak_mib=None;self._stop=threading.Event();self._thread=None;self._psutil=None
    def __enter__(self):
        try:
            import psutil
            self._psutil=psutil
        except ImportError:
            return self
        self._thread=threading.Thread(target=self._sample,daemon=True)
        self._thread.start();return self
    def _sample(self):
        root=self._psutil.Process()
        while not self._stop.is_set():
            total=0
            try:
                processes=[root,*root.children(recursive=True)]
                for process in processes:
                    try:total+=process.memory_info().rss
                    except (self._psutil.Error,OSError):pass
                mib=total/(1024*1024)
                self.peak_mib=mib if self.peak_mib is None else max(self.peak_mib,mib)
            except (self._psutil.Error,OSError):pass
            self._stop.wait(.1)
    def __exit__(self,*exc):
        self._stop.set()
        if self._thread:self._thread.join(timeout=1)


@lru_cache(maxsize=1)
def _spacy_pipeline():
    """Load the small PT model only for text modules and only if already installed."""
    try:
        import spacy
        if spacy.util.is_package('pt_core_news_sm'):
            return spacy.load('pt_core_news_sm',disable=('ner','parser'))
    except Exception:
        pass  # optional model; deterministic stdlib fallback remains available
    return None


@lru_cache(maxsize=8192)
def _token_cache(text: str) -> tuple[str, ...]:
    return tuple(token.casefold().replace('’', "'") for token in _WORD_RE.findall(text or ''))


def _tokens(text: str) -> list[str]:
    return list(_token_cache(text))


@lru_cache(maxsize=8192)
def _lemma(token: str) -> str:
    """Use installed small PT spaCy model on demand, else deterministic fallback."""
    token = token.casefold()
    nlp=_spacy_pipeline()
    if nlp is not None:
        try:
            lemma=str(nlp(token)[0].lemma_).casefold().strip()
            if lemma and lemma!='-pron-':return lemma
        except Exception:pass
    if token.endswith(('ar','er','ir')) and len(token)>3:
        return token
    # Controlled auxiliaries/periphrases: preserve lexical action, separately
    # compare negation and modality before approving a replacement.
    irregular = {'faremos': 'fazer', 'faremos': 'fazer', 'iremos': 'ir',
                 'vamos': 'ir', 'vou': 'ir', 'mostrarei': 'mostrar',
                 'mostramos': 'mostrar', 'fizemos': 'fazer', 'feito': 'fazer'}
    if token in irregular:
        return irregular[token]
    for suffix in ('ando', 'endo', 'indo'):
        if len(token) > len(suffix) + 2 and token.endswith(suffix):
            return token[:-len(suffix)] + ('ar' if suffix == 'ando' else 'er' if suffix == 'endo' else 'ir')
    for suffix in ('aremos', 'eremos', 'iremos', 'aria', 'erá', 'irá', 'aram', 'eram', 'iram', 'ando', 'endo', 'indo', 'amos', 'emos', 'imos', 'ou', 'eu', 'iu', 'ar', 'er', 'ir', 's'):
        if len(token) > len(suffix) + 3 and token.endswith(suffix):
            stem = token[:-len(suffix)]
            if suffix in ('ou', 'aram', 'amos', 'aremos'):
                return stem + 'ar'
            if suffix in ('eu', 'eram', 'emos', 'eremos'):
                return stem + 'er'
            if suffix in ('iu', 'iram', 'imos', 'iremos'):
                return stem + 'ir'
            return stem
    return token


def _core(tokens: list[str]) -> set[str]:
    return set(_core_cache(' '.join(tokens)))


@lru_cache(maxsize=8192)
def _core_cache(text: str) -> frozenset[str]:
    tokens=_token_cache(text)
    result=set()
    for i,token in enumerate(tokens):
        lemma=_lemma(token)
        # "vou/iremos/ vamos + infinitivo" marks future modality, not a
        # second informational action competing with the infinitive.
        if lemma=='ir' and i+1<len(tokens) and _lemma(tokens[i+1]).endswith(('ar','er','ir')):
            continue
        if token not in _STOP and len(lemma)>1:
            result.add(lemma)
    return frozenset(result)


def _sequence_tokens(tokens: list[str]) -> list[str]:
    output=[]
    for i,token in enumerate(tokens):
        lemma=_lemma(token)
        if lemma=='ir' and i+1<len(tokens) and _lemma(tokens[i+1]).endswith(('ar','er','ir')):
            continue
        output.append(lemma)
    return output


def _numbers(tokens: list[str]) -> set[str]:
    return {t for t in tokens if any(char.isdigit() for char in t) or t in _NUMBER_WORDS}


def _important_names(words: list[TranscriptWord]) -> set[str]:
    """Preserve likely proper names, excluding sentence-initial capitalization."""
    result=set()
    for index,word in enumerate(words):
        token=_tokens(word.text)
        if not token:continue
        raw=word.text.strip('.,;:!?()[]{}\"“”')
        if index and raw[:1].isupper() and token[0] not in _STOP:
            result.add(_lemma(token[0]))
    return result


def _ngram_overlap(left: list[str], right: list[str]) -> float:
    def grams(items):
        normalized=[_lemma(t) for t in items if t not in _STOP]
        return Counter(tuple(normalized[i:i+n]) for n in (1,2,3)
                       for i in range(max(0,len(normalized)-n+1)))
    a,b=grams(left),grams(right)
    if not a or not b:return 0.
    shared=sum((a & b).values())
    return shared/max(1,min(sum(a.values()),sum(b.values())))


@lru_cache(maxsize=1)
def _rapidfuzz_available():
    try:
        from rapidfuzz.fuzz import ratio
        return ratio
    except ImportError:
        return None


def _weighted_overlap(left: list[str], right: list[str]) -> float:
    a, b = _core(left), _core(right)
    if not a or not b:
        return 0.0
    return len(a & b) / max(1, min(len(a), len(b)))


def _sentences(words: list[dict], clip_start: float, pauses: list[tuple[float, float]]) -> list[list[TranscriptWord]]:
    result: list[list[TranscriptWord]] = []
    current: list[TranscriptWord] = []
    last_end = clip_start
    for item in sorted(words, key=lambda w: float(w.get('source_start', clip_start))):
        text = str(item.get('text', '')).strip()
        try:
            start = float(item.get('source_start', clip_start + float(item.get('start', 0))))
            end = float(item.get('source_end', clip_start + float(item.get('end', 0))))
        except (TypeError, ValueError):
            continue
        if not text or end <= start:
            continue
        if current and (start-last_end >= .32 or any(last_end <= p0 and start >= p1 for p0, p1 in pauses)):
            result.append(current); current = []
        word = TranscriptWord(text, start, end, float(item.get('probability') or 1.0))
        current.append(word); last_end = end
        if re.search(r'[.!?…]["”\']?$', text):
            result.append(current); current = []
    if current:
        result.append(current)
    return result


def _context_candidates(clip, report: dict, pause_spans: list[tuple[float, float]]) -> tuple[list[CutCandidate], list[str]]:
    sentences = _sentences(report.get('words', []), clip.start, pause_spans)
    found: list[CutCandidate] = []
    protected: list[str] = []
    for index, newer in enumerate(sentences):
        if len(newer) < 4:
            continue
        new_text = ' '.join(w.text for w in newer)
        nt = _tokens(new_text)
        if not _core(nt):
            continue
        new_start, new_end = newer[0].start, newer[-1].end
        # Search only nearby prior utterances and a bounded 30-second window.
        for back in range(1, min(index, 4) + 1):
            older = sentences[index-back]
            old_start, old_end = older[0].start, older[-1].end
            gap = new_start - old_end
            anchored_pause=any(p0 <= new_start and p1 >= old_end and p1-p0 >= .22
                               for p0,p1 in pause_spans)
            if gap < .22 or not anchored_pause or new_start-old_start > 35:
                continue
            old_text = ' '.join(w.text for w in older)
            ot = _tokens(old_text)
            if len(ot) < 2:
                continue
            # Contrastive facts that are not safely interchangeable.
            old_lemmas, new_lemmas = {_lemma(t) for t in ot}, {_lemma(t) for t in nt}
            if bool(old_lemmas & _NEGATION) != bool(new_lemmas & _NEGATION):
                protected.append('negação diferente'); continue
            if _numbers(ot) and _numbers(nt) and _numbers(ot) != _numbers(nt):
                protected.append('quantidades diferentes'); continue
            old_names,new_names=_important_names(older),_important_names(newer)
            if old_names and new_names and old_names != new_names:
                protected.append('nomes próprios diferentes'); continue
            opposites = ({'instalar', 'desinstalar'}, {'ativar', 'desativar'}, {'conectar', 'desconectar'})
            if any(pair <= (old_lemmas | new_lemmas) and (pair & old_lemmas) != (pair & new_lemmas)
                   for pair in opposites):
                protected.append('ação oposta'); continue
            if _tokens(new_text) and _tokens(new_text)[0] in _CONTINUATION:
                protected.append('continuidade da fala'); continue
            overlap = _weighted_overlap(ot, nt)
            seq = SequenceMatcher(None, _sequence_tokens(ot), _sequence_tokens(nt), autojunk=False).ratio()
            ngrams = _ngram_overlap(ot,nt)
            rapid=_rapidfuzz_available()
            fuzzy=(float(rapid(' '.join(_sequence_tokens(ot)),
                               ' '.join(_sequence_tokens(nt))))/100 if rapid else seq)
            cue = any(cue in new_text.casefold() for cue in _CUES)
            first_incomplete = not re.search(r'[.!?]["”\']?$', older[-1].text)
            newer_complete = bool(re.search(r'[.!?]["”\']?$', newer[-1].text)) or len(nt) >= 7
            if seq >= .98 and not first_incomplete and not cue:
                protected.append('repetição integral pode ser intencional')
                continue
            # Coverage is directional: every substantive idea from the first
            # attempt must survive in the later one. Additions are safe.
            old_core, new_core = _core(ot), _core(nt)
            covered = len(old_core & new_core) / max(1, len(old_core))
            old_distinct = old_core - new_core
            if overlap >= .72 and max(seq,fuzzy) >= .42 and ngrams >= .4 and covered >= .78 and newer_complete and not old_distinct:
                # Without a discourse cue, only clearly abandoned/incomplete
                # starts or a strong near-equivalent rewrite qualify.
                if cue or (first_incomplete and max(seq,fuzzy) >= .48) or (overlap >= .9 and max(seq,fuzzy) >= .7):
                    relative_start=max(0., old_start-clip.start)
                    relative_end=max(relative_start, old_end-clip.start)
                    if relative_end-relative_start >= .04:
                        reason = 'Reformulação próxima após pausa; a tentativa posterior cobre o núcleo anterior.'
                        evidence=(f'pausa {gap:.2f}s', f'conteúdo coberto {covered:.0%}',
                                  f'alinhamento {max(seq,fuzzy):.0%}',
                                  f'n-gramas {ngrams:.0%}', 'versão posterior completa')
                        found.append(CutCandidate(clip.id, relative_start, relative_end, reason,
                            evidence, min(98, 70+covered*20+seq*8), 'context',
                            f'ctx:{clip.id}:{round(old_start*1000)}:{round(old_end*1000)}'))
                        break
            elif overlap >= .35:
                protected.append('conteúdo relacionado, mas evidência insuficiente para excluir')
    return found, protected


def _filler_candidates(clip, report: dict) -> list[CutCandidate]:
    words = sorted(report.get('words', []), key=lambda w: float(w.get('source_start', 0)))
    found=[]
    clean=[]
    for item in words:
        text=str(item.get('text','')).strip()
        try:
            start=float(item.get('source_start', clip.start+float(item.get('start',0))))
            end=float(item.get('source_end', clip.start+float(item.get('end',0))))
        except (TypeError,ValueError):
            continue
        token=_tokens(text)
        if not token or end<=start: continue
        normalized=token[0]
        extended=bool(re.search(r'(?:é|ã|a|h){2,}', normalized))
        is_filler=normalized in _FILLERS or extended
        if is_filler and end-start <= 1.2 and item.get('probability',1) >= .25:
            found.append(CutCandidate(clip.id,max(0,start-clip.start),min(clip.end-clip.start,end-clip.start),
                'Hesitação lexical isolada com timestamp confirmado.',(text,),88,'filler',
                f'fill:{clip.id}:{round(start*1000)}:{round(end*1000)}'))
        clean.append((normalized,start,end,text))
    # Remove only earlier items in an adjacent stutter; preserve the final
    # occurrence and do not treat syntactic "é", "não", "tipo" or "né" as filler.
    for i in range(len(clean)-1):
        token,start,end,text=clean[i]
        nxt,nstart,nend,_=clean[i+1]
        if token==nxt and nstart-end <= .28 and token not in {'é','não','tipo','né'}:
            found.append(CutCandidate(clip.id,max(0,start-clip.start),min(clip.end-clip.start,end-clip.start),
                'Repetição adjacente da mesma palavra; ocorrência seguinte preservada.',
                (text, clean[i+1][3]),82,'filler',f'rep:{clip.id}:{round(start*1000)}'))
    return [c for c in found if c.end-c.start >= .025]


def _merge_candidates(candidates: list[CutCandidate]) -> tuple[list[CutCandidate], int]:
    ordered=sorted(candidates,key=lambda c:(c.clip_id,c.start,c.end))
    merged=[]
    for candidate in ordered:
        if merged and merged[-1].clip_id==candidate.clip_id and candidate.start <= merged[-1].end+.02:
            previous=merged[-1]
            modules=tuple(dict.fromkeys(previous.source_module.split('+')+[candidate.source_module]))
            merged[-1]=CutCandidate(previous.clip_id,previous.start,max(previous.end,candidate.end),
                previous.reason if candidate.source_module in previous.source_module else previous.reason+' / '+candidate.reason,
                tuple(dict.fromkeys(previous.evidence+candidate.evidence)),max(previous.score,candidate.score),
                '+'.join(modules),previous.id+'+'+candidate.id)
        else:
            merged.append(candidate)
    return merged,len(ordered)-len(merged)


def analyze_automatic_cleanup(clips, options: EditOptions, *, known_words=None,
                              analyze: Callable=run_analysis, progress=None,
                              control=None, stage=None, ai_options=None) -> EditPlan:
    """Run selected modules, sharing existing cached Silero and Whisper data.

    ``silence`` is the existing Silero route; ``transcribe`` is the existing
    Faster-Whisper route. This function never calls Qwen or a generative model.
    """
    started=time.perf_counter(); plan=EditPlan(options)
    feature_cache_before=(_token_cache.cache_info(),_lemma.cache_info(),_core_cache.cache_info())
    if options.empty:
        plan.stats={'empty_selection':True,'vad_calls':0,'transcription_calls':0}
        return plan
    known_words=known_words or {}
    needs_vad=options.remove_silences or options.analyze_context
    needs_text=options.remove_fillers or options.analyze_context
    opts=ai_options or AIOptions(enable_qwen=False)
    vad_data={'reports':[],'suggestions':[],'cache_hits':0,'cache_misses':0,'stages':[]}
    text_data={'reports':[],'cache_hits':0,'cache_misses':0,'stages':[]}
    vad_seconds=text_seconds=0.
    vad_peak=text_peak=None
    if needs_vad:
        if control: control.checkpoint()
        if stage: stage('Silero VAD · pausas no áudio original')
        then=time.perf_counter()
        with _ProcessMemorySampler() as memory:
            vad_data=analyze(clips,options=opts,known_words=known_words,progress=progress,
                             control=control,stage=stage,mode='silence')
        vad_seconds=time.perf_counter()-then;vad_peak=memory.peak_mib
    uncovered=[clip for clip in clips if clip.id not in known_words]
    # Existing project words are the canonical copy where coverage was checked
    # by MainWindow. Transcribe only clip ranges lacking persisted words.
    if needs_text and uncovered:
        if control: control.checkpoint()
        if stage: stage('Faster-Whisper · transcrição necessária')
        then=time.perf_counter()
        with _ProcessMemorySampler() as memory:
            text_data=analyze(uncovered,options=opts,known_words={},progress=progress,
                              control=control,stage=stage,mode='transcribe')
        text_seconds=time.perf_counter()-then;text_peak=memory.peak_mib
    reports_by_id={r['clip_id']:dict(r) for r in vad_data.get('reports',[])}
    for report in text_data.get('reports',[]):
        current=reports_by_id.setdefault(report['clip_id'],dict(report))
        current.update({key:value for key,value in report.items() if key not in ('speech','suggestions')})
    # Attach persisted transcript words to VAD reports when no transcription ran.
    lexical_seconds=0.;planning_started=time.perf_counter()
    for clip in clips:
        report=reports_by_id.setdefault(clip.id,{'clip_id':clip.id,'title':clip.title,'words':[],'speech':[],'suggestions':[]})
        if not report.get('words') and clip.id in known_words:
            report['words']=list(known_words[clip.id])
        if options.remove_silences:
            for finding in vad_data.get('suggestions',[]):
                if finding.get('clip_id')==clip.id:
                    plan.candidates.append(CutCandidate(clip.id,max(0,float(finding['a'])),
                        min(clip.end-clip.start,float(finding['b'])),
                        str(finding.get('note') or 'Silero detectou ausência de fala; margens aplicadas.'),
                        ('região sem fala detectada por Silero',),95,'silence',
                        f'sil:{clip.id}:{round(float(finding["a"])*1000)}:{round(float(finding["b"])*1000)}'))
        if options.remove_fillers:
            lexical_started=time.perf_counter()
            plan.candidates.extend(_filler_candidates(clip,report))
            lexical_seconds+=time.perf_counter()-lexical_started
        if options.analyze_context:
            pauses=[]
            speech=sorted(report.get('speech',[]),key=lambda s:float(s['start']))
            for left,right in zip(speech,speech[1:]):
                if float(right['start'])-float(left['end']) >= .22:
                    pauses.append((clip.start+float(left['end']),clip.start+float(right['start'])))
            lexical_started=time.perf_counter()
            context,protected=_context_candidates(clip,report,pauses)
            lexical_seconds+=time.perf_counter()-lexical_started
            plan.candidates.extend(context)
            plan.stats.setdefault('context_protected',[]).extend(
                {'clip_id':clip.id,'reason':reason} for reason in protected)
        plan.reports.append(report)
    plan.candidates,overlaps=_merge_candidates(plan.candidates)
    planning_seconds=time.perf_counter()-planning_started
    plan.metrics={'vad_pipeline_seconds':round(vad_seconds,4),
                  'transcription_pipeline_seconds':round(text_seconds,4),
                  'text_rules_seconds':round(lexical_seconds,4),
                  'cut_planning_seconds':round(max(0.,planning_seconds-lexical_seconds),4),
                  'analysis_seconds':round(time.perf_counter()-started,4),
                  'vad_pipeline_peak_rss_mib':round(vad_peak,2) if vad_peak is not None else None,
                  'transcription_pipeline_peak_rss_mib':round(text_peak,2) if text_peak is not None else None,
                  'cache_hits':int(vad_data.get('cache_hits',0))+int(text_data.get('cache_hits',0)),
                  'cache_misses':int(vad_data.get('cache_misses',0))+int(text_data.get('cache_misses',0)),
                  'stages':list(vad_data.get('stages',[]))+list(text_data.get('stages',[]))}
    plan.stats.update({'vad_calls':int(needs_vad),'transcription_calls':int(bool(needs_text and uncovered)),
                       'candidate_count':len(plan.candidates),'overlap_merges':overlaps,
                       'silence_candidates':sum('silence' in c.source_module for c in plan.candidates),
                       'filler_candidates':sum('filler' in c.source_module for c in plan.candidates),
                       'context_candidates':sum('context' in c.source_module for c in plan.candidates)})
    feature_cache_after=(_token_cache.cache_info(),_lemma.cache_info(),_core_cache.cache_info())
    plan.stats['text_feature_cache_hits']=sum(after.hits-before.hits for before,after in zip(feature_cache_before,feature_cache_after))
    plan.stats['text_feature_cache_misses']=sum(after.misses-before.misses for before,after in zip(feature_cache_before,feature_cache_after))
    return plan
