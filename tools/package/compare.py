#!/usr/bin/env python3
"""Score frame dumps against the golden images by the rule of
rust/crates/mds-app/tests/frame_dump.rs (LIMITS, overlay and score copied from there).

Usage: compare.py <dump dir> <golden dir> <stem> <frame>...
Prints one line per frame as the test does and exits 1 when a frame fails the rule.
"""

import struct
import sys
import zlib
from pathlib import Path

W, H = 640, 360
TOLERANCE, MIN_CLOSE, MAX_DIFF = 4, 0.9999, 48


def read_png(path):
    """8-bit RGBA, not interlaced: the PNGs mds-app and the C++ app write."""
    data = Path(path).read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{path}: not a PNG"
    pos, idat, ihdr = 8, b"", None
    while pos < len(data):
        n, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + n]
        if kind == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            idat += body
        pos += 12 + n
    w, h, depth, color, _, _, interlace = ihdr
    assert (w, h, depth, color, interlace) == (W, H, 8, 6, 0), f"{path}: {ihdr}"
    raw, stride, bpp = zlib.decompress(idat), W * 4, 4
    out, prev = bytearray(), bytearray(stride)
    for y in range(H):
        f, line = raw[y * (stride + 1)], bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b, c = prev[i], prev[i - bpp] if i >= bpp else 0
            if f == 1:
                line[i] = (line[i] + a) & 255
            elif f == 2:
                line[i] = (line[i] + b) & 255
            elif f == 3:
                line[i] = (line[i] + (a + b) // 2) & 255
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        out += line
        prev = line
    return out


def overlay(x, y):
    """The ground line and the bone axis the C++ app draws besides the models."""
    return 320 <= y <= 321 or (x == 320 and y <= 273)


def score(px, gold):
    n = close = mx = total = 0
    for i in range(W * H):
        if overlay(i % W, i // W):
            continue
        d = max(abs(px[i * 4 + c] - gold[i * 4 + c]) for c in range(3))
        n += 1
        close += d <= TOLERANCE
        mx = max(mx, d)
        total += d
    return n, close / n, mx, total / n


def main():
    dump, golden, stem, *frames = sys.argv[1:]
    ok = True
    for f in frames:
        n, close, mx, mean = score(read_png(Path(dump) / f"{stem}-{f}.png"),
                                   read_png(Path(golden) / f"{stem}-{f}.png"))
        good = close >= MIN_CLOSE and mx <= MAX_DIFF
        ok &= good
        print(f"frame {f}: {n} px, within {TOLERANCE} {close:.5f}, max {mx}, mean {mean:.4f}"
              f" {'pass' if good else 'FAIL'}")
    print(f"golden rule (within {TOLERANCE} >= {MIN_CLOSE}, max <= {MAX_DIFF}): "
          f"{'pass' if ok else 'FAIL'}")
    sys.exit(0 if ok else 1)


main()
