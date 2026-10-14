"""Measures BPM and energy by listening to a track's 30 s preview.

Spotify no longer provides BPM to new apps, and Deezer's BPM is almost always
zero or wrong, so we measure it ourselves. No numpy: onset envelope
in two bands (lows and highs) + autocorrelation, with a perceptual preference
around 120 BPM to reduce "half/double" errors.

Decoding MP3 requires the optional `miniaudio` package (pip install miniaudio).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

SAMPLE_RATE = 11025
HOP = 256
FPS = SAMPLE_RATE / HOP
MIN_BPM, MAX_BPM = 55.0, 200.0
LOW_CUTOFF_HZ = 150.0
PREFERRED_BPM = 120.0
PREFERENCE_OCTAVES = 1.0


@dataclass(frozen=True)
class Analysis:
    bpm: float
    confidence: float  # 0..1: how pronounced the beat is
    energy: float  # 0..1: loudness + onset density


def available() -> bool:
    try:
        import miniaudio  # noqa: F401
    except ImportError:
        return False
    return True


def decode_mp3(data: bytes) -> Sequence[int]:
    import miniaudio

    decoded = miniaudio.decode(
        data,
        output_format=miniaudio.SampleFormat.SIGNED16,
        nchannels=1,
        sample_rate=SAMPLE_RATE,
    )
    return decoded.samples


def measure(mp3: bytes) -> Analysis | None:
    """Decodes and analyzes. Module-level function so it can run in a ProcessPoolExecutor."""
    return analyze(decode_mp3(mp3))


def analyze(samples: Sequence[int]) -> Analysis | None:
    """None when the audio is too short or too quiet to measure."""
    low_energy, high_energy, full_energy = _band_energies(samples)
    if len(full_energy) < FPS * 8 or max(full_energy) < 1e-7:
        return None
    envelope = [
        low + high
        for low, high in zip(_onsets(low_energy), _onsets(high_energy))
    ]
    bpm, confidence = _tempo(envelope)
    return Analysis(round(bpm, 1), round(confidence, 3), round(_energy(full_energy, envelope), 3))


def _band_energies(samples: Sequence[int]) -> tuple[list[float], list[float], list[float]]:
    alpha = 1 - math.exp(-2 * math.pi * LOW_CUTOFF_HZ / SAMPLE_RATE)
    low_state = previous = 0.0
    low_acc = high_acc = full_acc = 0.0
    lows, highs, fulls = [], [], []
    count = 0
    for sample in samples:
        x = sample / 32768.0
        low_state += alpha * (x - low_state)  # 1-pole low-pass: kick drum and bass
        high = x - previous  # 1st difference emphasizes highs: snare and hi-hat
        previous = x
        low_acc += low_state * low_state
        high_acc += high * high
        full_acc += x * x
        count += 1
        if count == HOP:
            lows.append(low_acc / HOP)
            highs.append(high_acc / HOP)
            fulls.append(full_acc / HOP)
            low_acc = high_acc = full_acc = 0.0
            count = 0
    return lows, highs, fulls


def _onsets(energy: list[float]) -> list[float]:
    """Energy rises (in log scale), normalized so one band doesn't dominate the other."""
    logs = [math.log10(e + 1e-9) for e in energy]
    rises = [0.0] + [max(0.0, b - a) for a, b in zip(logs, logs[1:])]
    peak = max(rises) or 1.0
    return [r / peak for r in rises]


def _autocorrelation(envelope: list[float], lag: int) -> float:
    n = len(envelope) - lag
    return sum(envelope[i] * envelope[i + lag] for i in range(n)) / n if n > 0 else 0.0


def _tempo(envelope: list[float]) -> tuple[float, float]:
    mean = sum(envelope) / len(envelope)
    centered = [e - mean for e in envelope]
    zero = _autocorrelation(centered, 0) or 1e-12
    min_lag = int(60 * FPS / MAX_BPM)
    max_lag = int(math.ceil(60 * FPS / MIN_BPM))
    ac = {lag: _autocorrelation(centered, lag) for lag in range(1, max_lag * 2 + 2)}

    def score(lag: int) -> float:
        # A real beat also repeats at twice the period.
        return ac[lag] + 0.5 * ac.get(2 * lag, 0.0)

    def preference(bpm: float) -> float:
        return math.exp(-0.5 * (math.log2(bpm / PREFERRED_BPM) / PREFERENCE_OCTAVES) ** 2)

    best = max(range(min_lag, max_lag + 1), key=lambda lag: score(lag) * preference(60 * FPS / lag))
    # Parabolic interpolation for a fractional period.
    left, mid, right = ac[best - 1], ac[best], ac[best + 1]
    denominator = left - 2 * mid + right
    offset = 0.5 * (left - right) / denominator if denominator else 0.0
    period = best + max(-0.5, min(0.5, offset))
    confidence = max(0.0, min(1.0, mid / zero))
    return 60 * FPS / period, confidence


def _energy(full_energy: list[float], envelope: list[float]) -> float:
    rms_db = 10 * math.log10(sum(full_energy) / len(full_energy) + 1e-12)
    loudness = _scale(rms_db, -32.0, -8.0)
    threshold = sum(envelope) / len(envelope) * 2.5
    peaks = sum(
        1 for a, b, c in zip(envelope, envelope[1:], envelope[2:])
        if b > threshold and b >= a and b > c
    )
    density = _scale(peaks / (len(envelope) / FPS), 0.5, 5.0)
    return 0.6 * loudness + 0.4 * density


def _scale(value: float, low: float, high: float) -> float:
    return max(0.0, min(1.0, (value - low) / (high - low)))
