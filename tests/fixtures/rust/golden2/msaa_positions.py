#!/usr/bin/env python3
"""Derives the multisample positions of the C++ app from msaa.txt.

    python3 -I tests/fixtures/rust/golden2/msaa_positions.py [msaa.txt]

msaa.txt is the output of --mds-msaa-probe (src/tools/msaa_probe.cpp): per
sample mask, a 64x64 grid of the resolved red value of pixel (i, j) when a
white quad covers everything right of x = i - 1 + (a + 0.5) * step and below
y = j - 1 + (b + 0.5) * step. A sample at offset (sx, sy) from (i, j) is
covered when sx > i - 1 + (a + 0.5) * step, so the covered cells of one sample
form the rectangle a <= A, b <= B, and the sample lies within half a step of
(-1 + (A + 1) * step, -1 + (B + 1) * step).

With the app's own mask, the grid holds the count n of covered samples. The
resolve on the host is gamma-correct: the value is 255 * srgb(n / samples)
(the sRGB encoding of the covered fraction) to within 1, not 255 * n /
samples, so the script reads n through that curve and prints the measured
level of each n. Differencing n over a and b gives how many samples lie at
each grid point. With a single-bit mask it holds one sample, which names
the bit of each position. The script checks that both agree and that the
single bits add up to the full mask, and prints the positions in 1/16 px from
the D3D9 pixel center (the integer coordinate) and from the pixel's top-left
corner, y down. Exits 1 when the data do not fit this model.
"""

import pathlib
import sys


def srgb(linear):
    return 12.92 * linear if linear <= 0.0031308 else 1.055 * linear ** (1 / 2.4) - 0.055

# D3D10.1 standard 8x pattern, in 1/16 px from the pixel center.
STANDARD_8X = [(1, -3), (-1, 3), (5, 1), (-3, -5), (-5, 5), (-7, -1), (3, 7), (7, -7)]


def parse(path):
    device, grid, masks, rows = None, None, [], None
    for line in path.read_text().splitlines():
        word, *rest = line.split()
        if word == "device":
            device = rest
        elif word == "grid":
            grid = (int(rest[0]), float(rest[3]))
        elif word == "mask":
            rows = []
            masks.append((int(rest[0], 16), rows))
        elif word == "row":
            rows.append([int(v) for v in rest[1:]])
    return device, grid, masks


def bounds(values, cells):
    """The (A, B) of a one-sample grid, or None when its covered cells are no
    rectangle a <= A, b <= B (or empty)."""
    lit = {(a, b) for b in range(cells) for a in range(cells) if values[b][a]}
    if not lit:
        return None
    big_a = max(a for a, _ in lit)
    big_b = max(b for _, b in lit)
    full = {(a, b) for a in range(big_a + 1) for b in range(big_b + 1)}
    return (big_a, big_b) if lit == full else None


def main():
    path = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else pathlib.Path(__file__).with_name("msaa.txt"))
    device, (cells, step), masks = parse(path)
    print("device: type %s quality %s, levels %s (color) %s (depth), back buffer %sx%s, "
          "MULTISAMPLEANTIALIAS %s, mask %s" % (device[0], device[1], device[2], device[3],
                                                device[6], device[7], device[8], device[9]))
    samples = int(device[0])
    ok = True

    _, full = masks[0]
    levels = sorted({v for row in full for v in row})
    print("resolved values of the full mask:", levels)
    curve = [255 * srgb(k / samples) for k in range(samples + 1)]

    def count(value):
        k = min(range(samples + 1), key=lambda k: abs(curve[k] - value))
        return k if abs(curve[k] - value) <= 1 else None

    counts = [[count(v) for v in row] for row in full]
    if any(k is None for row in counts for k in row):
        print("FAIL: a full-mask value is not 255 * srgb(n / %d) to within 1" % samples)
        return 1
    print("n, measured value, 255 * n / %d, 255 * srgb(n / %d):" % (samples, samples))
    for k in range(samples + 1):
        measured = sorted({v for row, krow in zip(full, counts) for v, c in zip(row, krow) if c == k})
        print("  %d %s %.2f %.2f" % (k, measured, 255 * k / samples, curve[k]))

    def n(a, b):
        return counts[b][a] if a < cells and b < cells else 0

    def offset(index):
        return -1 + (index + 1) * step  # px from the integer coordinate

    from_counts = []
    for b in range(cells):
        for a in range(cells):
            d = n(a, b) - n(a + 1, b) - n(a, b + 1) + n(a + 1, b + 1)
            if d < 0:
                print("FAIL: negative density at", (a, b))
                ok = False
            from_counts += [(offset(a), offset(b))] * max(d, 0)

    from_bits, total = [], [[0] * cells for _ in range(cells)]
    for mask, grid in masks[1:]:
        for b in range(cells):
            for a in range(cells):
                total[b][a] += grid[b][a]
        rect = bounds(grid, cells)
        if rect is None:
            print("FAIL: mask %x is not one sample" % mask)
            ok = False
            continue
        from_bits.append((mask, offset(rect[0]), offset(rect[1])))
    one = curve[1]
    if any(round(t / one) != k for trow, krow in zip(total, counts) for t, k in zip(trow, krow)):
        print("FAIL: the single bits do not add up to the full mask")
        ok = False
    if sorted(from_counts) != sorted((x, y) for _, x, y in from_bits):
        print("FAIL: the positions from the counts and from the single bits differ")
        ok = False

    print("bit  center (1/16 px)  corner (1/16 px)")
    for mask, x, y in from_bits:
        print("%3d  %4g %4g         %4g %4g" % (mask.bit_length() - 1, x * 16, y * 16, x * 16 + 8, y * 16 + 8))
    found = [(x * 16, y * 16) for _, x, y in from_bits]
    print("the D3D10.1 standard 8x pattern, in bit order:", "yes" if found == STANDARD_8X else "no")
    print("the same set as the standard 8x pattern:", "yes" if sorted(found) == sorted(STANDARD_8X) else "no")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
