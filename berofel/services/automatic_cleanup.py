"""Local, reversible automatic cleanup using the editor's Silero/Parakeet cache.

All proposed intervals are clip-source-relative seconds. No generative model is
used here; transcript words always keep timestamps supplied by Parakeet TDT
or already persisted by the project.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from collections import Counter
from difflib import SequenceMatcher
from functools import lru_cache
import re
import threading
import time
import unicodedata
import math
from typing import Callable
from .domain_terms import BASE_ANALYSIS_TERMS
from .discourse_features import analyze_irony

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
    speaker: str | None = None


@dataclass(frozen=True)
class PhraseSignature:
    """Cached, compact evidence used to compare transcript spans directionally."""
    tokens: tuple[str, ...]
    concepts: frozenset[str]
    actions: frozenset[str]
    numbers: frozenset[str]
    negation: bool
    conditions: frozenset[str] = frozenset()
    modality: frozenset[str] = frozenset()
    entities: frozenset[str] = frozenset()
    time_references: frozenset[str] = frozenset()
    subjects: frozenset[str] = frozenset()
    question: bool = False


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
    risk_flags: tuple[str, ...] = ()
    requires_individual_review: bool = False
    speed: float | None = None

    def as_finding(self, title: str) -> dict:
        modules=set(self.source_module.split('+'))
        kind = ('speedup' if modules=={'speedup'} else
                'silencio' if modules=={'silence'} else 'filler' if modules=={'filler'}
                else 'contexto' if modules=={'context'} else 'misto')
        finding={'clip_id': self.clip_id, 'title': title, 'a': self.start, 'b': self.end,
                'type': kind, 'score': round(self.score), 'note': self.reason,
                'evidence': list(self.evidence), 'source_module': self.source_module,
                'candidate_id': self.id, 'checked': False,
                'risk_flags': list(self.risk_flags),
                'requires_individual_review': self.requires_individual_review}
        if self.speed is not None: finding['speed']=self.speed
        return finding


@dataclass
class EditPlan:
    options: EditOptions
    candidates: list[CutCandidate] = field(default_factory=list)
    reports: list[dict] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    stats: dict = field(default_factory=dict)


_WORD_RE = re.compile(r"[\wÀ-ÿ]+(?:['’][\wÀ-ÿ]+)?", re.UNICODE)
_STOP = frozenset('a o os as um uma uns umas de do da dos das em no na nos nas por para com e ou que se ao aos à às eu você voces vocês nós eles elas ele ela isso isto aquele aquela hoje vídeo hoje como está estou estão estava'.split())
_NEGATION = frozenset({'não', 'nunca', 'jamais', 'sem', 'nem', 'nenhum', 'nenhuma'})
_CONDITIONS = frozenset({'se', 'caso', 'desde', 'condição'})
_MODALITY = frozenset({'pode', 'podem', 'poderia', 'poderiam', 'deve', 'devem',
                       'deveria', 'deveriam', 'talvez', 'precisa', 'precisam',
                       'pretende', 'pretendem', 'possível', 'impossível'})
_ADDITIVE = frozenset({'também', 'alem', 'além', 'ainda', 'inclusive', 'adicionalmente'})
_SUBJECTS=frozenset({'eu','você','voce','vocês','voces','nós','nos','ele','ela',
                     'eles','elas','a_gente','vocês','voces'})
_TIME_REFERENCES=frozenset({'hoje','ontem','amanhã','amanha','agora','depois','antes',
                            'semana','mês','mes','ano','hora','minuto','segundo'})
_CUES = ('quer dizer', 'ou melhor', 'na verdade', 'vamos de novo', 'pera', 'não,')
_CONTINUATION = frozenset({'e', 'mas', 'porque', 'pois', 'então', 'quando', 'que', 'com'})
_FILLERS = frozenset({'ahn', 'hum', 'hmm', 'ããã', 'ééé', 'éh'})
_EMPHASIS_WORDS = frozenset({'bem', 'demais', 'mais', 'menos', 'muito', 'muita',
                             'muitos', 'muitas', 'super', 'tão'})
_PRESERVED_REPEAT_WORDS = frozenset({'é', 'não', 'tipo', 'né'}) | _EMPHASIS_WORDS
_RESTART_PREFIXES = frozenset({
    ('eu', 'vou'), ('eu', 'quero'), ('eu', 'posso'), ('eu', 'preciso'),
    ('eu', 'estou'), ('eu', 'estava'), ('nós', 'vamos'), ('nos', 'vamos'),
    ('a', 'gente', 'vai'), ('a', 'gente', 'quer'), ('a', 'gente', 'pode'),
    ('vou', 'fazer'), ('vou', 'mostrar'), ('vou', 'ensinar'),
    ('vamos', 'fazer'), ('vamos', 'mostrar'), ('vamos', 'começar'),
})
_NUMBER_WORDS = frozenset('zero um uma dois duas tres três quatro cinco seis sete oito nove dez onze doze treze catorze quatorze quinze dezesseis dezassete dezessete dezoito dezenove vinte'.split())
_CONCEPT_BY_LEMMA={
    'começar':'iniciar','mostrar':'demonstrar','exibir':'demonstrar',
    'apresentar':'demonstrar','ensinar':'demonstrar','demonstrar':'demonstrar',
    'remover':'retirar','retirar':'retirar','excluir':'retirar',
    'programa':'aplicativo','aplicativo':'aplicativo','software':'aplicativo',
    'legenda':'legenda','subtítulo':'legenda','subtitular':'legenda',
}
_KNOWN_ENTITIES=frozenset({'windows','linux','macos','berofelstudio','berofel','qwen',
    'silero','parakeet','ffmpeg','timeline','portugues','português','brasil'})
_ANALYSIS_APPROVED=frozenset(word.casefold() for term in BASE_ANALYSIS_TERMS
                             for word in _WORD_RE.findall(term))
_ANALYSIS_ALIAS_SEEN=set()
_ACTION_LEMMAS=frozenset({'começar','iniciar','mostrar','exibir','apresentar','ensinar','demonstrar',
    'fazer','instalar','desinstalar','configurar','editar','remover','retirar','excluir',
    'legendar','transcrever','exportar','abrir','salvar','gerar','permitir','funcionar',
    'processar','adicionar','criar','aparecer','reiniciar','usar','gravar','corrigir'})
_REPAIR_PATTERNS=(('na','verdade'),('quer','dizer'),('ou','melhor'),
                  ('melhor','dizendo'),('corrigindo',),('digo',),('espera',),('pera',))
_RETAKE_PATTERNS=(('vou','falar','de','novo'),('deixa','eu','refazer'),
    ('deixa','eu','recomecar'),('vou','recomecar'),('vamos','de','novo'),
    ('vamos','refazer'),('nao','pera'),('nao','espera'),('errei','vou','de','novo'),
    ('corta','essa','parte'),('essa','nao','ficou','boa'))
_RETAKE_STARTS=frozenset(pattern[0] for pattern in _RETAKE_PATTERNS)
_NUMBER_CANONICAL={
    'zero':'0','um':'1','uma':'1','dois':'2','duas':'2','tres':'3','três':'3',
    'quatro':'4','cinco':'5','seis':'6','sete':'7','oito':'8','nove':'9','dez':'10',
    'onze':'11','doze':'12','treze':'13','catorze':'14','quatorze':'14','quinze':'15',
    'dezesseis':'16','dezassete':'17','dezessete':'17','dezoito':'18','dezenove':'19',
    'vinte':'20','trinta':'30','quarenta':'40','cinquenta':'50','sessenta':'60',
    'setenta':'70','oitenta':'80','noventa':'90','cem':'100','cento':'100'}
_ANALYSIS_CRITICAL=frozenset(set(_NEGATION)|set(_CONDITIONS)|set(_MODALITY)|
    set(_SUBJECTS)|set(_KNOWN_ENTITIES)|{'instalar','desinstalar','ativar','desativar',
    'conectar','desconectar','permitir','impedir'})
_SUBJECT_GROUPS = {
    'eu': 'singular_1', 'meu': 'singular_1', 'minha': 'singular_1',
    'você': 'singular_2', 'voce': 'singular_2', 'cê': 'singular_2',
    'vocês': 'plural_2', 'voces': 'plural_2',
    'nós': 'plural_1', 'nos': 'plural_1', 'a_gente': 'plural_1',
    'ele': 'singular_3', 'ela': 'singular_3', 'eles': 'plural_3', 'elas': 'plural_3',
}
_TOKEN_CANONICAL={
    'nao':'não','voce':'você','voces':'vocês','tres':'três',
    'subtitulo':'subtítulo','subtitulos':'subtítulos',
    'ta':'está','tá':'está','to':'estou','tô':'estou',
    'cê':'você','ce':'você','pra':'para',
}


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
    normalized=unicodedata.normalize('NFC',unicodedata.normalize('NFKC',text or ''))
    return tuple(_TOKEN_CANONICAL.get(token.casefold().replace('’', "'"),
                                      token.casefold().replace('’', "'"))
                 for token in _WORD_RE.findall(normalized))


def _tokens(text: str) -> list[str]:
    return list(_token_cache(text))


@lru_cache(maxsize=8192)
def _lemma(token: str) -> str:
    """Use installed small PT spaCy model on demand, else deterministic fallback."""
    token = _TOKEN_CANONICAL.get(token.casefold(),token.casefold())
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
    return set(_phrase_signature(' '.join(tokens)).concepts)


def _sequence_tokens(tokens: list[str]) -> list[str]:
    output=[]
    for i,token in enumerate(tokens):
        token=_analysis_alias(token)
        lemma=_lemma(token)
        if lemma=='ir' and i+1<len(tokens) and _lemma(tokens[i+1]).endswith(('ar','er','ir')):
            continue
        output.append(_CONCEPT_BY_LEMMA.get(lemma,lemma))
    return output


def _numbers(tokens: list[str]) -> set[str]:
    return {_NUMBER_CANONICAL.get(t, t) for t in tokens
            if any(char.isdigit() for char in t) or t in _NUMBER_WORDS or t in _NUMBER_CANONICAL}


def _number_concepts(numbers: set[str] | frozenset[str]) -> set[str]:
    return {'numero:'+value for value in numbers}


def _repeated_emphasis(tokens: list[str]) -> Counter[str]:
    """Count adjacent emphasis words so Context cannot erase spoken emphasis."""
    repeated=Counter()
    for left,right in zip(tokens,tokens[1:]):
        if left==right and left in _EMPHASIS_WORDS:
            repeated[left]+=1
    return repeated


@lru_cache(maxsize=8192)
def _phrase_signature(text: str) -> PhraseSignature:
    tokens=_token_cache(text)
    concepts=[]
    for i,token in enumerate(tokens):
        analyzed=_analysis_alias(token)
        lemma=_lemma(analyzed)
        if lemma=='ir' and i+1<len(tokens) and _lemma(tokens[i+1]).endswith(('ar','er','ir')):
            continue
        if token not in _STOP and lemma not in _STOP and len(lemma)>1 and token not in _NUMBER_CANONICAL:
            concepts.append(_CONCEPT_BY_LEMMA.get(lemma,lemma))
    concepts.extend('numero:'+value for value in _numbers(list(tokens)))
    concept_set=frozenset(concepts)
    action_concepts=set(_ACTION_LEMMAS)|{'iniciar','demonstrar','retirar'}
    entities=frozenset(_analysis_alias(token) for token in tokens if _analysis_alias(token) in _KNOWN_ENTITIES or
                       (any(ch.isdigit() for ch in token)))
    subjects=frozenset(_SUBJECT_GROUPS[token] for token in tokens if token in _SUBJECT_GROUPS)
    question=bool(re.search(r'\?\s*$',text or ''))
    return PhraseSignature(tokens,concept_set,
        frozenset(concept_set & action_concepts),
        frozenset(_numbers(list(tokens))),bool(set(tokens)&_NEGATION),
        frozenset(set(tokens)&_CONDITIONS),frozenset(set(tokens)&_MODALITY),entities,
        frozenset(set(tokens)&_TIME_REFERENCES),subjects,question)


@lru_cache(maxsize=512)
def _analysis_alias(token: str) -> str:
    """Return a high-confidence spelling alias for comparisons only.

    Reuses the editor's cached VERO/Hunspell loader. It never edits transcript
    text, word offsets, captions, or ASR cache. Unknown/ambiguous words remain
    untouched, and approved technical vocabulary is protected.
    """
    folded=str(token).casefold()
    if (len(folded)<5 or folded in _ANALYSIS_APPROVED or folded in _STOP or
            folded in _ANALYSIS_CRITICAL or
            folded in _NUMBER_CANONICAL or
            any(ch.isdigit() for ch in folded)):
        return folded
    if folded not in _ANALYSIS_ALIAS_SEEN:
        if len(_ANALYSIS_ALIAS_SEEN)>=512:return folded
        _ANALYSIS_ALIAS_SEEN.add(folded)
    try:
        from .transcript_proofing import load_pt_br_dictionary
        dictionary=load_pt_br_dictionary()
        if dictionary is None or dictionary.lookup(token) or dictionary.lookup(folded):
            return folded
        candidates=[str(value).casefold() for value in dictionary.suggest(token)[:5]]
    except Exception:
        return folded
    if not candidates:
        return folded
    ratios=[SequenceMatcher(None,folded,candidate,autojunk=False).ratio() for candidate in candidates]
    order=sorted(range(len(candidates)),key=lambda index:ratios[index],reverse=True)
    best=order[0]
    runner_up=ratios[order[1]] if len(order)>1 else 0.
    alias=candidates[best]
    # Spell correction is only a candidate-generation aid. Never rewrite a
    # safety token into/out of a negation, number, entity, subject or action.
    if (alias in _ANALYSIS_CRITICAL or alias in _KNOWN_ENTITIES or
            alias in _NUMBER_CANONICAL or alias in _ACTION_LEMMAS or
            alias in _SUBJECT_GROUPS or alias in _NEGATION):
        return folded
    return alias if ratios[best]>=.90 and ratios[best]-runner_up>=.04 else folded


@lru_cache(maxsize=1024)
def _retake_offset(tokens: tuple[str, ...]) -> int:
    """Length of a leading spoken re-record command, zero when absent."""
    folded=tuple(_fold_token(token) for token in tokens)
    for pattern in _RETAKE_PATTERNS:
        if folded[:len(pattern)]==pattern:
            return len(pattern)
    return 0


def _fold_token(token: str) -> str:
    return ''.join(ch for ch in unicodedata.normalize('NFD',str(token).casefold())
                   if unicodedata.category(ch)!='Mn')


@lru_cache(maxsize=1024)
def _contains_retake_command(tokens: tuple[str, ...]) -> bool:
    folded=tuple(_fold_token(token) for token in tokens)
    return any(folded[i:i+len(pattern)]==pattern
               for i in range(len(folded)) for pattern in _RETAKE_PATTERNS)


def _repair_suffix(tokens: list[str]) -> tuple[int, tuple[str, ...], str] | None:
    """Return the text after an explicit self-repair marker, if present."""
    for index in range(len(tokens)):
        for pattern in _REPAIR_PATTERNS:
            if tuple(tokens[index:index+len(pattern)])==pattern:
                after=index+len(pattern)
                suffix=tuple(tokens[after:])
                if len(suffix)>=2:
                    return after,suffix,' '.join(pattern)
    return None


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
        normalized=[_CONCEPT_BY_LEMMA.get(_lemma(t),_lemma(t))
                    for t in items if t not in _STOP]
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
    ordered=sorted(words, key=lambda w: float(w.get('source_start', clip_start)))
    def restart_at(index):
        upcoming=[]
        for entry in ordered[index:index+4]:
            upcoming.extend(_tokens(str(entry.get('text',''))))
        upcoming=tuple(upcoming)
        markers=(
            ('no','video'),('no','vídeo'),('na','verdade'),('ou','melhor'),
            ('corrigindo',),('vamos','de','novo'),('quer','dizer'))
        return (any(upcoming[:len(marker)]==marker for marker in markers) or
                bool(_retake_offset(tuple(upcoming))) or
                any(upcoming[:len(prefix)]==prefix for prefix in _RESTART_PREFIXES))
    for index,item in enumerate(ordered):
        text = str(item.get('text', '')).strip()
        try:
            start = float(item.get('source_start', clip_start + float(item.get('start', 0))))
            end = float(item.get('source_end', clip_start + float(item.get('end', 0))))
        except (TypeError, ValueError):
            continue
        if not text or not math.isfinite(start) or not math.isfinite(end) or end <= start:
            continue
        # Split on an actual VAD pause or reliable hard punctuation. A generic
    # A word gap from ASR alone is not enough to declare a sentence boundary.
        gap=max(0.,start-last_end)
        preceding_correction=bool(current and
            _tokens(current[-1].text.strip(' ,;:'))[:1] in (['não'],['nao']))
        punctuation_restart=bool(current and not preceding_correction and
            re.search(r'[,;:…—–-]\s*$',current[-1].text) and restart_at(index))
        if current and (any(last_end <= p0 and start >= p1 and p1-p0 >= .22
                            for p0,p1 in pauses) or
                        (gap >= .25 and restart_at(index)) or
                        punctuation_restart or
                        re.search(r'[.!?]["”\']?$',current[-1].text)):
            result.append(current); current = []
        speaker=item.get('speaker_id',item.get('speaker'))
        raw_probability=item.get('probability')
        # Some ASR engines (including Parakeet TDT v3 through onnx-asr) do
        # not publish token confidence. Treat that as unknown/neutral, not as
        # a fabricated zero or a perfect score.
        probability=.5 if raw_probability is None else float(raw_probability)
        word = TranscriptWord(text, start, end, probability,
                              str(speaker) if speaker is not None else None)
        current.append(word); last_end = end
        # Ellipsis marks an interrupted thought and must stay attached to a
        # following repair ("cinco… na verdade, seis").
        if re.search(r'[.!?]["”\']?$', text):
            result.append(current); current = []
    if current:
        result.append(current)
    return result


def _context_candidates(clip, report: dict, pause_spans: list[tuple[float, float]],
                        control=None) -> tuple[list[CutCandidate], list[str]]:
    sentences = _sentences(report.get('words', []), clip.start, pause_spans)
    found: list[CutCandidate] = []
    protected: list[str] = []
    sentence_retake=[]
    for sentence in sentences:
        first_tokens=_tokens(sentence[0].text) if sentence else []
        # Retake instructions are conventional sentence-initial commands;
        # avoid scanning every lexical token in ordinary speech.
        if first_tokens and first_tokens[0] in _RETAKE_STARTS:
            all_tokens=tuple(token for word in sentence for token in _tokens(word.text))
            sentence_retake.append(_contains_retake_command(all_tokens))
        else:
            sentence_retake.append(False)
    # Work from the most recent attempt backwards so each candidate is judged
    # against the final take first. This bounds comparisons to nearby speech.
    for index in range(len(sentences)-1,-1,-1):
        newer=sentences[index]
        if control:control.checkpoint()
        if len(newer) < 4:
            continue
        new_text = ' '.join(w.text for w in newer)
        raw_nt = _tokens(new_text)
        lead_retake=_retake_offset(tuple(raw_nt))
        nt = raw_nt[lead_retake:] if lead_retake else raw_nt
        # A standalone instruction such as "deixa eu refazer" is a bridge,
        # never speech content eligible for deletion.
        if lead_retake and len(nt)<4:
            continue
        if not _core(nt):
            continue
        new_start, new_end = newer[0].start, newer[-1].end
        if any(right.start < left.end - .03 for left,right in zip(newer,newer[1:])):
            protected.append('timestamps de palavras sobrepostos ou fora de ordem'); continue
        # Search nearby prior utterances plus suffixes of long attempts. This
        # keeps distinctive earlier information outside a proposed cut.
        for back in range(1, min(index, 5) + 1):
            if control:control.checkpoint()
            older = sentences[index-back]
            candidates_before=len(found)
            old_start, old_end = older[0].start, older[-1].end
            old_text_for_context=' '.join(word.text for word in older)
            before_old=(' '.join(word.text for word in sentences[index-back-1])
                        if index-back>0 else '')
            after_new=(' '.join(word.text for word in sentences[index+1])
                       if index+1<len(sentences) else '')
            old_irony=analyze_irony(old_text_for_context,previous=before_old,
                                    following=new_text)
            new_irony=analyze_irony(new_text,previous=old_text_for_context,
                                    following=after_new)
            if old_irony['suspected'] or new_irony['suspected']:
                cues=old_irony['evidence'] if old_irony['suspected'] else new_irony['evidence']
                protected.append('possíveis sinais de ironia/contraste; tentativa preservada para revisão: '
                                 + '; '.join(cues[:2]))
                continue
            if any(right.start < left.end - .03 for left,right in zip(older,older[1:])):
                protected.append('timestamps de palavras sobrepostos ou fora de ordem'); continue
            gap = new_start - old_end
            retake_bridge=bool(lead_retake or any(sentence_retake[index-back+1:index]))
            anchored_pause=any(p0 <= new_start and p1 >= old_end and p1-p0 >= .22
                               for p0,p1 in pause_spans)
            new_prefix=tuple(nt[:3])
            prior_tokens=_tokens(' '.join(word.text for word in older))
            repeated_restart=any(new_prefix[:len(prefix)]==prefix and
                any(tuple(prior_tokens[position:position+len(prefix)])==prefix
                    for position in range(max(0,len(prior_tokens)-48),len(prior_tokens)))
                for prefix in _RESTART_PREFIXES)
            explicit_restart=bool(re.match(
                r'\s*(?:no vídeo|no video|na verdade|ou melhor|corrigindo|quer dizer|vamos de novo)',
                new_text,flags=re.IGNORECASE))
            no_pause_restart=gap >= -.05 and gap <= 1.25 and (explicit_restart or repeated_restart)
            max_distance=70. if retake_bridge else 35.
            if (not anchored_pause and not no_pause_restart and not retake_bridge) or new_start-old_start > max_distance:
                continue
            # If speaker metadata exists, a change of speaker is a hard
            # boundary. Missing speaker labels do not invent identity.
            old_speakers={word.speaker for word in older if word.speaker is not None}
            new_speakers={word.speaker for word in newer if word.speaker is not None}
            if ((len(old_speakers)>1 or len(new_speakers)>1) or
                    (old_speakers and new_speakers and old_speakers.isdisjoint(new_speakers))):
                protected.append('locutor diferente'); continue
            comparison_text=' '.join(nt)
            new_signature=_phrase_signature(comparison_text)
            whole_old_signature=_phrase_signature(' '.join(word.text for word in older))
            repair=_repair_suffix(nt)
            whole_old_tokens=list(whole_old_signature.tokens)
            exact_alignment=SequenceMatcher(None,_sequence_tokens(whole_old_tokens),
                _sequence_tokens(nt),autojunk=False).ratio()
            whole_complete=bool(re.search(r'[.!?]["”\']?$',older[-1].text))
            explicit_correction=bool(repair or any(value in new_text.casefold() for value in _CUES))
            if exact_alignment>=.98 and whole_complete and not explicit_correction:
                protected.append('repetição integral pode ser intencional')
                continue
            repair_signature=None
            repair_targeted=False
            correction=''
            if repair:
                _,repair_tokens,correction=repair
                repair_signature=_phrase_signature(' '.join(repair_tokens))
                # A correction cue only overrides a critical mismatch when
                # the corrected clause still carries the old topic/action.
                # This prevents "na verdade" from acting as a universal pass.
                old_noncritical=set(whole_old_signature.concepts)-set(whole_old_signature.numbers)-set(_NEGATION)
                suffix_overlap=(len(old_noncritical & set(repair_signature.concepts)) /
                                max(1,len(old_noncritical)))
                repair_targeted=suffix_overlap>=.55
            whole_mismatch=[]
            if whole_old_signature.negation!=new_signature.negation:whole_mismatch.append('negação')
            if (whole_old_signature.numbers and new_signature.numbers and
                whole_old_signature.numbers!=new_signature.numbers):whole_mismatch.append('números')
            if whole_old_signature.conditions!=new_signature.conditions:whole_mismatch.append('condição')
            if whole_old_signature.modality!=new_signature.modality:whole_mismatch.append('modalidade')
            if (whole_old_signature.time_references and new_signature.time_references and
                whole_old_signature.time_references!=new_signature.time_references):
                whole_mismatch.append('referência temporal')
            if (whole_old_signature.subjects and new_signature.subjects and
                    whole_old_signature.subjects.isdisjoint(new_signature.subjects)):
                whole_mismatch.append('sujeito diferente')
            if whole_old_signature.question!=new_signature.question:
                whole_mismatch.append('pergunta/resposta')
            old_whole_names,new_whole_names=_important_names(older),_important_names(newer)
            if old_whole_names and new_whole_names and old_whole_names!=new_whole_names:
                whole_mismatch.append('entidades')
            old_whole_lemmas={_lemma(token) for token in _tokens(' '.join(w.text for w in older))}
            new_whole_lemmas={_lemma(token) for token in nt}
            if any(pair <= (old_whole_lemmas|new_whole_lemmas) and
                   (pair&old_whole_lemmas)!=(pair&new_whole_lemmas)
                   for pair in ({'instalar','desinstalar'},{'ativar','desativar'},
                                {'conectar','desconectar'},{'permitir','impedir'})):
                whole_mismatch.append('ação oposta')
            if whole_mismatch and not repair:
                protected.append('divergência crítica na tentativa: '+', '.join(whole_mismatch))
                continue
            # Each long previous utterance is searched by useful suffix windows
            # as well as whole utterance; no unrelated prefix is discarded.
            starts={0}
            for window in (6,12,24,48):
                if len(older)>window: starts.add(len(older)-window)
            for suffix_start in sorted(starts):
                prior=older[suffix_start:]
                old_text=' '.join(w.text for w in prior)
                ot=_tokens(old_text)
                if len(ot)<3: continue
                old_signature=_phrase_signature(old_text)
                old_lemmas,new_lemmas={_lemma(t) for t in ot},{_lemma(t) for t in nt}
                old_emphasis=_repeated_emphasis(ot)
                new_emphasis=_repeated_emphasis(nt)
                if any(count>new_emphasis[word] for word,count in old_emphasis.items()):
                    protected.append('ênfase repetida preservada')
                    continue
                critical=[]
                if old_signature.negation!=new_signature.negation: critical.append('negação')
                if old_signature.numbers and new_signature.numbers and old_signature.numbers!=new_signature.numbers: critical.append('números')
                if old_signature.conditions!=new_signature.conditions: critical.append('condição')
                if old_signature.modality!=new_signature.modality: critical.append('modalidade')
                if (old_signature.time_references and new_signature.time_references and
                    old_signature.time_references!=new_signature.time_references):
                    critical.append('referência temporal')
                if (old_signature.subjects and new_signature.subjects and
                        old_signature.subjects.isdisjoint(new_signature.subjects)):
                    critical.append('sujeito diferente')
                if old_signature.question!=new_signature.question:
                    critical.append('pergunta/resposta')
                old_names,new_names=_important_names(prior),_important_names(newer)
                if old_names and new_names and old_names!=new_names: critical.append('entidades')
                opposites=({'instalar','desinstalar'},{'ativar','desativar'},
                           {'conectar','desconectar'},{'permitir','impedir'})
                if any(pair <= (old_lemmas|new_lemmas) and
                       (pair&old_lemmas)!=(pair&new_lemmas) for pair in opposites):
                    critical.append('ação oposta')
                if critical and not repair:
                    protected.append('divergência crítica: '+', '.join(critical)); continue
                if critical and repair and not repair_targeted:
                    protected.append('correção explícita sem alvo temático seguro'); continue
                if (nt and nt[0] in _CONTINUATION) or any(token in _ADDITIVE for token in nt):
                    protected.append('continuidade ou complemento da fala'); continue
                overlap=_weighted_overlap(ot,nt)
                left,right=_sequence_tokens(ot),_sequence_tokens(nt)
                seq=SequenceMatcher(None,left,right,autojunk=False).ratio()
                ngrams=_ngram_overlap(ot,nt)
                rapid=_rapidfuzz_available()
                fuzzy=float(rapid(' '.join(left),' '.join(right)))/100 if rapid else seq
                cue=(bool(repair) or lead_retake>0 or retake_bridge or
                     any(value in new_text.casefold() for value in _CUES))
                first_incomplete=not re.search(r'[.!?]["”\']?$',prior[-1].text)
                newer_complete=bool(re.search(r'[.!?]["”\']?$',newer[-1].text)) or len(nt)>=7
                if seq>=.98 and not first_incomplete and not cue:
                    protected.append('repetição integral pode ser intencional'); continue
                old_core,new_core=_core(ot),_core(nt)
                if repair and repair_signature:
                    corrected=set(repair_signature.concepts)
                    if critical:
                        old_core-=_number_concepts(old_signature.numbers)|set(_NEGATION)
                        prefix_end=repair[0]-len(correction.split())
                        new_core-=_number_concepts(_numbers(nt[:prefix_end]))
                        new_core-=set(_NEGATION)
                    new_core.update(corrected)
                covered=len(old_core&new_core)/max(1,len(old_core))
                distinct=old_core-new_core
                enough=(overlap>=.62 and max(seq,fuzzy)>=.35 and ngrams>=.28 and
                        covered>=.75 and newer_complete and not distinct)
                if not enough or not (cue or first_incomplete or (overlap>=.86 and max(seq,fuzzy)>=.62)):
                    if overlap>=.3: protected.append('conteúdo relacionado, mas evidência insuficiente para excluir')
                    continue
                candidate_start=prior[0].start
                relative_start=max(0.,candidate_start-clip.start)
                relative_end=max(relative_start,old_end-clip.start)
                if relative_end-relative_start<.04: continue
                flags=(tuple(['marcador de correção explícita']+
                             ['divergência: '+flag for flag in critical]) if repair else
                       tuple('divergência: '+flag for flag in critical))
                individual=bool(repair or critical)
                reason=('Autocorreção explícita identificada; exige aprovação individual.' if individual else
                        'Reformulação próxima; a versão posterior cobre o conteúdo distintivo da tentativa.')
                evidence=(f'pausa/reinício {max(0.,gap):.2f}s',f'cobertura direcional {covered:.0%}',
                          f'alinhamento {max(seq,fuzzy):.0%}',f'n-gramas {ngrams:.0%}',
                          'busca por sufixo da tentativa anterior' if suffix_start else 'comparação do trecho anterior')
                if retake_bridge:evidence+=('comando de regravação entre tentativas',)
                if repair:evidence+=(f'marcador de correção: {correction}',)
                found.append(CutCandidate(clip.id,relative_start,relative_end,reason,evidence,
                    min(96,68+covered*20+seq*8),'context',
                    f'ctx:{clip.id}:{round(candidate_start*1000)}:{round(old_end*1000)}',flags,individual))
                break
            if len(found)>candidates_before:
                break
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
        raw_probability=item.get('probability')
        try:
            probability=.5 if raw_probability is None else float(raw_probability)
        except (TypeError,ValueError):
            probability=0.
        if is_filler and end-start <= 1.2 and probability >= .25:
            found.append(CutCandidate(clip.id,max(0,start-clip.start),min(clip.end-clip.start,end-clip.start),
                'Hesitação lexical isolada com timestamp confirmado.',(text,),88,'filler',
                f'fill:{clip.id}:{round(start*1000)}:{round(end*1000)}'))
        try:
            raw_probability=item.get('probability')
            probability=.5 if raw_probability is None else float(raw_probability)
        except (TypeError,ValueError):
            probability=0.
        clean.append((normalized,start,end,text,probability))
    # Remove only earlier items in an adjacent stutter; preserve the final
    # occurrence and do not treat syntactic "é", "não", "tipo" or "né" as filler.
    for i in range(len(clean)-1):
        token,start,end,text,_probability=clean[i]
        nxt,nstart,nend,_,_next_probability=clean[i+1]
        if (token==nxt and nstart-end <= .28
                and token not in _PRESERVED_REPEAT_WORDS):
            found.append(CutCandidate(clip.id,max(0,start-clip.start),min(clip.end-clip.start,end-clip.start),
                'Repetição adjacente da mesma palavra; ocorrência seguinte preservada.',
                (text, clean[i+1][3]),82,'filler',f'rep:{clip.id}:{round(start*1000)}'))
    # A short repeated speech starter is a common restart even when the ASR
    # emits no separate sentence ("eu vou, eu vou mostrar"). Require a known
    # starter, a restart mark, a close boundary and a continuation after the
    # second copy; this deliberately leaves rhetorical repetitions intact.
    for length in (2, 3):
        last_start=len(clean)-2*length
        for first in range(max(0,last_start+1)):
            second=first+length
            phrase=tuple(clean[first+offset][0] for offset in range(length))
            if phrase not in _RESTART_PREFIXES:
                continue
            if any(clean[second+offset][0]!=phrase[offset] for offset in range(length)):
                continue
            if second+length>=len(clean):
                continue
            start,end=clean[first][1],clean[second-1][2]
            next_start=clean[second][1]
            marker=clean[second-1][3]
            if (not re.search(r'[,;:…]\s*$|\.{2,}\s*$|[—–-]\s*$',marker)
                    or next_start-end < -.05 or next_start-end > .65
                    or any(clean[index][4] < .4
                           for index in range(first,second+length))):
                continue
            evidence=' '.join(clean[index][3] for index in range(first,second))
            found.append(CutCandidate(
                clip.id, max(0.,start-clip.start), min(clip.end-clip.start,end-clip.start),
                'Reinício literal de uma abertura de fala; a repetição seguinte continua a frase.',
                (evidence, 'abertura repetida com pontuação de reinício'), 78, 'filler',
                f'restart:{clip.id}:{round(start*1000)}:{round(end*1000)}'))
    return [c for c in found if c.end-c.start >= .025]


def _merge_candidates(candidates: list[CutCandidate]) -> tuple[list[CutCandidate], int]:
    """Deduplicate exact proposals but never fuse distinct overlapping cuts.

    Overlap must remain visible to reviewers and is tagged so the UI can keep
    it out of bulk approval. Applying two conflicting cuts is rejected later.
    """
    ordered=sorted(candidates,key=lambda c:(c.clip_id,c.start,c.end,c.source_module,c.id))
    unique=[];seen=set()
    for candidate in ordered:
        key=(candidate.clip_id,round(candidate.start,6),round(candidate.end,6),candidate.source_module)
        if key in seen:continue
        seen.add(key);unique.append(candidate)
    conflict_indices=set();pairs=0
    for index,left in enumerate(unique):
        for other in range(index+1,len(unique)):
            right=unique[other]
            if right.clip_id!=left.clip_id:break
            if right.start >= left.end-.02:break
            if min(left.end,right.end)-max(left.start,right.start)>.02:
                conflict_indices.update((index,other));pairs+=1
    result=[replace(candidate,risk_flags=tuple(dict.fromkeys(candidate.risk_flags+
                (('overlaps another module suggestion',) if index in conflict_indices else ())))
                ) for index,candidate in enumerate(unique)]
    return result,pairs


def analyze_automatic_cleanup(clips, options: EditOptions, *, known_words=None,
                              analyze: Callable=run_analysis, progress=None,
                              control=None, stage=None, ai_options=None) -> EditPlan:
    """Run selected modules, sharing existing cached Silero and Parakeet data.

    ``silence`` is the existing Silero route; ``transcribe`` is the existing
    Parakeet ONNX route. This function never calls Qwen or a generative model.
    """
    started=time.perf_counter(); plan=EditPlan(options)
    feature_cache_before=(_token_cache.cache_info(),_lemma.cache_info(),_phrase_signature.cache_info())
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
        if stage: stage('Parakeet TDT v3 · transcrição necessária')
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
    lexical_seconds=0.;filler_seconds=0.;context_seconds=0.;planning_started=time.perf_counter()
    for clip in clips:
        report=reports_by_id.setdefault(clip.id,{'clip_id':clip.id,'title':clip.title,'words':[],'speech':[],'suggestions':[]})
        if not report.get('words') and clip.id in known_words:
            report['words']=list(known_words[clip.id])
        if options.remove_silences:
            for finding in vad_data.get('suggestions',[]):
                if finding.get('clip_id')==clip.id:
                    source_module=('speedup' if finding.get('type')=='speedup' else 'silence')
                    plan.candidates.append(CutCandidate(clip.id,max(0,float(finding['a'])),
                        min(clip.end-clip.start,float(finding['b'])),
                        str(finding.get('note') or 'Silero detectou ausência de fala; margens aplicadas.'),
                        ('região sem fala detectada por Silero',),95,source_module,
                        f'sil:{clip.id}:{round(float(finding["a"])*1000)}:{round(float(finding["b"])*1000)}',
                        speed=float(finding.get('speed',2.0)) if source_module=='speedup' else None))
        if options.remove_fillers:
            lexical_started=time.perf_counter()
            plan.candidates.extend(_filler_candidates(clip,report))
            elapsed=time.perf_counter()-lexical_started
            filler_seconds+=elapsed;lexical_seconds+=elapsed
        if options.analyze_context:
            pauses=[]
            speech=sorted(report.get('speech',[]),key=lambda s:float(s['start']))
            for left,right in zip(speech,speech[1:]):
                if float(right['start'])-float(left['end']) >= .22:
                    pauses.append((clip.start+float(left['end']),clip.start+float(right['start'])))
            lexical_started=time.perf_counter()
            context,protected=_context_candidates(clip,report,pauses,control=control)
            elapsed=time.perf_counter()-lexical_started
            context_seconds+=elapsed;lexical_seconds+=elapsed
            plan.candidates.extend(context)
            plan.stats.setdefault('context_protected',[]).extend(
                {'clip_id':clip.id,'reason':reason} for reason in protected)
        plan.reports.append(report)
    plan.candidates,overlaps=_merge_candidates(plan.candidates)
    planning_seconds=time.perf_counter()-planning_started
    plan.metrics={'vad_pipeline_seconds':round(vad_seconds,4),
                  'transcription_pipeline_seconds':round(text_seconds,4),
                  'text_rules_seconds':round(lexical_seconds,4),
                  'context_rules_seconds':round(context_seconds,4),
                  'filler_rules_seconds':round(filler_seconds,4),
                  'cut_planning_seconds':round(max(0.,planning_seconds-lexical_seconds),4),
                  'analysis_seconds':round(time.perf_counter()-started,4),
                  'vad_pipeline_peak_rss_mib':round(vad_peak,2) if vad_peak is not None else None,
                  'transcription_pipeline_peak_rss_mib':round(text_peak,2) if text_peak is not None else None,
                  'cache_hits':int(vad_data.get('cache_hits',0))+int(text_data.get('cache_hits',0)),
                  'cache_misses':int(vad_data.get('cache_misses',0))+int(text_data.get('cache_misses',0)),
                  'stages':list(vad_data.get('stages',[]))+list(text_data.get('stages',[]))}
    plan.stats.update({'vad_calls':int(needs_vad),'transcription_calls':int(bool(needs_text and uncovered)),
                       'candidate_count':len(plan.candidates),'overlap_merges':0,
                       'overlap_conflicts':overlaps,
                       'silence_candidates':sum('silence' in c.source_module for c in plan.candidates),
                       'speedup_candidates':sum('speedup' in c.source_module for c in plan.candidates),
                       'filler_candidates':sum('filler' in c.source_module for c in plan.candidates),
                       'context_candidates':sum('context' in c.source_module for c in plan.candidates)})
    feature_cache_after=(_token_cache.cache_info(),_lemma.cache_info(),_phrase_signature.cache_info())
    plan.stats['text_feature_cache_hits']=sum(after.hits-before.hits for before,after in zip(feature_cache_before,feature_cache_after))
    plan.stats['text_feature_cache_misses']=sum(after.misses-before.misses for before,after in zip(feature_cache_before,feature_cache_after))
    return plan
