"""Small, local ASR vocabulary assembled from trusted project transcripts.

The vocabulary is only a Faster-Whisper hint. It never edits transcript text,
changes timestamps, or becomes evidence for an automatic cut.
"""
from __future__ import annotations

from collections import Counter
import re
import unicodedata


BASE_HOTWORDS = (
    'Berofel Studio', 'Faster-Whisper', 'Silero', 'FFmpeg',
    'timeline', 'transcrição', 'legendas',
)

_WORD = re.compile(r"^[\wÀ-ÿ][\wÀ-ÿ'’-]*$", re.UNICODE)
_COMMON = frozenset('a ao aos aquela aquelas aquele aqueles aqui aquilo as até com como da das de dela delas dele deles depois do dos e ela elas ele eles em entre era essa essas esse esses esta estas este estes eu foi foram há hoje isso isto já lhe lhes mais mas me meu meus minha minhas muito na nas nem no nos nossa nossas nosso nossos o os ou para pela pelas pelo pelos por porque que se sem ser seu seus sua suas também tem tendo ter teu teus tu tua tuas um uma umas uns você vocês vos'.split())


def _clean(text: object) -> str:
    value=unicodedata.normalize('NFC',unicodedata.normalize('NFKC',str(text or '')))
    return value.strip().strip('.,;:!?()[]{}"“”‘’')


def _confidence(item: dict) -> float:
    try:
        return max(0.,min(1.,float(item.get('probability',0.))))
    except (TypeError,ValueError):
        return 0.


def project_hotwords(transcripts, base=BASE_HOTWORDS, *, confirmed_texts=(), max_terms=24,
                     max_dynamic_chars=220) -> str:
    """Return bounded project terms suitable for Faster-Whisper's hotwords.

    Terms from user-authored/edited captions are trusted. ASR-derived terms
    must recur across sources or over a wide time span, preventing a single
    transcription error from immediately teaching itself back to Whisper.
    Low-confidence words and common function words are ignored.
    """
    counts=Counter()
    positions={}
    phrases={}
    previous_by_source={}
    runs_by_source={}

    def flush_run(source):
        run=runs_by_source.pop(source,[])
        if len(run)>=2:
            phrase=' '.join(item[0] for item in run)
            if len(phrase)<=48:
                data=phrases.setdefault(phrase,{'count':0,'sources':set(),
                                                'first':run[0][1],'last':run[-1][2]})
                data['count']+=1
                data['sources'].add(source)
                data['first']=min(data['first'],run[0][1])
                data['last']=max(data['last'],run[-1][2])

    for raw in transcripts or ():
        if not isinstance(raw,dict):
            continue
        raw_text=str(raw.get('text') or '').strip()
        token=_clean(raw_text)
        probability=_confidence(raw)
        try:
            start=float(raw.get('source_start',raw.get('start',0.)))
            end=float(raw.get('source_end',raw.get('end',start)))
        except (TypeError,ValueError):
            continue
        if not token or not _WORD.fullmatch(token) or end<start:
            continue
        folded=token.casefold()
        if len(folded)<4 or folded in _COMMON or folded.isnumeric():
            flush_run(str(raw.get('source') or ''))
            continue
        source=str(raw.get('source') or '')
        sentence_end=bool(re.search(r'[.!?]["”\']?\s*$',raw_text))
        if probability>=.70:
            counts[folded]+=1
            location=positions.setdefault(folded,{'sources':set(),'first':start,'last':end})
            location['sources'].add(source)
            location['first']=min(location['first'],start)
            location['last']=max(location['last'],end)
        previous=previous_by_source.get(source)
        delta=start-previous['end'] if previous else None

        # Keep capitalized phrases without constructing a second per-word copy
        # of the project's transcript. Transcript reports are time ordered;
        # negative gaps intentionally break the phrase.
        eligible=probability>=.78 and token[:1].isupper()
        run=runs_by_source.get(source,[])
        adjacent=(run and previous and 0<=delta<=.65 and not previous['sentence_end'])
        if eligible and (not run or adjacent):
            run.append((token,start,end))
            runs_by_source[source]=run
        else:
            flush_run(source)
            if eligible:
                runs_by_source[source]=[(token,start,end)]
        previous_by_source[source]={'end':end,'sentence_end':sentence_end}
    for source in tuple(runs_by_source):
        flush_run(source)

    candidates=[]
    for folded,count in counts.items():
        location=positions[folded]
        independent=(len(location['sources'])>=2 or location['last']-location['first']>=30.)
        if count>=2 and independent:
            candidates.append((count,folded))
    for phrase,data in phrases.items():
        independent=(len(data['sources'])>=2 or data['last']-data['first']>=30.)
        if data['count']>=2 and independent:
            candidates.append((data['count']*2,phrase))

    # Text in manual captions and captions edited after auto-generation is
    # explicit user confirmation; it can seed the dictionary immediately.
    confirmed=Counter()
    confirmed_spelling={}
    for text in confirmed_texts or ():
        clean_text=unicodedata.normalize('NFC',unicodedata.normalize('NFKC',str(text or '')))
        tokens=[_clean(token) for token in re.findall(r"[\wÀ-ÿ][\wÀ-ÿ'’-]*",clean_text)]
        tokens=[token for token in tokens if len(token)>=4 and token.casefold() not in _COMMON]
        for token in tokens:
            folded=token.casefold()
            confirmed[folded]+=1
            confirmed_spelling.setdefault(folded,token)
        for index in range(len(tokens)-1):
            if tokens[index][:1].isupper() and tokens[index+1][:1].isupper():
                phrase=f'{tokens[index]} {tokens[index+1]}'
                if len(phrase)<=48:
                    confirmed[phrase.casefold()]+=2
                    confirmed_spelling.setdefault(phrase.casefold(),phrase)
    candidates.extend((1000+count,confirmed_spelling[term])
                      for term,count in confirmed.items())
    candidates.sort(key=lambda item:(-item[0],item[1].casefold()))

    fixed=[];seen=set()
    for value in base:
        clean=_clean(value)
        if clean and clean.casefold() not in seen:
            fixed.append(clean);seen.add(clean.casefold())
    dynamic=[];used_chars=0
    for _,value in candidates:
        folded=value.casefold()
        if folded in seen or len(dynamic)>=max_terms:
            continue
        extra=len(value)+2
        if used_chars+extra>max_dynamic_chars:
            continue
        dynamic.append(value);seen.add(folded);used_chars+=extra
    return ', '.join(fixed+dynamic)


def confirmed_caption_texts(project) -> tuple[str,...]:
    """Collect only captions typed or changed by the user."""
    texts=[]
    for clip in getattr(project,'clips',()):
        if getattr(clip,'kind','')!='text':
            continue
        text=str(getattr(clip,'text','') or '').strip()
        origin=str(getattr(clip,'generated_by','') or '')
        generated=str(getattr(clip,'caption_generated_text','') or '').strip()
        if text and (origin=='manual_caption' or
                     (origin=='auto_caption' and text!=generated)):
            texts.append(text)
    return tuple(texts)
