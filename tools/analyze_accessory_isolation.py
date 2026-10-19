"""Inspect saved accessory images and original triangle data; no GPU claims.

All channel differences remain failures. The delta>1 grouping separates the
observed classes for diagnosis; it is not a comparison tolerance.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import struct


def tags(line):
    return dict(re.findall(r"([^\s=]+)=([^\s]+)", line))


def fnv(data):
    value = 14695981039346656037
    for byte in data:
        value = ((value ^ byte) * 1099511628211) & ((1 << 64) - 1)
    return value


def f32(value):
    return struct.pack("<f", float(value))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("reference", type=Path)
    parser.add_argument("--driver", choices=("hardware", "warp"), default="hardware")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    log = (args.reference / "history_replay.dx9").read_text().splitlines()
    region = tags(next(line for line in log if line.startswith("PORTABLE_REGION ")))
    x, y, w, h = (int(region[key]) for key in ("x", "y", "width", "height"))
    matrices = {}
    geometry = []
    proof = []
    for draw in (1, 2):
        stem = args.archive / f"history_replay.reduction.draw{draw}"
        state = Path(str(stem) + ".state").read_text().splitlines()
        draw_line = tags(next(line for line in log if line.startswith(f"DRAW sequence={draw} ")))
        archived_draw = tags(state[0])
        if int(archived_draw["stride"]) != 32 or int(archived_draw["fvf"]) != 274:
            raise ValueError("this diagnostic requires position/normal/UV0 vertices")
        for key in ("type", "fvf", "indexed", "base", "minimum", "vertices", "start", "count"):
            if draw_line[key] != archived_draw[key]:
                raise ValueError(f"draw {draw}: mismatched {key}")
        if any("Version" in key and key.startswith("texture") for key in draw_line):
            raise ValueError("this diagnostic requires untextured draw evidence")
        vertices = Path(str(stem) + ".vertices").read_bytes()
        indices = Path(str(stem) + ".indices").read_bytes()
        for kind, data, key in (("vertices", vertices, "vbVersion"), ("indices", indices, "ibVersion")):
            if fnv(data) != int(draw_line[key]):
                raise ValueError(f"draw {draw}: {kind} hash differs")
        observed = tags(next(line for line in log if line.startswith(f"STATE sequence={draw} ")))
        compared = 0
        for line in state:
            kind = line.split()[0]
            values = tags(line)
            if kind in ("RS", "TSS", "SAMPLER"):
                key = f"rs.{values['key']}" if kind == "RS" else f"{'tss' if kind == 'TSS' else 'sampler'}.{values['stage']}.{values['key']}"
                if observed[key] != values["value"]:
                    raise ValueError(f"draw {draw}: state {key} differs")
                compared += 1
            if kind in ("WORLD", "VIEW", "PROJECTION"):
                transform = {"WORLD": 256, "VIEW": 2, "PROJECTION": 3}[kind]
                current = tags(next(line for line in log if line.startswith(f"MATRIX sequence={draw} transform={transform} ")))
                if any(f32(values[f"f{n}"]) != f32(current[f"m{n}"]) for n in range(16)):
                    raise ValueError(f"draw {draw}: {kind} differs")
                matrices[kind] = [struct.unpack("<f", f32(values[f"f{n}"]))[0] for n in range(16)]
        proof.append({"draw": draw, "vertexHash": fnv(vertices), "indexHash": fnv(indices), "statesCompared": compared})
        geometry = vertices, indices, archived_draw

    directory = args.reference / f"accessory-isolation-{args.driver}"
    actual = (args.reference / "history_replay.dx11_first_actual.bgra").read_bytes()
    live = (args.reference / "history_replay.dx11_first_rebuilt.bgra").read_bytes()
    original = (directory / "original.bgra").read_bytes()
    variants = {path.stem: path.read_bytes() for path in directory.glob("*.bgra")}
    if any(len(data) != w * h * 4 for data in (actual, live, original, *variants.values())):
        raise ValueError("image dimensions do not match viewport")
    if args.driver == "hardware" and original != live:
        raise ValueError("offline Hardware baseline differs from saved live DX11 image")
    different = [at for at in range(0, len(actual), 4) if actual[at:at + 4] != original[at:at + 4]]
    large = [at for at in different if max(abs(actual[at + c] - original[at + c]) for c in range(4)) > 1]
    single_names = sorted(name for name in variants if name.startswith("triangle"))
    pixel_report = []
    for at in large:
        native_color = actual[at:at + 4]
        matches = [name for name in single_names if variants[name][at:at + 4] == native_color]
        pixel_report.append({"x": x + at // 4 % w, "y": y + at // 4 // w,
                             "nativeBGRA": list(native_color), "replayBGRA": list(original[at:at + 4]),
                             "matchingSingleTriangles": matches,
                             "replayMatchingSingleTriangles": [name for name in single_names if variants[name][at:at + 4] == original[at:at + 4]],
                             "matchesWhenStrictLess": variants["strict_less"][at:at + 4] == native_color,
                             "matchesWhenOrderReversed": variants["reverse_triangles"][at:at + 4] == native_color})
    vertices, index_bytes, draw = geometry
    index_log = next(line for line in log if line.startswith("BUFFER sequence=2 kind=index "))
    index_format = int(tags(index_log)["format"])
    if index_format not in (101, 102):
        raise ValueError("unsupported index format")
    step = 2 if index_format == 101 else 4
    indices = struct.unpack("<" + ("H" if step == 2 else "I") * (len(index_bytes) // step), index_bytes)

    def project(vertex):
        value = list(struct.unpack_from("<3f", vertices, vertex * 32)) + [1]
        for name in ("WORLD", "VIEW", "PROJECTION"):
            matrix = matrices[name]
            value = [sum(value[k] * matrix[k * 4 + column] for k in range(4)) for column in range(4)]
        return x + (value[0] / value[3] + 1) * w / 2, y + (1 - value[1] / value[3]) * h / 2

    triangles = []
    for name in single_names:
        triangle = int(name[len("triangle"):])
        at = int(draw["start"]) + triangle * 3
        ids = indices[at:at + 3]
        positions = [struct.unpack_from("<3f", vertices, vertex * 32) for vertex in ids]
        screen = [project(vertex) for vertex in ids]
        triangles.append({"zeroBasedTriangle": triangle, "indices": ids, "positions": positions,
                          "projectedVerticesDoubleDiagnostic": screen,
                          "projectedHeight": max(p[1] for p in screen) - min(p[1] for p in screen)})
    report = {
        "newNativeAcceptance": False, "driver": args.driver, "viewport": [x, y, w, h],
        "matchedArchivedInputs": proof,
        "provenanceLimit": "Current native trace has no material/light values; those come from the older archive. Hardware output independently matches the saved live DX11 image.",
        "offlineEqualsSavedLiveDX11": original == live,
        "differentPixels": len(different), "deltaExactlyOnePixels": len(different) - len(large),
        "deltaAboveOnePixels": len(large), "largeDifferenceRows": dict(Counter(pixel["y"] for pixel in pixel_report)),
        "precedingDrawAffectsDivergentPixels": sum(variants["draw2_only"][at:at + 4] != original[at:at + 4] for at in different),
        "noSpecularEqualsOriginal": variants["no_specular"] == original,
        "largePixels": pixel_report, "triangles": triangles,
        "selectedVertexYValues": sorted({position[1] for triangle in triangles for position in triangle["positions"]}),
        "projectionLimit": "Double CPU projection diagnoses geometry only; it is not a native raster/depth/interpolation oracle.",
    }
    output = args.output or directory / "analysis.json"
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"driver={args.driver} differentPixels={len(different)} deltaAboveOne={len(large)} "
          f"offlineEqualsLive={original == live} output={output}")


if __name__ == "__main__":
    main()
