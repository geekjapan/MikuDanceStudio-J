"""Verify isolated accessory color measurements; no renderer activation.

Exit 32 retains any original RGBA8 mismatch. Shared-color substitution is a
diagnostic control, not permission to replace native lighting with fitted colors.
"""
import argparse
import csv
import json
from pathlib import Path
import struct

from analyze_accessory_isolation import tags, fnv, f32
from analyze_w_gpu_batch import image_difference


def rows(path):
    with path.open(newline="") as file:
        result = list(csv.DictReader(file))
    if any(None in row or any(v is None for v in row.values()) for row in result):
        raise ValueError("malformed CSV")
    return result


def pixel_count(a, b, stride):
    if len(a) != len(b) or len(a) % stride:
        raise ValueError("incompatible images")
    return sum(a[i:i+stride] != b[i:i+stride] for i in range(0, len(a), stride))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("reference", type=Path)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    root = args.directory
    manifest = json.loads((root / "manifest.json").read_text())
    trace = (args.reference / "history_replay.dx9").read_text().splitlines()
    region = tags(next(l for l in trace if l.startswith("PORTABLE_REGION ")))
    viewport = [int(region[k]) for k in ("x", "y", "width", "height")]
    x, y, w, h = viewport
    width, height = x+w, y+h
    if manifest["viewport"] != viewport or (manifest["width"], manifest["height"]) != (width, height):
        raise ValueError("viewport differs from saved application")
    if manifest["samples"] != 1 or manifest["diagnosticPolicy"] != 3 or manifest["triangle"] != 197:
        raise ValueError("unexpected diagnostic")
    for key in ("adapterPreflight", "sharedModelPreflight", "nativeColorSubstitution", "repeatExact"):
        if manifest[key] is not True:
            raise ValueError(f"missing GPU preflight: {key}")
    if manifest["repeatCount"] != 3:
        raise ValueError("incomplete repeat control")
    stem = args.archive / "history_replay.reduction.draw2"
    state = Path(str(stem)+".state").read_text().splitlines()
    saved_draw = tags(next(l for l in trace if l.startswith("DRAW sequence=2 ")))
    draw = tags(state[0])
    for key in ("type", "fvf", "indexed", "base", "minimum", "vertices", "start", "count"):
        if draw[key] != saved_draw[key]:
            raise ValueError(f"archived draw differs: {key}")
    vb = Path(str(stem)+".vertices").read_bytes()
    ib = Path(str(stem)+".indices").read_bytes()
    if fnv(vb) != int(saved_draw["vbVersion"]) or fnv(ib) != int(saved_draw["ibVersion"]):
        raise ValueError("geometry version differs from application")
    observed = tags(next(l for l in trace if l.startswith("STATE sequence=2 ")))
    states = 0
    for line in state:
        kind = line.split()[0]
        values = tags(line)
        if kind in ("RS", "TSS", "SAMPLER"):
            key = f"rs.{values['key']}" if kind == "RS" else f"{'tss' if kind == 'TSS' else 'sampler'}.{values['stage']}.{values['key']}"
            if observed[key] != values["value"]:
                raise ValueError("archived state differs from application")
            states += 1
        if kind in ("WORLD", "VIEW", "PROJECTION"):
            transform = {"WORLD": 256, "VIEW": 2, "PROJECTION": 3}[kind]
            saved = tags(next(l for l in trace if l.startswith(f"MATRIX sequence=2 transform={transform} ")))
            if any(f32(values[f"f{i}"]) != f32(saved[f"m{i}"]) for i in range(16)):
                raise ValueError("archived matrix differs from application")
    vertex_rows = rows(root / "vertices.csv")
    if len(vertex_rows) != 12 or {(int(r["vertex"]), int(r["k"])) for r in vertex_rows} != {(n, k) for n in range(3) for k in range(4)}:
        raise ValueError("incomplete SO color/position capture")
    clip_root = args.reference / "accessory-w-gpu-3"
    raw = (clip_root / "draw2.candidate_raw.clip").read_bytes()
    final = (clip_root / "draw2.candidate_final.clip").read_bytes()
    for row in vertex_rows:
        n, k, index = (int(row[key]) for key in ("vertex", "k", "sourceIndex"))
        expected = struct.unpack_from("<H", ib, (int(draw["start"])+197*3+n)*2)[0]
        if index != expected or not 0 <= k < 4:
            raise ValueError("triangle index differs")
        for column, data in (("rawClipBits", raw), ("finalClipBits", final)):
            if int(row[column]) != struct.unpack_from("<I", data, index*16+k*4)[0]:
                raise ValueError("lit SO clip differs from preceding depth diagnostic")
        if f32(row["diffuse"]) != struct.pack("<I", int(row["diffuseBits"])):
            raise ValueError("SO color bits/value disagree")
    images = {}
    for name in ("native", "model", "shared-native", "native-colors-dx9", "native-colors-dx11"):
        for suffix, stride in (("rgba", 4), ("rgba32f", 16)):
            data = (root / f"{name}.{suffix}").read_bytes()
            if len(data) != width*height*stride:
                raise ValueError("incomplete raster image")
            images[name, suffix] = data
    for suffix in ("rgba", "rgba32f"):
        if images["shared-native", suffix] != images["model", suffix]:
            raise ValueError("same DX11 SO colors disagree across APIs")
        for name in ("native-colors-dx9", "native-colors-dx11"):
            if images[name, suffix] != images["native", suffix]:
                raise ValueError("native constant-normal colors do not reproduce fixed lighting")
    constant_rows = rows(root / "constant_normals.csv")
    if len(constant_rows) != 12:
        raise ValueError("incomplete constant-normal control")
    color_delta = []
    for row, vertex in zip(constant_rows, vertex_rows):
        if (row["vertex"], row["k"]) != (vertex["vertex"], vertex["k"]) or row["shaderVertexBits"] != vertex["diffuseBits"]:
            raise ValueError("constant-normal / SO color mismatch")
        if f32(row["native"]) != struct.pack("<I", int(row["nativeBits"])):
            raise ValueError("constant-normal color bits/value disagree")
        delta = int(row["shaderVertexBits"])-int(row["nativeBits"])
        if delta:
            color_delta.append({"vertex": int(row["vertex"]), "channel": int(row["k"]), "dx11MinusNativeULP": delta})
    px, py = manifest["probe"]
    sample_rows = rows(root / "samples.csv")
    if len(sample_rows) != 100 or {(int(r["x"]), int(r["y"]), int(r["k"])) for r in sample_rows} != {(px+dx, py+dy, k) for dx in range(-2, 3) for dy in range(-2, 3) for k in range(4)}:
        raise ValueError("incomplete fixed sample coordinates")
    for row in sample_rows:
        sx, sy, k = (int(row[key]) for key in ("x", "y", "k"))
        sample_offset = (sy*width+sx)*4+k
        for label, name in (("native", "native"), ("model", "model"), ("sharedNative", "shared-native"), ("sharedReplay", "model")):
            if int(row[label+"Byte"]) != images[name, "rgba"][sample_offset]:
                raise ValueError("sample byte differs from image")
            bits = struct.unpack_from("<I", images[name, "rgba32f"], sample_offset*4)[0]
            if int(row[label+"Bits"]) != bits or f32(row[label]) != struct.pack("<I", bits):
                raise ValueError("sample float bits differ from image")
    offset = (py*width+px)*4
    probe = {}
    for name in ("native", "model", "shared-native", "native-colors-dx11"):
        probe[name] = {"rgba8": list(images[name, "rgba"][offset:offset+4]),
                       "rgba32f": list(struct.unpack_from("<4f", images[name, "rgba32f"], offset*4))}
    saved_image = (args.reference / "history_replay.dx11_first_actual.bgra").read_bytes()
    if len(saved_image) != w*h*4:
        raise ValueError("incomplete original application image")
    saved_offset = ((py-y)*w+px-x)*4
    b, g, r, a = saved_image[saved_offset:saved_offset+4]
    probe["savedApplicationRGBA8"] = [r, g, b, a]
    if w == 670 and probe["native"]["rgba8"] != [r, g, b, a]:
        raise ValueError("fixed residual differs from application capture")
    original = image_difference(images["native", "rgba"], images["model", "rgba"])
    report = {"viewport": viewport, "sourceVertexHash": fnv(vb), "sourceIndexHash": fnv(ib), "statesCompared": states,
              "originalRGBA8": original, "originalRGBA32F differentPixels": pixel_count(images["native", "rgba32f"], images["model", "rgba32f"], 16),
              "constantNormalColorDifferences": color_delta, "sharedColorBothFormats": "EXACT", "nativeColorSubstitutionBothFormats": "EXACT",
              "probe": probe, "repeatedCaptures": 3, "originalImageAccepted": original["differentPixels"] == 0, "applicationActivation": False}
    (root / "analysis.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report, indent=2))
    return 32 if original["differentPixels"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
