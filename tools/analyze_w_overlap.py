"""Validate reduced PMM overlap thresholds and fixed clip-input controls.

Reference bits are float32 plane inputs, not native clip captures or raw D24.
"""
import argparse
import csv
import json
from pathlib import Path
import struct
from analyze_accessory_isolation import tags, fnv, f32
from analyze_w_gpu_batch import vertices


PATHS = ("p0", "p1", "p2", "shared1", "shared2")
INSTRUCTIONS = ("native_dp4", "native_dot_z", "native_dot_w", "native_dot_zw")


def rows(path):
    with path.open(newline="") as file:
        data = list(csv.DictReader(file))
    if any(None in row or any(value is None for value in row.values()) for row in data):
        raise ValueError("malformed CSV")
    return data


def plane(clip, viewport, x, y, float_divide=False):
    ox, oy, w, h = viewport
    screen = []
    for p in clip:
        z = p[2]/p[3]
        if float_divide:
            z = struct.unpack("<f", f32(z))[0]
        screen.append((ox+(p[0]/p[3]+1)*w/2, oy+(1-p[1]/p[3])*h/2, z))
    a, b, c = screen
    den = (b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
    if not den:
        raise ValueError("degenerate clip triangle")
    u = ((b[1]-c[1])*(x-c[0])+(c[0]-b[0])*(y-c[1]))/den
    v = ((c[1]-a[1])*(x-c[0])+(a[0]-c[0])*(y-c[1]))/den
    return u*a[2]+v*b[2]+(1-u-v)*c[2], (u, v, 1-u-v)


def bits(value):
    return struct.unpack("<I", f32(value))[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("reference", type=Path)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    directory = args.directory
    trace = (args.reference / "history_replay.dx9").read_text().splitlines()
    region = tags(next(l for l in trace if l.startswith("PORTABLE_REGION ")))
    viewport = [int(region[k]) for k in ("x", "y", "width", "height")]
    ox, oy, w, h = viewport
    width, height = ox+w, oy+h
    state = (args.archive / "history_replay.reduction.draw2.state").read_text().splitlines()
    draw = tags(state[0])
    vb = (directory / "source.vertices").read_bytes()
    ib = (directory / "source.indices").read_bytes()
    native_draw = tags(next(l for l in trace if l.startswith("DRAW sequence=2 ")))
    if vb != (args.archive / "history_replay.reduction.draw2.vertices").read_bytes() or ib != (args.archive / "history_replay.reduction.draw2.indices").read_bytes():
        raise ValueError("reduced source geometry differs from archive")
    if fnv(vb) != int(native_draw["vbVersion"]) or fnv(ib) != int(native_draw["ibVersion"]):
        raise ValueError("archived geometry version differs from application capture")
    for key in ("type", "fvf", "indexed", "base", "minimum", "vertices", "start", "count"):
        if draw[key] != native_draw[key]:
            raise ValueError("draw range differs from application capture")
    if draw["fvf"] != "274" or draw["stride"] != "32" or draw["base"] != "0":
        raise ValueError("unsupported geometry")
    matrix_bytes = b""
    for name, transform in (("WORLD", 256), ("VIEW", 2), ("PROJECTION", 3)):
        fields = tags(next(l for l in state if l.startswith(name+" ")))
        captured = tags(next(l for l in trace if l.startswith(f"MATRIX sequence=2 transform={transform} ")))
        block = b"".join(f32(fields[f"f{k}"]) for k in range(16))
        if block != b"".join(f32(captured[f"m{k}"]) for k in range(16)):
            raise ValueError("archived transform differs from application capture")
        matrix_bytes += block
    if (directory / "source.matrices").read_bytes() != matrix_bytes:
        raise ValueError("measured source transform changed")
    observed_states = tags(next(l for l in trace if l.startswith("STATE sequence=2 ")))
    state_count = 0
    for line in state:
        fields = tags(line)
        kind = line.split()[0]
        if kind in ("RS", "TSS", "SAMPLER"):
            key = f"rs.{fields['key']}" if kind == "RS" else f"{'tss' if kind == 'TSS' else 'sampler'}.{fields['stage']}.{fields['key']}"
            if fields["value"] != observed_states[key]:
                raise ValueError("archived pipeline state differs from application capture")
            state_count += 1
    index_format = int(tags(next(l for l in trace if l.startswith("BUFFER sequence=2 kind=index ")))["format"])
    if index_format not in (101, 102):
        raise ValueError("unsupported index format")
    indices = [v[0] for v in struct.iter_unpack("<H" if index_format == 101 else "<I", ib)]
    def triangle_indices(n):
        start = int(draw["start"])+n*3
        return indices[start:start+3]
    clip = [vertices(directory / f"p{p}_raw.clip") for p in range(3)]
    if any(len(c) != len(vb)//32 for c in clip):
        raise ValueError("incomplete source clip capture")
    if any(struct.pack("<3f", *a[:3]) != struct.pack("<3f", *b[:3]) for a, b in zip(clip[0], clip[1])):
        raise ValueError("W-only policy changed XYZ")
    for policy in (1, 2):
        previous = args.reference / f"accessory-w-gpu-{policy}" / "draw2.candidate_raw.clip"
        if previous.read_bytes() != (directory / f"p{policy}_raw.clip").read_bytes():
            raise ValueError("candidate clip policy changed from preceding GPU validation")
    coordinates = rows(directory / "coordinates.csv")
    groups = {}
    for row in coordinates:
        groups.setdefault(row["pair"], []).append((int(row["x"]), int(row["y"]), int(row["holdout"])))
    expected_groups = {"135_227": (1220, 505)} if viewport == [565, 25, 1032, 774] else {
        "197_231": (427, 338), "185_231": (381, 340), "197_197": (430, 234)} if viewport == [274, 25, 670, 503] else {}
    if not expected_groups or groups.keys() != expected_groups.keys():
        raise ValueError("unexpected residual selection")
    thresholds = rows(directory / "thresholds.csv")
    indexed = {}
    for row in thresholds:
        key = row["pair"], int(row["triangle"]), int(row["x"]), int(row["y"]), int(row["cycle"]), row["path"]
        if key in indexed or row["repeatExact"] != "1":
            raise ValueError("duplicate or unstable threshold")
        indexed[key] = row
    expected = set()
    details = []
    relations = []
    for pair, points in groups.items():
        if len(points) != 3 or points[0] != (*expected_groups[pair], 0) or any(p[2] != 1 for p in points[1:]) or len(set(points)) != 3:
            raise ValueError("missing primary or independent coverage coordinates")
        selected = sorted({int(n) for n in pair.split("_")})
        for t in selected:
            ids = triangle_indices(t)
            for x, y, holdout in points:
                if holdout:
                    _, weights = plane([clip[0][i] for i in ids], viewport, x, y)
                    if min(weights) <= 1e-4:
                        raise ValueError("holdout lacks interior coverage")
                for cycle in range(3):
                    for path in PATHS+(INSTRUCTIONS if cycle == 0 else ()):
                        key = pair, t, x, y, cycle, path
                        expected.add(key)
                        row = indexed.get(key)
                        if row is None or int(row["holdout"]) != holdout:
                            raise ValueError("missing fixed threshold control")
                        if path in ("p1", "p2") and row["dx9Bits"] != indexed[pair, t, x, y, cycle, "p0"]["dx9Bits"]:
                            raise ValueError("original native reference changed")
                        if path in INSTRUCTIONS and row["dx11Bits"] != indexed[pair, t, x, y, cycle, "shared2"]["dx11Bits"]:
                            raise ValueError("instruction control changed shared DX11 clip")
                native = int(indexed[pair, t, x, y, 0, "p0"]["dx9Bits"])
                item = {"pair": pair, "triangle": t, "x": x, "y": y, "holdout": holdout, "native": native}
                for p in range(3):
                    vertices_ = [clip[p][i] for i in ids]
                    double_plane, _ = plane(vertices_, viewport, x, y)
                    float_z_plane, _ = plane(vertices_, viewport, x, y, True)
                    measured = int(indexed[pair, t, x, y, 0, f"p{p}"]["dx11Bits"])
                    item[f"p{p}"] = {"measuredBits": measured, "minusNativeSteps": measured-native,
                        "doubleClipPlaneDiagnostic": double_plane,
                        "measuredMinusRoundedDoublePlaneSteps": measured-bits(double_plane),
                        "floatVertexZPlaneDiagnostic": float_z_plane,
                        "measuredMinusRoundedFloatVertexZPlaneSteps": measured-bits(float_z_plane),
                        "clip": vertices_}
                for op in INSTRUCTIONS:
                    measured = int(indexed[pair, t, x, y, 0, op]["dx9Bits"])
                    item[op] = {"measuredBits": measured, "minusOriginalNativeSteps": measured-native}
                details.append(item)
        if len(selected) == 2:
            for x, y, holdout in points:
                for p in range(3):
                    a = indexed[pair, selected[0], x, y, 0, f"p{p}"]
                    b = indexed[pair, selected[1], x, y, 0, f"p{p}"]
                    relations.append({"pair": pair, "x": x, "y": y, "holdout": holdout, "policy": p,
                        "firstMinusSecondNativeSteps": int(a["dx9Bits"])-int(b["dx9Bits"]),
                        "firstMinusSecondDX11Steps": int(a["dx11Bits"])-int(b["dx11Bits"])})
    if indexed.keys() != expected:
        raise ValueError("unexpected threshold matrix entries")
    images = rows(directory / "images.csv")
    expected_images = {(pair, kind, comp, order, p) for pair in groups
        for kind in ("Shaded", "ID") for comp in (range(3) if kind == "ID" else (0,))
        for order in range(1 if len(set(pair.split("_"))) == 1 else 2) for p in range(3)}
    measured_images = [(r["pair"], r["kind"], int(r["comparison"]), int(r["order"]), int(r["policy"])) for r in images]
    if len(set(measured_images)) != len(measured_images) or set(measured_images) != expected_images or any(r["cycle"] != "0" or r["repeat"] != "0" for r in images):
        raise ValueError("incomplete shaded/ID control matrix")
    saved_native = (args.reference / "history_replay.dx11_first_actual.bgra").read_bytes()
    image_cache = {}
    choice_checks = 0
    for row in images:
        pair, kind, comp, order, p = row["pair"], row["kind"], int(row["comparison"]), int(row["order"]), int(row["policy"])
        name = f"{pair}_{kind.lower()}_c{comp}_o{order}_p{p}"
        a = (directory / (name+"_native.rgba")).read_bytes()
        b = (directory / (name+"_dx11.rgba")).read_bytes()
        if any(len(data) != width*height*4 for data in (a, b)):
            raise ValueError("reduced image size differs")
        differences = sum(a[n:n+4] != b[n:n+4] for n in range(0, len(a), 4))
        if differences != int(row["differentPixels"]) or (kind == "ID" and comp == 2 and differences):
            raise ValueError("reduced image count or depth-disabled control differs")
        px, py = int(row["x"]), int(row["y"])
        at = (py*width+px)*4
        if list(a[at:at+3]) != [int(row[f"native{c}"]) for c in "RGB"] or list(b[at:at+3]) != [int(row[f"replay{c}"]) for c in "RGB"]:
            raise ValueError("reported reduced pixel colors differ")
        if kind == "Shaded" and order == 0:
            saved_at = ((py-oy)*w+px-ox)*4
            if a[at:at+4] != bytes(reversed(saved_native[saved_at:saved_at+3]))+saved_native[saved_at+3:saved_at+4]:
                raise ValueError("reduction did not preserve original native pixel")
        if kind == "ID" and comp == 0 and order == 0:
            image_cache[pair, p] = a, b
    for relation in relations:
        a, b = image_cache[relation["pair"], relation["policy"]]
        at = (relation["y"]*width+relation["x"])*4
        for data, key in ((a, "firstMinusSecondNativeSteps"), (b, "firstMinusSecondDX11Steps")):
            expected_color = b"\xff\x00\x00\xff" if relation[key] < 0 else b"\x00\xff\x00\xff"
            if data[at:at+4] != expected_color:
                raise ValueError("thresholds do not predict reduced ID surface choice")
            choice_checks += 1
    summaries = {}
    for path in PATHS+INSTRUCTIONS:
        selected_rows = [r for r in thresholds if r["path"] == path]
        item = {"total": len(selected_rows), "backendDifferentThresholds": sum(r["dx9Bits"] != r["dx11Bits"] for r in selected_rows)}
        if path in INSTRUCTIONS:
            item["matchesOriginalNative"] = sum(int(r["dx9Bits"]) == int(indexed[r["pair"], int(r["triangle"]), int(r["x"]), int(r["y"]), 0, "p0"]["dx9Bits"]) for r in selected_rows)
        if path.startswith("shared"):
            candidate = "p"+path[-1]
            item["matchesCandidateDX11"] = sum(r["dx11Bits"] == indexed[r["pair"], int(r["triangle"]), int(r["x"]), int(r["y"]), int(r["cycle"]), candidate]["dx11Bits"] for r in selected_rows)
        summaries[path] = item
    cycles = []
    for pair, t, x, y, cycle, path in indexed:
        if cycle:
            original = indexed[pair, t, x, y, 0, path]
            current = indexed[pair, t, x, y, cycle, path]
            if any(current[field] != original[field] for field in ("dx9Bits", "dx11Bits")):
                cycles.append({"pair": pair, "triangle": t, "x": x, "y": y, "cycle": cycle, "path": path,
                    "nativeSteps": int(current["dx9Bits"])-int(original["dx9Bits"]), "dx11Steps": int(current["dx11Bits"])-int(original["dx11Bits"])})
    result = {"viewport": viewport, "thresholdPairs": len(thresholds), "imageComparisons": len(images),
        "referenceRepeatsExact": True, "sourceGeometryVersionVerified": True, "sourceMatricesUnchanged": True,
        "sourceStatesCompared": state_count,
        "candidateClipMatchesPreviousValidation": True, "summaries": summaries,
        "cyclicThresholdChanges": cycles, "thresholdSurfaceChoiceChecks": choice_checks,
        "surfaceRelations": relations, "details": details, "images": images,
        "rawNativeVertexCapture": False, "rawD24Readback": False, "fullSceneAcceptance": False,
        "limit": "Real archived PMM reductions on the tested driver only. Double planes diagnose saved DX11 clip inputs; they are not a native interpolation oracle. Candidate policies and three coverage-selected coordinates per group are held fixed."}
    (directory / "analysis.json").write_text(json.dumps(result, indent=2)+"\n")
    print(f"thresholdPairs={len(thresholds)} imageComparisons={len(images)} surfaceChoiceChecks={choice_checks} cyclicChanges={len(cycles)}")
    for path, item in summaries.items():
        print(path, item)
    for item in details:
        if not item["holdout"]:
            print(f"primary={item['pair']} triangle={item['triangle']} pixel={item['x']},{item['y']} native={item['native']} p0={item['p0']['measuredBits']} p1={item['p1']['measuredBits']} p2={item['p2']['measuredBits']}")


if __name__ == "__main__":
    main()
