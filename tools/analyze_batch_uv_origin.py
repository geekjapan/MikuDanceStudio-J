"""Validate vertex-generation/raster isolation on frozen draw-23 input."""
import argparse
import csv
import hashlib
import json
import struct
from collections import defaultdict
from pathlib import Path


def csv_rows(path):
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def compare_pixels(left, right):
    if len(left) != len(right) or len(left) % 16:
        raise ValueError("invalid float-image sizes")
    return sum(a != b for a, b in zip(struct.iter_unpack("4f", left), struct.iter_unpack("4f", right)))


def analyze(path):
    metadata = dict(token.split("=", 1) for token in (path / "metadata.txt").read_text().split() if "=" in token)
    summary = (path / "summary.txt").read_text()
    if "complete=1 controls=78 " not in summary or metadata["dx9NativePreRasterCapture"] != "0":
        raise ValueError("incomplete/mislabelled diagnostic")
    gates = csv_rows(path / "gates.csv")
    if len(gates) != 78:
        raise ValueError("missing controls")
    modes = {"original", "mesh_uv_from_so", "shared_clip_uv_ps2", "shared_clip_uv_ps3"}
    for i in range(3):
        modes.update({f"uniform_normal{i}", f"uniform_mesh_uv{i}", f"shared_uniform_uv{i}"})
    evidence = {}
    output = []
    for geometry in ("saved", "independent"):
        images = {}
        group = [row for row in gates if row["geometry"] == geometry]
        if {r["mode"] for r in group} != modes:
            raise ValueError(f"missing modes: {geometry}")
        for mode in sorted(modes):
            rows = [r for r in group if r["mode"] == mode]
            if len(rows) != 3 or {r["repeat"] for r in rows} != {"0", "1", "2"}:
                raise ValueError(f"missing repeat: {geometry}/{mode}")
            if any({k: v for k, v in r.items() if k != "repeat"} !=
                   {k: v for k, v in rows[0].items() if k != "repeat"} for r in rows[1:]):
                raise ValueError(f"unstable stats: {geometry}/{mode}")
            for side in ("dx9", "dx11"):
                files = [path / f"{geometry}_{mode}.repeat{r}.{side}.float" for r in range(3)]
                hashes = [digest(file) for file in files]
                if len(set(hashes)) != 1:
                    raise ValueError(f"unstable image: {geometry}/{mode}/{side}")
                if files[0].stat().st_size != int(rows[0]["knownPixels"]) * 16:
                    raise ValueError("image/known viewport size mismatch")
                for file, value in zip(files, hashes):
                    evidence[file.name] = value
                images[mode, side] = files[0].read_bytes()
        baseline = {side: images["original", side] for side in ("dx9", "dx11")}
        original_different = compare_pixels(baseline["dx9"], baseline["dx11"])
        for mode in ("mesh_uv_from_so", "shared_clip_uv_ps2", "shared_clip_uv_ps3"):
            if images[mode, "dx11"] != baseline["dx11"] or images[mode, "dx9"] != baseline["dx11"]:
                raise ValueError(f"common input did not preserve candidate and match native: {geometry}/{mode}")
        uniform = []
        for vertex in range(3):
            auto, mesh, shared = (f"uniform_normal{vertex}", f"uniform_mesh_uv{vertex}", f"shared_uniform_uv{vertex}")
            if images[auto, "dx11"] != images[mesh, "dx11"]:
                raise ValueError("mesh override changed candidate UV generation")
            if images[mesh, "dx9"] != images[mesh, "dx11"] or images[shared, "dx9"] != images[mesh, "dx11"] or images[shared, "dx11"] != images[mesh, "dx11"]:
                raise ValueError("uniform shared UV raster output differs")
            uniform.append({"vertex": vertex, "nativeGeneratedVsMeshPixels": compare_pixels(images[auto, "dx9"], images[mesh, "dx9"]),
                            "candidateGeneratedVsMeshPixels": 0, "sharedUVRasterExact": True})
        output.append({"geometry": geometry, "originalUVFloatDifferentPixels": original_different,
                       "meshUVOverrideMatchesCandidate": True, "commonClipAndUVBetweenApisExact": True,
                       "commonClipAndUVPreservesCandidate": True, "uniformNormalControls": uniform})
    vertex_groups = defaultdict(list)
    for row in csv_rows(path / "vertices.csv"):
        vertex_groups[row["geometry"], row["vertex"]].append({k: v for k, v in row.items() if k != "repeat"})
    if len(vertex_groups) != 6 or any(len(rows) != 3 or rows[0] != rows[1] or rows[0] != rows[2] for rows in vertex_groups.values()):
        raise ValueError("unstable/incomplete pre-raster SO")
    for geometry in ("saved", "independent"):
        files = [path / f"{geometry}.so.repeat{repeat}.input" for repeat in range(3)]
        hashes = [digest(file) for file in files]
        if len(set(hashes)) != 1 or any(file.stat().st_size != 72 for file in files):
            raise ValueError("unstable/incomplete raw stream-output vertices")
        for file, value in zip(files, hashes):
            evidence[file.name] = value
    focus = []
    for row in csv_rows(path / "pixels.csv"):
        if row["geometry"] == "saved" and row["x"] == metadata["x"] and row["y"] == metadata["y"] and row["repeat"] == "0":
            focus.append({"mode": row["mode"], "nativeUV": [float(row[k]) for k in ("nativeU", "nativeV")],
                          "candidateUV": [float(row[k]) for k in ("candidateU", "candidateV")]})
    for name in ("gates.csv", "pixels.csv", "vertices.csv", "summary.txt"):
        evidence[name] = digest(path / name)
    if output[0]["originalUVFloatDifferentPixels"] == 0 or not any(c["nativeGeneratedVsMeshPixels"] for c in output[0]["uniformNormalControls"]):
        raise ValueError("saved generation difference was not reproduced")
    return {"status": "DIAGNOSTIC_EVIDENCE_VALID", "imageAcceptance": False, "productionActivation": False,
            "diagnosticOnly": True, "dx11PreRasterSO": True, "dx9NativePreRasterCapture": False,
            "controls": len(gates), "repeats": 3, "pixel": [int(metadata["x"]), int(metadata["y"])],
            "geometries": output, "focus": focus, "evidenceSHA256": evidence,
            "conclusion": "generated_Toon_vertex_UV_path; identical_mesh_UV_and_clip_rasterize_exactly_for_this_input",
            "unresolved": "normal_transform_vs_normalization_vs_texture_matrix_arithmetic"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--compare", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = analyze(args.input)
    if args.compare:
        if result != analyze(args.compare):
            raise ValueError("identical archived input differs across architectures")
        result["crossArchitectureExact"] = True
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in ("status", "controls", "pixel", "conclusion", "unresolved")}))


if __name__ == "__main__":
    main()
