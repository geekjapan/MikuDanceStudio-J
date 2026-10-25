#!/usr/bin/env python3
"""Writes the VSQ fixtures and cases.tsv next to this script.

A VSQ is a Standard MIDI File. Track 0 carries tempo, time and key signature;
each singer track carries the VOCALOID sequence as text meta events
("DM:nnnn:" plus up to 119 bytes of an INI-style text) followed by a few
controller and note events. The text lists [EventList], one [ID#nnnn]
section per event, then one [h#nnnn] section per handle, in that order, which
is the order src/io/vsq_load.cpp scans in.

Usage: generate.py   (rewrites every *.vsq and cases.tsv in this directory)
"""
import os
import struct

HERE = os.path.dirname(os.path.abspath(__file__))
JP = "cp932"

# Shift-JIS lyrics.
A, I, U, E, O = (c.encode(JP) for c in "あいうえお")
KA, SHI, TSU, NI, HI, N = (c.encode(JP) for c in "かしつにひん")


def vlq(n):
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.append(0x80 | (n & 0x7F))
        n >>= 7
    return bytes(reversed(out))


def meta(delta, typ, data):
    return vlq(delta) + b"\xff" + bytes([typ, len(data)]) + data


def tempo(delta, usec):
    return meta(delta, 0x51, usec.to_bytes(3, "big"))


def time_sig(delta, nn=4, dd=2):
    return meta(delta, 0x58, bytes([nn, dd, 24, 8]))


def key_sig(delta, sf, minor):
    return meta(delta, 0x59, bytes([sf & 0xFF, 1 if minor else 0]))


def end_of_track(delta=0):
    return meta(delta, 0x2F, b"")


def name(delta, text):
    return meta(delta, 0x03, text)


def text_events(blob, chunk=119):
    out = b""
    for n, i in enumerate(range(0, len(blob), chunk)):
        out += meta(0, 0x01, b"DM:%04d:" % n + blob[i : i + chunk])
    return out


def controller(delta, cc, value):
    return vlq(delta) + bytes([0xB0, cc, value])


def note_pair(delta, length, key=60):
    return vlq(delta) + bytes([0x90, key, 64]) + vlq(length) + bytes([0x80, key, 0])


def track(events):
    body = b"".join(events)
    return b"MTrk" + struct.pack(">I", len(body)) + body


def smf(tracks, division=480, fmt=1, ntracks=None, magic=b"MThd", hdrlen=6):
    n = len(tracks) if ntracks is None else ntracks
    return magic + struct.pack(">IHHH", hdrlen, fmt, n, division) + b"".join(tracks)


def note(tick, length, lyric, phonemes, vibrato=False):
    return dict(tick=tick, length=length, lyric=lyric, phonemes=phonemes, vibrato=vibrato)


def singer_text(notes, eol=b"\n", memo=None):
    """The sequence text: [EventList], [ID#] sections, then [h#] sections."""
    ids, handles = [], []
    hid = 1  # h#0000 is the singer icon handle
    lines = [b"[Common]", b"Version=DSB301", b"Name=Track", b"[EventList]", b"0=ID#0000"]
    for i, n in enumerate(notes, 1):
        lines.append(b"%d=ID#%04d" % (n["tick"], i))
    lines.append(b"EOS")
    ids += [b"[ID#0000]", b"Type=Singer", b"IconHandle=h#0000"]
    for i, n in enumerate(notes, 1):
        lyric_h = hid
        hid += 1
        ids += [b"[ID#%04d]" % i, b"Type=Anote"]
        if memo is not None and i == 1:
            ids.append(memo)
        ids += [b"Length=%d" % n["length"], b"Note#=%d" % (60 + i % 12), b"Dynamics=64"]
        if n["vibrato"]:
            ids.append(b"VibratoHandle=h#%04d" % hid)
        ids.append(b"LyricHandle=h#%04d" % lyric_h)
        handles.append((lyric_h, [b"[h#%04d]" % lyric_h, b'L0="%s","%s",0.000000,64,0,0'
                                  % (n["lyric"], n["phonemes"])]))
        if n["vibrato"]:
            handles.append((hid, [b"[h#%04d]" % hid, b"IconID=$04040001", b"Length=100"]))
            hid += 1
    handles.sort(key=lambda h: h[0])
    handle_lines = [b"[h#0000]", b"IconID=$07010001", b"IDS=MIKU", b"Length=1"]
    for _, ls in handles:
        handle_lines += ls
    return eol.join(lines + ids + handle_lines) + eol


def master(tempos, key=True, extra=()):
    ev = [name(0, b"Master Track"), time_sig(0)]
    if key:
        ev.append(key_sig(0, 0, False))
    last = 0
    for tick, usec in tempos:
        ev.append(tempo(tick - last, usec))
        last = tick
    ev += list(extra)
    ev.append(end_of_track())
    return track(ev)


def singer(blob, chunk=119, pre=(), extra=(), tail=True):
    ev = [name(0, b"Voice1")] + list(pre) + [text_events(blob, chunk)]
    ev += [controller(0, 0x64, 0), controller(10, 0x65, 0)]
    ev += [note_pair(0, 480), note_pair(480, 240)]
    ev += list(extra)
    if tail:
        ev.append(end_of_track())
    return track(ev)


def phonemes_row(items):
    return [note(480 * 4 * (k // 4) + 480 * (k % 4), 360, lyric, ph) for k, (lyric, ph) in enumerate(items)]


T120 = [(0, 500000)]
files = {}
cases = []  # (file, model)


def add(fname, data, models=("full",)):
    files[fname] = data
    for m in models:
        cases.append((fname, m))


FACE_MODELS = ("full", "no-a", "no-i", "no-u", "no-o", "no-a-no-o", "lookalike", "empty")

# ---- valid files ---------------------------------------------------------
basic = [note(1920, 480, A, b"a"), note(2400, 480, I, b"i"), note(2880, 480, U, b"M"),
         note(3360, 480, E, b"e"), note(3840, 480, O, b"o"), note(4320, 480, KA, b"k a", True)]
add("basic.vsq", smf([master(T120), singer(singer_text(basic))]))

vowel_items = [(A, b"a"), (I, b"i"), (U, b"u"), (U, b"M"), (E, b"e"), (O, b"o"),
               (N, b"N"), (N, b"m"), (b"x", b"x"), (b"-", b"h"),
               (A, b"a h"), (E, b"e h"), (O, b"o h"), (I, b"i h"), (U, b"u h"), (U, b"M h"),
               (b"q", b"q r"), (b"zz", b"zz"), (b"w", b"w a"), (b"y", b"j a"),
               (b"hu", b"p\\ M"), (b"hu", b"p\\M"), (b"hu", b"p\\ a"), (b"s", b"s M")]
add("vowels.vsq", smf([master(T120), singer(singer_text(phonemes_row(vowel_items)))]),
    FACE_MODELS)

consonants = ["k'", "S", "tS", "J", "C", "m'", "4'", "g'", "dZ", "b'", "p'", "4", "j", "p\\", "dz", "ts"]
items = [(c.encode(), c.encode() + b" " + v.encode()) for c in consonants for v in "aiuo"]
items += [(b"e", c.encode() + b" e") for c in ("k'", "S", "4")]
add("consonants.vsq", smf([master(T120), singer(singer_text(phonemes_row(items)))]))

tempos = [(0, 500000), (1920, 400000), (3840, 600000), (7680, 300000), (9000, 700000)]
tc = [note(t, 240, A, b"a") for t in (0, 960, 2000, 3000, 4000, 5000, 7000, 8000, 9500, 12000, 20000)]
add("tempo-changes.vsq", smf([master(tempos), singer(singer_text(tc))]))
add("tempo-on-note-tracks.vsq",
    smf([master(T120), singer(singer_text(tc[:6]), pre=[tempo(960, 400000)]),
         singer(singer_text(tc[6:]), pre=[tempo(100, 250000)])]))
add("tempo-after-event-list.vsq",
    smf([master(T120), singer(singer_text(tc[:6]), extra=[tempo(960, 400000)])]))

add("one-track.vsq",
    smf([track([name(0, b"Voice1"), time_sig(0), tempo(0, 428571), text_events(singer_text(basic)),
                end_of_track()])]))

multi = [smf([master(T120)] + [singer(singer_text([note(1920 * (t + 1), 480, A, b"a"),
                                                     note(2400 * (t + 1), 240, O, b"o")]))
                                for t in range(3)])][0]
add("multi-track.vsq", multi)

rests = [note(3840, 240, A, b"a"), note(5000, 120, I, b"i"), note(9000, 480, U, b"M"),
         note(9600, 480, O, b"o")]
add("rests.vsq", smf([master(T120), singer(singer_text(rests))]))

overlap = [note(0, 960, A, b"a"), note(480, 960, I, b"i"), note(600, 100, U, b"M"),
           note(600, 100, O, b"o"), note(1000, 2000, E, b"e")]
add("overlap.vsq", smf([master(T120), singer(singer_text(overlap))]))

long_notes = [note(0, 48000, A, b"a"), note(60000, 480000, O, b"o"), note(600000, 240, I, b"i")]
add("long-notes.vsq", smf([master(T120), singer(singer_text(long_notes))]))

add("empty-track.vsq",
    smf([master(T120), singer(singer_text(basic)), track([end_of_track()]),
         track([name(0, b"Empty"), end_of_track()])]))
add("empty-track-first.vsq",
    smf([master(T120), track([end_of_track()]), singer(singer_text(basic))]))
add("no-notes.vsq", smf([master(T120), singer(singer_text([]))]))
add("crlf.vsq", smf([master(T120), singer(singer_text(basic, eol=b"\r\n"))]))
add("small-chunks.vsq", smf([master(T120), singer(singer_text(basic), chunk=11)]))
add("big-chunks.vsq", smf([master(T120), singer(singer_text(basic), chunk=247)]))
add("long-line.vsq",
    smf([master(T120), singer(singer_text(basic, memo=b"Memo=" + b"x" * 260 + b"Length=7"))]))
add("key-signatures.vsq",
    smf([master(T120, key=False, extra=[key_sig(0, 3, False), key_sig(0, 255, True)]),
         singer(singer_text(basic))]))
add("division-960.vsq", smf([master(T120), singer(singer_text(basic))], division=960))
add("division-smpte.vsq", smf([master(T120), singer(singer_text(basic))], division=0xE728))
add("vibrato.vsq", smf([master(T120), singer(singer_text(
    [note(1920, 480, A, b"a", True), note(2400, 480, I, b"i"), note(2880, 480, O, b"o", True)]))]))

# ---- accepted although the header is wrong -------------------------------
add("bad-magic.vsq", smf([master(T120), singer(singer_text(basic))], magic=b"XXXX"))
add("bad-header-length.vsq", smf([master(T120), singer(singer_text(basic))], hdrlen=0x7F7F))
add("format-0-two-tracks.vsq", smf([master(T120), singer(singer_text(basic))], fmt=0))

# ---- rejected by the C++ with a message box ------------------------------
good = smf([master(T120), singer(singer_text(basic))])
add("trunc-track.vsq", good[: len(good) - 40])
add("trunc-no-end-of-track.vsq", smf([master(T120), singer(singer_text(basic), tail=False)]))
add("ntracks-too-many.vsq", smf([master(T120), singer(singer_text(basic))], ntracks=0xFFFF))
add("sysex.vsq", smf([master(T120), singer(singer_text(basic), extra=[vlq(0) + b"\xf0\x02\x7e\xf7"])]))
add("program-change.vsq", smf([master(T120), singer(singer_text(basic), extra=[vlq(0) + b"\xc0\x05"])]))
add("running-status.vsq", smf([master(T120), singer(singer_text(basic), extra=[vlq(0) + b"\x40\x40"])]))
add("unknown-meta.vsq", smf([master(T120), singer(singer_text(basic), extra=[meta(0, 0x20, b"\x00")])]))
add("sequence-number.vsq",
    smf([track([vlq(0) + b"\xff\x00\x02\x00\x01", end_of_track()]), singer(singer_text(basic))]))
add("short-text-event.vsq",
    smf([master(T120), track([meta(0, 0x01, b"DM:00"), end_of_track()])]))
add("empty-track-only.vsq", smf([track([end_of_track()])]))

# ---- the C++ never returns -----------------------------------------------
add("empty-file.vsq", b"")
add("trunc-header.vsq", good[:11])
add("header-only.vsq", good[:14])
add("no-event-list.vsq", smf([master(T120), singer(b"[Common]\nVersion=DSB301\n")]))

# ---- the C++ stops with a fault ------------------------------------------
add("one-note.vsq", smf([master(T120), singer(singer_text([note(1920, 480, A, b"a")]))]))
add("long-lyric.vsq", smf([master(T120), singer(singer_text(
    [note(1920, 480, A * 4, b"a"), note(2400, 480, I, b"i")]))]))
add("long-consonant.vsq", smf([master(T120), singer(singer_text(
    [note(1920, 480, A, b"abcdef a"), note(2400, 480, I, b"i")]))]))
add("bad-lyric-line.vsq", smf([master(T120), singer(
    singer_text(basic).replace(b'L0="', b"L0=", 1).replace(b'","a",', b",a,", 1))]))

for fname, data in files.items():
    with open(os.path.join(HERE, fname), "wb") as f:
        f.write(data)
with open(os.path.join(HERE, "cases.tsv"), "w") as f:
    f.write("# file\tmodel (morph table in tools/vsq_check/vsq_check.cpp)\n")
    for fname, model in cases:
        f.write(f"{fname}\t{model}\n")
print(f"wrote {len(files)} files, {len(cases)} cases")
