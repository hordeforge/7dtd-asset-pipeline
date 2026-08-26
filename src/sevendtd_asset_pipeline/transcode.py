"""Turn source files the standard library cannot read into ones it can.

Two lanes of the editorless writer were narrower than the tools around them.
`audio_clip` reads WAV through the standard `wave` module, so an author whose
source was `.ogg`, `.mp3` or `.flac` had to convert by hand before the bundle
would take it. `texture_2d` reads through Pillow, which covers PNG, JPEG and
TGA but not SVG — and vector source art is exactly what an icon lane wants.

Both gaps close with tools this project already researched and already
declares: **FFmpeg** decodes any audio container to 16-bit PCM WAV, and
**ImageMagick** rasterizes SVG (and PSD, and EXR) to PNG. Neither becomes a
requirement — a WAV or a PNG still needs nothing — but with them installed the
set of files a mod can drop into `assets-src/bundle/` grows to what an author
actually has on disk.

The conversion is always to a temporary file, never over the source: the
editable original is the thing a person signed off on, and a lane that
overwrites it has destroyed the only copy at the higher quality.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .errors import PipelineError
from .workdir import scratch_dir

# What FFmpeg is asked to read. WAV is absent deliberately: the standard
# library already reads it, and routing it through a subprocess would make a
# working lane depend on an optional tool.
AUDIO_SUFFIXES = (".ogg", ".mp3", ".flac", ".aiff", ".aif", ".m4a", ".opus", ".wma")
# What ImageMagick is asked to read. Pillow covers the raster formats; these
# are the ones it does not, led by the vector case.
IMAGE_SUFFIXES = (".svg", ".psd", ".exr", ".webp", ".avif")

FFMPEG_TIMEOUT = 120
MAGICK_TIMEOUT = 120


def _run(command: list[str], timeout: int, what: str) -> None:
    """Run a converter, and fail with its own diagnostics rather than a code."""
    try:
        result = subprocess.run(
            command, check=False, timeout=timeout, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
    except FileNotFoundError as exc:  # pragma: no cover - guarded by the caller
        raise PipelineError(f"{command[0]} is not on PATH: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise PipelineError(f"{command[0]} did not finish converting {what} in {timeout}s") from exc
    if result.returncode != 0:
        output = result.stdout.decode("utf-8", errors="replace").strip().splitlines()
        tail = "\n".join(output[-6:]) if output else "(no output)"
        raise PipelineError(f"{command[0]} could not convert {what}:\n{tail}")


@contextmanager
def as_wav(source: Path, rate: int | None = None) -> Iterator[Path]:
    """Yield `source` as a 16-bit PCM WAV, decoding through FFmpeg if needed.

    A `.wav` is yielded unchanged and costs nothing. Anything in
    `AUDIO_SUFFIXES` is decoded to a temporary file that disappears with the
    context, so the lossy original stays exactly as authored.
    """
    if source.suffix.lower() == ".wav":
        yield source
        return
    if not shutil.which("ffmpeg"):
        raise PipelineError(
            f"{source.name} is not a WAV, and reading it needs FFmpeg, which is not "
            "installed. Install it (shamway script install-tools --with-authoring), "
            "or convert the file to 16-bit PCM WAV first."
        )
    with scratch_dir("audio-") as directory:
        decoded = directory / f"{source.stem}.wav"
        command = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(source)]
        if rate is not None:
            command += ["-ar", str(rate)]
        command += ["-c:a", "pcm_s16le", str(decoded)]
        _run(command, FFMPEG_TIMEOUT, source.name)
        if not decoded.is_file():
            raise PipelineError(f"ffmpeg reported success but wrote no audio for {source.name}")
        yield decoded


@contextmanager
def as_png(source: Path, density: int = 384) -> Iterator[Path]:
    """Yield `source` as a PNG, rasterizing through ImageMagick if needed.

    `density` is the DPI an SVG is rendered at before it is scaled down to an
    atlas cell. Rasterizing at the final size is the standard way to get a
    soft, crawling icon out of clean vector art, so this deliberately renders
    large and lets the cell step handle the downscale with a real resampler.
    """
    if source.suffix.lower() not in IMAGE_SUFFIXES:
        yield source
        return
    magick = shutil.which("magick") or shutil.which("convert")
    if not magick:
        raise PipelineError(
            f"{source.name} needs ImageMagick to rasterize, and it is not installed. "
            "Install it (shamway script install-tools --with-authoring), or export "
            "the source to PNG first."
        )
    with scratch_dir("image-") as directory:
        rendered = directory / f"{source.stem}.png"
        command = [magick]
        if source.suffix.lower() == ".svg":
            command += ["-background", "none", "-density", str(density)]
        command += [str(source), "-strip", str(rendered)]
        _run(command, MAGICK_TIMEOUT, source.name)
        if not rendered.is_file():
            raise PipelineError(f"{magick} reported success but wrote no image for {source.name}")
        yield rendered
