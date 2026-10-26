#!/usr/bin/env python3
"""Write the mmegold scenes: a PMM and an EMM template per scene, and the
scenes' own effects.

Python standard library only; the PMMs come from golden2's build_pmm.

    python3 -I tests/fixtures/rust/mmegold/gen_mmegold.py --write
    python3 -I tests/fixtures/rust/mmegold/gen_mmegold.py --check

An EMM names an effect as "$(fixtures)\\..." (tests/fixtures/rust/mme/effects),
"$(mmegold)\\..." (this directory), or "$(corpus)\\..." (the ray-mmd corpus).
MMEffect uses EMM effect paths as they are, so tools/oracle/mmegold.ps1 writes
each EMM with absolute paths beside a copy of its PMM. README.md says what each
scene checks.
"""
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "golden2"))
import gen_golden2 as g2  # noqa: E402


# Seen from the front of the models by a perspective camera at (0, 4, 20).
CAMERA = [(0, -20.0, (0.0, 4.0, 0.0), (0.0, g2.PI, 0.0), 30)]
IDENTITY = [0.0, 0.0, 0.0, 1.0]
CHAIN = g2.SceneModel(g2.CHAIN, g2.at(0.0))
# morph4.pmx to the left of chain8 (yaw pi), its center bone moving by 2 and
# its morph あ rising to 1 by frame 30.
MORPH4 = g2.SceneModel(
    g2.MORPH4,
    {0: [(0, [4.0, 0.0, 0.0], IDENTITY), (30, [6.0, 0.0, 0.0], IDENTITY)]},
    {1: [(0, 0.0), (30, 1.0)]})

OBJECT_HEAD = """float Script : STANDARDSGLOBAL <
    string ScriptOutput = "color";
    string ScriptClass = "object";
    string ScriptOrder = "standard";
> = 0.8;

float4x4 WorldViewProjMatrix : WORLDVIEWPROJECTION;
"""
OBJECT_TAIL = """
technique Main < string MMDPass = "object"; > {
    pass P0 { VertexShader = compile vs_3_0 VS(); PixelShader = compile ps_3_0 PS(); }
}
"""

CONTROL_FX = ("// mmegold: CONTROLOBJECT values of morph4.pmx color the owner.\n"
              + OBJECT_HEAD + """float MorphA : CONTROLOBJECT < string name = "morph4.pmx"; string item = "あ"; >;
float3 BodyPos : CONTROLOBJECT < string name = "morph4.pmx"; string item = "上半身"; >;
float4x4 Center : CONTROLOBJECT < string name = "morph4.pmx"; string item = "センター"; >;
float3 ModelPos : CONTROLOBJECT < string name = "morph4.pmx"; >;
float4x4 ModelWorld : CONTROLOBJECT < string name = "morph4.pmx"; >;
bool Visible : CONTROLOBJECT < string name = "morph4.pmx"; >;
float Size : CONTROLOBJECT < string name = "morph4.pmx"; >;
float Missing : CONTROLOBJECT < string name = "missing.pmx"; string item = "あ"; >;

float4 VS(float4 Pos : POSITION) : POSITION { return mul(Pos, WorldViewProjMatrix); }
float4 PS() : COLOR0 { return float4(MorphA, frac(Center._41 * 0.25), Visible ? 1 : 0, 1); }
""" + OBJECT_TAIL).encode("cp932")

ANIME_FX = ("// mmegold: blink.gif (rust/crates/mds-mmert/tests/data) on the owner.\n"
            + OBJECT_HEAD + """float Time : TIME;
texture Anim : ANIMATEDTEXTURE < string ResourceName = "blink.gif"; >;
sampler AnimSamp = sampler_state {
    texture = <Anim>;
    MinFilter = POINT; MagFilter = POINT; MipFilter = NONE;
    AddressU = CLAMP; AddressV = CLAMP;
};

struct VS_OUT {
    float4 Pos : POSITION;
    float2 Tex : TEXCOORD0;
};
VS_OUT VS(float4 Pos : POSITION, float2 Tex : TEXCOORD0) {
    VS_OUT o;
    o.Pos = mul(Pos, WorldViewProjMatrix);
    o.Tex = Tex;
    return o;
}
float4 PS(VS_OUT i) : COLOR0 { return tex2D(AnimSamp, i.Tex); }
""" + OBJECT_TAIL).encode("ascii")

# mme/effects/post.fx without the two RenderColorTarget1 lines. The Final pass
# draws to the back buffer, which the dump mode multisamples, and Direct3D 9
# drops a draw that binds the non-multisampled Full beside it.
_POST = (HERE.parent / "mme" / "effects" / "post.fx").read_text(encoding="ascii")
POST_FX = ("// mmegold: mme/effects/post.fx with the Final pass's second target unbound (see README.md).\n"
           + _POST.replace('        "RenderColorTarget1=Full;"\n', "")
                  .replace('"Pass=Final;"\n        "RenderColorTarget1=;";', '"Pass=Final;";')
           ).encode("ascii")
assert POST_FX.count(b"RenderColorTarget1") == 0

MAIN = "$(corpus)\\Main\\main.fx"
# scene -> models, accessories, the EMM's [Effect] rows, frames
SCENES = {
    "objects": dict(rows={"Pmd0": "$(fixtures)\\objects.fx"}, frames=[0, 30]),
    "post": dict(rows={"Pmd0": "$(mmegold)\\post.fx"}, frames=[0, 30]),
    "offscreen": dict(rows={"Pmd0": "$(fixtures)\\offscreen.fx"}, frames=[0, 30]),
    "timeofday": dict(rows={"Pmd0": "$(corpus)\\Skybox\\Time of day\\Time of day.fx"},
                      frames=[0, 30]),
    "main": dict(rows={"Pmd0": MAIN}, frames=[0, 30]),
    "control": dict(models=[CHAIN, MORPH4], rows={"Pmd0": "$(mmegold)\\control.fx"},
                    frames=[0, 15, 30]),
    "anime": dict(rows={"Pmd0": "$(mmegold)\\anime.fx"}, frames=[0, 3, 4, 9, 30]),
    # ray-mmd as it is meant to run: ray.fx on the ray.x accessory, main.fx on
    # the model.
    "ray": dict(accessories=[g2.Accessory("ray.x", (0.0, 0.0, 0.0))],
                rows={"Pmd0": MAIN, "Acs0": "$(corpus)\\ray.fx"}, frames=[0, 30]),
}


def emm(models, accessories, rows):
    # [Object] rows match the staged files by their file names.
    objects = ["Pmd%d = %s" % (i, m.spec["file"].lstrip(".\\")) for i, m in enumerate(models)]
    objects += ["Acs%d = %s" % (i, a.file) for i, a in enumerate(accessories)]
    effects = ["Default = none"] + ["%s = %s" % kv for kv in rows.items()]
    return ("[Info]\nVersion = 3\n\n[Object]\n%s\n\n[Effect]\n%s\n"
            % ("\n".join(objects), "\n".join(effects))).encode("ascii")


def generate():
    out = {"control.fx": CONTROL_FX, "anime.fx": ANIME_FX, "post.fx": POST_FX}
    for name, scene in SCENES.items():
        models = scene.get("models", [CHAIN])
        accessories = scene.get("accessories", [])
        out[name + ".pmm"] = g2.build_pmm(models, CAMERA, g2.LIGHT, g2.SHADOW_OFF,
                                          perspective=0, accessories=accessories)
        out[name + ".emm"] = emm(models, accessories, scene["rows"])
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--frames", action="store_true",
                      help="print '<scene> <frame>...' per scene for the oracle")
    args = ap.parse_args(argv)
    if args.frames:
        for name, scene in SCENES.items():
            print(name, *scene["frames"])
        return 0
    files = generate()
    if args.write:
        for name, data in files.items():
            (HERE / name).write_bytes(data)
        print("mmegold: wrote %d files" % len(files))
        return 0
    drift = [n for n, d in files.items()
             if not (HERE / n).is_file() or (HERE / n).read_bytes() != d]
    for n in drift:
        print("mmegold: DRIFT " + n, file=sys.stderr)
    if drift:
        return 1
    print("mmegold: %d files match" % len(files))
    return 0


if __name__ == "__main__":
    sys.exit(main())
