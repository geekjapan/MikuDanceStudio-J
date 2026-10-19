"""Validate diagnostic fused-W clip captures and fresh native PMM image controls.

Every nonzero channel difference remains an image acceptance failure.
"""
import argparse
import json
from pathlib import Path
import struct
import math
from analyze_accessory_isolation import tags, fnv, f32
from generate_sensitive_depth_matrices import multiply, dot


def vertices(path):
    data = path.read_bytes()
    if not data or len(data) % 16:
        raise ValueError("incomplete float4 capture")
    return list(struct.iter_unpack("<4f", data))


def image_difference(a, b):
    if len(a) != len(b) or len(a) % 4:
        raise ValueError("incompatible image sizes")
    different = large = maximum = 0
    for n in range(0, len(a), 4):
        delta = max(abs(a[n+c]-b[n+c]) for c in range(4))
        different += delta != 0
        large += delta > 1
        maximum = max(maximum, delta)
    return {"differentPixels": different, "deltaAboveOne": large, "maxDelta": maximum}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("reference", type=Path)
    parser.add_argument("policy", type=int, choices=(1, 2, 3, 4, 5))
    parser.add_argument("--lighting", action="store_true", help="validate the isolated material-order candidate (policy 3 geometry)")
    parser.add_argument("--normals", action="store_true", help="validate rounded normal matrix/fused dot plus material-order diagnostic (policy 3 geometry)")
    args = parser.parse_args()
    args.lighting = args.lighting or args.normals
    if args.lighting and args.policy != 3:
        raise ValueError("lighting diagnostic holds geometry at policy 3")
    directory = args.reference / ("accessory-normal-gpu" if args.normals else "accessory-lighting-gpu" if args.lighting else f"accessory-w-gpu-{args.policy}")
    log = (args.reference / "history_replay.dx9").read_text().splitlines()
    region = tags(next(line for line in log if line.startswith("PORTABLE_REGION ")))
    expected_size = int(region["width"])*int(region["height"])*4
    proof = []
    vertex_count = w_changed = xyz_changed = 0
    for draw in (1, 2):
        stem = args.archive / f"history_replay.reduction.draw{draw}"
        state = Path(str(stem)+".state").read_text().splitlines()
        actual_draw = tags(next(line for line in log if line.startswith(f"DRAW sequence={draw} ")))
        archived_draw = tags(state[0])
        for key in ("type", "fvf", "indexed", "base", "minimum", "vertices", "start", "count"):
            if actual_draw[key] != archived_draw[key]:
                raise ValueError(f"archived draw {draw}: {key} differs from application capture")
        if archived_draw["fvf"] != "274" or archived_draw["stride"] != "32":
            raise ValueError("this diagnostic requires position/normal/UV0")
        vertex_bytes = Path(str(stem)+".vertices").read_bytes()
        index_bytes = Path(str(stem)+".indices").read_bytes()
        if fnv(vertex_bytes) != int(actual_draw["vbVersion"]) or fnv(index_bytes) != int(actual_draw["ibVersion"]):
            raise ValueError("archive geometry version differs from application capture")
        matrices = {}
        observed = tags(next(line for line in log if line.startswith(f"STATE sequence={draw} ")))
        states = 0
        for line in state:
            kind = line.split()[0]
            fields = tags(line)
            if kind in ("WORLD", "VIEW", "PROJECTION"):
                transform = {"WORLD": 256, "VIEW": 2, "PROJECTION": 3}[kind]
                captured = tags(next(line for line in log if line.startswith(f"MATRIX sequence={draw} transform={transform} ")))
                if any(f32(fields[f"f{n}"]) != f32(captured[f"m{n}"]) for n in range(16)):
                    raise ValueError("native transform differs from application capture")
                matrices[kind] = [struct.unpack("<f", f32(fields[f"f{n}"]))[0] for n in range(16)]
            if kind in ("RS", "TSS", "SAMPLER"):
                key = f"rs.{fields['key']}" if kind == "RS" else f"{'tss' if kind == 'TSS' else 'sampler'}.{fields['stage']}.{fields['key']}"
                if observed[key] != fields["value"]:
                    raise ValueError("archived pipeline state differs from application capture")
                states += 1
        combined = multiply(multiply(matrices["WORLD"], matrices["VIEW"], "sequential"), matrices["PROJECTION"], "sequential")
        before = vertices(directory / f"draw{draw}.original_raw.clip")
        after = vertices(directory / f"draw{draw}.candidate_raw.clip")
        expected_xyz = vertices(directory / f"draw{draw}.expected_xyz.clip")
        final = vertices(directory / f"draw{draw}.candidate_final.clip")
        z_baseline = vertices(args.reference / "accessory-w-gpu-2" / f"draw{draw}.candidate_raw.clip") if args.policy >= 3 else None
        count = len(vertex_bytes)//32
        if not count or len(vertex_bytes) % 32 or any(len(capture) != count for capture in (before, after, expected_xyz, final)):
            raise ValueError("incomplete clip capture")
        for n in range(count):
            obj = (*struct.unpack_from("<3f", vertex_bytes, n*32), 1.)
            expected_w = dot(obj, combined[3::4], "fused")
            if f32(after[n][3]) != f32(expected_w) or struct.pack("<3f", *after[n][:3]) != struct.pack("<3f", *expected_xyz[n][:3]):
                raise ValueError("GPU candidate W/XYZ differs from fixed arithmetic policy")
            if args.policy == 1 and struct.pack("<3f", *before[n][:3]) != struct.pack("<3f", *after[n][:3]):
                raise ValueError("W-only policy changed XYZ before center correction")
            if z_baseline is not None:
                rule = {3: "fused", 4: "double", 5: "sequential"}[args.policy]
                if f32(after[n][2]) != f32(dot(obj, combined[2::4], rule)):
                    raise ValueError("GPU Z candidate differs from declared CPU arithmetic")
                if any(f32(after[n][k]) != f32(z_baseline[n][k]) for k in (0, 1, 3)):
                    raise ValueError("Z candidate changed baseline XY/W")
            w_changed += f32(before[n][3]) != f32(after[n][3])
            xyz_changed += struct.pack("<3f", *before[n][:3]) != struct.pack("<3f", *after[n][:3])
        if args.normals:
            from analyze_normal_transforms import normal_matrix
            identity = [1. if k in (0,5,10,15) else 0. for k in range(16)]
            expected_normal = normal_matrix(multiply(matrices['WORLD'],matrices['VIEW'],'sequential'),identity)
            normal_bytes = (directory/f'draw{draw}.normal_candidate.matrix').read_bytes()
            if normal_bytes != struct.pack('<16f',*expected_normal):
                raise ValueError('real batch normal matrix differs from declared arithmetic')
            colors = vertices(directory/f'draw{draw}.normal_candidate_lit.float4')
            if len(colors) != count:
                raise ValueError('incomplete actual diagnostic shader color capture')
            indices = struct.unpack('<'+'H'*(len(index_bytes)//2),index_bytes)
            referenced = set(indices[int(archived_draw['start']):int(archived_draw['start'])+3*int(archived_draw['count'])])
            if any(n>=count or any(not math.isfinite(v) or not 0<=v<=1 for v in colors[n]) for n in referenced):
                raise ValueError('invalid referenced diagnostic vertex color')
            if any(f32(colors[n][3]) != f32(1) for n in referenced):
                raise ValueError('diagnostic changed material alpha')
        vertex_count += count
        proof.append({"draw": draw, "vertexHash": fnv(vertex_bytes), "indexHash": fnv(index_bytes), "statesCompared": states})
        if args.normals:
            proof[-1].update({'normalMatrixVerified':True,'actualCandidateColorVertices':count,'referencedColorVertices':len(referenced),'colorRepeatBitsVerifiedInProbe':True})
    native_saved = (args.reference / "history_replay.dx11_first_actual.bgra").read_bytes()
    if len(native_saved) != expected_size:
        raise ValueError("native viewport image size differs")
    controls = {}
    for path in sorted(directory.glob("*.bgra")):
        if path.stem.endswith("-native"):
            continue
        a = path.read_bytes()
        b = path.with_name(path.stem+"-native.bgra").read_bytes()
        if len(a) != expected_size or len(b) != expected_size:
            raise ValueError("control image size differs")
        controls[path.stem] = image_difference(a, b)
        if path.stem in ("original", "repeat") and b != native_saved:
            raise ValueError("original native image changed")
    if len(controls) != 14:
        raise ValueError("incomplete control matrix")
    if (directory / "repeat.bgra").read_bytes() != (directory / "original.bgra").read_bytes():
        raise ValueError("candidate repeat changed")
    baseline = (args.reference / "accessory-native-hardware" / "original.bgra").read_bytes()
    if len(baseline) != expected_size:
        raise ValueError("missing unmodified DX11 baseline")
    result = {"policy": args.policy, "shaderVerticesVerified": vertex_count,
        "candidateWMatchesCpuFused": True, "candidateXYZMatchesDeclaredPolicy": True,
        "changedWVertices": w_changed, "changedXYZVertices": xyz_changed,
        "nativeOriginalMatchesSavedApplication": True, "repeatExact": True,
        "archiveProof": proof, "baseline": image_difference(baseline, native_saved),
        "controls": controls, "fullSceneAcceptance": False}
    if args.policy >= 3:
        result["candidateZMatchesCpu"] = True
        result["candidateXYWHeldFixed"] = True
    if args.lighting:
        result["lightingCandidate"] = "roundedMaterialFactor_then_diffuseEmissiveFused_then_ambientFused"
        result["productionActivation"] = False
    if args.normals:
        result["normalCandidate"] = "roundedWorldViewInverseTranspose_then_fusedXYZDot_then_hardwareNormalize"
        preceding = args.reference / "accessory-lighting-gpu"
        if any((preceding/path.name).read_bytes() != path.read_bytes() for path in directory.glob("*-native.bgra")):
            raise ValueError("normal candidate changed preceding native controls")
        result["precedingNativeControlsUnchanged"] = True
        result["versusMaterialOnlyCandidate"] = {name:image_difference((directory/(name+".bgra")).read_bytes(),(preceding/(name+".bgra")).read_bytes()) for name in controls}
    (directory / "analysis.json").write_text(json.dumps(result, indent=2)+"\n")
    print(f"policy={args.policy} vertices={vertex_count} changedW={w_changed} changedXYZ={xyz_changed} nativeOriginal=UNCHANGED repeat=EXACT")
    print(f"baseline={result['baseline']} candidate={controls['original']} noDepth={controls['no_depth']}")
    return 32 if args.lighting and any(c["differentPixels"] for c in controls.values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
