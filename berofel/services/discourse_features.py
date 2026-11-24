"""Lightweight, deterministic discourse cues shared by cleanup and clipper.

These features are editorial evidence, never ground truth about intent. The
module uses only transcript text already present in the project and Python's
standard library; it loads no ASR, language model, or network resource.
"""
from __future__ import annotations

from collections import Counter
import re
import unicodedata
from typing import Mapping, Sequence


_TOKEN = re.compile(r"[\wÀ-ÿ]+(?:['’][\wÀ-ÿ]+)?", re.UNICODE)
_STOP = frozenset("""
    a ao aos aquela aquele aquilo as até ate com como da das de dela dele
    deles demais do dos e ela elas ele eles em essa esse esta esta está este
    eu foi foram isso isto já ja lhe mais mas me mesmo menos meu minha muito
    na nas nem no nos nossa nosso o os ou para pela pelo por porque qual
    quando que quem se sem ser seu sua também tambem tem te um uma você voce
    vocês voces vou vai vamos é e são sao está está estão estao era eram foi
    hoje agora então entao aí ai lá la
""".split())
_POSITIVE = frozenset("""
    otimo otima otimos otimas excelente perfeito perfeita maravilhoso
    maravilhosa incrivel incriveis fantastico fantastica sensacional
    lindo linda adorei amei parabens parabéns genial sucesso funciona funcionou
    resolveu certo bom boa legal show
""".split())
_NEGATIVE = frozenset("""
    péssimo pessimo pessima horrivel horrível ruim errado errada falhou
    falhar quebrou travou travado travada problema problemas erro erros
    impossível impossivel atrasado atrasada perdeu perdeu perda bug caiu
    trava travou travaram travando
    queima queimou lento lenta frustrante desastre falha difícil dificil
""".split())
_IRONY_MARKERS = (
    (('so', 'que', 'nao'), 'marcador explícito “só que não”', .85),
    (('ironia',), 'menção explícita a ironia', .90),
    (('sarcasmo',), 'menção explícita a sarcasmo', .90),
    (('aham', 'sei'), 'resposta convencional potencialmente irônica', .58),
    (('confia',), '“confia” pode funcionar como marcador de ironia', .52),
)
_CONTRAST = frozenset(('mas porém porem só so embora apesar entretanto contudo'.split()))
_RESOLUTION = frozenset("""
    resolveu resolvido resolveu-se funcionou funcionando consegui conseguiu
    conseguimos deu certo corrigido corrigida pronto finalmente
""".split())
_QUESTION_START = frozenset(('quem quando onde como qual quanto'.split()))
_REVEAL_START = frozenset(('descobri descobrimos percebi percebemos resultado segredo afinal'.split()))
_CONCLUSION_START = frozenset(('resumindo concluindo conclusão conclusao enfim finalmente'.split()))
_ANSWER_START = frozenset(('porque por isso então entao a resposta isso significa quer dizer'.split()))


def normalize_tokens(text: object) -> tuple[str, ...]:
    value = unicodedata.normalize('NFKD', str(text or '').casefold())
    value = ''.join(char for char in value if not unicodedata.combining(char))
    return tuple(_TOKEN.findall(value))


def content_terms(text: object) -> Counter[str]:
    return Counter(token for token in normalize_tokens(text)
                   if len(token) > 2 and token not in _STOP and not token.isdigit())


def _polarity(tokens: Sequence[str]) -> int:
    positive = sum(token in _POSITIVE for token in tokens)
    negative = sum(token in _NEGATIVE for token in tokens)
    return (1 if positive > negative else -1 if negative > positive else 0)


def analyze_irony(text: object, *, previous: object = '', following: object = '') -> dict:
    """Return possible irony cues, not a semantic verdict or probability.

    A single positive/negative word is deliberately insufficient. Contextual
    incongruity, an explicit marker, or multiple independent style cues are
    required before ``suspected`` is set.
    """
    raw = str(text or '')
    tokens = normalize_tokens(raw)
    prev_tokens = normalize_tokens(previous)
    next_tokens = normalize_tokens(following)
    evidence: list[str] = []
    score = 0.0
    explicit = False
    for pattern, label, weight in _IRONY_MARKERS:
        if any(tokens[i:i + len(pattern)] == pattern
               for i in range(max(0, len(tokens) - len(pattern) + 1))):
            evidence.append(label)
            score = max(score, weight)
            explicit = explicit or weight >= .8

    own_positive = any(token in _POSITIVE for token in tokens)
    own_negative = any(token in _NEGATIVE for token in tokens)
    marked_contrast = bool(set(tokens) & _CONTRAST) or bool(re.search(r'[:,…—]', raw))
    if own_positive and own_negative and marked_contrast:
        evidence.append('avaliação positiva e resultado negativo na mesma fala')
        evidence.append('elogio junto de falha ou resultado adverso')
        score += .56

    surrounding = prev_tokens + next_tokens
    surrounding_polarity = _polarity(surrounding)
    current_polarity = _polarity(tokens)
    contextual_clash = ((own_positive and surrounding_polarity < 0) or
                        (own_negative and surrounding_polarity > 0))
    if ((current_polarity and surrounding_polarity and current_polarity != surrounding_polarity)
            or contextual_clash):
        evidence.append('polaridade da fala contrasta com o contexto vizinho')
        score += .29

    quoted = bool(re.search(r'[“\"\']\s*[^“\"\']{1,50}\s*[”\"\']', raw))
    laughter = any(token in {'haha', 'hahaha', 'kkk', 'rs'} for token in tokens)
    exaggerated = any(token in {'absurdo', 'perfeito', 'maravilha', 'fantastico',
                                'incrivel', 'sensacional'} for token in tokens)
    if quoted and surrounding_polarity < 0 and own_positive:
        evidence.append('expressão positiva entre aspas após contexto negativo')
        score += .18
    if laughter and surrounding_polarity < 0:
        evidence.append('marcador de riso junto de contexto negativo')
        score += .20
    if exaggerated and own_negative:
        evidence.append('intensificador positivo exagerado junto de evento negativo')
        score += .15
    if raw.count('!') >= 2 and own_positive and surrounding_polarity < 0:
        evidence.append('ênfase gráfica positiva após contexto negativo')
        score += .10

    # A stated resolution often explains a polarity change sincerely. Do not
    # negate an explicit irony marker, but reduce this common false-positive.
    if not explicit and set(tokens) & _RESOLUTION:
        score = max(0.0, score - .30)
        evidence.append('marcador de resolução reduz suspeita de ironia')

    score = min(.98, score)
    independent = len(set(evidence))
    suspected = explicit or (score >= .55 and independent >= 2)
    return {
        'score': round(score, 3),
        'suspected': suspected,
        'evidence': tuple(evidence),
        'note': 'sinais heurísticos; intenção irônica não é confirmada pelo texto',
    }


def discourse_role(text: object) -> str:
    """Classify common conversational function from explicit lexical cues."""
    value = ' '.join(normalize_tokens(text))
    tokens = normalize_tokens(text)
    if ('?' in str(text) or (tokens and tokens[0] in _QUESTION_START) or
            tokens[:2] == ('por', 'que')):
        return 'question'
    if tokens and tokens[0] in _REVEAL_START:
        return 'reveal'
    if tokens and tokens[0] in _CONCLUSION_START:
        return 'conclusion'
    if tokens and tokens[0] in _ANSWER_START:
        return 'answer'
    if re.search(r'\b(na verdade|descobri|o segredo|o resultado|aconteceu)\b', value):
        return 'reveal'
    return 'unspecified'


def _weighted_jaccard(left: Counter[str], right: Counter[str]) -> float:
    keys = left.keys() | right.keys()
    if not keys:
        return 0.0
    # Counts are capped so repeated filler or a frequently repeated topic word
    # cannot overwhelm the rest of the local vocabulary.
    intersection = sum(min(min(3, left[k]), min(3, right[k])) for k in keys)
    union = sum(max(min(3, left[k]), min(3, right[k])) for k in keys)
    return intersection / max(1, union)


def text_tiling_boundaries(turns: Sequence[Mapping], radius: int = 2) -> dict[int, float]:
    """TextTiling-inspired lexical-cohesion valleys between transcript turns.

    Returns ``boundary_index -> heuristic shift score``. Index ``i`` denotes
    the boundary before turn ``i``. This block comparison uses existing
    sentences/turns, not fixed word windows, and is intentionally a cue rather
    than a hard segmentation decision.
    """
    if len(turns) < 3:
        return {}
    term_counts = [content_terms(turn.get('text', '')) for turn in turns]
    result: dict[int, float] = {}
    for index in range(1, len(turns)):
        left = Counter()
        right = Counter()
        for row in term_counts[max(0, index - radius):index]:
            left.update(row)
        for row in term_counts[index:min(len(turns), index + radius)]:
            right.update(row)
        left_n, right_n = sum(left.values()), sum(right.values())
        if min(left_n, right_n) < 3:
            continue
        cross = _weighted_jaccard(left, right)
        left_pairs = [_weighted_jaccard(term_counts[j - 1], term_counts[j])
                      for j in range(max(1, index - radius + 1), index)
                      if term_counts[j - 1] and term_counts[j]]
        right_pairs = [_weighted_jaccard(term_counts[j - 1], term_counts[j])
                       for j in range(index + 1, min(len(turns), index + radius))
                       if term_counts[j - 1] and term_counts[j]]
        internal = (sum(left_pairs + right_pairs) / len(left_pairs + right_pairs)
                    if left_pairs or right_pairs else cross)
        marker_tokens = normalize_tokens(turns[index].get('text', ''))[:5]
        marker = any(marker_tokens[:len(pattern)] == pattern for pattern in (
            ('mudando', 'de', 'assunto'), ('falando', 'nisso'),
            ('por', 'outro', 'lado'), ('agora', 'sobre')))
        score = .65 * max(0.0, internal - cross) + .35 * (1.0 - cross)
        if marker:
            score = min(1.0, score + .20)
        # Sparse short talk should not invent a topic change just because two
        # neighboring sentences use different nouns.
        if cross < .12 and not marker:
            score *= .72
        result[index] = round(min(1.0, max(0.0, score)), 3)
    return result
