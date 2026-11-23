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


def project_hotwords(transcripts, base=BASE_HOTWORDS, *, max_terms=24,
                     max_dynamic_chars=220) -> str:
    """Return bounded project terms suitable for Faster-Whisper's hotwords.

    Repeated transcript terms are preferred. A single title-cased term is
    admitted only when confidently recognized mid-sentence, avoiding most
    sentence-initial capitalization. Adjacent confident proper-name tokens
    can be kept as a short phrase. Low-confidence words and common function
    words are not fed back into ASR.
    """
    rows=[]
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
            continue
        rows.append({'text':token,'folded':folded,'probability':probability,
                     'start':start,'end':end,'source':str(raw.get('source') or ''),
                     'sentence_end':bool(re.search(r'[.!?]["”\']?\s*$',raw_text))})
    rows.sort(key=lambda row:(row['source'],row['start'],row['end']))

    counts=Counter(row['folded'] for row in rows if row['probability']>=.70)
    scores={}
    previous_by_source={}
    for row in rows:
        if row['probability']<.88 or not row['text'][:1].isupper():
            previous_by_source[row['source']]=row
            continue
        previous=previous_by_source.get(row['source'])
        if previous and row['start']-previous['end']<=.8 and not previous['sentence_end']:
            scores[row['folded']]=max(scores.get(row['folded'],0),1.0+row['probability'])
        previous_by_source[row['source']]=row

    # Preserve short consecutive capitalized names/brands as one hint phrase.
    phrases=Counter()
    run=[]
    for row in rows:
        eligible=(row['probability']>=.78 and row['text'][:1].isupper()
                  and row['folded'] not in _COMMON)
        adjacent=(run and row['source']==run[-1]['source']
                  and row['start']-run[-1]['end']<=.65
                  and not run[-1]['sentence_end'])
        if eligible and (not run or adjacent):
            run.append(row)
        else:
            if len(run)>=2:
                phrase=' '.join(item['text'] for item in run)
                if len(phrase)<=48:phrases[phrase]+=1
            run=[row] if eligible else []
    if len(run)>=2:
        phrase=' '.join(item['text'] for item in run)
        if len(phrase)<=48:phrases[phrase]+=1

    candidates=[]
    for folded,count in counts.items():
        if count>=2 or folded in scores:
            candidates.append((scores.get(folded,0)+count,folded))
    candidates.extend((count*2,phrase) for phrase,count in phrases.items())
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
