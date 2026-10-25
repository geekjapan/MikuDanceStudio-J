#!/usr/bin/env python3
"""Writes the .x fixtures of the mds-accessory tests into this directory.

    python3 tests/fixtures/rust/accessory/gen_accessory_x.py

Standard library only. The output is deterministic; SHA256SUMS lists it.
What each file must parse to is asserted in rust/crates/mds-accessory/tests/.
"""
import hashlib
import os
import struct

HERE = os.path.dirname(os.path.abspath(__file__))
SJIS = "cp932"


def f(*xs):
    return ";".join("%.6f" % x for x in xs) + ";"


def header(version="0303", fmt="txt ", floats="0032"):
    eol = "\r\n" if fmt == "txt " else ""
    return ("xof %s%s%s%s" % (version, fmt, floats, eol)).encode("ascii")


def write(name, data):
    if isinstance(data, str):
        data = data.encode("ascii")
    with open(os.path.join(HERE, name), "wb") as fh:
        fh.write(data)


TEMPLATE = """template Header {
 <3D82AB43-62DA-11cf-AB39-0020AF71E433>
 WORD major;
 WORD minor;
 DWORD flags;
}

"""

MATERIAL = """Material %s {
 %s;%s;%s;%s;;
 %s;
 %s;%s;%s;;
 %s;%s;%s;;
%s}
"""


def material(name, diffuse, power, spec, emis, tex=None):
    t = ""
    if tex is not None:
        t = " TextureFilename {\n  \"%s\";\n }\n" % tex
    return MATERIAL % (
        name,
        *("%.6f" % c for c in diffuse),
        "%.6f" % power,
        *("%.6f" % c for c in spec),
        *("%.6f" % c for c in emis),
        t,
    )


# --- cube: 8 positions, 6 quads, one normal per face, UVs, one material --------
CUBE_V = [(-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
          (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]
CUBE_F = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 4, 7, 3), (1, 2, 6, 5), (0, 1, 5, 4), (3, 7, 6, 2)]
CUBE_N = [(0, 0, -1), (0, 0, 1), (-1, 0, 0), (1, 0, 0), (0, -1, 0), (0, 1, 0)]
CUBE_UV = [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0), (1, 0), (1, 1), (0, 1)]
CUBE_MAT = dict(diffuse=(0.8, 0.4, 0.2, 1.0), power=10.0, spec=(0.5, 0.25, 1.0), emis=(0.1, 0.2, 0.3),
                tex="cube.bmp")


def cube_text():
    s = TEMPLATE + "Header {\n 1;\n 0;\n 1;\n}\n// a comment\n# another comment\n"
    s += "Mesh Cube {\n 8;\n"
    s += ",\n".join(" " + f(*v) for v in CUBE_V).rstrip(";") + ";;\n"
    s += " 6;\n" + ",\n".join(" 4;%d,%d,%d,%d;" % q for q in CUBE_F) + ";;\n"
    s += " MeshNormals {\n  6;\n" + ",\n".join("  " + f(*n) for n in CUBE_N) + ";;\n"
    s += "  6;\n" + ",\n".join("  4;%d;%d;%d;%d;" % (i, i, i, i) for i in range(6)) + ";;\n }\n"
    s += " MeshTextureCoords {\n  8;\n" + ",\n".join("  %s" % f(*u) for u in CUBE_UV) + ";;\n }\n"
    s += " MeshMaterialList {\n  1;\n  6;\n  0,0,0,0,0,0;;\n  "
    s += material("CubeMat", **CUBE_MAT).replace("\n", "\n  ").rstrip() + "\n }\n}\n"
    return s


def cube_bin(floats="0032"):
    """The same cube in the binary format (0303bin)."""
    wide = floats == "0064"

    def name(s):
        return struct.pack("<HI", 1, len(s)) + s.encode()

    def ints(*xs):
        return struct.pack("<HI", 6, len(xs)) + struct.pack("<%dI" % len(xs), *xs)

    def flts(*xs):
        if wide:
            return struct.pack("<HI", 7, len(xs)) + struct.pack("<%dd" % len(xs), *xs)
        return struct.pack("<HI", 7, len(xs)) + struct.pack("<%df" % len(xs), *xs)

    def string(s):
        return struct.pack("<HI", 2, len(s)) + s.encode() + struct.pack("<H", 20)

    O, C = struct.pack("<H", 10), struct.pack("<H", 11)
    guid = b"\x01" * 16
    out = struct.pack("<H", 31) + name("Foo") + O + struct.pack("<H", 5) + guid
    out += struct.pack("<H", 41) + name("x") + struct.pack("<H", 20) + C
    out += name("Mesh") + name("Cube") + O
    out += ints(8) + flts(*[c for v in CUBE_V for c in v])
    out += ints(6) + ints(*[x for q in CUBE_F for x in (4,) + q])
    out += name("MeshNormals") + O + ints(6) + flts(*[c for n in CUBE_N for c in n])
    out += ints(6) + ints(*[x for i in range(6) for x in (4, i, i, i, i)]) + C
    out += name("MeshTextureCoords") + O + ints(8) + flts(*[c for u in CUBE_UV for c in u]) + C
    out += name("MeshMaterialList") + O + ints(1, 6, 0, 0, 0, 0, 0, 0)
    out += name("Material") + name("CubeMat") + O
    m = CUBE_MAT
    out += flts(*m["diffuse"], m["power"], *m["spec"], *m["emis"])
    out += name("TextureFilename") + O + string(m["tex"]) + C + C + C + C
    return header(fmt="bin ", floats=floats) + out


# --- several materials, interleaved faces, a material reference -------------------
def multi_material():
    verts = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (2, 0, 0), (1, 1, 0), (0, 2, 0)]
    faces = [(3, (0, 1, 2)), (4, (1, 3, 4, 2)), (3, (2, 4, 5)), (3, (0, 2, 5))]
    mats = [2, 0, 1, 0]
    s = material("Shared", (0.1, 0.2, 0.3, 0.5), 3.0, (1, 1, 1), (0, 0, 0), "env.sph")
    s += "Mesh Strip {\n 6;\n" + ",\n".join(" " + f(*v) for v in verts).rstrip(";") + ";;\n"
    s += " 4;\n" + ",\n".join(" %d;%s;" % (n, ",".join(map(str, idx))) for n, idx in faces) + ";;\n"
    s += " MeshNormals {\n  1;\n  0.000000;0.000000;1.000000;;\n  4;\n"
    s += ",\n".join("  %d;%s;" % (n, ",".join("0" * 1 for _ in idx)) for n, idx in faces) + ";;\n }\n"
    s += " MeshTextureCoords {\n  6;\n" + ",\n".join("  " + f(v[0] * 0.5, v[1] * 0.5) for v in verts) + ";;\n }\n"
    s += " MeshMaterialList {\n  3;\n  4;\n  " + ",".join(map(str, mats)) + ";;\n"
    s += material("Mat0", (1, 0, 0, 1), 1.0, (0, 0, 0), (0, 0, 0), "a.bmp").replace("\n", "\n  ")
    s += "{ Shared }\n"
    s += material("Mat2", (0, 0, 1, 1), 2.0, (0, 0, 0), (0, 0, 0), "b.bmp*c.spa").replace("\n", "\n  ")
    s += " }\n}\n"
    return s


# --- nested frames with transforms ---------------------------------------------------
def tri_mesh(name):
    return ("Mesh %s {\n 3;\n 1.000000;0.000000;0.000000;,\n 0.000000;1.000000;0.000000;,\n"
            " 0.000000;0.000000;1.000000;;\n 1;\n 3;0,1,2;;\n}\n") % name


def ftm(m):
    return "FrameTransformMatrix {\n " + ",".join("%.6f" % x for x in m) + ";;\n}\n"


def frames():
    t10 = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 10, 0, 0, 1]
    rz90 = [0, 1, 0, 0, -1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
    t5 = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 5, 0, 1]
    s = "Frame Outer {\n" + ftm(t10) + tri_mesh("MeshA")
    s += "Frame Inner {\n" + ftm(rz90) + tri_mesh("MeshB") + "}\n"
    s += ftm(t5) + tri_mesh("MeshC") + "}\n" + tri_mesh("Top")
    return s


# --- no normals, no UVs, no material list --------------------------------------------
QUAD_V = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]


def quad(extra="", name="Quad"):
    return ("Mesh %s {\n 4;\n" % name + ",\n".join(" " + f(*v) for v in QUAD_V).rstrip(";") + ";;\n"
            " 1;\n 4;0,1,2,3;;\n" + extra + "}\n")


def quad_normals():
    return (" MeshNormals {\n  1;\n  0.000000;1.000000;0.000000;;\n  1;\n  4;0,0,0,0;;\n }\n")


def quad_uv():
    return " MeshTextureCoords {\n  4;\n" + ",\n".join("  " + f(*v[:2]) for v in QUAD_V) + ";;\n }\n"


def sphere_map():
    names = ["tex.bmp*sphere.sph", "light.spa", "plain.png*notmap.bmp", "screen.bmp", "x.SPH",
             "mix.bmp*env.spa", None, "a.sph*"]
    body = "Mesh Sph {\n 3;\n 0.000000;0.000000;0.000000;,\n 1.000000;0.000000;0.000000;,\n 0.000000;1.000000;0.000000;;\n"
    n = len(names) + 1
    body += " %d;\n" % n + ",\n".join(" 3;0,1,2;" for _ in range(n)) + ";;\n"
    body += " MeshMaterialList {\n  %d;\n  %d;\n  %s;;\n" % (n, n, ",".join(str(i) for i in range(n)))
    out = body.encode("ascii")
    for i, t in enumerate(names):
        out += material("M%d" % i, (1, 1, 1, 1), 5.0, (0, 0, 0), (0, 0, 0), t).encode("ascii")
    jp = material("M8", (1, 1, 1, 1), 5.0, (0, 0, 0), (0, 0, 0), "@@")
    out += jp.replace("@@", "テクスチャ.bmp*スフィア.sph").encode(SJIS)
    out += b" }\n}\n"
    return out


def malformed():
    good = "Mesh M {\n 3;\n0;0;0;,\n1;0;0;,\n0;1;0;;\n 1;\n 3;0,1,2;;\n%s}\n"
    return {
        "bad_header.x": header(version="0101") + good.replace("%s", "").encode(),
        "not_x.x": b"hello, this is not a DirectX file\n",
        "compressed_tzip.x": header(fmt="tzip") + b"\x00\x01\x02\x03",
        "compressed_bzip.x": header(fmt="bzip") + b"\x00\x01\x02\x03",
        "truncated_mesh.x": header() + b"Mesh M {\n 3;\n0;0;0;,\n1;0;0;,\n}\n",
        "unterminated.x": header() + good.replace("%s", "").rstrip().rstrip("}").encode(),
        "face_index_range.x": header() + good.replace("0,1,2", "0,1,5").replace("%s", "").encode(),
        "face_two_vertices.x": header() + good.replace("3;0,1,2", "2;0,1").replace("%s", "").encode(),
        "material_index_range.x": header() + (good % " MeshMaterialList {\n  1;\n  1;\n  1;;\n" + material("A", (1, 1, 1, 1), 0, (0, 0, 0), (0, 0, 0)) + " }\n").encode(),
        "material_count.x": header() + (good % " MeshMaterialList {\n  2;\n  1;\n  0;;\n" + material("A", (1, 1, 1, 1), 0, (0, 0, 0), (0, 0, 0)) + " }\n").encode(),
        "normals_count.x": header() + (good % " MeshNormals {\n  1;\n  0;0;1;;\n  1;\n  4;0,0,0,0;;\n }\n").encode(),
        "texcoord_count.x": header() + (good % " MeshTextureCoords {\n  2;\n  0;0;,\n  1;1;;\n }\n").encode(),
        "no_mesh.x": header() + material("Lonely", (1, 1, 1, 1), 0, (0, 0, 0), (0, 0, 0)).encode(),
        "empty_mesh.x": header() + b"Mesh M {\n 0;\n 0;\n}\n",
        "no_faces.x": header() + b"Mesh M {\n 3;\n0;0;0;,\n1;0;0;,\n0;1;0;;\n 0;\n}\n",
        "frame_matrix_short.x": header() + b"Frame F {\n FrameTransformMatrix {\n 1,0,0,0,0,1,0,0,0,0,1,0,0,0,0;;\n }\n" + tri_mesh("T").encode() + b"}\n",
        "stray_brace.x": header() + b"}}}\n",
    }


def main():
    write("cube.x", header() + cube_text().encode("ascii"))
    write("cube_bin.x", cube_bin())
    write("cube_bin64.x", cube_bin("0064"))
    write("multi_material.x", header(version="0302") + multi_material().encode("ascii"))
    write("frames.x", header(version="0302", floats="0064") + frames().encode("ascii"))
    write("no_normals_uvs.x", header() + quad().encode("ascii"))
    write("normals_no_uv.x", header() + quad(quad_normals()).encode("ascii"))
    write("normals_uv.x", header() + quad(quad_normals() + quad_uv()).encode("ascii"))
    write("sphere_map.x", header() + sphere_map())
    for k, v in malformed().items():
        write(k, v)
    write("placed.vac", "vac\r\ncube.x\r\n2.5\r\n1.0,2.0,3.0\r\n0.5,0.25,0.125\r\n\r\n\r\n1\r\n")
    write("placed_default.vac", "vac\ncube.x\n")
    sums = []
    for n in sorted(os.listdir(HERE)):
        if n.endswith((".x", ".vac")):
            sums.append("%s  %s\n" % (hashlib.sha256(open(os.path.join(HERE, n), "rb").read()).hexdigest(), n))
    write("SHA256SUMS", "".join(sums))


if __name__ == "__main__":
    main()
