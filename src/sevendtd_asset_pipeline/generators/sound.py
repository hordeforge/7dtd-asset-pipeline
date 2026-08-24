#!/usr/bin/env python3
"""Synthesize the sound a mod needs, as code, with a recorded seed.

`shamway generate audio` measures and converts clips. This script *creates* them: each
subcommand is one designed voice rather than a generic oscillator, because
"explosion" and "sine wave with noise" are not the same request. Nothing here
is recorded or downloaded, so the script itself is the clip's provenance — the
same role a prompt plays for generated art. Re-running it reproduces the file
byte-for-byte.

    shamway generate sound blast   art/audio/blast-near.wav --seed 7
    shamway generate sound blast   art/audio/blast-far.wav  --seed 7 --distant
    shamway generate sound nuclear-blast art/audio/nuclear-near.wav --seed 7
    shamway generate sound tick    art/audio/fuse-tick.wav
    shamway generate sound whoosh  art/audio/throw.wav --seconds 1.4
    shamway generate sound bomb-whistle art/audio/fall.wav --seconds 4
    shamway generate sound hum     art/audio/generator-loop.wav --loop
    shamway generate sound beep    art/audio/ui-confirm.wav --hz 880 --beeps 2
    shamway generate sound sounds-xml myModBlast --distant myModBlastDistant

Standard library only, so the audio lane works on a bare host. Output is mono
16-bit PCM at 44.1 kHz: Unity imports that without complaint and compresses it
when the bundle is built, and 7DTD positions sounds in 3D itself, so a stereo
clip on a 3D AudioSource is downmixed anyway.

Check the result before importing it:

    shamway check-sound art/audio/blast-near.wav

and listen to it. Deterministic does not mean good.
"""

from __future__ import annotations

import argparse
import array
import math
import random
import shutil
import sys
import wave
from pathlib import Path

from .. import atomic

RATE = 44100

# The largest magnitude a 16-bit sample can hold, so clamped writes never
# overflow 'h'. Not the dBFS full-scale reference `check-sound` divides by
# (32768.0); the two differ by one LSB on purpose and must not be unified.
PCM_PEAK = 32767


# ---------------------------------------------------------------- primitives


def seconds(count: float, rate: int = RATE) -> list[float]:
    """A time axis, in seconds, one entry per sample."""
    return [index / rate for index in range(int(count * rate))]


def noise(size: int, generator: random.Random) -> list[float]:
    """White noise in [-1, 1). The generator carries the recorded seed."""
    return [generator.random() * 2.0 - 1.0 for _ in range(size)]


def lowpass(
    samples: list[float], cutoff_hz: float, rate: int = RATE, passes: int = 1
) -> list[float]:
    """One-pole IIR low-pass, applied `passes` times for a steeper roll-off.

    Deliberately the simplest filter that does the job: an explosion's rumble
    and a distant thud are shaped by *how much* high frequency is gone, not by
    the precision of the transition band.
    """
    alpha = 1.0 - math.exp(-2.0 * math.pi * cutoff_hz / rate)
    for _ in range(passes):
        accumulator = 0.0
        output = []
        for value in samples:
            accumulator += alpha * (value - accumulator)
            output.append(accumulator)
        samples = output
    return samples


def highpass(samples: list[float], cutoff_hz: float, rate: int = RATE) -> list[float]:
    low = lowpass(samples, cutoff_hz, rate)
    return [value - filtered for value, filtered in zip(samples, low, strict=True)]


def envelope(times: list[float], attack: float, decay: float, power: float = 1.0) -> list[float]:
    """Linear attack into an exponential decay, the shape most impacts have."""
    attack = max(attack, 1e-6)
    return [
        (min(time / attack, 1.0) * math.exp(-max(time - attack, 0.0) / decay)) ** power
        for time in times
    ]


def fade_tail(samples: list[float], length: float, rate: int = RATE) -> list[float]:
    """Fade the last `length` seconds to zero so the clip cannot end on a step."""
    count = min(int(length * rate), len(samples))
    if count <= 0:
        return samples
    start = len(samples) - count
    return [
        value if index < start else value * (len(samples) - index) / count
        for index, value in enumerate(samples)
    ]


def remove_dc(samples: list[float], cutoff_hz: float = 12.0, rate: int = RATE) -> list[float]:
    """Strip DC and infrasound from a finished mix.

    Anything below about 20 Hz is inaudible on the speakers a player has, but
    it is not free: it moves the waveform off centre, so the normalizer spends
    headroom on it and the clip clicks when playback starts. Long low-frequency
    layers — a filtered random walk, a sub-bass sweep — reliably leave some
    behind, which `shamway check-sound` reports as a DC offset.
    """
    return highpass(samples, cutoff_hz, rate)


def normalize(samples: list[float], peak_db: float = -1.0) -> list[float]:
    peak = max((abs(value) for value in samples), default=0.0) or 1.0
    target = 10 ** (peak_db / 20.0)
    return [value / peak * target for value in samples]


def compress(samples: list[float], threshold: float = 0.18, ratio: float = 3.0) -> list[float]:
    """Reduce peak-to-body range without waveshaping the waveform."""
    release = math.exp(-1.0 / (RATE * 0.06))
    envelope_value = 0.0
    gain_value = 1.0
    output = []
    for sample in samples:
        level = abs(sample)
        coefficient = 0.0 if level > envelope_value else release
        envelope_value = coefficient * envelope_value + (1.0 - coefficient) * level
        if envelope_value <= threshold:
            target_gain = 1.0
        else:
            compressed_level = threshold + (envelope_value - threshold) / ratio
            target_gain = compressed_level / envelope_value
        gain_coefficient = 0.0 if target_gain < gain_value else release
        gain_value = gain_coefficient * gain_value + (1.0 - gain_coefficient) * target_gain
        output.append(sample * gain_value)
    return output


def mix(*layers: tuple[float, list[float]]) -> list[float]:
    """Sum weighted layers, tolerating different lengths."""
    length = max(len(samples) for _, samples in layers)
    output = [0.0] * length
    for weight, samples in layers:
        for index, value in enumerate(samples):
            output[index] += weight * value
    return output


def loopable(samples: list[float], crossfade: float = 0.25, rate: int = RATE) -> list[float]:
    """Make a clip loop without a seam by crossfading its tail over its head.

    The result is shorter than the input by the crossfade length. Do this for
    anything a sound group loops; a click at the loop point is the single most
    recognisable sign of a mod-made ambience.
    """
    count = int(crossfade * rate)
    if count <= 0 or count * 2 >= len(samples):
        return samples
    head, tail = samples[:count], samples[-count:]
    blended = [
        tail[index] * (1.0 - index / count) + head[index] * (index / count)
        for index in range(count)
    ]
    return blended + samples[count:-count]


# ------------------------------------------------------------------- voices


def blast(duration: float, generator: random.Random, distant: bool) -> list[float]:
    """A large explosion, near-field or heard kilometres away.

    The two are the same event, not two sounds: near has the broadband crack
    and the sub-bass pressure sweep, distant has neither, because air absorbs
    high frequencies over distance and the shock front arrives as a swell.
    Generate both from one seed and wire them as a sound group's clip and its
    `DistantClip` — see `shamway generate sound sounds-xml`.
    """
    times = seconds(duration)
    white = noise(len(times), generator)

    brown = []
    accumulator = 0.0
    for value in white:
        accumulator += value
        brown.append(accumulator)
    # Remove the random walk's drift, which is DC offset by another name.
    drift_start, drift_end = brown[0], brown[-1]
    span = max(len(brown) - 1, 1)
    brown = [
        value - (drift_start + (drift_end - drift_start) * index / span)
        for index, value in enumerate(brown)
    ]
    scale = max((abs(value) for value in brown), default=1.0) or 1.0
    brown = [value / scale for value in brown]

    if distant:
        rumble = lowpass(brown, 70.0, passes=3)
        peak = max((abs(value) for value in rumble), default=1.0) or 1.0
        onset = envelope(times, 0.6, duration * 0.37, power=0.8)
        rumble = [
            value
            / peak
            * shape
            * (
                1.0
                + 0.45
                * math.sin(2 * math.pi * 0.35 * time)
                * math.sin(2 * math.pi * 0.11 * time + 0.7)
            )
            for value, shape, time in zip(rumble, onset, times, strict=True)
        ]
        # A faint delayed thud, so there is *some* transient at distance.
        thud_shape = envelope([max(time - 0.45, 0.0) for time in times], 0.01, 0.12)
        thud = [
            value * shape for value, shape in zip(lowpass(white, 400.0), thud_shape, strict=True)
        ]
        return normalize(remove_dc(fade_tail(mix((1.0, rumble), (0.35, thud)), 2.5)), -2.0)

    shock_noise = lowpass(white, 4200.0)
    shock = []
    for time, grit in zip(times, shock_noise, strict=True):
        positive = math.exp(-time / 0.035)
        negative = 0.55 * math.exp(-(time - 0.05) / 0.065) if time >= 0.05 else 0.0
        shock.append((positive - negative) * 0.72 + grit * math.exp(-time / 0.09) * 0.28)

    # Pressure wave: an exponential sweep from 70 Hz to 22 Hz over three
    # seconds. Below about 25 Hz it is felt more than heard, which is the point.
    start_hz, end_hz, sweep_length = 70.0, 22.0, 3.0
    rate_constant = math.log(end_hz / start_hz) / sweep_length
    sweep = []
    for time, shape in zip(times, envelope(times, 0.03, 2.2, power=1.2), strict=True):
        held = min(time, sweep_length)
        phase = 2 * math.pi * start_hz * (math.exp(rate_constant * held) - 1.0) / rate_constant
        if time > sweep_length:
            phase += 2 * math.pi * end_hz * (time - sweep_length)
        sweep.append(math.sin(phase) * shape)

    rumble = lowpass(brown, 110.0, passes=2)
    peak = max((abs(value) for value in rumble), default=1.0) or 1.0
    rumble = [
        value
        / peak
        * shape
        * (
            1.0
            + 0.35 * math.sin(2 * math.pi * 0.7 * time + 1.0) * math.sin(2 * math.pi * 0.23 * time)
        )
        for value, shape, time in zip(
            rumble, envelope(times, 0.12, duration * 0.33, power=0.9), times, strict=True
        )
    ]
    body_band = lowpass(highpass(white, 45.0), 850.0, passes=2)
    body = [
        value * min(time / 0.02, 1.0) * math.exp(-time / 1.5)
        for value, time in zip(body_band, times, strict=True)
    ]
    reflected = [0.0] * len(times)
    offset = int(0.28 * RATE)
    for index in range(offset, len(times)):
        age = (index - offset) / RATE
        reflected[index] = body_band[index - offset] * math.exp(-age / 0.22)

    fracture_band = lowpass(highpass(white, 700.0), 6800.0, passes=2)
    fracture = [
        value
        * min(time / 0.003, 1.0)
        * math.exp(-time / 0.28)
        * (0.76 + 0.24 * math.sin(2.0 * math.pi * (37.0 * time + 8.0 * time * time)))
        for value, time in zip(fracture_band, times, strict=True)
    ]
    fracture_returns = [0.0] * len(times)
    for delay, gain in ((0.16, 0.42), (0.39, 0.24)):
        delay_samples = int(delay * RATE)
        for index in range(delay_samples, len(times)):
            fracture_returns[index] += fracture[index - delay_samples] * gain

    thunder_band = lowpass(highpass(white, 38.0), 460.0, passes=2)
    thunder = []
    for value, time in zip(thunder_band, times, strict=True):
        age = max(time - 0.12, 0.0)
        shape = 0.0 if time < 0.12 else min(age / 0.08, 1.0) * math.exp(-age / 1.45)
        thunder.append(value * shape * (0.78 + 0.22 * math.sin(2.0 * math.pi * 2.1 * age)))

    mixed = mix(
        (0.82, shock),
        (0.86, sweep),
        (0.78, body),
        (0.38, reflected),
        (0.72, fracture),
        (0.48, fracture_returns),
        (0.88, thunder),
        (0.72, rumble),
    )
    return normalize(remove_dc(fade_tail(compress(mixed), 1.5)))


def nuclear_blast(duration: float, generator: random.Random) -> list[float]:
    """A near nuclear detonation, not a peak-boosted generic impact.

    A broad pressure wall is followed by separated terrain returns and a dense
    low-mid coda. Infrasonic identity is shifted into the audible low band so
    the result survives ordinary speakers and a game's positional mixer.
    """
    times = seconds(duration)
    white = noise(len(times), generator)

    pressure_noise = lowpass(highpass(white, 120.0), 5200.0)
    shock = []
    boom = []
    boom_phase = 0.0
    pressure_crack = []
    for time, grit in zip(times, pressure_noise, strict=True):
        positive = math.exp(-time / 0.075)
        negative_time = max(time - 0.085, 0.0)
        negative = 0.72 * math.exp(-negative_time / 0.12) if time >= 0.085 else 0.0
        shock.append((positive - negative) * 0.65)

        # The boom is its own long pressure wave. Its second harmonic keeps the
        # descending low fundamental audible on ordinary speakers and through
        # positional game mixers. The short crack sits above it; it must never
        # consume the headroom and reduce the whole detonation to a dry thump.
        progress = min(time / 2.4, 1.0)
        boom_hz = 108.0 * ((44.0 / 108.0) ** progress)
        boom_phase += 2.0 * math.pi * boom_hz / RATE
        boom_shape = min(time / 0.055, 1.0) * math.exp(-time / 1.35)
        boom.append(boom_shape * (math.sin(boom_phase) + 0.34 * math.sin(2.0 * boom_phase + 0.25)))
        pressure_crack.append(grit * min(time / 0.0015, 1.0) * math.exp(-time / 0.055))

    shatter_band = lowpass(highpass(white, 650.0), 7800.0, passes=2)
    shatter = [
        value
        * min(time / 0.004, 1.0)
        * math.exp(-time / 0.42)
        * (0.72 + 0.28 * math.sin(2.0 * math.pi * (31.0 * time + 7.0 * time * time)))
        for value, time in zip(shatter_band, times, strict=True)
    ]
    shatter_reflections = [0.0] * len(times)
    for delay, gain in ((0.17, 0.48), (0.36, 0.34), (0.61, 0.22)):
        offset = int(delay * RATE)
        for index in range(offset, len(times)):
            shatter_reflections[index] += shatter[index - offset] * gain

    thunder_band = lowpass(highpass(white, 32.0), 520.0, passes=2)
    thunder = []
    for value, time in zip(thunder_band, times, strict=True):
        age = max(time - 0.16, 0.0)
        shape = 0.0 if time < 0.16 else min(age / 0.11, 1.0) * math.exp(-age / 2.6)
        roll = 0.72 + 0.28 * math.sin(2.0 * math.pi * (1.7 * age + 0.16 * age * age))
        thunder.append(value * shape * roll)

    body = []
    phase_a = phase_b = phase_c = 0.0
    for time in times:
        phase_a += 2 * math.pi * (92.0 - 48.0 * min(time / 3.8, 1.0)) / RATE
        phase_b += 2 * math.pi * (61.0 - 24.0 * min(time / 5.0, 1.0)) / RATE
        phase_c += 2 * math.pi * 113.0 / RATE
        shape = math.exp(-time / 3.2) * min(time / 0.025, 1.0)
        body.append(
            shape
            * (
                0.78 * math.sin(phase_a)
                + 0.52 * math.sin(phase_b + 0.4)
                + 0.18 * math.sin(phase_c + 1.1)
            )
        )

    return_noise = lowpass(white, 900.0)
    returns = [0.0] * len(times)
    for delay, gain, decay in ((0.34, 0.68, 0.16), (0.82, 0.58, 0.24), (1.47, 0.38, 0.34)):
        offset = int(delay * RATE)
        for index in range(offset, len(times)):
            age = (index - offset) / RATE
            returns[index] += return_noise[index - offset] * math.exp(-age / decay) * gain

    low_coda = lowpass(white, 240.0, passes=3)
    mid_coda = lowpass(highpass(white, 180.0), 1600.0, passes=2)
    coda = [
        (1.15 * low + 0.42 * mid) * min(time / 0.18, 1.0) * math.exp(-time / (duration * 0.31))
        for low, mid, time in zip(low_coda, mid_coda, times, strict=True)
    ]

    mixed = mix(
        (0.22, shock),
        (1.40, boom),
        (0.12, pressure_crack),
        (0.72, shatter),
        (0.58, shatter_reflections),
        (1.18, thunder),
        (1.25, body),
        (0.85, returns),
        (1.0, coda),
    )
    return normalize(remove_dc(fade_tail(compress(mixed), 2.0)), -0.2)


def tick(generator: random.Random) -> list[float]:
    """One dry mechanical click: a noise transient exciting short resonances.

    A countdown should sound like a mechanism, not like a beep — this is what
    an item's `SoundTick` wants, played once per `SoundTickDelay`.
    """
    times = seconds(0.09)
    transient = [
        value * shape
        for value, shape in zip(
            noise(len(times), generator), envelope(times, 0.0005, 0.0025), strict=True
        )
    ]
    ring = [
        0.60 * math.sin(2 * math.pi * 2350 * time) * a
        + 0.35 * math.sin(2 * math.pi * 4100 * time) * b
        + 0.25 * math.sin(2 * math.pi * 860 * time) * c
        for time, a, b, c in zip(
            times,
            envelope(times, 0.0005, 0.012),
            envelope(times, 0.0005, 0.006),
            envelope(times, 0.001, 0.018),
            strict=True,
        )
    ]
    knock = [
        math.sin(2 * math.pi * 190 * time) * shape * 0.3
        for time, shape in zip(times, envelope(times, 0.001, 0.02), strict=True)
    ]
    body = highpass(transient, 600.0)
    return normalize(mix((0.8, body), (1.0, ring), (1.0, knock)), -3.0)


def whoosh(duration: float, generator: random.Random) -> list[float]:
    """Filtered noise that rises and falls: a thrown object, a passing shell.

    The pitch cue is the filter sweeping up and back down, not a tone; that is
    what makes it read as movement rather than as wind.
    """
    times = seconds(duration)
    white = noise(len(times), generator)
    bright = lowpass(highpass(white, 220.0), 6000.0)
    dark = lowpass(white, 700.0)
    output = []
    for index, time in enumerate(times):
        position = time / duration
        # Sine hump: closest at the middle of the clip.
        nearness = math.sin(math.pi * position) ** 1.5
        output.append(bright[index] * nearness + dark[index] * (1.0 - nearness) * 0.6)
    shaped = [
        value * shape
        for value, shape in zip(
            output, [math.sin(math.pi * t / duration) ** 1.2 for t in times], strict=True
        )
    ]
    return normalize(remove_dc(fade_tail(shaped, min(0.15, duration * 0.2))), -3.0)


def bomb_whistle(
    duration: float, generator: random.Random, start_hz: float, end_hz: float
) -> list[float]:
    """A descending aerodynamic whistle for a bomb falling past the listener.

    Integrating the changing frequency keeps phase continuous; multiplying a
    sine by a changing frequency would create the wrong instantaneous pitch.
    A restrained turbulent layer keeps the result from reading as a clean
    electronic test tone.
    """
    times = seconds(duration)
    white = noise(len(times), generator)
    air = lowpass(highpass(white, 180.0), 3400.0)
    phase = 0.0
    output: list[float] = []
    for index, time in enumerate(times):
        position = min(time / duration, 1.0)
        # Ease the descent so it reads as a continuous fall rather than a siren.
        frequency = start_hz + (end_hz - start_hz) * (position**1.15)
        phase += 2.0 * math.pi * frequency / RATE
        flutter = 0.88 + 0.08 * math.sin(2.0 * math.pi * 3.2 * time)
        tone = math.sin(phase) + 0.24 * math.sin(2.0 * phase + 0.35)
        output.append(tone * flutter + 0.16 * air[index])
    attack = min(int(0.04 * RATE), len(output))
    for index in range(attack):
        output[index] *= index / max(attack, 1)
    return normalize(remove_dc(fade_tail(output, min(0.18, duration * 0.12))), -4.0)


def hum(duration: float, generator: random.Random, base_hz: float, loop: bool) -> list[float]:
    """Electrical hum: a fundamental with harmonics and a little noise on top.

    Use `--loop` for anything a sound group repeats; the crossfade removes the
    seam that otherwise ticks once per cycle forever.
    """
    times = seconds(duration + (0.25 if loop else 0.0))
    tone = []
    for time in times:
        value = (
            math.sin(2 * math.pi * base_hz * time)
            + 0.42 * math.sin(2 * math.pi * base_hz * 2 * time + 0.6)
            + 0.22 * math.sin(2 * math.pi * base_hz * 3 * time + 1.4)
            + 0.10 * math.sin(2 * math.pi * base_hz * 5 * time + 2.1)
        )
        # Slow amplitude drift, so it sounds like hardware rather than a synth.
        value *= 1.0 + 0.06 * math.sin(2 * math.pi * 0.7 * time)
        tone.append(value)
    grit = lowpass(noise(len(times), generator), 2200.0)
    output = remove_dc(mix((1.0, tone), (0.12, grit)))
    if loop:
        output = loopable(output)
        return normalize(output, -6.0)
    ramp = int(0.02 * RATE)
    for index in range(min(ramp, len(output))):
        output[index] *= index / ramp
    return normalize(fade_tail(output, 0.05), -6.0)


def beep(hz: float, count: int, generator: random.Random) -> list[float]:
    """A short electronic cue, optionally repeated. For UI and warnings."""
    single = seconds(0.11)
    shape = envelope(single, 0.004, 0.045)
    body = [
        (math.sin(2 * math.pi * hz * time) + 0.25 * math.sin(2 * math.pi * hz * 2 * time)) * value
        for time, value in zip(single, shape, strict=True)
    ]
    gap = [0.0] * int(0.07 * RATE)
    output: list[float] = []
    for index in range(max(count, 1)):
        output.extend(body)
        if index < count - 1:
            output.extend(gap)
    return normalize(fade_tail(output, 0.02), -3.0)


# -------------------------------------------------------------------- output


def write_wav(path: Path, samples: list[float], rate: int = RATE) -> None:
    """Write through a temporary file so a failed run leaves no half-written clip."""
    pcm = array.array(
        "h", (max(-PCM_PEAK, min(PCM_PEAK, int(value * PCM_PEAK))) for value in samples)
    )
    # WAV holds little-endian samples; 'h' is native order, so a big-endian
    # host would write byte-swapped samples without this.
    if sys.byteorder == "big":
        pcm.byteswap()
    with atomic.staged_write(path) as staged, wave.open(str(staged), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm.tobytes())


def describe(path: Path, samples: list[float], rate: int, seed: int) -> None:
    peak = max((abs(value) for value in samples), default=0.0)
    energy = math.sqrt(sum(value * value for value in samples) / len(samples)) if samples else 0.0
    print(f"path:     {path}")
    print(f"seed:     {seed}")
    print(f"duration: {len(samples) / rate:.3f} s ({len(samples)} frames)")
    print(f"format:   1 ch, {rate} Hz, 16-bit PCM")
    print(f"peak:     {peak:.4f} ({20 * math.log10(peak) if peak else float('-inf'):.1f} dBFS)")
    print(f"rms:      {energy:.4f}")
    print(f"next:     shamway check-sound {path}   # then listen to it")


SOUNDS_XML = """<configs>
	<append xpath="/Sounds">
		<SoundDataNode name="{group}">
			<AudioSource name="@:Sounds/Prefabs/AudioSource_{source}.prefab" />
			<AudioClip ClipName="#@modfolder({mod}):Resources/{bundle}?{stem}.wav" />{distant}{noise}
		</SoundDataNode>
	</append>
</configs>
"""
DISTANT_LINES = """
			<DistantClip ClipName="#@modfolder({mod}):Resources/{bundle}?{stem}.wav" />
			<DistantFadeStart value="{fade_start}" />
			<DistantFadeEnd value="{fade_end}" />"""
NOISE_LINE = """
			<Noise ID="{group}" range="{range}" volumeScale="1" heardBy="Enemy" />"""

GUIDANCE = """# Paste into Config/sounds.xml, then: shamway validate
#
# DistantFadeStart defaults to -1, meaning never, so a DistantClip without it
# is authored and then never played. Both elements are emitted above whenever
# --distant is given.
#
# The AudioSource prefab decides how far the sound carries at all:
# Audio.Manager.LoadAudio returns nothing past its maxDistance, so a
# kilometre-scale event needs a mod-owned AudioSource in the bundle rather than
# a grenade-scale vanilla one.
#
# <Noise> is deliberately absent unless you pass --noise. It reports the sound
# to the AI director, and a mod sound layered on top of a vanilla event that
# already reports its own noise would call the horde twice for one event.
#
# See docs/authoring/audio.md."""


def sounds_xml(args: argparse.Namespace) -> int:
    group = args.group or args.stem
    distant = (
        DISTANT_LINES.format(
            mod=args.mod,
            bundle=args.bundle,
            stem=args.distant,
            fade_start=args.fade_start,
            fade_end=args.fade_end,
        )
        if args.distant
        else ""
    )
    noise = NOISE_LINE.format(group=group, range=args.range) if args.noise else ""
    print(
        SOUNDS_XML.format(
            group=group,
            source=args.source,
            mod=args.mod,
            bundle=args.bundle,
            stem=args.stem,
            distant=distant,
            noise=noise,
        ),
        end="",
    )
    print(GUIDANCE, file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Every voice takes --seed; record it, and the clip is reproducible.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    def voice(name: str, help_text: str) -> argparse.ArgumentParser:
        sub = commands.add_parser(name, help=help_text)
        sub.add_argument("output", type=Path)
        sub.add_argument(
            "--seed", type=int, default=0, help="recorded seed; keeps output reproducible"
        )
        sub.add_argument(
            "--peak", type=float, default=None, help="override the normalized peak (0..1)"
        )
        sub.add_argument(
            "--promote",
            type=Path,
            default=None,
            help="also write the same bytes here (the bundle copy, under its mod-prefixed stem)",
        )
        return sub

    blast_parser = voice("blast", "large explosion, near-field or distant")
    blast_parser.add_argument(
        "--seconds", type=float, default=None, help="default 11 near, 15 distant"
    )
    blast_parser.add_argument(
        "--distant", action="store_true", help="the same event heard kilometres away"
    )

    nuclear_parser = voice(
        "nuclear-blast", "near nuclear detonation: pressure wall, heavy returns, long coda"
    )
    nuclear_parser.add_argument("--seconds", type=float, default=16.0)

    tick_parser = voice("tick", "one dry mechanical click (an item's SoundTick)")
    tick_parser.add_argument("--repeats", type=int, default=1, help="clicks in the clip")
    tick_parser.add_argument("--interval", type=float, default=1.0, help="seconds between clicks")

    whoosh_parser = voice("whoosh", "a thrown or passing object")
    whoosh_parser.add_argument("--seconds", type=float, default=1.2)

    whistle_parser = voice("bomb-whistle", "a bomb falling with gradually descending pitch")
    whistle_parser.add_argument("--seconds", type=float, default=4.0)
    whistle_parser.add_argument("--start-hz", type=float, default=1100.0)
    whistle_parser.add_argument("--end-hz", type=float, default=360.0)

    hum_parser = voice("hum", "electrical hum for machinery or ambience")
    hum_parser.add_argument("--seconds", type=float, default=3.0)
    hum_parser.add_argument("--hz", type=float, default=60.0, help="mains fundamental")
    hum_parser.add_argument("--loop", action="store_true", help="crossfade into a seamless loop")

    beep_parser = voice("beep", "short electronic cue for UI or warnings")
    beep_parser.add_argument("--hz", type=float, default=880.0)
    beep_parser.add_argument("--beeps", type=int, default=1)

    xml = commands.add_parser("sounds-xml", help="print a Config/sounds.xml entry for a clip")
    xml.add_argument("stem", help="the clip's bundle stem, without .wav")
    xml.add_argument("--group", help="sound group name; defaults to the stem")
    xml.add_argument("--mod", default="MyMod", help="ModInfo.xml Name")
    xml.add_argument("--bundle", default="mymod.unity3d", help="bundle filename")
    xml.add_argument("--distant", help="stem of the distant variant, if any")
    xml.add_argument(
        "--fade-start",
        type=int,
        default=120,
        help="metres past which the distant clip plays (default -1 in game means never)",
    )
    xml.add_argument(
        "--fade-end", type=int, default=200, help="metres past which the near clip stops"
    )
    xml.add_argument(
        "--source",
        default="Explosion",
        help="vanilla AudioSource prefab suffix, e.g. Explosion, Impact, UseAction, UI_Item, Interact",
    )
    xml.add_argument(
        "--noise",
        action="store_true",
        help="also report this sound to the AI director; omit when layering on a vanilla "
        "event that already reports its own",
    )
    xml.add_argument("--range", type=int, default=40, help="AI noise range in metres")

    args = parser.parse_args(argv)
    if args.command == "sounds-xml":
        return sounds_xml(args)

    generator = random.Random(args.seed)  # noqa: S311 - seeded waveform noise, not secrets
    if args.command == "blast":
        duration = args.seconds or (15.0 if args.distant else 11.0)
        samples = blast(duration, generator, args.distant)
    elif args.command == "nuclear-blast":
        if args.seconds < 8.0:
            raise SystemExit("ERROR: a nuclear-blast needs at least 8 seconds for its coda")
        samples = nuclear_blast(args.seconds, generator)
    elif args.command == "tick":
        one = tick(generator)
        if args.repeats > 1:
            gap = [0.0] * max(int(args.interval * RATE) - len(one), 0)
            samples = []
            for index in range(args.repeats):
                samples.extend(one)
                if index < args.repeats - 1:
                    samples.extend(gap)
        else:
            samples = one
    elif args.command == "whoosh":
        samples = whoosh(args.seconds, generator)
    elif args.command == "bomb-whistle":
        if args.seconds <= 0 or args.start_hz <= 0 or args.end_hz <= 0:
            raise SystemExit("ERROR: duration and whistle frequencies must be positive")
        if args.end_hz >= args.start_hz:
            raise SystemExit("ERROR: --end-hz must be lower than --start-hz")
        samples = bomb_whistle(args.seconds, generator, args.start_hz, args.end_hz)
    elif args.command == "hum":
        samples = hum(args.seconds, generator, args.hz, args.loop)
    elif args.command == "beep":
        samples = beep(args.hz, args.beeps, generator)
    else:  # pragma: no cover - argparse rejects anything else
        raise SystemExit(f"ERROR: unknown voice {args.command}")

    if args.peak is not None:
        if not 0 < args.peak <= 1:
            raise SystemExit("ERROR: --peak must be between 0 and 1")
        samples = normalize(samples, 20 * math.log10(args.peak))
    write_wav(args.output, samples)
    describe(args.output, samples, RATE, args.seed)
    if args.promote is not None:
        # Promote from the generator, never by hand: the shipped clip is then
        # the recorded design by construction, and cannot drift from it.
        args.promote.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(args.output, args.promote)
        print(f"promoted: {args.promote} (byte-identical)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
