"""Local, deterministic voice-planning helpers for Berofel Studio."""

from .text_normalizer import NormalizedSpeechText, normalize_pt_br
from .capabilities import inspect_purec_capabilities
from .quality_inspector import (calculate_temporal_coverage,
                                calculate_text_error_rates,
                                inspect_generated_wav_with_parakeet)
from .acoustic_analyzer import analyze_pcm_f32le, analyze_pitch_yin_f32le
from .pronunciation_dictionary import (PronunciationDictionary,
                                       apply_pronunciations)

__all__ = ["NormalizedSpeechText", "normalize_pt_br", "inspect_purec_capabilities",
           "calculate_text_error_rates", "calculate_temporal_coverage",
           "inspect_generated_wav_with_parakeet",
           "analyze_pcm_f32le", "analyze_pitch_yin_f32le", "PronunciationDictionary",
           "apply_pronunciations"]
