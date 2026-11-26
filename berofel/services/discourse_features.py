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
    maravilhosa maravilha incrivel incriveis fantastico fantastica sensacional
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
    (('aham', 'sei'), 'resposta convencional potencialmente irônica', .58),
    (('confia',), '“confia” pode funcionar como marcador de ironia', .52),
)
_IRONY_MENTION = re.compile(
    r"\b(?:(?:isso|isto)\s+(?:e|foi)|foi|era|seria|com|falando com|"
    r"estou sendo|estava sendo)\s+(?:uma\s+)?"
    r"(?:ironia|sarcasmo|ironic[oa])\b")
_IRONY_DENIAL = re.compile(
    r"\b(?:nao\s+(?:e|foi|era|estou sendo)|sem)\s+(?:uma\s+)?"
    r"(?:ironia|sarcasmo|ironic[oa])\b|\b(?:falo|estou falando)\s+serio\b")
_NEGATORS = frozenset(('nao', 'nem', 'nunca', 'jamais'))
_CONTRAST = frozenset(('mas porém porem só so embora apesar entretanto contudo'.split()))
_RESOLUTION = frozenset("""
    resolveu resolvido resolveu-se funcionou funcionando consegui conseguiu
    conseguimos deu certo corrigido corrigida pronto finalmente
""".split())
_QUESTION_START = frozenset(('quem quando onde como qual quanto'.split()))
_QUESTION_PREFIXES = (
    ('voce', 'sabia'), ('ja', 'imaginou'), ('sera', 'que'),
    ('voce', 'concorda'), ('alguem', 'sabe'), ('tem', 'como'),
    ('pode', 'me', 'explicar'))
_REVEAL_START = frozenset(('descobri descobrimos percebi percebemos resultado segredo afinal'.split()))
_CONCLUSION_START = frozenset(('resumindo concluindo conclusão conclusao enfim finalmente'.split()))
_ANSWER_PREFIXES = (
    ('porque',), ('por', 'isso'), ('entao',), ('a', 'resposta'),
    ('isso', 'significa'), ('quer', 'dizer'))
_REACTION_PATTERNS = (
    (('nossa',), 'reação textual: “nossa”', .66),
    (('caramba',), 'reação textual: “caramba”', .72),
    (('eita',), 'reação textual: “eita”', .70),
    (('meu', 'deus'), 'reação textual: “meu Deus”', .76),
    (('nao', 'acredito'), 'reação textual de surpresa', .78),
    (('olha', 'isso'), 'chamada de atenção para um evento', .64),
    (('que', 'isso'), 'reação textual: “que isso”', .62),
    (('meu', 'amigo'), 'reação coloquial potencialmente enfática', .48),
)
_HUMOR_MARKERS = frozenset((
    'haha', 'hahaha', 'kkkk', 'kkk', 'rs', 'zoeira', 'brincadeira', 'piada', 'meme'))
_RHETORICAL_PATTERNS = (
    ('quem', 'nunca'), ('so', 'eu', 'que'), ('so', 'eu'),
    ('nao', 'e', 'possivel'), ('vai', 'me', 'dizer', 'que'),
)
_REPAIR_MARKERS = (
    ('na', 'verdade'), ('ou', 'melhor'), ('quer', 'dizer'), ('corrigindo',),
    ('pera',), ('espera',), ('vamos', 'de', 'novo'), ('falei', 'errado'),
)


def _is_negated(tokens: Sequence[str], index: int) -> bool:
    """Check a short negation scope without crossing an explicit contrast."""
    for previous in reversed(tokens[max(0, index - 3):index]):
        if previous in _CONTRAST:
            break
        if previous in _NEGATORS:
            return True
    return False


def normalize_tokens(text: object) -> tuple[str, ...]:
    value = unicodedata.normalize('NFKD', str(text or '').casefold())
    value = ''.join(char for char in value if not unicodedata.combining(char))
    return tuple(_TOKEN.findall(value))


def content_terms(text: object) -> Counter[str]:
    return Counter(token for token in normalize_tokens(text)
                   if len(token) > 2 and token not in _STOP and not token.isdigit())


def _polarity(tokens: Sequence[str]) -> int:
    positive = negative = 0
    for index, token in enumerate(tokens):
        if token not in _POSITIVE and token not in _NEGATIVE:
            continue
        # Curto escopo determinístico para “não funcionou” e “nunca foi bom”.
        negated = _is_negated(tokens, index)
        polarity = -1 if token in _NEGATIVE else 1
        if negated:
            polarity *= -1
        if polarity > 0:
            positive += 1
        else:
            negative += 1
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
    normalized = ' '.join(tokens)
    evidence: list[str] = []
    score = 0.0
    explicit = False
    denied_mention = bool(_IRONY_DENIAL.search(normalized))
    for pattern, label, weight in _IRONY_MARKERS:
        if any(tokens[i:i + len(pattern)] == pattern
               for i in range(max(0, len(tokens) - len(pattern) + 1))):
            evidence.append(label)
            score = max(score, weight)
            explicit = explicit or weight >= .8

    if _IRONY_MENTION.search(normalized) and not denied_mention:
        evidence.append('autodescrição explícita da fala como irônica/sarcástica')
        score = max(score, .82)
        explicit = True
    elif denied_mention:
        evidence.append('menção a ironia/sarcasmo negada ou fala marcada como séria')

    positive_positions: list[int] = []
    negative_positions: list[int] = []
    for index, token in enumerate(tokens):
        if token not in _POSITIVE and token not in _NEGATIVE:
            continue
        negated = _is_negated(tokens, index)
        is_positive = token in _POSITIVE
        if negated:
            is_positive = not is_positive
        (positive_positions if is_positive else negative_positions).append(index)
    own_positive = bool(positive_positions)
    own_negative = bool(negative_positions)
    marked_contrast = bool(set(tokens) & _CONTRAST) or bool(re.search(r'[:,…—]', raw))
    if own_positive and own_negative:
        evidence.append('avaliação positiva e resultado negativo na mesma fala')
        if marked_contrast:
            evidence.append('elogio junto de falha ou resultado adverso')
            score += .56
        elif min(positive_positions) < max(negative_positions):
            evidence.append('elogio antecede evento adverso, sem depender da pontuação')
            score += .42

    surrounding = prev_tokens + next_tokens
    surrounding_polarity = _polarity(surrounding)
    current_polarity = _polarity(tokens)
    contextual_clash = bool(
        surrounding_polarity < 0 and own_positive or
        surrounding_polarity > 0 and own_negative or
        current_polarity and surrounding_polarity and
        current_polarity != surrounding_polarity)
    if contextual_clash:
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

    if denied_mention and not explicit:
        score = max(0.0, score - .15)

    score = min(.98, score)
    independent = len(set(evidence))
    suspected = explicit or (score >= .55 and independent >= 2)
    return {
        'score': round(score, 3),
        'suspected': suspected,
        'evidence': tuple(evidence),
        'note': 'sinais heurísticos; intenção irônica não é confirmada pelo texto',
    }


def _contains_pattern(tokens: Sequence[str], pattern: Sequence[str]) -> bool:
    return any(tokens[index:index + len(pattern)] == tuple(pattern)
               for index in range(max(0, len(tokens) - len(pattern) + 1)))


def analyze_discourse(text: object, *, previous: object = '', following: object = '',
                      speaker_id: object = None, previous_speaker: object = None,
                      following_speaker: object = None) -> dict:
    """Collect local, explainable editorial cues for a transcript candidate.

    Known speaker changes exclude that neighbor from irony comparison. Humor,
    surprise and rhetorical-question flags remain clues, never semantic
    verdicts, cut commands or predictions of clip performance.
    """
    raw = str(text or '')
    tokens = normalize_tokens(raw)
    excluded_speakers: list[str] = []
    if (speaker_id is not None and previous_speaker is not None and
            speaker_id != previous_speaker):
        previous = ''
        excluded_speakers.append('anterior')
    if (speaker_id is not None and following_speaker is not None and
            speaker_id != following_speaker):
        following = ''
        excluded_speakers.append('posterior')

    irony = analyze_irony(raw, previous=previous, following=following)
    reaction_score = 0.0
    cues: list[str] = []
    for pattern, label, weight in _REACTION_PATTERNS:
        if _contains_pattern(tokens, pattern):
            reaction_score = max(reaction_score, weight)
            cues.append(label)

    humor_marker = any(token in _HUMOR_MARKERS for token in tokens)
    if humor_marker:
        cues.append('marcador textual de riso, brincadeira ou humor potencial')
    rhetorical_question = ('?' in raw and any(
        _contains_pattern(tokens, pattern) for pattern in _RHETORICAL_PATTERNS))
    if rhetorical_question:
        cues.append('pergunta retórica possível; conferir entonação e contexto')
    repair_marker = any(_contains_pattern(tokens, pattern)
                        for pattern in _REPAIR_MARKERS)
    if repair_marker:
        cues.append('marcador textual de correção ou reinício')
    if irony['suspected']:
        cues.extend(irony['evidence'][:3])

    humor_score = .45 if humor_marker else 0.0
    rhetorical_score = .65 if rhetorical_question else 0.0
    repair_score = .45 if repair_marker else 0.0
    editorial_score = max(
        reaction_score, humor_score, rhetorical_score, repair_score,
        float(irony['score']) if irony['suspected'] else 0.0)
    return {
        'role': discourse_role(raw),
        'irony': irony,
        'reaction_score': round(reaction_score, 3),
        'humor_marker': humor_marker,
        'rhetorical_question': rhetorical_question,
        'repair_marker': repair_marker,
        'editorial_score': round(editorial_score, 3),
        'cues': tuple(dict.fromkeys(cues)),
        'speaker_context_excluded': tuple(excluded_speakers),
        'note': 'sinais textuais locais; não confirmam intenção, humor nem potencial de viralização',
    }


def discourse_role(text: object) -> str:
    """Classify common conversational function from explicit lexical cues."""
    value = ' '.join(normalize_tokens(text))
    tokens = normalize_tokens(text)
    if ('?' in str(text) or (tokens and tokens[0] in _QUESTION_START) or
            tokens[:2] == ('por', 'que') or
            any(tokens[:len(prefix)] == prefix
                for prefix in _QUESTION_PREFIXES)):
        return 'question'
    if tokens and tokens[0] in _REVEAL_START:
        return 'reveal'
    if tokens and tokens[0] in _CONCLUSION_START:
        return 'conclusion'
    if any(tokens[:len(prefix)] == prefix for prefix in _ANSWER_PREFIXES):
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
