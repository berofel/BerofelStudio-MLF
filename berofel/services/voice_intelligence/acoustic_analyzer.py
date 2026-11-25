"""Low-cost, deterministic PCM measurements for voice-reference windows.

This module intentionally uses the standard library so reference checks can
still start in reduced installations. Features are descriptive measurements,
not speaker identity, perceptual quality, or calibrated SNR.
"""
from __future__ import annotations

from array import array
import math
import sys

ACOUSTIC_FEATURE_VERSION = 1
PITCH_FEATURE_VERSION = 1
SPECTRAL_FEATURE_VERSION = 2


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = round((len(ordered) - 1) * max(0.0, min(1.0, fraction)))
    return ordered[index]


def analyze_pcm_f32le(pcm: bytes, *, sample_rate: int = 16000,
                      frame_ms: int = 20) -> dict:
    """Summarize mono little-endian float PCM in bounded short frames."""
    if sample_rate <= 0 or frame_ms <= 0:
        raise ValueError("sample_rate e frame_ms precisam ser positivos")
    usable = len(pcm) - len(pcm) % 4
    if usable == 0:
        raise ValueError("PCM vazio")
    samples = array("f")
    samples.frombytes(pcm[:usable])
    if sys.byteorder != "little":
        samples.byteswap()
    frame_size = max(1, round(sample_rate * frame_ms / 1000))
    frame_rms: list[float] = []
    frame_zcr: list[float] = []
    square_sum = 0.0
    peak = 0.0
    clipped = quiet = crossings = 0
    previous_sign = 0
    for frame_start in range(0, len(samples), frame_size):
        frame_end = min(frame_start + frame_size, len(samples))
        frame_square = 0.0
        frame_crossings = 0
        frame_previous_sign = 0
        for index in range(frame_start, frame_end):
            value = float(samples[index])
            if not math.isfinite(value):
                raise ValueError("PCM contém NaN ou infinito")
            magnitude = abs(value)
            square = value * value
            square_sum += square
            frame_square += square
            peak = max(peak, magnitude)
            clipped += magnitude >= .999
            quiet += magnitude < .005
            sign = 1 if value >= 0 else -1
            if previous_sign and sign != previous_sign:
                crossings += 1
            if frame_previous_sign and sign != frame_previous_sign:
                frame_crossings += 1
            previous_sign = frame_previous_sign = sign
        count = frame_end - frame_start
        frame_rms.append(math.sqrt(frame_square / count))
        frame_zcr.append(frame_crossings / max(1, count - 1))

    count = len(samples)
    rms = math.sqrt(square_sum / count)
    rms_dbfs = 20 * math.log10(max(rms, 1e-12))
    peak_dbfs = 20 * math.log10(max(peak, 1e-12))
    # A quiet-frame contrast is only a rough proxy. It is reported only if
    # there are enough truly low-level frames and enough active frames; music,
    # room tone or continuous speech can invalidate the interpretation.
    quiet_frames = [value for value in frame_rms if value < .00316]  # -50 dBFS
    active_frames = [value for value in frame_rms if value >= .01778]  # -35 dBFS
    proxy = None
    proxy_confidence = "unavailable"
    if len(quiet_frames) >= 5 and len(active_frames) >= 5:
        quiet_level = _percentile(quiet_frames, .5) or 0.0
        active_level = _percentile(active_frames, .5) or 0.0
        if quiet_level > 0 and active_level > quiet_level:
            proxy = 20 * math.log10(active_level / quiet_level)
            proxy_confidence = "rough_quiet_frame_contrast"
    return {
        "feature_version": ACOUSTIC_FEATURE_VERSION,
        "sample_rate": sample_rate,
        "sample_count": count,
        "duration_seconds": count / sample_rate,
        "rms_dbfs": rms_dbfs,
        "peak_dbfs": peak_dbfs,
        "crest_factor_db": peak_dbfs - rms_dbfs,
        "clipped_fraction": clipped / count,
        "near_silence_fraction": quiet / count,
        "zero_crossing_rate": crossings / max(1, count - 1),
        "frame_rms_dbfs_p10": (20 * math.log10(max(_percentile(frame_rms, .1) or 0.0, 1e-12))),
        "frame_rms_dbfs_p50": (20 * math.log10(max(_percentile(frame_rms, .5) or 0.0, 1e-12))),
        "frame_rms_dbfs_p90": (20 * math.log10(max(_percentile(frame_rms, .9) or 0.0, 1e-12))),
        "frame_zcr_p50": _percentile(frame_zcr, .5),
        "speech_to_quiet_level_db_proxy": proxy,
        "level_contrast_confidence": proxy_confidence,
        "snr_db": None,
        "snr_confidence": "unavailable_without_noise_reference",
    }


def analyze_pitch_yin_f32le(pcm: bytes, *, sample_rate: int = 16000,
                            min_f0_hz: float = 65.0,
                            max_f0_hz: float = 400.0,
                            max_frames: int = 60) -> dict:
    """Estimate descriptive voiced F0 statistics with bounded YIN sampling.

    This is an optional diagnostic, not a speaker-identity or emotion
    classifier. At most ``max_frames`` evenly distributed 40 ms frames are
    measured, so long references are not analyzed in a Python loop per sample.
    NumPy is imported lazily; if it is unavailable, the caller can retain the
    other standard-library acoustic features.
    """
    if sample_rate <= 0 or max_frames <= 0:
        raise ValueError("sample_rate e max_frames precisam ser positivos")
    if not (0 < min_f0_hz < max_f0_hz < sample_rate / 2):
        raise ValueError("A faixa de F0 precisa estar dentro da faixa de Nyquist")
    usable = len(pcm) - len(pcm) % 4
    if usable == 0:
        raise ValueError("PCM vazio")
    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("NumPy é necessário para estimar F0 por YIN") from exc

    signal = np.frombuffer(pcm[:usable], dtype="<f4")
    if signal.size < round(sample_rate * .04):
        return {"feature_version": PITCH_FEATURE_VERSION,
                "status": "too_short", "f0_median_hz": None,
                "confidence_median": None, "voiced_frame_count": 0,
                "sampled_frame_count": 0}
    if not bool(np.isfinite(signal).all()):
        raise ValueError("PCM contém NaN ou infinito")

    frame_size = max(16, round(sample_rate * .04))
    hop = max(1, round(sample_rate * .5))
    starts = list(range(0, max(1, len(signal) - frame_size + 1), hop))
    if starts[-1] != len(signal) - frame_size:
        starts.append(len(signal) - frame_size)
    if len(starts) > max_frames:
        indices = np.linspace(0, len(starts) - 1, max_frames, dtype=int)
        starts = [starts[int(index)] for index in indices]

    min_lag = max(2, int(sample_rate / max_f0_hz))
    max_lag = min(frame_size // 2, int(sample_rate / min_f0_hz))
    if max_lag <= min_lag:
        return {"feature_version": PITCH_FEATURE_VERSION,
                "status": "insufficient_frame", "f0_median_hz": None,
                "confidence_median": None, "voiced_frame_count": 0,
                "sampled_frame_count": 0}

    pitches: list[float] = []
    confidences: list[float] = []
    for start in starts:
        frame = signal[start:start + frame_size].astype(np.float64, copy=True)
        frame -= float(frame.mean())
        rms = float(np.sqrt(np.mean(frame * frame)))
        if rms < 1e-4:
            continue
        differences = np.empty(max_lag + 1, dtype=np.float64)
        differences[0] = 0.0
        for lag in range(1, max_lag + 1):
            delta = frame[:-lag] - frame[lag:]
            differences[lag] = float(np.dot(delta, delta))
        cumulative = np.cumsum(differences[1:])
        tau = np.arange(1, max_lag + 1, dtype=np.float64)
        cmnd = np.ones(max_lag + 1, dtype=np.float64)
        cmnd[1:] = differences[1:] * tau / np.maximum(cumulative, 1e-20)
        eligible = cmnd[min_lag:max_lag + 1]
        if eligible.size == 0:
            continue
        local = int(np.argmin(eligible))
        lag = min_lag + local
        # Prefer the first meaningful valley, as in the established YIN
        # threshold step; fall back to the best in-band valley conservatively.
        threshold_hits = np.flatnonzero(eligible < .15)
        if threshold_hits.size:
            lag = min_lag + int(threshold_hits[0])
            while lag < max_lag and cmnd[lag + 1] < cmnd[lag]:
                lag += 1
        confidence = max(0.0, min(1.0, 1.0 - float(cmnd[lag])))
        if confidence < .70:
            continue
        refined = float(lag)
        if 1 <= lag < max_lag:
            left, center, right = float(cmnd[lag - 1]), float(cmnd[lag]), float(cmnd[lag + 1])
            denominator = left - 2.0 * center + right
            if abs(denominator) > 1e-12:
                refined += max(-.5, min(.5, .5 * (left - right) / denominator))
        frequency = sample_rate / refined if refined > 0 else 0.0
        if min_f0_hz <= frequency <= max_f0_hz:
            pitches.append(frequency)
            confidences.append(confidence)

    if len(pitches) < 3:
        status = ("unvoiced_or_low_confidence" if not pitches else
                  "insufficient_voiced_coverage")
        median = p10 = p90 = mad = semitone_mad = None
        confidence_median = None
    else:
        ordered = sorted(pitches)
        median = _percentile(ordered, .5)
        p10, p90 = _percentile(ordered, .1), _percentile(ordered, .9)
        deviations = [abs(value - float(median)) for value in ordered]
        mad = _percentile(deviations, .5)
        semitones = [12.0 * math.log2(value / float(median)) for value in ordered]
        semitone_mad = _percentile(sorted(abs(value) for value in semitones), .5)
        confidence_median = _percentile(confidences, .5)
        status = "measured"
    return {
        "feature_version": PITCH_FEATURE_VERSION,
        "method": "YIN difference function with CMND threshold and parabolic refinement",
        "status": status,
        "f0_median_hz": median,
        "f0_p10_hz": p10,
        "f0_p90_hz": p90,
        "f0_mad_hz": mad,
        "f0_mad_semitones": semitone_mad,
        "confidence_median": confidence_median,
        "voiced_frame_count": len(pitches),
        "sampled_frame_count": len(starts),
        "confidence_threshold": .70,
        "identity_score": None,
    }


def analyze_spectral_f32le(pcm: bytes, *, sample_rate: int = 16000,
                           frame_ms: int = 30, hop_ms: int = 10,
                           max_frames: int = 120, mel_bands: int = 26,
                           mfcc_count: int = 13) -> dict:
    """Return bounded descriptive spectrum/MFCC statistics for mono float PCM.

    At most ``max_frames`` evenly spaced frames are analyzed. The ACF HNR
    field is explicitly a rough periodicity proxy and is not used as a quality
    gate. MFCCs and spectral measures are not speaker embeddings or identity
    scores. NumPy is imported lazily; missing NumPy only disables this report.
    """
    if sample_rate <= 0 or frame_ms <= 0 or hop_ms <= 0 or max_frames <= 0:
        raise ValueError("taxa, duração de quadro, salto e limite devem ser positivos")
    if (frame_ms>100 or hop_ms>100 or max_frames>512 or mel_bands<4 or
            mel_bands>80 or mfcc_count<2 or mfcc_count>40 or mfcc_count>mel_bands):
        raise ValueError("configuração de análise espectral inválida ou excede os limites de memória")
    usable=len(pcm)-len(pcm)%4
    if usable==0:
        raise ValueError("PCM vazio")
    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("NumPy é necessário para a análise espectral") from exc
    signal=np.frombuffer(pcm[:usable],dtype="<f4")
    if signal.size==0 or not bool(np.isfinite(signal).all()):
        raise ValueError("PCM vazio ou contém NaN/infinito")
    frame_size=max(16,round(sample_rate*frame_ms/1000))
    hop=max(1,round(sample_rate*hop_ms/1000))
    if signal.size<frame_size:
        return {"feature_version":SPECTRAL_FEATURE_VERSION,
                "status":"too_short","sampled_frame_count":0,
                "spectral_centroid_hz_p50":None,"spectral_rolloff85_hz_p50":None,
                "spectral_flatness_p50":None,"mfcc_median":None,
                "hnr_acf_proxy_db_p50":None,
                "hnr_note":"Unavailable: fewer than one analysis frame."}
    starts=np.arange(0,signal.size-frame_size+1,hop,dtype=np.int64)
    if starts.size>max_frames:
        starts=starts[np.linspace(0,starts.size-1,max_frames,dtype=np.int64)]
    frames=np.asarray(signal[starts[:,None]+np.arange(frame_size)[None,:]],dtype=np.float64)
    frames-=frames.mean(axis=1,keepdims=True)
    rms=np.sqrt(np.mean(frames*frames,axis=1))
    voiced=rms>=1e-4
    if not bool(voiced.any()):
        return {"feature_version":SPECTRAL_FEATURE_VERSION,
                "status":"unvoiced_or_low_energy","sampled_frame_count":int(starts.size),
                "spectral_centroid_hz_p50":None,"spectral_rolloff85_hz_p50":None,
                "spectral_flatness_p50":None,"mfcc_median":None,
                "hnr_acf_proxy_db_p50":None,
                "hnr_note":"Unavailable for silent or near-silent frames."}
    frames=frames[voiced]
    window=np.hanning(frame_size)
    n_fft=1 << (frame_size-1).bit_length()
    spectrum=np.fft.rfft(frames*window[None,:],n=n_fft,axis=1)
    power=np.square(np.abs(spectrum))
    magnitude=np.sqrt(power)
    frequencies=np.fft.rfftfreq(n_fft,1.0/sample_rate)
    magnitude_sum=np.maximum(magnitude.sum(axis=1),1e-20)
    centroid=(magnitude@frequencies)/magnitude_sum
    cumulative=np.cumsum(power,axis=1)
    thresholds=.85*cumulative[:,-1:]
    bins=np.argmax(cumulative>=thresholds,axis=1)
    rolloff=frequencies[bins]
    safe_power=np.maximum(power,1e-20)
    flatness=np.exp(np.mean(np.log(safe_power),axis=1))/np.maximum(np.mean(safe_power,axis=1),1e-20)

    mel_low=2595.0*np.log10(1.0+30.0/700.0)
    mel_high=2595.0*np.log10(1.0+(sample_rate/2.0)/700.0)
    mel_points=np.linspace(mel_low,mel_high,mel_bands+2)
    hz_points=700.0*(np.power(10.0,mel_points/2595.0)-1.0)
    filters=np.zeros((mel_bands,frequencies.size),dtype=np.float64)
    for band in range(mel_bands):
        left,center,right=hz_points[band:band+3]
        filters[band]=np.maximum(0.0,np.minimum(
            (frequencies-left)/max(center-left,1e-12),
            (right-frequencies)/max(right-center,1e-12)))
    log_mel=np.log(np.maximum(power@filters.T,1e-10))
    sample_index=np.arange(mel_bands,dtype=np.float64)+.5
    coefficient_index=np.arange(mfcc_count,dtype=np.float64)[:,None]
    dct=np.cos(np.pi/mel_bands*coefficient_index*sample_index[None,:])
    dct[0]*=math.sqrt(1.0/mel_bands)
    if mfcc_count>1:
        dct[1:]*=math.sqrt(2.0/mel_bands)
    mfcc=log_mel@dct.T

    # HNR proxy via normalized autocorrelation in a broad voiced-pitch band.
    # It is descriptive only: room noise and phonetic content affect it.
    # Zero-pad far enough to obtain the linear (not circular) autocorrelation;
    # the feature-spectrum FFT is too short for reliable period lags.
    acf_fft_size=1 << (2*frame_size-2).bit_length()
    acf_spectrum=np.fft.rfft(frames*window[None,:],n=acf_fft_size,axis=1)
    acf_power=np.square(np.abs(acf_spectrum))
    acf=np.fft.irfft(acf_power,n=acf_fft_size,axis=1)
    acf_zero=np.maximum(acf[:,0],1e-20)
    min_lag=max(1,int(sample_rate/400.0))
    max_lag=min(acf.shape[1]-1,int(sample_rate/65.0))
    periodicity=np.max(acf[:,min_lag:max_lag+1],axis=1)/acf_zero if max_lag>=min_lag else np.array([])
    periodicity=np.clip(periodicity,1e-6,1.0-1e-6)
    hnr=10.0*np.log10(periodicity/(1.0-periodicity)) if periodicity.size else np.array([])

    def stats(values):
        return {"p10":float(np.percentile(values,10)),
                "p50":float(np.percentile(values,50)),
                "p90":float(np.percentile(values,90))}
    hnr_stats=stats(hnr) if hnr.size else {"p10":None,"p50":None,"p90":None}
    return {
        "feature_version":SPECTRAL_FEATURE_VERSION,"status":"measured",
        "method":"hann-windowed rFFT, triangular Mel bank and orthonormal DCT-II",
        "sampled_frame_count":int(starts.size),"voiced_frame_count":int(len(frames)),
        "spectral_centroid_hz":stats(centroid),
        "spectral_centroid_hz_p50":stats(centroid)["p50"],
        "spectral_rolloff85_hz":stats(rolloff),
        "spectral_rolloff85_hz_p50":stats(rolloff)["p50"],
        "spectral_flatness":stats(flatness),
        "spectral_flatness_p50":stats(flatness)["p50"],
        "mfcc_median":[float(value) for value in np.median(mfcc,axis=0)],
        "hnr_acf_proxy_db":hnr_stats,"hnr_acf_proxy_db_p50":hnr_stats["p50"],
        "hnr_note":"Rough autocorrelation periodicity proxy; not calibrated HNR or a quality gate.",
    }
