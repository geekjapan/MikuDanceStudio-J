#!/usr/bin/env python3
"""Write tests/fixtures/pose_cases.txt: the sensor frames, model bones and
options that cxx/harness.cpp and tests/pose_oracle.rs both run.

Usage: tests/cxx/gen_cases.py > tests/fixtures/pose_cases.txt
Deterministic: a fixed seed and no input but this file.
"""
import random
import struct

rng = random.Random(0x4D4B494E)


def h(x):
    return struct.pack(">f", x).hex()


# OpenNI joint id -> name; the order of CaptureSkeletonJoints.
IDS = [
    "Center", "Neck", "Head", "RShoulder", "RElbow", "RWrist", "LShoulder",
    "LElbow", "LWrist", "RHip", "RKnee", "RAnkle", "LHip", "LKnee", "LAnkle",
    "Torso", "RHand", "LHand", "RFoot", "LFoot", "RClavicle", "LClavicle",
    "HeadDir",
]

# A standing performer in millimetres, x to the performer's left.
STAND = {
    "Center": (0, 1000, 2000), "Torso": (0, 1150, 2000), "Neck": (0, 1450, 2000),
    "Head": (0, 1620, 2000), "HeadDir": (0, 1620, 1900),
    "RShoulder": (-200, 1420, 2000), "LShoulder": (200, 1420, 2000),
    "RClavicle": (-100, 1440, 2000), "LClavicle": (100, 1440, 2000),
    "RElbow": (-320, 1180, 1980), "LElbow": (320, 1180, 1980),
    "RWrist": (-380, 930, 1900), "LWrist": (380, 930, 1900),
    "RHand": (-390, 850, 1880), "LHand": (390, 850, 1880),
    "RHip": (-100, 980, 2000), "LHip": (100, 980, 2000),
    "RKnee": (-110, 560, 1990), "LKnee": (110, 560, 1990),
    "RAnkle": (-110, 110, 2000), "LAnkle": (110, 110, 2000),
    "RFoot": (-110, 60, 2120), "LFoot": (110, 60, 2120),
}

LOST = (0.0, -999.0, 0.0)


def pose(noise=3.0, lost=(), tweak=None):
    p = {k: tuple(c + rng.uniform(-noise, noise) for c in v) for k, v in STAND.items()}
    if tweak:
        p.update(tweak(p))
    for k in lost:
        p[k] = LOST
    return p


FULL_BONES = [
    "center", "upper", "neck", "larm", "lelbow", "rarm", "relbow", "lower",
    "lleg", "rleg", "lknee", "rknee", "lik", "rik", "lshoulder", "rshoulder",
    "lankle", "other",
]
BIND_Y = {"lleg": 8.2, "lankle": 1.1}
STALE = {"lik": (1.5, 2.5, 3.5), "rik": (-1.5, 2.5, 3.5)}

out = []


def case(name, frames, version=15, fps=30, mirror=1, lost_bone=0, bones=None, ik=(),
         bind=None):
    bones = bones or FULL_BONES
    bind = BIND_Y if bind is None else bind
    out.append(f"case {name}")
    out.append(f"config {version} {fps} {mirror} {lost_bone}")
    for b in bones:
        y = bind.get(b, -1.0)
        t = STALE.get(b, (0.0, 0.0, 0.0))
        out.append(
            f"bone {b} {h(y)} {h(t[0])} {h(t[1])} {h(t[2])} {h(0)} {h(0)} {h(0)} {h(1)}"
        )
    for b, on in ik:
        out.append(f"ik {b} {on}")
    for record, p in frames:
        out.append(f"frame {record}")
        for i, n in enumerate(IDS):
            x, y, z = p[n]
            out.append(f"j {i} {h(x)} {h(y)} {h(z)}")
    out.append("end")


def run(n, record=lambda i: 0, **kw):
    return [(record(i), pose(**kw)) for i in range(n)]


rec_mid = lambda i: 1 if 2 <= i <= 5 else 0

case("stand_v15", run(8, rec_mid), ik=[("lik", 1), ("rik", 1)])
case("stand_v14", run(6, rec_mid, ), version=14, ik=[("lik", 1), ("rik", 0)])
case("stand_v13", run(6, rec_mid), version=13, ik=[("lik", 0), ("rik", 1)])
case("unmirrored", run(6, rec_mid), mirror=0, ik=[("lik", 1), ("rik", 1)])
case("unmirrored_noik", run(6, rec_mid), mirror=0)
case("fps60", run(10, rec_mid), fps=60, ik=[("lik", 1), ("rik", 1)])
case("fps5_no_smoothing", run(4, rec_mid), fps=5, ik=[("lik", 1), ("rik", 1)])
case("fps400_clamp", run(34, lambda i: 1 if i > 31 else 0), fps=400)
case("no_bind_heights", run(5, rec_mid), bind={}, ik=[("lik", 1), ("rik", 1)])
case("no_center_bone", run(5, rec_mid), bones=[b for b in FULL_BONES if b != "center"],
     ik=[("lik", 1), ("rik", 1)], lost_bone=1, mirror=1)

# Lost joints, with and without the lost-bone option.
case("lost_arms", run(6, rec_mid, lost=("RElbow", "LWrist", "RClavicle")),
     ik=[("lik", 1), ("rik", 1)])
case("lost_arms_reset", run(6, rec_mid, lost=("RElbow", "LWrist", "RClavicle")),
     lost_bone=1, ik=[("lik", 1), ("rik", 1)])
case("lost_legs", run(6, rec_mid, lost=("RKnee", "LAnkle", "LFoot")),
     lost_bone=0, ik=[("lik", 1), ("rik", 1)])
case("lost_legs_reset", run(6, rec_mid, lost=("RKnee", "LAnkle", "LFoot")),
     lost_bone=1, mirror=0, ik=[("lik", 1), ("rik", 1)])
case("lost_torso", run(5, rec_mid, lost=("Torso", "Neck", "Center")), lost_bone=1)
case("lost_all_but_center",
     [(rec_mid(i), {**{k: LOST for k in STAND}, "Center": STAND["Center"]}) for i in range(5)],
     lost_bone=1)
case("lost_right_leg", run(5, rec_mid, lost=("RKnee", "RAnkle", "RHip")), lost_bone=0,
     bind={})
case("lost_only_left_leg", run(5, rec_mid, lost=("RKnee",)), bind={})


def toes_down(p):
    # Foot pointing down and back: the toe-down default branch.
    return {"RFoot": (p["RAnkle"][0], p["RAnkle"][1] - 40, p["RAnkle"][2] - 60),
            "LFoot": (p["LAnkle"][0], p["LAnkle"][1] - 40, p["LAnkle"][2] - 60)}


def toes_flat(p):
    # Foot flat and forward, narrow stance: the "straight" branch.
    return {"RFoot": (p["RAnkle"][0] - 20, p["RAnkle"][1], p["RAnkle"][2] + 150),
            "LFoot": (p["LAnkle"][0] + 20, p["LAnkle"][1], p["LAnkle"][2] + 150)}


def toes_wide(p):
    return {"RFoot": (p["RAnkle"][0] - 200, p["RAnkle"][1], p["RAnkle"][2] + 150),
            "LFoot": (p["LAnkle"][0] + 200, p["LAnkle"][1], p["LAnkle"][2] + 150)}


case("toes_down", run(5, rec_mid, tweak=toes_down), ik=[("lik", 1), ("rik", 1)])
case("toes_flat", run(5, rec_mid, tweak=toes_flat), ik=[("lik", 1), ("rik", 1)])
case("toes_wide", run(5, rec_mid, tweak=toes_wide), ik=[("lik", 1), ("rik", 1)])


def hands_on_wrists(p):
    return {"RHand": p["RWrist"], "LHand": p["LWrist"]}


case("hand_on_wrist", run(5, rec_mid, tweak=hands_on_wrists))


def arms_up(p):
    return {"RElbow": (-250, 1700, 2000), "LElbow": (250, 1700, 2000),
            "RWrist": (-250, 1950, 2000), "LWrist": (250, 1950, 2000),
            "RHand": (-250, 2050, 2000), "LHand": (250, 2050, 2000)}


def leaning(p):
    return {"Torso": (80, 1140, 1950), "Neck": (160, 1430, 1880), "Head": (200, 1590, 1790),
            "RShoulder": (-130, 1400, 1900), "LShoulder": (270, 1400, 1860)}


def kick(p):
    return {"RKnee": (-120, 780, 2200), "RAnkle": (-130, 600, 2550),
            "RFoot": (-130, 560, 2680)}


case("arms_up", run(5, rec_mid, tweak=arms_up), ik=[("lik", 1), ("rik", 0)])
case("leaning", run(5, rec_mid, tweak=leaning), ik=[("lik", 1), ("rik", 0)])
case("kick", run(5, rec_mid, tweak=kick), ik=[("lik", 0), ("rik", 1)])
case("kick_unmirrored", run(5, rec_mid, tweak=kick), mirror=0, ik=[("lik", 0), ("rik", 1)])

# Recording switched on and off at the very first frames; the trace restarts.
case("record_twice", run(9, lambda i: 1 if i in (0, 1, 4, 5, 6) else 0),
     ik=[("lik", 1), ("rik", 1)])
# Fast movement for the smoothing history to carry.
case("walk", [(rec_mid(i), pose(noise=40.0)) for i in range(12)], fps=60,
     ik=[("lik", 1), ("rik", 1)])

print("\n".join(out))
