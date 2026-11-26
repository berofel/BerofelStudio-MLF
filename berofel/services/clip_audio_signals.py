"""BerofelStudio: lightweight audio-event features and explainable clip ranking.

Reference implementation written independently. Requires only NumPy. No ASR, LLM,
or audio/video rendering is performed here. All timestamps are milliseconds on
THE SAME media timeline used by the existing editor transcript.

Use cached feature arrays when available: don't decode audio a second time.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from array import array
from typing import Iterable, Mapping, Sequence
import re
import unicodedata
import numpy as np


EPS = 1e-9

# Profile weights for the currently measured dimensions. Visual evidence stays
# unavailable until the editor provides frame features; weights are renormalized
# over dimensions that have actual data.
CLIP_SCORE_PROFILES = {
    "Geral": {"hook": .20, "context": .20, "audio": .15, "value": .15,
              "payoff": .15, "rhythm": .10, "visual": .05},
    "Podcast": {"hook": .20, "context": .25, "audio": .12, "value": .15,
                 "payoff": .16, "rhythm": .12, "visual": 0.},
    "Gameplay": {"hook": .15, "context": .10, "audio": .25, "value": .05,
                 "payoff": .15, "rhythm": .10, "visual": .20},
    "Tutorial": {"hook": .15, "context": .25, "audio": .05, "value": .30,
                 "payoff": .15, "rhythm": .08, "visual": .02},
    "Terror": {"hook": .15, "context": .20, "audio": .20, "value": .05,
               "payoff": .25, "rhythm": .10, "visual": .05},
    "Humor": {"hook": .20, "context": .15, "audio": .20, "value": .05,
              "payoff": .30, "rhythm": .08, "visual": .02},
    "Debate": {"hook": .20, "context": .25, "audio": .15, "value": .15,
               "payoff": .15, "rhythm": .08, "visual": .02},
    "Vlog": {"hook": .20, "context": .15, "audio": .15, "value": .10,
             "payoff": .15, "rhythm": .10, "visual": .15},
    "Lives": {"hook": .20, "context": .15, "audio": .25, "value": .08,
              "payoff": .13, "rhythm": .10, "visual": .09},
    "Aulas": {"hook": .15, "context": .25, "audio": .05, "value": .30,
              "payoff": .15, "rhythm": .08, "visual": .02},
    "Histórias": {"hook": .15, "context": .25, "audio": .10, "value": .10,
                  "payoff": .25, "rhythm": .10, "visual": .05},
    "Notícias": {"hook": .15, "context": .20, "audio": .10, "value": .25,
                 "payoff": .15, "rhythm": .10, "visual": .05},
    "Entrevistas": {"hook": .15, "context": .25, "audio": .15, "value": .15,
                    "payoff": .15, "rhythm": .12, "visual": .03},
    "Motivacional": {"hook": .20, "context": .15, "audio": .15, "value": .20,
                     "payoff": .20, "rhythm": .08, "visual": .02},
    "Esportivo": {"hook": .15, "context": .10, "audio": .25, "value": .05,
                  "payoff": .15, "rhythm": .10, "visual": .20},
    "Personalizado": {"hook": .20, "context": .20, "audio": .15, "value": .15,
                      "payoff": .15, "rhythm": .10, "visual": .05},
}

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


def _sparse_term_cosine(left: set[str], right: set[str]) -> float:
    """Cosine similarity for the binary sparse term sets used by MMR."""
    if not left or not right:
        return 0.0
    shared = len(left & right)
    return float(np.clip(shared / ((len(left) * len(right)) ** 0.5), 0.0, 1.0))


@dataclass
class FrameFeatures:
    """Compact cached frame features (audio analysis, not display waveform min/max)."""

    times_ms: np.ndarray
    rms_dbfs: np.ndarray
    peak_dbfs: np.ndarray
    clip_fraction: np.ndarray
    frame_ms: float
    sample_rate: int
    level_kind: str = 'pcm_rms'
    spectral_flux: np.ndarray | None = None
    zero_crossing_rate: np.ndarray | None = None

    def __post_init__(self) -> None:
        lengths = [len(self.times_ms), len(self.rms_dbfs),
                   len(self.peak_dbfs), len(self.clip_fraction)]
        if len(set(lengths)) != 1:
            raise ValueError(f"Feature arrays have different lengths: {lengths}")
        arrays = (self.times_ms, self.rms_dbfs, self.peak_dbfs,
                  self.clip_fraction, self.spectral_flux,
                  self.zero_crossing_rate)
        if any(values is not None and not np.isfinite(values).all()
               for values in arrays):
            raise ValueError("Feature arrays must contain only finite values")
        if len(self.times_ms) > 1 and np.any(np.diff(self.times_ms) < 0):
            raise ValueError("Feature timestamps must be ordered")
        for name in ('spectral_flux', 'zero_crossing_rate'):
            values = getattr(self, name)
            if values is not None and len(values) != lengths[0]:
                raise ValueError(f"{name} must have the same length as frame features")
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
            "level_kind": self.level_kind,
            "spectral_flux": (self.spectral_flux.round(6).tolist()
                              if self.spectral_flux is not None else None),
            "zero_crossing_rate": (self.zero_crossing_rate.round(6).tolist()
                                   if self.zero_crossing_rate is not None else None),
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
            level_kind=str(d.get('level_kind','pcm_rms')),
            spectral_flux=(np.asarray(d['spectral_flux'],dtype=np.float32)
                           if d.get('spectral_flux') is not None else None),
            zero_crossing_rate=(np.asarray(d['zero_crossing_rate'],dtype=np.float32)
                                if d.get('zero_crossing_rate') is not None else None),
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
    fft_size = 1 << max(8, int(n - 1).bit_length())
    analysis_window = np.hanning(n).astype(np.float32)
    # Typed float32 buffers avoid retaining millions of boxed Python floats
    # for long recordings. Each frame still occupies only 20 ms of source.
    rms_list = array('f')
    peak_list = array('f')
    clipped_list = array('f')
    flux_list = array('f')
    zcr_list = array('f')
    previous_spectrum = None
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
            signs = framed >= 0
            zcr = np.mean(signs[:, 1:] != signs[:, :-1], axis=1) if n > 1 else np.zeros(len(framed))
            zcr_list.extend(zcr.tolist())
            # One small FFT per existing 20 ms PCM frame. Normalizing each
            # magnitude spectrum reduces sensitivity to microphone gain.
            spectra = np.abs(np.fft.rfft(framed * analysis_window,
                                           n=fft_size, axis=1)).astype(np.float32)
            spectra /= np.maximum(np.sum(spectra, axis=1, keepdims=True), EPS)
            previous = (previous_spectrum[None, :] if previous_spectrum is not None
                        else spectra[:1])
            sequence = np.concatenate((previous, spectra), axis=0)
            delta = np.maximum(0., sequence[1:] - sequence[:-1])
            flux_list.extend(np.sum(delta * delta, axis=1).tolist())
            previous_spectrum = spectra[-1].copy()
        rem = a[full_len:].copy()
    if rem.size:
        rms_list.append(float(np.sqrt(np.mean(rem.astype(np.float64)**2))))
        peak_list.append(float(np.max(np.abs(rem))))
        clipped_list.append(float(np.mean(np.abs(rem) >= 0.995)))
        zcr_list.append(float(np.mean((rem[1:] >= 0) != (rem[:-1] >= 0))) if len(rem) > 1 else 0.)
        padded = np.zeros(n, dtype=np.float32)
        padded[:len(rem)] = rem
        spectrum = np.abs(np.fft.rfft(padded * analysis_window, n=fft_size)).astype(np.float32)
        spectrum /= max(float(np.sum(spectrum)), EPS)
        flux_list.append(float(np.sum(np.maximum(0., spectrum - previous_spectrum) ** 2))
                         if previous_spectrum is not None else 0.)
    return FrameFeatures(
        times_ms=np.arange(len(rms_list), dtype=np.float64) * (n * 1000.0 / sample_rate),
        rms_dbfs=_to_dbfs(np.frombuffer(rms_list, dtype=np.float32)),
        peak_dbfs=_to_dbfs(np.frombuffer(peak_list, dtype=np.float32)),
        clip_fraction=np.frombuffer(clipped_list, dtype=np.float32),
        frame_ms=n * 1000.0 / sample_rate,
        sample_rate=sample_rate,
        spectral_flux=np.frombuffer(flux_list, dtype=np.float32),
        zero_crossing_rate=np.frombuffer(zcr_list, dtype=np.float32),
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
    # Keep the local reference speaker-relative: an absolute -55/-65 dBFS
    # gate discarded low-gain microphones even when their speech was clearly
    # present in the transcript timestamps. This floor only rejects near-zero
    # PCM; the event threshold remains a rise over the recording's own median.
    valid = speech & (rms_dbfs > -80)
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
        return np.full(len(rms_dbfs), -80, dtype=np.float32)
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
    active = (rise >= relative_rise_db) & (frames.rms_dbfs > -80) & speech
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
            "kind": ("relative_energy_surge" if frames.level_kind == 'pcm_rms'
                     else "relative_waveform_peak_surge"),
            "start_ms": round(start_ms),
            "end_ms": round(end_ms),
            "rise_db": round(max_delta, 2),
            "peak_dbfs": round(peak_db, 2),
            "clipped_fraction": round(clipped, 4),
            "strength": round(float(np.clip((max_delta - relative_rise_db) / 12.0, 0, 1)), 3),
            "speech_verified": speech_intervals_ms is not None,
            "level_source": frames.level_kind,
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
    profile: str = "Geral",
    *, weights_override: Mapping[str, float] | None = None,
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
    audio_available = frames is not None or bool(verified)
    if verified:
        strengths = sorted((float(e.get("strength", 0)) for e in verified), reverse=True)
        # Cap strong evidence to prevent repeated music beats inflating the score.
        audio = float(np.clip(0.75*strengths[0] + 0.25*min(len(strengths)/3, 1.0), 0, 1))
    elif audio_available:
        # A measured signal with no speech-aligned relative surge is neutral.
        # Silence/low dynamics are not sufficient grounds to call good speech
        # uninteresting, but the acoustic dimension is still observed.
        audio = 0.5
    else:
        audio = 0.0
    spectral_novelty = None
    if (frames is not None and frames.spectral_flux is not None and
            len(frames.spectral_flux) == len(frames.times_ms)):
        left = int(np.searchsorted(frames.times_ms, start, side='left'))
        right = int(np.searchsorted(frames.times_ms, end, side='left'))
        all_flux = frames.spectral_flux
        local = all_flux[left:right]
        if local.size and all_flux.size:
            baseline = float(np.median(all_flux))
            mad = float(np.median(np.abs(all_flux - baseline)))
            scale = max(1.4826 * mad, 1e-6)
            relative_flux = max(0., float(np.percentile(local, 90)) - baseline) / scale
            spectral_novelty = float(np.clip((relative_flux - 1.) / 4., 0., 1.))
            # Spectral change is a small positive cue, never a standalone
            # candidate or a claim that a sound is meaningful.
            audio = float(np.clip(audio + .20 * spectral_novelty, 0., 1.))
    figurative = float(np.clip(candidate.get('figurative_score', 0.0), 0, 1))
    discourse = float(np.clip(candidate.get('discourse_score', 0.0), 0, 1))
    # Explainable editorial dimensions. Values not supplied by the analysis are
    # omitted rather than fabricated, and weights are renormalized accordingly.
    context_component = .8*context + .2*boundary
    if 'figurative_score' in candidate:
        context_component += .025*figurative
    if 'discourse_score' in candidate:
        context_component += .025*discourse
    dimensions = {
        'hook': hook,
        'context': float(np.clip(context_component, 0., 1.)),
        'audio': audio if audio_available else None,
        'value': candidate.get('information_score'),
        'payoff': candidate.get('payoff_score'),
        'rhythm': candidate.get('rhythm_score'),
        'visual': candidate.get('visual_score'),
    }
    weights = dict(CLIP_SCORE_PROFILES.get(profile, CLIP_SCORE_PROFILES['Geral']))
    if weights_override is not None:
        allowed=set(weights)
        overrides={str(key):float(value) for key,value in weights_override.items()}
        if (not overrides or set(overrides)-allowed or
                any(not np.isfinite(value) or value < 0. or value > 1.
                    for value in overrides.values()) or not any(overrides.values())):
            raise ValueError('Custom score weights must be finite values in [0, 1] with positive sum')
        weights.update(overrides)
        total_weight=sum(weights.values())
        weights={key:value/total_weight for key,value in weights.items()}
    if frames is not None and frames.level_kind != 'pcm_rms':
        # The timeline waveform is a quantized 100 ms peak envelope, not RMS.
        # It can support a coarse event cue but receives less ranking weight.
        weights['audio'] *= .55
    available_weight = sum(weights[key] for key, value in dimensions.items()
                           if value is not None and weights.get(key, 0.) > 0.)
    if available_weight <= EPS:
        raise ValueError('Não há evidências disponíveis para classificar o candidato.')
    components = {key: (round(float(np.clip(value, 0., 1.)), 3)
                        if value is not None and weights.get(key, 0.) > 0.
                        else None)
                  for key, value in dimensions.items()}
    raw = sum(weights[key]*float(value) for key, value in dimensions.items()
              if value is not None and weights.get(key, 0.) > 0.) / available_weight
    evidence_coverage = sum(weights[key] for key, value in dimensions.items()
                            if value is not None and weights.get(key, 0.) > 0.)
    penalties: list[str] = []
    if frames is not None and len(frames.times_ms):
        left = int(np.searchsorted(frames.times_ms, start, side='left'))
        right = int(np.searchsorted(frames.times_ms, end, side='left'))
        if right > left and frames.level_kind == 'pcm_rms':
            mean_clip_fraction = float(np.mean(frames.clip_fraction[left:right]))
            if mean_clip_fraction > 0.01:
                raw -= 0.08
                penalties.append("Amostras próximas ao limite digital em parte significativa do áudio")
    transcript_confidence = candidate.get('transcript_confidence_score')
    confidence_coverage = candidate.get('transcript_confidence_coverage', 1.0)
    try:
        transcript_confidence = float(transcript_confidence)
    except (TypeError, ValueError):
        transcript_confidence = None
    try:
        confidence_coverage = float(confidence_coverage)
    except (TypeError, ValueError):
        confidence_coverage = 0.
    if (transcript_confidence is not None and
            (not np.isfinite(transcript_confidence) or
             not 0. <= transcript_confidence <= 1.)):
        transcript_confidence = None
    if (not np.isfinite(confidence_coverage) or
            not 0. <= confidence_coverage <= 1.):
        confidence_coverage = 0.
    if (transcript_confidence is not None and
            confidence_coverage > 0.):
        # ASR confidence may be uncalibrated. Use a deliberately small capped
        # ranking penalty, weighted by coverage, and disclose it to the reviewer.
        confidence_penalty = .08 * (1. - transcript_confidence) * confidence_coverage
        raw -= confidence_penalty
        if confidence_penalty >= .01:
            penalties.append(
                f"Confiança ASR relatada baixa ({transcript_confidence:.2f}; "
                f"cobertura {confidence_coverage:.0%}); sinal não calibrado")
    # Prevent noisy clips from outranking semantically incoherent clips.
    if context < 0.5:
        raw = min(raw, 0.59)
        penalties.append("Contexto insuficiente para clipe independente")
    reasons: list[str] = []
    if verified:
        if frames is not None and frames.level_kind != 'pcm_rms':
            reasons.append(f"{len(verified)} mudança(s) na envoltória de pico, alinhada(s) às palavras")
        else:
            reasons.append(f"{len(verified)} evento(s) de RMS ligados à fala")
        roles = {str(e.get("conversation_role", "")) for e in verified}
        for label in ("question", "answer", "reveal"):
            if label in roles:
                reasons.append({"question": "Mudança de energia durante pergunta",
                                "answer": "Mudança de energia durante resposta",
                                "reveal": "Mudança de energia durante revelação"}[label])
    elif audio_available:
        reasons.append("Áudio medido; nenhum pico relativo alinhado à fala foi detectado (valor neutro)")
    else:
        reasons.append("Áudio indisponível; ranking baseado nas evidências restantes")
    if context >= 0.75:
        reasons.append("Conversa com contexto independente")
    if hook >= 0.75:
        reasons.append("Gancho contextual forte")
    if figurative >= .55:
        reasons.append("Possíveis sinais de ironia/figura de linguagem; conferir no áudio")
    if discourse >= .62:
        reasons.append("Sinais discursivos de reação, humor, pergunta retórica ou reinício; conferir no áudio")
    if verified and frames is not None and frames.level_kind != 'pcm_rms':
        reasons.append('Sinal acústico aproximado pela waveform de pico da timeline (100 ms)')
    if spectral_novelty is not None and spectral_novelty >= .25:
        reasons.append('Mudança espectral relativa no áudio (cue acústico, sem interpretação semântica)')
    semantic = .6*context + .4*hook
    return {
        "start_ms": int(start), "end_ms": int(end),
        "score": round(100*float(np.clip(raw, 0, 1)), 1),
        "semantic_score": round(semantic, 3),
        "audio_score": round(audio, 3) if audio_available else None,
        "figurative_score": round(figurative, 3) if 'figurative_score' in candidate else None,
        "discourse_score": round(discourse, 3) if 'discourse_score' in candidate else None,
        "audio_available": audio_available,
        "audio_event_evidence": bool(verified),
        "spectral_novelty": round(spectral_novelty, 3)
            if spectral_novelty is not None else None,
        "transcript_confidence_score": (
            round(transcript_confidence, 3) if transcript_confidence is not None else None),
        "transcript_confidence_coverage": (
            round(confidence_coverage, 3) if transcript_confidence is not None else 0.),
        "audio_source": frames.level_kind if frames is not None else None,
        "boundary_score": round(boundary, 3),
        "profile": profile if profile in CLIP_SCORE_PROFILES else 'Geral',
        "components": components,
        "evidence_coverage": round(float(evidence_coverage), 3),
        "reasons": reasons,
        "warnings": penalties,
        "note": "Ranking editorial relativo, não probabilidade de viralização",
    }


def select_diverse_clips(ranked: Sequence[Mapping], max_clips: int = 5,
                         max_overlap_ratio: float = 0.35,
                         diversity_lambda: float = 0.75) -> list[dict]:
    """Rank with MMR while keeping hard temporal/near-duplicate safeguards.

    Lexical deduplication is deliberately conservative and only operates on
    transcript text already attached to candidates. It adds no ASR/model work.
    Relevance is the existing 0-100 editorial score; similarity combines sparse
    content-term cosine with temporal IoU. The lambda is a ranking tradeoff,
    not a calibrated quality parameter.
    """
    if int(max_clips) <= 0:
        return []
    if not 0.0 <= float(diversity_lambda) <= 1.0:
        raise ValueError('diversity_lambda must be between 0 and 1')
    prepared = []
    for index, candidate in enumerate(ranked):
        try:
            start = float(candidate['start_ms'])
            end = float(candidate['end_ms'])
            relevance = float(candidate['score'])
        except (KeyError, TypeError, ValueError):
            continue
        if not (np.isfinite(start) and np.isfinite(end) and
                np.isfinite(relevance) and 0.0 <= start < end):
            continue
        prepared.append({'index': index, 'candidate': dict(candidate),
                         'start': start, 'end': end,
                         'source': str(candidate.get('source') or ''),
                         'relevance': float(np.clip(relevance / 100.0, 0.0, 1.0)),
                         'terms': _diversity_terms(candidate.get('text', ''))})
    remaining = sorted(prepared, key=lambda item: (-item['relevance'], item['index']))
    chosen = []
    while remaining and len(chosen) < int(max_clips):
        best_index = None
        best_utility = float('-inf')
        for position, item in enumerate(remaining):
            similarities = []
            duplicate = False
            for previous in chosen:
                same_source = (not item['source'] or not previous['source'] or
                               item['source'] == previous['source'])
                intersection = (max(0.0, min(item['end'], previous['end']) -
                                    max(item['start'], previous['start']))
                                if same_source else 0.0)
                shorter = min(item['end'] - item['start'],
                              previous['end'] - previous['start'])
                containment = intersection / max(shorter, EPS)
                if (same_source and containment > max_overlap_ratio) or _same_topic_duplicate(
                        item['candidate'], previous['candidate'],
                        item['terms'], previous['terms']):
                    duplicate = True
                    break
                union = ((item['end'] - item['start']) +
                         (previous['end'] - previous['start']) - intersection)
                temporal_iou = intersection / max(union, EPS) if same_source else 0.0
                lexical = _sparse_term_cosine(item['terms'], previous['terms'])
                similarities.append(.65 * temporal_iou + .35 * lexical)
            if duplicate:
                continue
            redundancy = max(similarities, default=0.0)
            utility = (float(diversity_lambda) * item['relevance'] -
                       (1.0 - float(diversity_lambda)) * redundancy)
            if utility > best_utility:
                best_utility = utility
                best_index = position
        if best_index is None:
            break
        chosen.append(remaining.pop(best_index))
    return [item['candidate'] for item in chosen]
