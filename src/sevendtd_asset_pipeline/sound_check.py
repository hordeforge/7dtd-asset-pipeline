"""Offline gate for a clip before it becomes a bundle asset.

The audio lane has the same shape as the mesh lane: a generator writes a file,
and everything that can be known without the game should be known before the
file reaches Unity. What can be known offline is the *format* and the
*measurements* — a clip that is stereo, or 8-bit, or clipping, or two frames of
silence, is broken regardless of how it sounds.

What cannot be known offline is whether it is the right sound, and whether the
player hears it: `Audio.Manager.LoadAudio` returns nothing past the AudioSource
prefab's `maxDistance`, and a sound group's fade ranges decide which clip
plays. Those are listening tests, and this report never claims otherwise.
"""

from __future__ import annotations

import array
import math
import wave
from dataclasses import asdict, dataclass
from pathlib import Path

from .errors import PipelineError

FULL_SCALE = 32768.0
# 7DTD ships 44.1 kHz content and Unity resamples anything else on import; the
# other two are common source rates that survive that path without surprises.
EXPECTED_RATES = (22050, 44100, 48000)


@dataclass(frozen=True)
class SoundReport:
    path: str
    channels: int
    sample_rate: int
    sample_width_bits: int
    frame_count: int
    duration_seconds: float
    peak: float
    peak_dbfs: float | None
    """None for digital silence, where the decibel value is undefined."""
    rms: float
    dc_offset: float
    clipped_samples: int
    leading_silence_seconds: float
    trailing_silence_seconds: float
    problems: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.problems

    def as_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["problems"] = list(self.problems)
        data["notes"] = list(self.notes)
        data["ok"] = self.ok
        return data


def _read(path: Path) -> tuple[list[int], int, int, int]:
    try:
        with wave.open(str(path), "rb") as handle:
            channels = handle.getnchannels()
            width = handle.getsampwidth()
            rate = handle.getframerate()
            frames = handle.readframes(handle.getnframes())
    except (OSError, wave.Error) as exc:
        raise PipelineError(f"cannot read WAV {path}: {exc}") from exc
    if width != 2:
        raise PipelineError(
            f"{path} is {width * 8}-bit PCM; convert it to 16-bit first "
            f"(shamway generate audio convert)"
        )
    # A header can declare either field zero (or negative, which reads back
    # wrapped); every duration and silence measure below divides by them.
    if channels < 1 or rate < 1:
        raise PipelineError(
            f"{path} declares {channels} channel(s) at {rate} Hz; the WAV header "
            "is damaged beyond measurement"
        )
    samples = array.array("h")
    samples.frombytes(frames)
    return list(samples), channels, rate, width * 8


def _silence_edges(mono: list[int], rate: int, floor: float) -> tuple[float, float]:
    threshold = floor * FULL_SCALE
    leading = 0
    while leading < len(mono) and abs(mono[leading]) <= threshold:
        leading += 1
    trailing = 0
    while trailing < len(mono) - leading and abs(mono[len(mono) - 1 - trailing]) <= threshold:
        trailing += 1
    return leading / rate, trailing / rate


def check_sound(
    clip: Path,
    max_seconds: float = 30.0,
    require_mono: bool = True,
    silence_floor: float = 0.002,
) -> SoundReport:
    """Measure a WAV clip and reject the format mistakes a listener cannot fix."""
    clip = Path(clip)
    if not clip.is_file():
        raise PipelineError(f"no such clip: {clip}")
    samples, channels, rate, bits = _read(clip)
    if not samples:
        raise PipelineError(f"{clip} contains no audio frames")

    frames = len(samples) // max(channels, 1)
    mono = samples if channels == 1 else [
        int(sum(samples[index : index + channels]) / channels)
        for index in range(0, len(samples), channels)
    ]
    peak = max(abs(value) for value in mono)
    clipped = sum(1 for value in mono if value >= 32767 or value <= -32767)
    energy = math.sqrt(sum(value * value for value in mono) / len(mono))
    mean = sum(mono) / len(mono)
    leading, trailing = _silence_edges(mono, rate, silence_floor)

    problems: list[str] = []
    notes: list[str] = []
    duration = frames / rate

    if require_mono and channels != 1:
        problems.append(
            f"{channels} channels; 7DTD positions sounds in 3D and downmixes a stereo "
            "clip on a 3D AudioSource, so author mono (pass require_mono=false for a "
            "deliberate 2D UI or music clip)"
        )
    if rate not in EXPECTED_RATES:
        problems.append(
            f"sample rate {rate} Hz is not one of {', '.join(str(r) for r in EXPECTED_RATES)}; "
            "Unity will resample it on import, which is a silent quality change"
        )
    if duration > max_seconds:
        problems.append(
            f"{duration:.2f} s exceeds the {max_seconds:.0f} s limit for a bundle clip; "
            "long ambience belongs in a looping clip, not a one-shot"
        )
    if peak == 0:
        problems.append("the clip is digital silence")
    elif peak / FULL_SCALE < 0.05:
        problems.append(
            f"peak is {20 * math.log10(peak / FULL_SCALE):.1f} dBFS; the clip is effectively "
            "inaudible next to vanilla content, normalize it before shipping"
        )
    if clipped > 0:
        problems.append(
            f"{clipped} sample(s) at full scale; the clip is clipping and will distort "
            "when the mixer adds any gain"
        )
    if abs(mean) / FULL_SCALE > 0.02:
        problems.append(
            f"DC offset {mean / FULL_SCALE:+.3f}; remove it or the clip clicks on start "
            "and steals headroom"
        )
    if leading > 0.25:
        notes.append(
            f"{leading:.2f} s of leading silence; a one-shot triggered by a game event "
            "sounds late by exactly that much"
        )
    if trailing < 0.01 and peak > 0:
        notes.append("no trailing silence; check the end for a click, a fade costs nothing")

    return SoundReport(
        path=str(clip),
        channels=channels,
        sample_rate=rate,
        sample_width_bits=bits,
        frame_count=frames,
        duration_seconds=round(duration, 4),
        peak=round(peak / FULL_SCALE, 5),
        peak_dbfs=round(20 * math.log10(peak / FULL_SCALE), 2) if peak else None,
        rms=round(energy / FULL_SCALE, 5),
        dc_offset=round(mean / FULL_SCALE, 5),
        clipped_samples=clipped,
        leading_silence_seconds=round(leading, 4),
        trailing_silence_seconds=round(trailing, 4),
        problems=tuple(problems),
        notes=tuple(notes),
    )
