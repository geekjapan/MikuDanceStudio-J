"""Validate measured normal stages and exact float32 texture-dot hypotheses."""
import argparse
import csv
import hashlib
import json
import re
import struct
from collections import defaultdict
from fractions import Fraction
from pathlib import Path


def rows(path):
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


def hash_file(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def f32(value):
    return struct.unpack("<f", struct.pack("<f", float(value)))[0]


def bits(value):
    return struct.unpack("<I", struct.pack("<f", value))[0]


def fused(a, b, c):
    exact = Fraction(a) * Fraction(b) + Fraction(c)
    # These captured operands have a sufficiently narrow exponent range that
    # their exact product + accumulator fits float64. Assert it, rather than
    # silently permitting double-rounding an arbitrary rational through f64.
    if Fraction(float(exact)) != exact:
        raise ValueError("exact fused sum does not fit float64")
    return f32(exact)


def analyze(directory, matrix):
    summary = (directory / "summary.txt").read_text()
    metadata = dict(token.split("=", 1) for token in (directory / "metadata.txt").read_text().split() if "=" in token)
    if "complete=1 observations=54 " not in summary or metadata["originalNormalize"] != "0":
        raise ValueError("incomplete probe / unexpected original normalization state")
    tables = {name: rows(directory / name) for name in ("controls.csv", "pixels.csv", "vertices.csv", "images.csv")}
    hashes = {name: hash_file(directory / name) for name in tables}
    hashes["summary.txt"] = hash_file(directory / "summary.txt")
    groups = defaultdict(list)
    for row in tables["controls.csv"]:
        groups[row["geometry"], row["mode"]].append(row)
    if len(groups) != 18:
        raise ValueError("missing normal/texture controls")
    controls = {}
    for key, group in groups.items():
        if len(group) != 3 or {r["repeat"] for r in group} != {"0", "1", "2"}:
            raise ValueError(f"missing repeat: {key}")
        if any({k: v for k, v in r.items() if k != "repeat"} !=
               {k: v for k, v in group[0].items() if k != "repeat"} for r in group[1:]):
            raise ValueError(f"unstable stats: {key}")
        controls[key] = {k: int(v) for k, v in group[0].items() if k not in ("geometry", "mode", "repeat")}
        for side in ("dx9", "dx11"):
            files = [directory / f"{key[0]}_{key[1]}.repeat{repeat}.{side}.float" for repeat in range(3)]
            values = [hash_file(path) for path in files]
            if len(set(values)) != 1:
                raise ValueError(f"unstable image: {key}/{side}")
            if any(path.stat().st_size != controls[key]["knownPixels"] * 16 for path in files):
                raise ValueError(f"incorrect image size: {key}/{side}")
            hashes.update({path.name: value for path, value in zip(files, values)})
        if controls[key]["betweenApis"] == 0:
            a = directory / f"{key[0]}_{key[1]}.repeat0.dx9.float"
            b = directory / f"{key[0]}_{key[1]}.repeat0.dx11.float"
            if hashes[a.name] != hashes[b.name]:
                raise ValueError("zero-difference claim disagrees with full image bytes")
    for geometry in ("saved", "independent"):
        for mode in ("raw_xy", "raw_z", "normalized_xy", "normalized_z", "toon_fused", "toon_normalized_fused"):
            if controls[geometry, mode]["betweenApis"]:
                raise ValueError(f"expected equal stage differs: {geometry}/{mode}")
        for side in ("dx9", "dx11"):
            if hashes[f"{geometry}_original.repeat0.{side}.float"] != hashes[f"{geometry}_toon_separate.repeat0.{side}.float"]:
                raise ValueError("separate expression did not preserve baseline")
        if hashes[f"{geometry}_original.repeat0.dx9.float"] != hashes[f"{geometry}_toon_fused.repeat0.dx9.float"]:
            raise ValueError("native texture-stage baseline changed")
    if controls["saved", "original"]["betweenApis"] != 15:
        raise ValueError("original 15 UV differences not reproduced")
    vertex = {}
    for row in tables["vertices.csv"]:
        key = row["geometry"], row["mode"], int(row["vertex"])
        value = tuple(float(row[c]) for c in ("x", "y"))
        if key in vertex and vertex[key] != value:
            raise ValueError("unstable vertex stream output")
        if tuple(bits(v) for v in value) != tuple(int(row[c]) for c in ("bitsX", "bitsY")):
            raise ValueError("printed vertex values lost float32 bits")
        vertex[key] = value
    if len(vertex) != 54 or len(tables["vertices.csv"]) != 162:
        raise ValueError("missing vertex-stage evidence")
    predictions = []
    for geometry in ("saved", "independent"):
        for normalized in (False, True):
            xy, z = ("normalized_xy", "normalized_z") if normalized else ("raw_xy", "raw_z")
            baseline = "toon_normalized" if normalized else "original"
            candidate = "toon_normalized_fused" if normalized else "toon_fused"
            for n in range(3):
                normal = (*vertex[geometry, xy, n], vertex[geometry, z, n][0], 1.0)
                for component in range(2):
                    separate = combined = 0.0
                    steps = []
                    for k in range(4):
                        product = f32(normal[k] * matrix[k * 4 + component])
                        separate = f32(separate + product)
                        combined = fused(normal[k], matrix[k * 4 + component], combined)
                        steps.append({"term": "XYZ1"[k], "separate": separate, "fused": combined,
                                      "bitsSeparate": bits(separate), "bitsFused": bits(combined)})
                    if separate != vertex[geometry, baseline, n][component] or combined != vertex[geometry, candidate, n][component]:
                        raise ValueError(f"CPU dot prediction differs from GPU SO: {geometry}/{normalized}/{n}/{component}")
                    predictions.append({"geometry": geometry, "normalized": normalized, "vertex": n,
                                        "component": "UV"[component], "steps": steps,
                                        "finalUlpDistance": abs(bits(separate) - bits(combined)),
                                        "firstDifferentTerm": next((s["term"] for s in steps if s["bitsSeparate"] != s["bitsFused"]), None)})
    image_groups = defaultdict(list)
    for row in tables["images.csv"]:
        image_groups[row["geometry"], row["mode"]].append(row)
    if len(image_groups) != 10:
        raise ValueError("missing final RGBA controls")
    image_report = []
    for key, group in image_groups.items():
        if len(group) != 3 or {r["repeat"] for r in group} != {"0", "1", "2"}:
            raise ValueError("missing byte-image repeats")
        first = group[0]
        if any({k: v for k, v in r.items() if k != "repeat"} !=
               {k: v for k, v in first.items() if k != "repeat"} for r in group[1:]):
            raise ValueError("unstable RGBA observation")
        for side in ("dx9", "dx11"):
            files = [directory / f"{key[0]}_{key[1]}.repeat{repeat}.{side}.rgba" for repeat in range(3)]
            values = [hash_file(path) for path in files]
            if len(set(values)) != 1:
                raise ValueError("unstable complete RGBA image")
            hashes.update({path.name: value for path, value in zip(files, values)})
        if key[1] in ("toon_fused", "toon_normalized_fused"):
            if int(first["differentPixels"]) or hashes[f"{key[0]}_{key[1]}.repeat0.dx9.rgba"] != hashes[f"{key[0]}_{key[1]}.repeat0.dx11.rgba"]:
                raise ValueError("fused coordinate candidate did not restore complete RGBA image")
        image_report.append({"geometry": key[0], "mode": key[1], "differentPixels": int(first["differentPixels"]),
                             "nativeRGBA": [int(first["native" + c]) for c in "RGBA"],
                             "candidateRGBA": [int(first["candidate" + c]) for c in "RGBA"]})
    # The final measured bytecode retains explicit float mul/add for the
    # baseline texture matrix and double product/add with dtof for candidate.
    for policy in range(3):
        listing = (directory / f"vertex{policy}.asm").read_text()
        if policy == 1 and not all(token in listing for token in ("dmul", "dadd", "dtof")):
            raise ValueError("fused candidate instructions were not retained")
        for suffix in ("hlsl", "asm"):
            name = f"vertex{policy}.{suffix}"
            hashes[name] = hash_file(directory / name)
    return {"status": "DIAGNOSTIC_EVIDENCE_VALID", "diagnosticOnly": True, "imageAcceptance": False,
            "productionActivation": False, "originalNormalizationEnabled": False,
            "rawNormalStagesExact": True, "enabledNormalizationControlExact": True,
            "textureDotIsFirstDifferentStage": True, "candidateMatchesNativeObservedUV": True,
            "controls": 18, "observations": 54, "repeats": 3,
            "arithmeticPredictions": predictions, "images": image_report, "evidenceSHA256": hashes,
            "conclusion": "Toon_texture_matrix_z_term_multiply_accumulate_rounding; candidate_matches_observed_native_not_driver_instruction_capture"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--compare", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    text = (args.archive / "history_replay.scene_prefix.draw23.state").read_text()
    line = next(l for l in text.splitlines() if l.startswith("TEXTURE_MATRIX "))
    matrix = [f32(value) for value in re.findall(r"f\d+=([^ ]+)", line)]
    if len(matrix) != 16:
        raise ValueError("texture matrix is incomplete")
    result = analyze(args.input, matrix)
    if args.compare:
        if result != analyze(args.compare, matrix):
            raise ValueError("identical archive differs across architectures")
        result["crossArchitectureExact"] = True
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in ("status", "controls", "observations", "conclusion")}))


if __name__ == "__main__":
    main()
