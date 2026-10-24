#!/usr/bin/env python3
"""Join `mds-fx reflect` with the fx_reflect.exe JSON (RM-3) per file and report differences.

  fx_reflect_compare.py --d3dx fx-reflect.txt [--corpus DIR] [--bin mds-fx] [--summary]

DIR holds the ray-mmd checkout (default $MDS_CORPUS, or $TMPDIR/mds-corpus). The repo's
res/assets stands in for C:\\mds\\repo\\res\\assets. Prints one line per difference, then a
count per difference class. Exit status 1 when any difference remains.
"""
import argparse
import collections
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def local_path(win, corpus):
    low = win.replace("\\", "/")
    for marker, base in (("/corpus/", corpus), ("/repo/", REPO)):
        i = low.lower().find(marker)
        if i >= 0:
            return resolve_ci(base, low[i + len(marker):])
    return None


def resolve_ci(base, rel):
    cur = Path(base)
    for part in rel.split("/"):
        hit = None
        if (cur / part).exists():
            hit = cur / part
        else:
            for e in os.listdir(cur):
                if e.lower() == part.lower():
                    hit = cur / e
                    break
        if hit is None:
            return None
        cur = hit
    return cur


def text(s):
    """D3DX strings hold one char per raw byte; decode as mds-fx does (UTF-8, else Shift-JIS)."""
    raw = s.encode("latin-1")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp932", errors="replace")


def norm_value(v):
    return text(v) if isinstance(v, str) else v


def reflect(pairs, binary):
    out = subprocess.run([binary, "reflect"] + [f"{a}={b}" for a, b in pairs],
                         capture_output=True, text=True, check=False).stdout
    return {json.loads(l)["file"]: json.loads(l) for l in out.splitlines()}


SHAPE = ("class", "type", "rows", "columns")


def compare_annotations(owner, d, m, emit):
    dn, mn = [a["name"] for a in d], [a["name"] for a in m]
    if dn != mn:
        emit("annotations.names", f"{owner}: d3dx {dn} mds {mn}")
        return
    for a, b in zip(d, m):
        for f in SHAPE:
            if a[f] != b[f]:
                emit(f"annotation.{f}", f"{owner}.{a['name']}: d3dx {a[f]} mds {b[f]}")
        va, vb = norm_value(a.get("value")), b.get("value")
        if va != vb:
            emit("annotation.value", f"{owner}.{a['name']}: d3dx {va!r} mds {vb!r}")


def compare_file(label, d, m, emit):
    dp, mp = d["parameters"], m["parameters"]
    dnames = [p["name"] for p in dp]
    mnames = {p["name"]: p for p in mp}
    for p in mp:
        if p["name"] not in dnames:
            emit(f"param.extra [{p['declared'].strip()}]", p["name"])
    present = [p for p in mp if p["name"] in dnames]
    for p in dp:
        if p["name"] not in mnames:
            emit(f"param.missing class={p['class']} type={p['type']}", p["name"])
    if [p["name"] for p in present] != [n for n in dnames if n in mnames]:
        emit("param.order", "order of shared parameters differs")
    for p in dp:
        q = mnames.get(p["name"])
        if q is None:
            continue
        if p["semantic"] != q["semantic"]:
            kind = "semantic.case" if p["semantic"].lower() == q["semantic"].lower() else "semantic"
            emit(f"param.{kind}", f"{p['name']}: d3dx {p['semantic']!r} mds {q['semantic']!r}")
        for f in SHAPE + ("elements",):
            if p[f] != q[f]:
                emit(f"param.{f} [{q['declared'].strip()}]", f"{p['name']}: d3dx {p[f]} mds {q[f]}")
        compare_annotations(p["name"], p["annotations"], q["annotations"], emit)
    dt, mt = d["techniques"], m["techniques"]
    if [t["name"] for t in dt] != [t["name"] for t in mt]:
        emit("technique.names", f"d3dx {[t['name'] for t in dt]} mds {[t['name'] for t in mt]}")
        return
    for t, u in zip(dt, mt):
        compare_annotations(f"technique {t['name']}", t["annotations"], u["annotations"], emit)
        if [p["name"] for p in t["passes"]] != [p["name"] for p in u["passes"]]:
            emit("pass.names", f"{t['name']}: d3dx {[p['name'] for p in t['passes']]} "
                               f"mds {[p['name'] for p in u['passes']]}")
            continue
        for p, q in zip(t["passes"], u["passes"]):
            compare_annotations(f"{t['name']}/{p['name']}", p["annotations"], q["annotations"], emit)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--d3dx", required=True)
    ap.add_argument("--corpus", default=os.environ.get("MDS_CORPUS") or str(Path(tempfile.gettempdir()) / "mds-corpus"))
    ap.add_argument("--bin", default=str(REPO / "rust/target/debug/mds-fx"))
    args = ap.parse_args()

    lines = [json.loads(l) for l in open(args.d3dx, encoding="utf-8")]
    files = [l for l in lines if "file" in l]
    pairs, skipped = [], []
    for f in files:
        p = local_path(f["file"], args.corpus)
        (pairs if p else skipped).append((f["file"], str(p)) if p else f["file"])
    mine = reflect(pairs, args.bin)

    classes = collections.defaultdict(lambda: [set(), 0])
    def run(label, d):
        def emit(kind, detail):
            print(f"{label}: {kind}: {detail}")
            classes[kind][0].add(label)
            classes[kind][1] += 1
        m = mine.get(label)
        if m is None:
            emit("file.missing", "no output from mds-fx")
        elif m["result"] != "ok":
            emit("file.error", m["error"])
        elif d["result"] == "ok":
            compare_file(label, d, m, emit)
        else:
            emit("file.d3dx-error", d.get("error", ""))
    for f in files:
        if f["file"] in skipped:
            print(f"{f['file']}: file.skipped: not found locally")
            classes["file.skipped"][0].add(f["file"]); classes["file.skipped"][1] += 1
        else:
            run(f["file"], f)
    n = collections.Counter()
    for f in files:
        n["parameters"] += len(f["parameters"])
        n["annotations"] += sum(len(p["annotations"]) for p in f["parameters"])
        n["techniques"] += len(f["techniques"])
        n["passes"] += sum(len(t["passes"]) for t in f["techniques"])
    print(f"\nfiles: {len(files)}  compared: {len(pairs)}  skipped: {len(skipped)}  d3dx totals: {dict(n)}")
    print("class\tfiles\tcount")
    for k, (fs, n) in sorted(classes.items()):
        print(f"{k}\t{len(fs)}\t{n}")
    print(f"differing files: {len(set().union(*[v[0] for v in classes.values()]) if classes else [])}")
    return 1 if classes else 0


if __name__ == "__main__":
    sys.exit(main())
