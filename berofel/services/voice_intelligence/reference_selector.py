"""Small deterministic quality ranker for speech-reference candidates.

The rank is a heuristic for choosing a usable conditioning window. It is not a
speaker-identity score, SNR measurement, or calibrated probability. Missing
metrics are excluded and remaining weights are renormalized.
"""
from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class ReferenceCandidateScore:
    start: float
    duration: float
    active_fraction: float
    active_seconds: float
    score: float
    confidence: str
    components: dict[str, float]


def _unit(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def score_reference_candidate(candidate: dict, acoustic: dict | None = None
                              ) -> ReferenceCandidateScore:
    """Score VAD activity plus measured level, silence and clipping.

    Useful duration is capped at 12 s so a long, poor recording does not win
    solely because it is long. Acoustic terms are optional for compatibility
    with systems where FFmpeg cannot provide a candidate PCM scan.
    """
    acoustic = acoustic or {}
    duration = max(.001, float(candidate["duration"]))
    active = _unit(candidate.get("active_fraction", 0.0))
    active_seconds = max(0.0, min(duration, float(candidate.get("active_seconds", 0.0))))
    components: dict[str, float | None] = {
        "voice_activity": active,
        "useful_duration": _unit(active_seconds / 12.0),
        "recording_level": None,
        "low_clipping": None,
        "low_near_silence": None,
        "pitch_trackability": None,
    }
    rms_dbfs = acoustic.get("rms_dbfs")
    if rms_dbfs is not None and math.isfinite(float(rms_dbfs)):
        components["recording_level"] = _unit((float(rms_dbfs) + 48.0) / 30.0)
    clipped = acoustic.get("clipped_fraction")
    if clipped is not None and math.isfinite(float(clipped)):
        components["low_clipping"] = 1.0 - _unit(float(clipped) / .02)
    near_silence = acoustic.get("near_silence_fraction")
    if near_silence is not None and math.isfinite(float(near_silence)):
        components["low_near_silence"] = 1.0 - _unit(float(near_silence))
    pitch_trackability = acoustic.get("pitch_trackability")
    if pitch_trackability is not None and math.isfinite(float(pitch_trackability)):
        components["pitch_trackability"] = _unit(pitch_trackability)
    weights = {"voice_activity": .30, "useful_duration": .05,
               "recording_level": .18, "low_clipping": .22,
               "low_near_silence": .15, "pitch_trackability": .10}
    available = [(name, weights[name], value) for name, value in components.items()
                 if value is not None]
    total_weight = sum(weight for _name, weight, _value in available)
    score = sum(weight * float(value) for _name, weight, value in available) / total_weight
    confidence = "limited" if len(available) < 4 else "heuristic"
    return ReferenceCandidateScore(float(candidate["start"]), duration, active,
        active_seconds, score, confidence,
        {name: float(value) for name, _weight, value in available})


def rank_reference_candidates(candidates: list[dict],
                              acoustics: dict[tuple[float, float], dict] | None = None
                              ) -> list[ReferenceCandidateScore]:
    """Rank candidate windows deterministically; ties prefer longer speech."""
    acoustics = acoustics or {}
    scores = [score_reference_candidate(item,
        acoustics.get((float(item["start"]), float(item["duration"]))))
        for item in candidates]
    return sorted(scores, key=lambda item: (item.score, item.active_seconds,
                                           item.active_fraction, item.duration,
                                           -item.start), reverse=True)
