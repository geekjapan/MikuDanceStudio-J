#!/usr/bin/env python3
"""Tests for gen_fixtures.py: determinism, magic, version and record counts.

Run: python3 -I tools/fixtures/test_gen_fixtures.py

The expected counts below are written out by hand, not read from the
generator tables, so a wrong table fails here.
"""
import contextlib
import io
import shutil
import struct
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # python3 -I drops the script directory

import gen_fixtures as g  # noqa: E402

FIXTURES = g.DEFAULT_DIR
BONES = ["全ての親", "センター", "上半身", "首", "頭", "髪1", "髪2", "髪3"]
# Bone keys per bone in swing600.vmd (frame 0 key included).
VMD_COUNTS = {"全ての親": 2, "センター": 7, "上半身": 5, "首": 6, "頭": 6,
              "髪1": 9, "髪2": 11, "髪3": 21, "髪ＩＫ": 3}
# Non-head bone keys per bone in swing600.pmm (頭 lost the key at frame 300).
PMM_SPARSE = [1, 6, 4, 5, 5, 8, 10, 20, 2]


class Reader:
    def __init__(self, data, offset=0):
        self.data, self.o = data, offset

    def take(self, n):
        assert self.o + n <= len(self.data), "read past end"
        out = self.data[self.o:self.o + n]
        self.o += n
        return out

    def u8(self):
        return self.take(1)[0]

    def u16(self):
        return struct.unpack("<H", self.take(2))[0]

    def u32(self):
        return struct.unpack("<I", self.take(4))[0]

    def i32(self):
        return struct.unpack("<i", self.take(4))[0]

    def f32(self):
        return struct.unpack("<f", self.take(4))[0]

    def text(self):
        return self.take(self.u8()).decode("cp932")


def cstr(raw):
    return raw.split(b"\0")[0].decode("cp932")


class Determinism(unittest.TestCase):
    def test_two_runs_give_the_same_bytes(self):
        self.assertEqual(g.generate(), g.generate())

    def test_committed_files_match(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(g.main(["--check"]), 0)
        self.assertEqual(out.getvalue().strip(), "fixtures: 8 files match")

    def test_check_names_a_drifted_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copytree(FIXTURES, tmp, dirs_exist_ok=True)
            path = Path(tmp) / "swing600.vmd"
            raw = bytearray(path.read_bytes())
            raw[100] ^= 0xFF
            path.write_bytes(bytes(raw))
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                self.assertEqual(g.main(["--check", "--dir", tmp]), 1)
            self.assertIn("swing600.vmd", err.getvalue())
            self.assertNotIn("chain8", err.getvalue())

    def test_total_size_under_256_kib(self):
        self.assertLess(sum(map(len, g.generate().values())), 256 * 1024)


class Models(unittest.TestCase):
    def setUp(self):
        self.files = g.generate()

    def test_pmd(self):
        r = Reader(self.files["chain8.pmd"])
        self.assertEqual(r.take(3), b"Pmd")
        self.assertEqual(r.f32(), 1.0)
        self.assertEqual(cstr(r.take(20)), "chain8")
        r.take(256)
        self.assertEqual(r.u32(), 16)
        r.take(38 * 16)
        self.assertEqual(r.u32(), 42)
        r.take(2 * 42)
        self.assertEqual(r.u32(), 1)
        r.take(70)
        self.assertEqual(r.u16(), 8)
        names = []
        for _ in range(8):
            names.append(cstr(r.take(20)))
            r.take(19)
        self.assertEqual(names, BONES)  # all 8 names decode as cp932

    def pmx_header(self, name):
        data = self.files[name]
        r = Reader(data)
        self.assertEqual(r.take(4), b"PMX ")
        self.assertEqual(r.f32(), 2.0)
        settings = r.take(9)
        self.assertEqual(settings[0], 8)
        self.assertEqual(settings[1], 0)  # text encoding byte: UTF-16LE
        for _ in range(4):
            length = r.u32()
            self.assertEqual(length % 2, 0)
            r.take(length)
        return data, r, settings

    def test_pmx_header_vertices_and_names(self):
        expect = {"chain8.pmx": 16, "chain8_ik.pmx": 16, "morph4.pmx": 4}
        for name, vertices in expect.items():
            data, r, _ = self.pmx_header(name)
            self.assertEqual(r.u32(), vertices, name)
            at = 0
            bones = BONES + (["髪ＩＫ"] if name == "chain8_ik.pmx" else [])
            if name == "morph4.pmx":
                bones = ["センター", "上半身"]
            for bone in bones:  # each bone name appears once, in order
                raw = struct.pack("<I", 2 * len(bone)) + bone.encode("utf-16-le")
                at = data.index(raw, at) + len(raw)

    def test_pmx_widths_differ_between_files(self):
        widths = {n: self.pmx_header(n)[2][3:] for n in
                  ("chain8.pmx", "chain8_ik.pmx", "morph4.pmx")}
        self.assertEqual(len(set(widths.values())), 3)

    def test_morph4_has_four_vertex_morphs(self):
        data = self.files["morph4.pmx"]
        for name in ("まばたき", "あ", "い", "う"):
            raw = struct.pack("<I", 2 * len(name)) + name.encode("utf-16-le")
            self.assertEqual(data.count(raw), 1)


class Motion(unittest.TestCase):
    def setUp(self):
        self.files = g.generate()

    def test_vmd_counts(self):
        r = Reader(self.files["swing600.vmd"])
        self.assertEqual(r.take(25), b"Vocaloid Motion Data 0002")
        r.take(5)
        self.assertEqual(cstr(r.take(20)), "chain8")
        counts = {}
        for _ in range(r.u32()):
            name = cstr(r.take(15))
            r.u32(), r.take(28 + 64)
            counts[name] = counts.get(name, 0) + 1
        self.assertEqual(counts, VMD_COUNTS)
        self.assertEqual(sum(counts.values()), 70)
        self.assertEqual(r.u32(), 16)       # morph keys
        r.take(16 * 23)
        self.assertEqual(r.u32(), 3)        # camera keys
        r.take(3 * 61)
        self.assertEqual(r.u32(), 2)        # light keys
        r.take(2 * 28)
        self.assertEqual(r.u32(), 2)        # self shadow keys
        r.take(2 * 9)
        self.assertEqual(r.u32(), 4)        # IK keys
        r.take(4 * 30)
        self.assertEqual(r.o, len(r.data))

    def test_vpd_text(self):
        raw = self.files["pose.vpd"]
        self.assertTrue(raw.startswith(b"Vocaloid Pose Data file\r\n\r\n"))
        self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"))  # CRLF only
        text = raw.decode("cp932")
        self.assertIn("3;", text)
        self.assertEqual(text.count("Bone"), 3)
        for bone in ("センター", "首", "髪3"):
            self.assertIn("{" + bone + "\r\n", text)


class Pmm(unittest.TestCase):
    def track(self, r, dense, size):
        """(dense, sparse) records as (index, frame, previous, next)."""
        def rec(index):
            frame, prev, nxt = struct.unpack("<III", r.take(12))
            r.take(size - 12)
            return index, frame, prev, nxt
        heads = [rec(i) for i in range(dense)]
        sparse = []
        for _ in range(r.i32()):
            index = r.i32()
            sparse.append(rec(index))
        return heads, sparse

    def test_pmm_layout_and_counts(self):
        data = g.generate()["swing600.pmm"]
        self.assertEqual(data[:25], b"Polygon Movie maker 0002\0")
        self.assertEqual(data[0x14:0x19], b"0002\0")
        models, _ = self.parse()
        self.assertEqual([m["path"] for m in models], g.PMM_MODELS)
        self.assertEqual([m["slot"] for m in models], [0, 1, 2, 3])
        self.assertEqual([len(m["bones"]) for m in models], [9, 2, 8, 8])
        self.assertEqual([len(m["morphs"]) for m in models], [0, 4, 0, 0])
        self.assertEqual([len(m["ik"]) for m in models], [1, 0, 0, 0])
        self.assertEqual([len(m["selectors"]) for m in models], [4, 2, 3, 3])
        self.assertEqual(models[0]["bones"][:8], BONES)
        self.assertEqual([len(m["morph_track"][1]) for m in models],
                         [0, 12, 0, 0])

    def parse(self, name="swing600.pmm"):
        """Walk the model sections; return the models and the reader."""
        r = Reader(g.generate()[name])
        r.take(30 + 23)
        r.u8()
        count = r.u8()
        models = []
        for _ in range(count):
            m = {"slot": r.u8(), "name": r.text()}
            r.text()
            m["path"] = cstr(r.take(256))
            groups = r.u8()
            m["bones"] = [r.text() for _ in range(r.i32())]
            m["morphs"] = [r.text() for _ in range(r.i32())]
            m["ik"] = [r.i32() for _ in range(r.i32())]
            m["selectors"] = [r.i32() for _ in range(r.i32())]
            r.take(2 + 4 + 16)
            self.assertEqual(r.u8(), groups)
            r.take(groups + 8)
            m["bone_track"] = self.track(r, len(m["bones"]), 58)
            m["morph_track"] = self.track(r, len(m["morphs"]), 17)
            m["display_track"] = self.track(
                r, 1, 14 + len(m["ik"]) + 8 * len(m["selectors"]))
            r.take(31 * len(m["bones"]) + 4 * len(m["morphs"]) + len(m["ik"])
                   + 16 * len(m["selectors"]) + 7)
            models.append(m)
        return models, r

    def test_global_tail_is_consumed_exactly(self):
        models, r = self.parse()
        camera = self.track(r, 1, 78)
        r.take(36 + 1)
        light = self.track(r, 1, 37)
        r.take(24 + 6)                      # light state, empty accessory list
        r.take(28 + 257 + 272 + 269 + 11 + 31)   # timeline .. physics
        gravity = self.track(r, 1, 34)
        r.take(5)
        shadow = self.track(r, 1, 18)
        r.take(92)                          # appearance
        self.assertEqual(r.u8(), 1)
        for slot in range(len(models)):
            self.assertEqual((r.u8(), r.i32()), (slot, 0))
        self.assertEqual(r.o, len(r.data))
        self.assertEqual([len(t[1]) for t in (camera, light, gravity, shadow)],
                         [0, 1, 0, 1])

    def chains(self, heads, sparse):
        """Walk every track; check links and frames. Return per-head chains."""
        by_index = {rec[0]: rec for rec in heads + sparse}
        self.assertEqual(len(by_index), len(heads) + len(sparse))
        seen, out = set(), []
        for head in heads:
            chain, cur = [head], head
            while cur[3]:
                nxt = by_index[cur[3]]
                self.assertEqual(nxt[2], cur[0], "previous disagrees")
                self.assertGreater(nxt[1], cur[1], "frames must increase")
                self.assertNotIn(nxt[0], seen)
                seen.add(nxt[0])
                chain.append(nxt)
                cur = nxt
            self.assertEqual(head[1], 0)
            out.append(chain)
        self.assertEqual(seen, {rec[0] for rec in sparse},
                         "every record is on a track")
        return out

    def test_every_track_is_a_well_formed_chain(self):
        models, _ = self.parse()
        for m in models:
            for key in ("bone_track", "morph_track", "display_track"):
                self.chains(*m[key])

    def test_bone_pool_has_a_gap_inside_one_track(self):
        models, _ = self.parse()
        heads, sparse = models[0]["bone_track"]
        chains = self.chains(heads, sparse)
        self.assertEqual([len(c) - 1 for c in chains], PMM_SPARSE)
        used = {rec[0] for rec in sparse}
        gaps = sorted(set(range(min(used), max(used) + 1)) - used)
        self.assertEqual(len(gaps), 1)
        gap = gaps[0]
        self.assertEqual(gap, 34)  # between index 25 (frame 200) and 46 (400)
        # The gap lies inside bone 4's track: frames 200 and 400 are linked
        # with each other, and no other track holds a key at frame 300 + gap.
        bridges = [(a, b) for a, b in zip(chains[4], chains[4][1:])
                   if a[0] < gap < b[0]]
        self.assertEqual(len(bridges), 1)
        a, b = bridges[0]
        self.assertEqual((a[1], b[1]), (200, 400))   # frame 300 was freed
        self.assertEqual(b[2], a[0])                 # previous bridges the gap
        self.assertEqual(a[3], b[0])                 # next bridges the gap
        self.assertEqual([r[1] for r in chains[4]], [0, 100, 200, 400, 500, 599])

    def test_camera3_has_three_camera_keys_and_three_light_keys(self):
        # Same models as swing600.pmm; only the camera and light tracks differ.
        models, r = self.parse("camera3.pmm")
        base_models, base = self.parse()
        self.assertEqual(models, base_models)
        self.assertEqual(r.o, base.o)
        self.assertEqual(r.data[:r.o], base.data[:base.o])
        camera = self.track(r, 1, 78)
        r.take(36 + 1)
        light = self.track(r, 1, 37)
        r.take(24 + 6)
        r.take(28 + 257 + 272 + 269 + 11 + 31)
        gravity = self.track(r, 1, 34)
        r.take(5)
        shadow = self.track(r, 1, 18)
        r.take(92)
        self.assertEqual(r.u8(), 1)
        for slot in range(len(models)):
            self.assertEqual((r.u8(), r.i32()), (slot, 0))
        self.assertEqual(r.o, len(r.data))
        frames = lambda t: [rec[1] for rec in self.chains(*t)[0]]  # noqa: E731
        self.assertEqual(frames(camera), [0, 200, 400])
        self.assertEqual(frames(light), [0, 300, 450])
        self.assertEqual(frames(gravity), [0])
        self.assertEqual(frames(shadow), [0, 300])


if __name__ == "__main__":
    unittest.main(verbosity=2)
