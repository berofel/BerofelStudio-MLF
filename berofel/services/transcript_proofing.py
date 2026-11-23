"""Local, review-only Portuguese spelling suggestions for caption text.

Hunspell data and Spylls are optional and loaded only when the user asks for
proofing. Suggestions never rewrite transcript words or timestamps by themselves.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os
from pathlib import Path
import re

from .asr_vocabulary import BASE_HOTWORDS


_WORD = re.compile(r"[\wÀ-ÿ][\wÀ-ÿ'’-]*", re.UNICODE)
_PT_BR_BASES = (
    Path(os.environ.get('LOCALAPPDATA', '')) / 'BFS' / 'dictionaries' / 'pt_BR',
    Path(r'C:\Program Files\LibreOffice\share\extensions\dict-pt\pt_BR'),
    Path(r'C:\Program Files (x86)\LibreOffice\share\extensions\dict-pt\pt_BR'),
)


@dataclass(frozen=True)
class SpellingSuggestion:
    start: int
    end: int
    word: str
    suggestions: tuple[str, ...]


def project_approved_words(project, *, max_captions: int = 500,
                           max_words: int = 500) -> frozenset[str]:
    """Return bounded product/proper-name terms confirmed in this project.

    Only technical terms (digits, internal capitals, or all-caps tokens) from
    user-authored/edited captions are added; ordinary sentence words are not
    whitelisted, so a typo in prose still remains reviewable.
    """
    approved = {word.casefold() for term in BASE_HOTWORDS for word in _WORD.findall(term)}
    count = captions = 0
    for clip in getattr(project, 'clips', ()):
        if getattr(clip, 'kind', '') != 'text':
            continue
        text = str(getattr(clip, 'text', '') or '')
        origin = str(getattr(clip, 'generated_by', '') or '')
        generated = str(getattr(clip, 'caption_generated_text', '') or '').strip()
        if not text or not (origin == 'manual_caption' or
                            (origin == 'auto_caption' and text.strip() != generated)):
            continue
        captions += 1
        if captions > max_captions:
            break
        for match in _WORD.finditer(text):
            word = match.group(0)
            has_internal_capital = any(char.isupper() for char in word[1:])
            if (len(word) >= 3 and (any(char.isdigit() for char in word)
                                    or has_internal_capital or word.isupper())):
                approved.add(word.casefold())
                count += 1
                if count >= max_words:
                    return frozenset(approved)
    return frozenset(approved)


def find_pt_br_dictionary() -> Path | None:
    """Find a Hunspell prefix; BFS_HUNSPELL_PT_BR may point to one explicitly."""
    configured = os.environ.get('BFS_HUNSPELL_PT_BR', '').strip()
    if configured:
        candidates = (Path(configured),)
    else:
        local_dir = Path(os.environ.get('LOCALAPPDATA', '')) / 'BFS' / 'dictionaries'
        try:
            versioned_dirs = (tuple(sorted(local_dir.glob('pt_BR-*'), reverse=True))
                              if local_dir.is_dir() else ())
        except OSError:
            versioned_dirs = ()
        versioned = tuple(folder / 'pt_BR' for folder in versioned_dirs)
        candidates = versioned + _PT_BR_BASES
    for base in candidates:
        try:
            if base.with_suffix('.aff').is_file() and base.with_suffix('.dic').is_file():
                return base
        except OSError:
            continue
    return None


@lru_cache(maxsize=1)
def load_pt_br_dictionary():
    """Load VERO/Hunspell lazily; return None when the optional local assets are absent."""
    base = find_pt_br_dictionary()
    if base is None:
        return None
    try:
        from spylls.hunspell import Dictionary
    except ImportError:
        return None
    try:
        return Dictionary.from_files(str(base))
    except Exception:
        return None


def spelling_suggestions(text: str, *, dictionary=None, approved_words=(),
                         max_tokens: int = 12000, max_issues: int = 40,
                         max_suggestions: int = 3) -> tuple[SpellingSuggestion, ...]:
    """Return bounded spelling candidates; this function never edits ``text``.

    ``dictionary`` follows Spylls' lookup/suggest interface, allowing the UI to
    test the path without loading a dictionary or a neural language model.
    """
    if dictionary is None:
        dictionary = load_pt_br_dictionary()
    if dictionary is None or not text:
        return ()
    approved = {str(word).casefold() for word in approved_words if word}
    results = []
    for index, match in enumerate(_WORD.finditer(str(text))):
        if index >= max_tokens or len(results) >= max_issues:
            break
        word = match.group(0)
        folded = word.casefold()
        if len(word) < 3 or folded in approved or folded.isnumeric():
            continue
        try:
            correct = dictionary.lookup(word) or (word[:1].isupper() and dictionary.lookup(folded))
        except Exception:
            continue
        if correct:
            continue
        try:
            candidates = dictionary.suggest(word)
        except Exception:
            continue
        unique = []
        seen = {folded}
        for candidate in candidates:
            candidate = str(candidate).strip()
            key = candidate.casefold()
            if not candidate or key in seen:
                continue
            seen.add(key)
            if word[:1].isupper():
                candidate = candidate[:1].upper() + candidate[1:]
            unique.append(candidate)
            if len(unique) >= max_suggestions:
                break
        if unique:
            results.append(SpellingSuggestion(match.start(), match.end(), word,
                                               tuple(unique)))
    return tuple(results)


def apply_suggestion(text: str, issue: SpellingSuggestion, replacement: str) -> str:
    """Replace exactly one reviewed word span, leaving all other text untouched."""
    current = str(text)
    if (issue.start < 0 or issue.end <= issue.start or issue.end > len(current)
            or current[issue.start:issue.end] != issue.word
            or replacement not in issue.suggestions):
        raise ValueError('A sugestão não corresponde mais ao texto selecionado.')
    return current[:issue.start] + replacement + current[issue.end:]
