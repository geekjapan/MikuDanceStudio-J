#!/usr/bin/env python3
"""Write the WAV inputs of tools/wave_check and mds-media into a directory.

    python3 tests/fixtures/rust/media/gen_wav.py tests/fixtures/rust/media/wav

Deterministic: the same bytes on every run (a fixed LCG, no clock, no random).
Each file isolates one behavior of src/media/wave_audio.cpp or
src/media/wave_data_chunk.cpp; the README lists what each one covers.
"""
import math
import struct
import sys
from pathlib import Path


def lcg(seed):
    state = seed
    while True:
        state = (state * 1103515245 + 12345) & 0x7FFFFFFF
        yield state >> 8


def pcm(rate, channels, bits, seconds, seed=1):
    """A swept sine with a slow amplitude ramp plus noise, so every column differs."""
    noise = lcg(seed)
    frames = int(rate * seconds)
    out = bytearray()
    for n in range(frames):
        t = n / rate
        amp = 0.15 + 0.8 * (n / max(frames - 1, 1))
        for c in range(channels):
            v = amp * math.sin(2 * math.pi * (180 + 900 * t + 90 * c) * t)
            v += (next(noise) % 2001 - 1000) / 40000.0
            v = max(-1.0, min(1.0, v))
            if bits == 8:
                out.append(int(round(v * 127)) + 128)
            elif bits == 16:
                out += struct.pack("<h", int(round(v * 32767)))
            else:  # 24
                out += int(round(v * 8388607)).to_bytes(3, "little", signed=True)
    return bytes(out)


def chunk(tag, body, pad=True):
    c = tag + struct.pack("<I", len(body)) + body
    return c + (b"\0" if pad and len(body) % 2 else b"")


def fmt(tag, channels, rate, bits, extra=b"", block=None, avg=None):
    block = channels * bits // 8 if block is None else block
    avg = rate * block if avg is None else avg
    return chunk(b"fmt ", struct.pack("<HHIIHH", tag, channels, rate, avg, block, bits) + extra)


def riff(*chunks, form=b"WAVE", magic=b"RIFF"):
    body = form + b"".join(chunks)
    return magic + struct.pack("<I", len(body)) + body


def wav(rate, channels, bits, seconds, *, before=(), seed=1):
    return riff(
        fmt(1, channels, rate, bits),
        *before,
        chunk(b"data", pcm(rate, channels, bits, seconds, seed)),
    )


def files():
    f = {}
    f["pcm8_mono_8000"] = wav(8000, 1, 8, 0.5, seed=1)
    f["pcm8_stereo_11025"] = wav(11025, 2, 8, 0.4, seed=2)
    f["pcm16_mono_11025"] = wav(11025, 1, 16, 0.4, seed=3)
    f["pcm16_stereo_22050"] = wav(22050, 2, 16, 0.3, seed=4)
    f["pcm16_stereo_44100"] = wav(44100, 2, 16, 0.2, seed=5)
    f["pcm24_mono_8000"] = wav(8000, 1, 24, 0.3, seed=6)

    # An odd-sized chunk before data: the pad byte is part of the stream.
    f["odd_chunk_before_data"] = wav(
        8000, 1, 8, 0.3, before=[chunk(b"junk", b"abcde")], seed=7
    )
    # An odd-sized data chunk: size is the declared odd value, pad byte follows.
    odd = pcm(8000, 1, 8, 0.3, seed=8)[:-1]
    f["odd_data_size"] = riff(fmt(1, 1, 8000, 8), chunk(b"data", odd))
    f["list_info_before_data"] = wav(
        11025,
        1,
        16,
        0.3,
        before=[chunk(b"LIST", b"INFO" + chunk(b"INAM", b"title\0") + chunk(b"ISFT", b"gen\0"))],
        seed=9,
    )
    # A LIST text that holds "ddata" (skipped: the scan consumes the second d)
    # and one that holds a real "data" tag (taken: the scan has no chunk walk).
    f["list_ddata_text"] = wav(
        8000, 1, 8, 0.3, before=[chunk(b"LIST", b"INFO" + chunk(b"ICMT", b"ddata!!"))], seed=10
    )
    f["list_decoy_data"] = wav(
        8000,
        1,
        8,
        0.3,
        before=[chunk(b"LIST", b"INFO" + chunk(b"ICMT", b"data" + struct.pack("<I", 64) + b"x" * 40))],
        seed=11,
    )
    # fmt with a cbSize field (18 bytes): the fixed-offset header reads still hold.
    f["fmt_extended"] = riff(
        fmt(1, 1, 8000, 16, extra=struct.pack("<H", 0)),
        chunk(b"data", pcm(8000, 1, 16, 0.3, seed=12)),
    )
    f["empty_data"] = riff(fmt(1, 1, 8000, 8), chunk(b"data", b""))

    f["no_data_chunk"] = riff(fmt(1, 1, 8000, 8), chunk(b"LIST", b"INFO" + chunk(b"INAM", b"x\0")))
    full = wav(8000, 1, 8, 0.5, seed=13)
    f["truncated_data"] = full[: 44 + 2000]  # data claims 4000 bytes, 2000 present
    f["truncated_header"] = full[:30]
    f["truncated_in_data_size"] = full[:38]  # ends inside the data size field
    f["truncated_before_riff_end"] = full[:3]
    f["data_size_negative"] = riff(
        fmt(1, 1, 8000, 8), b"data" + struct.pack("<I", 0xFFFFFFF0) + b"\x80" * 64
    )

    f["format_float"] = riff(
        fmt(3, 1, 8000, 32), chunk(b"data", pcm(8000, 1, 16, 0.1, seed=14))
    )
    f["format_adpcm"] = riff(fmt(2, 1, 8000, 4), chunk(b"data", b"\0" * 64))
    f["not_riff"] = riff(fmt(1, 1, 8000, 8), chunk(b"data", b"\x80" * 64), magic=b"RIFX")
    # A chunk ahead of fmt moves the tag out of the fixed offset the C++ reads.
    f["junk_before_fmt"] = riff(
        chunk(b"JUNK", b"\0" * 8), fmt(1, 1, 8000, 8), chunk(b"data", b"\x80" * 64)
    )
    f["block_align_zero"] = riff(
        fmt(1, 1, 8000, 8, block=0), chunk(b"data", pcm(8000, 1, 8, 0.1, seed=15))
    )
    f["rate_too_low"] = riff(  # avg bytes/s so small that a column holds 0 blocks
        fmt(1, 1, 100, 16, avg=100), chunk(b"data", pcm(100, 1, 16, 0.5, seed=16))
    )
    return f


if __name__ == "__main__":
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    for name, data in files().items():
        (out / f"{name}.wav").write_bytes(data)
