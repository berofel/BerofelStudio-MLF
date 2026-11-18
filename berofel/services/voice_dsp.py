"""Lightweight, deterministic DSP controls for synthesized or imported voice.

The source file is never rewritten. Preview and export consume the same FFmpeg
filter builder through the canonical multitrack graph.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

DSP_SCHEMA_VERSION = 1

VOICE_EQ_PRESETS = {
    'Natural': (0.0, 0.0, 0.0),
    'Graves suaves': (2.0, 0.0, -0.5),
    'Voz encorpada': (2.5, 1.0, -1.0),
    'Agudos reduzidos': (0.0, 0.0, -2.5),
    'Voz clara': (-0.5, 1.0, 2.0),
    'Documentário': (1.0, 1.0, 0.5),
}


@dataclass(frozen=True)
class VoiceEQ:
    bass_db: float = 0.0
    mids_db: float = 0.0
    treble_db: float = 0.0
    bypass: bool = False

    def validated(self) -> 'VoiceEQ':
        values = (self.bass_db, self.mids_db, self.treble_db)
        if any(not math.isfinite(float(value)) or not -12.0 <= float(value) <= 12.0
               for value in values):
            raise ValueError('Cada banda do EQ deve ficar entre -12 e +12 dB.')
        return VoiceEQ(*(round(float(value), 2) for value in values),
                       bypass=bool(self.bypass))


def voice_eq_filters(eq: VoiceEQ | None = None) -> list[str]:
    """Return FFmpeg EQ/limiter filters for the current non-destructive clip."""
    settings = (eq or VoiceEQ()).validated()
    if settings.bypass:
        return []
    filters=[]
    if abs(settings.bass_db) >= .01:
        filters.append(f'bass=f=120:width_type=q:width=0.707:gain={settings.bass_db:.2f}')
    if abs(settings.mids_db) >= .01:
        filters.append(f'equalizer=f=1200:t=q:w=1.000:g={settings.mids_db:.2f}')
    if abs(settings.treble_db) >= .01:
        filters.append(f'treble=f=5000:width_type=q:width=0.707:gain={settings.treble_db:.2f}')
    # Boosting multiple bands can exceed full scale. The limiter is inserted
    # only when EQ is active; neutral EQ leaves samples untouched.
    if filters:
        filters.append('alimiter=limit=0.95:level=disabled')
    return filters


def clip_voice_eq(clip) -> VoiceEQ:
    return VoiceEQ(
        bass_db=getattr(clip, 'voice_eq_bass_db', 0.0),
        mids_db=getattr(clip, 'voice_eq_mids_db', 0.0),
        treble_db=getattr(clip, 'voice_eq_treble_db', 0.0),
        bypass=getattr(clip, 'voice_dsp_bypass', False),
    )


def voice_pitch_filters(semitones: float, rubberband_available: bool = False) -> list[str]:
    """Shift pitch without changing clip duration, using FFmpeg's built-in DSP.

    Prefer Rubber Band's pitch shifter when the bundled FFmpeg exposes it; this
    keeps duration fixed and preserves vocal formants. Builds without that
    filter use FFmpeg's built-in ``asetrate`` + ``atempo`` fallback.
    """
    value=float(semitones)
    if not math.isfinite(value) or not -4.0 <= value <= 4.0:
        raise ValueError('O pitch da narração deve ficar entre -4 e +4 semitons.')
    if abs(value)<.005:return []
    ratio=2.0**(value/12.0)
    if rubberband_available:
        return [f'rubberband=tempo=1.0:pitch={ratio:.8f}:'
                'formant=preserved:pitchq=quality']
    return [f'asetrate=48000*{ratio:.8f}', 'aresample=48000',
            f'atempo={1.0/ratio:.8f}']


def combined_rubberband_filter(speed: float, semitones: float) -> str:
    """Combine tempo and voice pitch in one Rubber Band pass.

    Use only when pitch-preserving speed and a pitch adjustment are active and
    the FFmpeg build has the filter. This avoids cascading two phase vocoders.
    """
    rate=float(speed)
    pitch=float(semitones)
    if not math.isfinite(rate) or not .25<=rate<=10.:
        raise ValueError('A velocidade de processamento deve ficar entre 0,25× e 10×.')
    if not math.isfinite(pitch) or not -4.<=pitch<=4.:
        raise ValueError('O pitch da narração deve ficar entre -4 e +4 semitons.')
    ratio=2.0**(pitch/12.0)
    return (f'rubberband=tempo={rate:.6f}:pitch={ratio:.8f}:'
            'formant=preserved:pitchq=quality')
