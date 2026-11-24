"""BerofelStudio: lightweight audio-event features and explainable clip ranking.

Reference implementation written independently. Requires only NumPy. No ASR, LLM,
or audio/video rendering is performed here. All timestamps are milliseconds on
THE SAME media timeline used by the existing editor transcript.

Use cached feature arrays when available: don't decode audio a second time.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Iterable, Mapping, Sequence
import re
import unicodedata
import numpy as np


EPS = 1e-9

# Small PT-BR function-word list for candidate diversity only. It is not a
# prohibited-word list and never changes transcript text or timestamps.
_DIVERSITY_STOPWORDS = frozenset((
    'a', 'ao', 'aos', 'aquela', 'aquele', 'aquilo', 'as', 'ate', 'com',
    'como', 'da', 'das', 'de', 'dela', 'dele', 'deles', 'demais', 'do',
    'dos', 'e', 'ela', 'elas', 'ele', 'eles', 'em', 'essa', 'esse', 'esta',
    'este', 'eu', 'foi', 'foram', 'isso', 'isto', 'ja', 'la', 'lhe', 'mais',
    'mas', 'me', 'mesmo', 'menos', 'meu', 'minha', 'muito', 'na', 'nas',
    'nem', 'no', 'nos', 'nossa', 'nossas', 'nosso', 'nossos', 'o', 'os',
    'ou', 'para', 'pela', 'pelas', 'pelo', 'pelos', 'por', 'porque', 'qual',
    'quando', 'que', 'quem', 'se', 'sem', 'ser', 'seu', 'sua', 'suas',
    'tambem', 'tem', 'tendo', 'te', 'um', 'uma', 'voce', 'voces', 'vou',
    'vai', 'vamos', 'foi', 'era', 'sao', 'esta', 'estao', 'ter', 'tinha'))


def _diversity_terms(text: object) -> set[str]:
    """Extract cheap, accent-insensitive content terms for list diversity."""
    normalized = unicodedata.normalize('NFKD', str(text or '').casefold())
    normalized = ''.join(char for char in normalized
                         if not unicodedata.combining(char))
    return {token for token in re.findall(r'[a-z0-9]+', normalized)
            if len(token) > 1 and token not in _DIVERSITY_STOPWORDS}


def _same_topic_duplicate(left: Mapping, right: Mapping,
                          left_terms: set[str] | None = None,
                          right_terms: set[str] | None = None) -> bool:
    """Conservatively detect near-duplicate transcript candidates.

    Require several shared content terms and both high containment and
    substantial Jaccard overlap. This keeps a candidate that adds a meaningful
    detail from being discarded just because it discusses the same topic.
    """
    left_terms = left_terms if left_terms is not None else _diversity_terms(
        left.get('text', ''))
    right_terms = right_terms if right_terms is not None else _diversity_terms(
        right.get('text', ''))
    if min(len(left_terms), len(right_terms)) < 5:
        return False
    shared = left_terms & right_terms
    if len(shared) < 5:
        return False
    containment = len(shared) / min(len(left_terms), len(right_terms))
    jaccard = len(shared) / len(left_terms | right_terms)
    return containment >= .92 and jaccard >= .82


@dataclass
class FrameFeatures:
    """Compact cached frame features (audio analysis, not display waveform min/max)."""

    times_ms: np.ndarray
    rms_dbfs: np.ndarray
    peak_dbfs: np.ndarray
    clip_fraction: np.ndarray
    frame_ms: float
    sample_rate: int

    def __post_init__(self) -> None:
        lengths = [len(self.times_ms), len(self.rms_dbfs),
                   len(self.peak_dbfs), len(self.clip_fraction)]
        if len(set(lengths)) != 1:
            raise ValueError(f"Feature arrays have different lengths: {lengths}")
        if self.frame_ms <= 0 or self.sample_rate <= 0:
            raise ValueError("frame_ms and sample_rate must be positive")

    def to_dict(self) -> dict:
        return {
            "times_ms": self.times_ms.round(2).tolist(),
            "rms_dbfs": self.rms_dbfs.round(3).tolist(),
            "peak_dbfs": self.peak_dbfs.round(3).tolist(),
            "clip_fraction": self.clip_fraction.round(4).tolist(),
            "frame_ms": self.frame_ms,
            "sample_rate": self.sample_rate,
        }

    @classmethod
    def from_dict(cls, d: Mapping) -> "FrameFeatures":
        return cls(
            times_ms=np.asarray(d["times_ms"], dtype=np.float64),
            rms_dbfs=np.asarray(d["rms_dbfs"], dtype=np.float32),
            peak_dbfs=np.asarray(d["peak_dbfs"], dtype=np.float32),
            clip_fraction=np.asarray(d["clip_fraction"], dtype=np.float32),
            frame_ms=float(d["frame_ms"]),
            sample_rate=int(d["sample_rate"]),
        )


def _to_dbfs(x: np.ndarray) -> np.ndarray:
    return (20.0 * np.log10(np.maximum(x, EPS))).astype(np.float32)


def extract_frames_from_chunks(
    chunks: Iterable[np.ndarray], sample_rate: int, frame_ms: int = 20
) -> FrameFeatures:
    """Single-pass PCM extractor. Feed PCM chunks from the existing ingest/decode.

    Input: mono float PCM in [-1, 1]. If editor has stereo PCM, use its
    established downmix strategy, preferably speech-centered, before feeding.
    Analysis is frame-aligned; no attempt is made to infer true peak or LUFS.
    """
    if sample_rate < 1000 or not 5 <= frame_ms <= 1000:
        raise ValueError("Invalid sample rate or frame size")
    n = round(sample_rate * frame_ms / 1000)
    if n < 1:
        raise ValueError("Frame size too small")
    rms_list: list[float] = []
    peak_list: list[float] = []
    clipped_list: list[float] = []
    rem = np.empty(0, dtype=np.float32)
    for chunk in chunks:
        a = np.asarray(chunk, dtype=np.float32).reshape(-1)
        if a.size == 0:
            continue
        if not np.all(np.isfinite(a)):
            raise ValueError("Non-finite PCM samples")
        if rem.size:
            a = np.concatenate((rem, a))
        full_len = (len(a) // n) * n
        if full_len:
            framed = a[:full_len].reshape(-1, n)
            # Accumulate in float64 to avoid transient overflow/precision loss.
            rms_list.extend(np.sqrt(np.mean(framed.astype(np.float64)**2, axis=1)).tolist())
            peak_list.extend(np.max(np.abs(framed), axis=1).tolist())
            clipped_list.extend(np.mean(np.abs(framed) >= 0.995, axis=1).tolist())
        rem = a[full_len:].copy()
    if rem.size:
        rms_list.append(float(np.sqrt(np.mean(rem.astype(np.float64)**2))))
        peak_list.append(float(np.max(np.abs(rem))))
        clipped_list.append(float(np.mean(np.abs(rem) >= 0.995)))
    return FrameFeatures(
        times_ms=np.arange(len(rms_list), dtype=np.float64) * (n * 1000.0 / sample_rate),
        rms_dbfs=_to_dbfs(np.asarray(rms_list, dtype=np.float64)),
        peak_dbfs=_to_dbfs(np.asarray(peak_list, dtype=np.float64)),
        clip_fraction=np.asarray(clipped_list, dtype=np.float32),
        frame_ms=n * 1000.0 / sample_rate,
        sample_rate=sample_rate,
    )


def speech_frame_mask(
    frames: FrameFeatures, intervals_ms: Sequence[Sequence[int | float]] | None
) -> np.ndarray:
    """Project existing VAD/word-time intervals onto analyzed audio frames.

    A None mask means speech information is unavailable, so peaks are *not*
    assumed to be speech. Empty list means known absence of speech.
    """
    if intervals_ms is None:
        return np.ones(len(frames.times_ms), dtype=bool)
    mask = np.zeros(len(frames.times_ms), dtype=bool)
    # Search sorted boundaries; avoid creating a full-length temporary Boolean
    # array for every transcript word (would be O(words * audio_frames)).
    starts = frames.times_ms
    ends = starts + frames.frame_ms
    for s, e in intervals_ms:
        if float(e) <= float(s):
            continue
        left = int(np.searchsorted(ends, float(s), side="right"))
        right = int(np.searchsorted(starts, float(e), side="left"))
        mask[left:right] = True
    return mask


def _baseline_db(
    times_ms: np.ndarray, rms_dbfs: np.ndarray, speech: np.ndarray,
    baseline_window_s: int = 30,
) -> np.ndarray:
    """Rolling local reference, using 1-s bins to avoid O(N*frames) medians."""
    if len(rms_dbfs) == 0:
        return rms_dbfs.copy()
    seconds = np.floor(times_ms / 1000).astype(int)
    count = int(seconds[-1]) + 1
    # Use voiced, non-silent frames to avoid lowering reference in quiet gaps.
    valid = speech & (rms_dbfs > -65)
    ref = np.full(count, np.nan, dtype=np.float32)
    # Slice adjacent time buckets by index, rather than doing one full-array
    # scan for every second of a multi-hour video.
    boundaries = np.searchsorted(seconds, np.arange(count + 1), side="left")
    for sec in range(count):
        left, right = int(boundaries[sec]), int(boundaries[sec+1])
        segment = rms_dbfs[left:right]
        values = segment[valid[left:right]]
        if len(values):
            ref[sec] = float(np.median(values))
    available = ref[np.isfinite(ref)]
    if len(available) == 0:
        return np.full(len(rms_dbfs), -65, dtype=np.float32)
    fallback = float(np.median(available))
    radius = max(1, baseline_window_s // 2)
    reference = np.empty(count, dtype=np.float32)
    for sec in range(count):
        left, right = max(0, sec-radius), min(count, sec+radius+1)
        area = ref[left:right]
        good = area[np.isfinite(area)]
        reference[sec] = float(np.median(good)) if len(good) else fallback
    return reference[seconds]


def detect_energy_events(
    frames: FrameFeatures,
    speech_intervals_ms: Sequence[Sequence[float]] | None,
    *,
    relative_rise_db: float = 6.0,
    min_duration_ms: int = 100,
    merge_gap_ms: int = 350,
) -> list[dict]:
    """Detect atypical energy bursts, not 'viral moments'.

    Only report speech-aligned events if intervals are provided. Without a
    speech mask, events are exploratory and have speech_verified=False.
    Intensity thresholds are configurable *hypotheses*, not calibrated facts.
    """
    if len(frames.times_ms) == 0:
        return []
    speech = speech_frame_mask(frames, speech_intervals_ms)
    baseline = _baseline_db(frames.times_ms, frames.rms_dbfs, speech)
    rise = frames.rms_dbfs - baseline
    active = (rise >= relative_rise_db) & (frames.rms_dbfs > -55) & speech
    idxs = np.flatnonzero(active)
    if not len(idxs):
        return []
    groups: list[list[int]] = [[int(idxs[0])]]
    for idx in idxs[1:]:
        if (idx - groups[-1][-1] - 1) * frames.frame_ms <= merge_gap_ms:
            groups[-1].append(int(idx))
        else:
            groups.append([int(idx)])
    events: list[dict] = []
    for group in groups:
        first, last = group[0], group[-1]
        # Count only active frames, not bridging silence, toward min duration.
        if len(group) * frames.frame_ms < min_duration_ms:
            continue
        start_ms = float(frames.times_ms[first]); end_ms = float(frames.times_ms[last] + frames.frame_ms)
        max_delta = float(np.max(rise[group]))
        peak_db = float(np.max(frames.peak_dbfs[first:last+1]))
        clipped = float(np.mean(frames.clip_fraction[first:last+1]))
        events.append({
            "kind": "relative_energy_surge",
            "start_ms": round(start_ms),
            "end_ms": round(end_ms),
            "rise_db": round(max_delta, 2),
            "peak_dbfs": round(peak_db, 2),
            "clipped_fraction": round(clipped, 4),
            "strength": round(float(np.clip((max_delta - relative_rise_db) / 12.0, 0, 1)), 3),
            "speech_verified": speech_intervals_ms is not None,
            "meaning": "energy change only; semantic interpretation required",
        })
    return events



def align_events_to_conversation(
    events: Sequence[Mapping],
    turns: Sequence[Mapping],
) -> list[dict]:
    """Attach existing semantic turns to events without a new language model.

    Turn schema: start_ms, end_ms, role (e.g. question/answer/reveal), and
    optional speaker_id. Roles must be obtained from existing transcript
    analysis; this function does not guess them from punctuation.
    """
    ordered = sorted(turns, key=lambda t: float(t["start_ms"]))
    result: list[dict] = []
    for event in events:
        start, end = float(event["start_ms"]), float(event["end_ms"])
        overlaps = [t for t in ordered if float(t["start_ms"]) < end and
                    float(t["end_ms"]) > start]
        if overlaps:
            chosen = max(overlaps, key=lambda t: min(end, float(t["end_ms"]))
                         - max(start, float(t["start_ms"])))
        else:
            chosen = None
        item = dict(event)
        if chosen is not None:
            item["conversation_role"] = str(chosen.get("role", "unspecified"))
            if "speaker_id" in chosen:
                item["speaker_id"] = chosen["speaker_id"]
            if "turn_id" in chosen:
                item["turn_id"] = chosen["turn_id"]
        result.append(item)
    return result


def score_clip(
    candidate: Mapping,
    events: Sequence[Mapping],
    frames: FrameFeatures | None = None,
) -> dict:
    """Score a transcript-proposed clip using cheap reusable event features.

    candidate={start_ms,end_ms,context_score,hook_score,boundary_score}
    All 3 scores must be supplied by the EXISTING semantic/cut pipeline in [0,1].
    The returned 0-100 score is an editorial ranking, not a virality probability.
    """
    start, end = float(candidate["start_ms"]), float(candidate["end_ms"])
    if not 0 <= start < end:
        raise ValueError("Invalid candidate time range")
    for key in ("context_score", "hook_score", "boundary_score"):
        if key not in candidate or not 0 <= float(candidate[key]) <= 1:
            raise ValueError(f"Expected existing {key} in [0, 1]")
    context, hook, boundary = (float(candidate[k]) for k in
                               ("context_score", "hook_score", "boundary_score"))
    span_events = [e for e in events if float(e["start_ms"]) < end
                   and float(e["end_ms"]) > start]
    verified = [e for e in span_events if e.get("speech_verified", False)]
    if verified:
        strengths = sorted((float(e.get("strength", 0)) for e in verified), reverse=True)
        # Cap strong evidence to prevent repeated music beats inflating the score.
        audio = float(np.clip(0.75*strengths[0] + 0.25*min(len(strengths)/3, 1.0), 0, 1))
        audio_available = True
    else:
        audio = 0.0
        audio_available = False
    figurative = float(np.clip(candidate.get('figurative_score', 0.0), 0, 1))
    if 'figurative_score' in candidate:
        # Optional, intentionally small contribution from the deterministic
        # context analyzer. A suspected irony cue is not a virality probability.
        semantic = 0.55*context + 0.35*hook + 0.10*figurative
    else:
        semantic = 0.6*context + 0.4*hook
    # Graceful degradation: when speech-verified audio is absent, do not punish
    # genuinely good quiet content. Reweight only available components.
    if audio_available:
        raw = 0.70*semantic + 0.20*audio + 0.10*boundary
    else:
        raw = 0.875*semantic + 0.125*boundary
    penalties: list[str] = []
    if frames is not None and len(frames.times_ms):
        mask = (frames.times_ms >= start) & (frames.times_ms < end)
        if np.any(mask):
            mean_clip_fraction = float(np.mean(frames.clip_fraction[mask]))
            if mean_clip_fraction > 0.01:
                raw -= 0.08
                penalties.append("Amostras próximas ao limite digital em parte significativa do áudio")
    # Prevent noisy clips from outranking semantically incoherent clips.
    if context < 0.5:
        raw = min(raw, 0.59)
        penalties.append("Contexto insuficiente para clipe independente")
    reasons: list[str] = []
    if verified:
        reasons.append(f"{len(verified)} evento(s) de energia ligados à fala")
        roles = {str(e.get("conversation_role", "")) for e in verified}
        for label in ("question", "answer", "reveal"):
            if label in roles:
                reasons.append({"question": "Mudança de energia durante pergunta",
                                "answer": "Mudança de energia durante resposta",
                                "reveal": "Mudança de energia durante revelação"}[label])
    if context >= 0.75:
        reasons.append("Conversa com contexto independente")
    if hook >= 0.75:
        reasons.append("Gancho contextual forte")
    if figurative >= .55:
        reasons.append("Possíveis sinais de ironia/figura de linguagem; conferir no áudio")
    if not verified:
        reasons.append("Áudio não verificado; nota baseada no texto e limites")
    return {
        "start_ms": int(start), "end_ms": int(end),
        "score": round(100*float(np.clip(raw, 0, 1)), 1),
        "semantic_score": round(semantic, 3),
        "audio_score": round(audio, 3) if audio_available else None,
        "figurative_score": round(figurative, 3) if 'figurative_score' in candidate else None,
        "audio_available": audio_available,
        "boundary_score": round(boundary, 3),
        "reasons": reasons,
        "warnings": penalties,
        "note": "Ranking editorial relativo, não probabilidade de viralização",
    }


def select_diverse_clips(ranked: Sequence[Mapping], max_clips: int = 5,
                         max_overlap_ratio: float = 0.35) -> list[dict]:
    """Greedily retain high-ranking clips with temporal and lexical diversity.

    Lexical deduplication is deliberately conservative and only operates on
    transcript text already attached to candidates. It adds no ASR/model work.
    """
    chosen: list[tuple[dict, set[str]]] = []
    for c in sorted(ranked, key=lambda c: float(c["score"]), reverse=True):
        s, e = float(c["start_ms"]), float(c["end_ms"])
        if e <= s:
            continue
        terms = _diversity_terms(c.get('text', ''))
        duplicates = False
        for prev, prev_terms in chosen:
            ps, pe = float(prev["start_ms"]), float(prev["end_ms"])
            intersection = max(0.0, min(e, pe)-max(s, ps))
            ratio = intersection / min(e-s, pe-ps)
            if ratio > max_overlap_ratio:
                duplicates = True
                break
            if _same_topic_duplicate(c, prev, terms, prev_terms):
                duplicates = True
                break
        if not duplicates:
            chosen.append((dict(c), terms))
            if len(chosen) >= max_clips:
                break
    return [candidate for candidate, _terms in chosen]
