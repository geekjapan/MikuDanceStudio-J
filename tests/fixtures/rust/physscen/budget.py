"""Prints the catch-up substeps and the main-step budget of each pump pass of
budget.txt, from PlaybackCatchup (src/app/playback_catchup.cpp, BLOCK 2) in
float32: play from frame 0, a clock that advances `ms` per pass.

    python3 -I tests/fixtures/rust/physscen/budget.py [ms] [passes]
"""
import struct
import sys


def f32(x):
    return struct.unpack("<f", struct.pack("<f", x))[0]


def passes(ms, count, start=0.0):
    tick = f32(1.0 / 60.0)
    cursor = start
    for k in range(1, count + 1):
        target = f32(f32(f32(float(ms * k)) * f32(0.001)) + start)
        budget = f32(f32(float(ms)) * f32(0.001))
        c = f32(cursor + tick)
        substeps = 0
        if target > c:
            while True:
                substeps += 1
                budget = f32(budget - tick)
                c = f32(c + tick)
                if not c < target:
                    break
        cursor = target
        yield k, substeps, budget


if __name__ == "__main__":
    ms = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    rows = list(passes(ms, count))
    assert ms != 50 or count < 11 or rows[10][2] < 0, "pass 11 of 50 ms is negative"
    for k, substeps, budget in rows:
        print(k, substeps, budget.hex())
