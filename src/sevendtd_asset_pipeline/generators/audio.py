#!/usr/bin/env python3
"""Report on, convert, and synthesize bundle-ready mono WAV clips.

Uses only the Python standard library, so the audio lane works on a host with
no third-party packages at all. Every subcommand prints the numbers an audio
review needs (duration, channels, rate, peak, RMS) so a change is reviewable
without opening an editor, and writes through a temporary file so a failed run
never leaves a half-written clip in the Unity project.

    shamway generate audio report  clip.wav
    shamway generate audio convert source.wav out.wav --rate 44100 --mono --peak 0.89
    shamway generate audio tone    out.wav --seconds 1.5 --hz 440 --seed 7

7DTD positions sounds in 3D itself, so a stereo clip on a 3D AudioSource is
downmixed anyway; mono is the default for that reason.
"""

from __future__ import annotations

import argparse
import array
import math
import random
import struct
import sys
import wave
from pathlib import Path

from .. import atomic

# The largest magnitude a 16-bit sample can hold, so clamped writes never
# overflow 'h'. Not the dBFS full-scale reference `check-sound` divides by
# (32768.0); the two differ by one LSB on purpose and must not be unified.
PCM_PEAK = 32767


def read_wav(path: Path) -> tuple[array.array[int], int, int]:
    with wave.open(str(path), "rb") as handle:
        if handle.getsampwidth() != 2:
            raise SystemExit(f"ERROR: {path} is not 16-bit PCM; convert it first")
        # A damaged header can declare either field zero; resampling and the
        # duration report below divide by both.
        channels = handle.getnchannels()
        rate = handle.getframerate()
        if channels < 1 or rate < 1:
            raise SystemExit(
                f"ERROR: {path} declares {channels} channel(s) at {rate} Hz; "
                "the WAV header is damaged beyond conversion"
            )
        frames = handle.readframes(handle.getnframes())
        samples = array.array("h")
        samples.frombytes(frames)
        # WAV holds little-endian samples; 'h' is native order, so a big-endian
        # host would convert byte-swapped values without this.
        if sys.byteorder == "big":
            samples.byteswap()
        return samples, channels, rate


def write_wav(path: Path, samples: array.array[int], rate: int, channels: int = 1) -> None:
    with atomic.staged_write(path) as staged, wave.open(str(staged), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        # WAV holds little-endian samples; 'h' is native order. Swap a copy,
        # never the caller's array: it stays in host order for arithmetic.
        payload = samples
        if sys.byteorder == "big":
            payload = array.array("h", samples)
            payload.byteswap()
        handle.writeframes(payload.tobytes())


def describe(path: Path, samples: array.array[int], channels: int, rate: int) -> None:
    frames = len(samples) // channels
    peak = max((abs(value) for value in samples), default=0) / PCM_PEAK
    energy = math.sqrt(sum(value * value for value in samples) / len(samples)) if samples else 0.0
    print(f"path:     {path}")
    print(f"duration: {frames / rate:.3f} s ({frames} frames)")
    print(f"format:   {channels} ch, {rate} Hz, 16-bit PCM")
    print(f"peak:     {peak:.4f} ({20 * math.log10(peak) if peak else -math.inf:.1f} dBFS)")
    print(f"rms:      {energy / PCM_PEAK:.4f}")
    if peak >= 1.0:
        print("WARN: the clip is clipping at full scale", file=sys.stderr)
    if peak < 0.05:
        print("WARN: the clip is nearly silent", file=sys.stderr)


def to_mono(samples: array.array[int], channels: int) -> array.array[int]:
    if channels == 1:
        return samples
    mono = array.array("h")
    for index in range(0, len(samples), channels):
        frame = samples[index : index + channels]
        mono.append(int(sum(frame) / len(frame)))
    return mono


def resample(samples: array.array[int], source_rate: int, target_rate: int) -> array.array[int]:
    """Linear resample. Adequate for conversion; not a mastering-grade filter."""
    if source_rate == target_rate:
        return samples
    ratio = target_rate / source_rate
    count = int(len(samples) * ratio)
    output = array.array("h", bytes(2 * count))
    for index in range(count):
        position = index / ratio
        left = int(position)
        right = min(left + 1, len(samples) - 1)
        weight = position - left
        output[index] = int(samples[left] * (1 - weight) + samples[right] * weight)
    return output


def normalize(samples: array.array[int], peak: float) -> array.array[int]:
    current = max((abs(value) for value in samples), default=0)
    if current == 0:
        return samples
    scale = (peak * PCM_PEAK) / current
    return array.array[int]("h", (max(-PCM_PEAK, min(PCM_PEAK, int(v * scale))) for v in samples))


def decode_bank(bank: Path, out_dir: Path) -> int:
    """Decode every sample in an FSB5 bank to a WAV beside it.

    Two uses, and the second is why it is here rather than in a mod's own
    script. The obvious one is reference listening: the game stores every clip
    as an FSB5 bank inside a `.resource` stream, and hearing a vanilla clip at
    its true rate and channel count settles arguments about level and length.

    The other is that this pipeline *hand-writes* those banks. An encoder read
    back only by the code that wrote it has not been read back, and this is a
    decoder written by someone else — the same reason the block compressor is
    graded with `texture2ddecoder`.
    """
    try:
        import fsb5
    except ImportError:
        print(
            "ERROR: reading an FSB5 bank needs the 'fsb5' capability.\n"
            "       Install it, then retry:  shamway capabilities --json",
            file=sys.stderr,
        )
        return 1

    try:
        parsed = fsb5.FSB5(bank.read_bytes())
    except (OSError, ValueError, IndexError, struct.error) as exc:
        print(f"ERROR: cannot read {bank}: {exc}", file=sys.stderr)
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"bank:    {bank}")
    print(f"mode:    {parsed.header.mode}  samples: {parsed.header.numSamples}")
    for index, sample in enumerate(parsed.samples):
        stem = sample.name or f"sample{index:03d}"
        target = out_dir / f"{stem}.wav"
        try:
            target.write_bytes(parsed.rebuild_sample(sample))
        except Exception as exc:  # noqa: BLE001 - the library raises many types
            # A bank this tool did not write may be Vorbis, which needs the
            # optional decoder. Name the sample rather than aborting the rest.
            print(f"  {stem}: cannot decode ({exc})", file=sys.stderr)
            continue
        print(
            f"  {target.name}: {sample.frequency} Hz, {sample.channels} ch, "
            f"{sample.samples} samples"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    report = commands.add_parser("report", help="print duration, format, peak, and RMS")
    report.add_argument("clip", type=Path)

    convert = commands.add_parser("convert", help="downmix, resample, and normalize a clip")
    convert.add_argument("source", type=Path)
    convert.add_argument("output", type=Path)
    convert.add_argument("--rate", type=int, default=44100)
    convert.add_argument("--mono", action="store_true", default=True)
    convert.add_argument("--stereo", dest="mono", action="store_false")
    convert.add_argument(
        "--peak", type=float, default=0.89, help="normalize to this peak (0 disables)"
    )

    bank = commands.add_parser(
        "from-bank", help="decode an FSB5 bank to WAV, for reference listening"
    )
    bank.add_argument("bank", type=Path, help="an .fsb / .resource stream, or one this tool wrote")
    bank.add_argument("out_dir", type=Path, help="directory to write one WAV per sample into")

    tone = commands.add_parser("tone", help="synthesize a seeded tone/noise placeholder")
    tone.add_argument("output", type=Path)
    tone.add_argument("--seconds", type=float, default=1.0)
    tone.add_argument("--hz", type=float, default=440.0)
    tone.add_argument("--rate", type=int, default=44100)
    tone.add_argument("--noise", type=float, default=0.0, help="0..1 noise mixed with the tone")
    tone.add_argument("--seed", type=int, default=0, help="recorded seed keeps output reproducible")

    args = parser.parse_args(argv)

    if args.command == "report":
        samples, channels, rate = read_wav(args.clip)
        describe(args.clip, samples, channels, rate)
        return 0

    if args.command == "from-bank":
        return decode_bank(args.bank, args.out_dir)

    if args.command == "convert":
        samples, channels, rate = read_wav(args.source)
        if args.mono:
            samples = to_mono(samples, channels)
            channels = 1
        if channels != 1:
            raise SystemExit("ERROR: --stereo resampling of multi-channel audio is not supported")
        samples = resample(samples, rate, args.rate)
        if args.peak > 0:
            samples = normalize(samples, args.peak)
        write_wav(args.output, samples, args.rate, channels)
        describe(args.output, samples, channels, args.rate)
        return 0

    generator = random.Random(args.seed)  # noqa: S311 - seeded waveform noise, not secrets
    count = int(args.seconds * args.rate)
    samples = array.array("h", bytes(2 * count))
    for index in range(count):
        # Cosine fade in and out, so a looping or repeated placeholder does not
        # click at its boundaries.
        envelope = 0.5 - 0.5 * math.cos(2 * math.pi * min(index, count - index) / max(count, 1))
        value = math.sin(2 * math.pi * args.hz * index / args.rate)
        if args.noise:
            value = (1 - args.noise) * value + args.noise * (generator.random() * 2 - 1)
        samples[index] = int(0.8 * PCM_PEAK * envelope * value)
    write_wav(args.output, samples, args.rate)
    print(f"seed: {args.seed}")
    describe(args.output, samples, 1, args.rate)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
