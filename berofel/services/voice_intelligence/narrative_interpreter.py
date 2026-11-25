"""Deterministic PT-BR narrative and prosody planning (no model or network).

The result is advisory metadata. It does not claim to steer Qwen: the installed
Pure C server has no validated per-sentence prosody/emotion control contract.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import re
import unicodedata

INTERPRETER_VERSION = 1

_SENTENCE_BREAK = re.compile(r"[.!?\n]+", re.UNICODE)
_WORD = re.compile(r"[\wÀ-ÿ]+", re.UNICODE)
_ABBREVIATIONS = {"dr.", "dra.", "sr.", "sra.", "av.", "etc.", "prof.", "profa."}

# Small, intentionally conservative vocabulary. A token is evidence, never a
# universal label; negation and contradictory cues reduce confidence.
_CUES = {
    "joy": ("feliz", "alegre", "conseguimos", "consegui", "adorei", "maravilhoso", "ótimo", "incrível", "funcionou", "vitória"),
    "sadness": ("triste", "saudade", "adeus", "perdi", "perda", "lamento", "sozinho", "chorar", "falhou"),
    "fear": ("medo", "assustado", "perigo", "ameaça", "passos", "silêncio", "socorro", "terror"),
    "anger": ("raiva", "furioso", "absurdo", "inaceitável", "irritado", "revoltante"),
    "surprise": ("surpresa", "surpreso", "inesperado", "espere", "como assim", "não acredito"),
    "curiosity": ("como funciona", "por que", "qual", "vamos conhecer", "descobrir", "investigar"),
    "confidence": ("garanto", "com certeza", "comprovado", "preste atenção", "precisamos resolver"),
    "humor": ("engraçado", "piada", "brincadeira", "aparentemente discordou", "que beleza"),
}
_NEGATORS = {"nao", "nunca", "jamais", "nem"}
_INTENSIFIERS = {"muito", "extremamente", "realmente", "totalmente", "demais", "tão"}
_NEGATIVE_CUES = {"perdi", "perda", "falhou", "problema", "terrível", "adeus", "medo", "perigo"}

_PROSODY = {
    "neutral": (1.00, 1.00, 1.00), "joy": (1.04, 1.15, 1.00),
    "sadness": (0.93, 0.82, 1.20), "fear": (1.02, 1.18, 1.16),
    "anger": (1.04, 1.20, 0.92), "surprise": (1.03, 1.20, 1.05),
    "curiosity": (0.99, 1.08, 1.05), "confidence": (0.98, 0.92, 1.00),
    "humor": (1.00, 1.12, 1.15),
}


def _fold(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value or "").casefold())
    return "".join(ch for ch in value if not unicodedata.combining(ch))


def _tokens(value: str) -> list[str]:
    return _WORD.findall(_fold(value))


def _sentence_spans(source: str) -> list[tuple[int, int, str]]:
    """Split at sentence punctuation while preserving exact source offsets."""
    spans: list[tuple[int, int, str]] = []
    cursor = 0
    for match in _SENTENCE_BREAK.finditer(source):
        mark = match.group()
        end = match.end()
        if mark == "\n" or "\n" in mark:
            boundary = end
        else:
            before = source[max(cursor, match.start() - 6):match.start() + 1]
            if any(_fold(before).endswith(_fold(abbr)) for abbr in _ABBREVIATIONS):
                continue
            if (source[match.start():match.start() + 1] == "." and
                    match.start() > 0 and end < len(source) and
                    source[match.start() - 1].isdigit() and source[end].isdigit()):
                continue
            if end < len(source) and not source[end].isspace():
                continue
            boundary = end
        left = cursor
        right = boundary
        while left < right and source[left].isspace():
            left += 1
        while right > left and source[right - 1].isspace():
            right -= 1
        if right > left:
            spans.append((left, right, source[left:right]))
        cursor = boundary
    left = cursor
    right = len(source)
    while left < right and source[left].isspace():
        left += 1
    while right > left and source[right - 1].isspace():
        right -= 1
    if right > left:
        spans.append((left, right, source[left:right]))
    return spans


@dataclass(frozen=True)
class SentencePlan:
    index: int
    start: int
    end: int
    text: str
    emotion: str
    style: str
    confidence: float
    valence: float
    arousal: float
    dominance: float
    narrative_state: str
    speed_target: float
    melodic_range_target: float
    pause_target: float
    evidence: tuple[str, ...]


def _state(text: str, index: int, count: int) -> str:
    tokens = _tokens(text)
    words = set(tokens)
    folded = _fold(text)
    if any(marker in folded for marker in ("resumindo", "por fim", "em conclusao", "para concluir")):
        return "conclusion"
    if "?" in text or (tokens and tokens[0] in {"como", "qual", "quando", "onde", "quem", "por"}):
        return "question"
    if any(marker in folded for marker in ("a resposta", "porque", "isso acontece", "o motivo")):
        return "explanation"
    if index == 0 and count > 1:
        return "introduction"
    return "development"


def _score(text: str) -> tuple[str, float, float, float, float, tuple[str, ...]]:
    tokens = _tokens(text)
    token_set = set(tokens)
    folded = _fold(text)
    scores = {name: 0.0 for name in _CUES}
    evidence: list[str] = []
    for emotion, cues in _CUES.items():
        for cue in cues:
            cue_tokens = _tokens(cue)
            if len(cue_tokens) > 1:
                found = " ".join(cue_tokens) in " ".join(tokens)
                positions = [i for i in range(len(tokens) - len(cue_tokens) + 1)
                             if tokens[i:i + len(cue_tokens)] == cue_tokens] if found else []
            else:
                positions = [i for i, token in enumerate(tokens) if token == cue_tokens[0]]
            for position in positions:
                negated = any(token in _NEGATORS for token in tokens[max(0, position - 3):position])
                intensity = 1.25 if any(token in _INTENSIFIERS for token in tokens[max(0, position - 2):position]) else 1.0
                score = intensity * (-0.7 if negated else 1.0)
                # Irony is only a weak negative cue when a positive expression
                # co-occurs with explicit loss/failure; it never forces a label.
                if emotion == "joy" and token_set.intersection(_NEGATIVE_CUES):
                    score *= 0.15
                scores[emotion] += score
                evidence.append(f"{emotion}:{cue}" + (":negated" if negated else ""))
    if "!" in text and max(scores.values(), default=0) > 0:
        for name in ("joy", "anger", "surprise", "fear"):
            scores[name] += 0.12
    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    name, best = ranked[0]
    second = ranked[1][1]
    if best < 0.85:
        name = "neutral"
        confidence = 0.35
    else:
        # A heuristic certainty indicator, not a calibrated probability.
        confidence = min(0.95, 0.45 + 0.18 * best + 0.12 * max(0.0, best - second))
        if best - second < 0.25:
            confidence = min(confidence, 0.58)
    positive = sum(scores[key] for key in ("joy", "humor", "confidence", "curiosity"))
    negative = sum(scores[key] for key in ("sadness", "fear", "anger"))
    valence = max(-1.0, min(1.0, (positive - negative) / max(1.0, positive + negative)))
    arousal = 0.40 + min(0.45, 0.12 * best) if name != "neutral" else 0.40
    if name in {"anger", "fear", "surprise"}:
        arousal = min(1.0, arousal + 0.12)
    dominance = 0.78 if name == "anger" else 0.72 if name == "confidence" else 0.25 if name in {"fear", "sadness"} else 0.5
    style = "humor" if name == "humor" else "documentary" if name == "confidence" else name
    return name, confidence, valence, arousal, dominance, tuple(evidence[:12])


def plan_narrative_interpretation(text: str) -> dict:
    """Build a low-cost sentence-level plan; never calls an ASR or LLM.

    ``prosody_application`` is deliberately ``analysis_only``. Values are
    relative targets for future validated controls, not applied audio effects.
    """
    source = str(text or "")
    sentences = _sentence_spans(source)
    plans = []
    prior_emotion = "neutral"
    for index, (start, end, sentence) in enumerate(sentences):
        emotion, confidence, valence, arousal, dominance, evidence = _score(sentence)
        # Hysteresis: weak one-line changes do not create an emotional jump.
        if (index and emotion != "neutral" and confidence < 0.60 and
                emotion != prior_emotion):
            emotion = prior_emotion
            confidence = min(confidence, 0.5)
        speed, melodic, pause = _PROSODY.get(emotion, _PROSODY["neutral"])
        state = _state(sentence, index, len(sentences))
        plans.append(asdict(SentencePlan(index=index, start=start, end=end,
            text=sentence, emotion=emotion, style=emotion, confidence=round(confidence, 3),
            valence=round(valence, 3), arousal=round(arousal, 3),
            dominance=round(dominance, 3), narrative_state=state,
            speed_target=speed, melodic_range_target=melodic,
            pause_target=pause, evidence=evidence)))
        if confidence >= 0.60:
            prior_emotion = emotion
    return {
        "schema_version": INTERPRETER_VERSION,
        "method": "deterministic_pt_br_rules",
        "sentence_count": len(plans),
        "sentences": plans,
        "prosody_application": "analysis_only_backend_capability_unverified",
        "score_note": "Heuristic cues; confidence is not a calibrated probability.",
    }
