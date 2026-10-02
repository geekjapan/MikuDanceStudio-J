"""Test explicit affine arithmetic candidates against saved float32 outputs.

Float32 is rounded after named operations; fused candidates round once after
multiply/add using binary64 (sufficient here, not a general FMA implementation).
No parameters are fitted to individual pixels.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import struct


def f32(x):
    return struct.unpack("<f", struct.pack("<f", x))[0]


def bits(x):
    return struct.unpack("<I", struct.pack("<f", x))[0]


def candidates(start, end, span, coordinate):
    t = coordinate + .5
    a, b = f32(start / 255), f32(end / 255)
    am, bm = f32(start * f32(1 / 255)), f32(end * f32(1 / 255))
    out = {}
    for decode, low, high in (("divide", a, b), ("reciprocal", am, bm)):
        diff = f32(high-low)
        slope = f32(diff/span)
        out[decode+"_slope_separate"] = f32(low+f32(t*slope))
        out[decode+"_slope_fused"] = f32(low+t*slope)
        weight = f32(t/span)
        out[decode+"_weight_separate"] = f32(low+f32(weight*diff))
        out[decode+"_weight_fused"] = f32(low+weight*diff)
        out[decode+"_barycentric_separate"] = f32(f32(f32(1-weight)*low)+f32(weight*high))
        out[decode+"_barycentric_fused"] = f32((1-weight)*low+weight*high)
    byte_slope = f32((end-start)/span)
    out["byte_plane_divide"] = f32(f32(start+f32(t*byte_slope))/255)
    out["byte_plane_reciprocal"] = f32(f32(start+f32(t*byte_slope))*f32(1/255))
    out["ideal_single_round"] = f32((start+t*(end-start)/span)/255)
    # Evaluate a coordinate-space intercept instead of shifting the pixel coordinate.
    slope = f32(f32(b-a)/span)
    intercept = f32(a+f32(.5*slope))
    out["divide_intercept_separate"] = f32(intercept+f32(coordinate*slope))
    out["divide_intercept_fused"] = f32(intercept+coordinate*slope)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    stats = {}
    for span_index, span in enumerate((32,48,64,63.75)):
        for palette, endpoints in enumerate(((64,64),(0,255),(255,0),(63,65))):
            for axis in (0,1):
                data = (args.root/f"s{span_index}-c{palette}-f116-a{axis}-p0.raw").read_bytes()
                if len(data) != 64*64*16:
                    raise ValueError("invalid image dimensions")
                limit = int(span)-2
                for y in range(2,limit):
                    for x in range(2,limit):
                        observed = struct.unpack_from("<4f",data,(y*64+x)*16)
                        for channel, coordinate in ((0,x),(1,y)):
                            actual = bits(observed[channel])
                            for name, prediction in candidates(*endpoints,span,coordinate).items():
                                stat = stats.setdefault(name,{"channels":0,"exact":0,"maxAbsULP":0,"ULPHistogram":Counter(),"groups":{},"firstMismatch":None})
                                delta = bits(prediction)-actual
                                stat["channels"] += 1
                                stat["exact"] += delta == 0
                                stat["maxAbsULP"] = max(stat["maxAbsULP"],abs(delta))
                                stat["ULPHistogram"][delta] += 1
                                group = stat["groups"].setdefault(f"span{span_index}_palette{palette}",{"channels":0,"exact":0,"maxAbsULP":0})
                                group["channels"] += 1
                                group["exact"] += delta == 0
                                group["maxAbsULP"] = max(group["maxAbsULP"],abs(delta))
                                if delta and stat["firstMismatch"] is None:
                                    stat["firstMismatch"] = {"span":span,"palette":palette,"axis":axis,"x":x,"y":y,"channel":channel,"observed":observed[channel],"prediction":prediction,"ULPDelta":delta}
    perpendicular = []
    for span_index, span in enumerate((32,48,64,63.75)):
        for palette in range(4):
            data = (args.root/f"s{span_index}-c{palette}-f116-a0-p0.raw").read_bytes()
            limit = int(span)-2
            for channel in (0,1):
                nonconstant = 0
                maximum_spread = 0
                example = None
                for coordinate in range(2,limit):
                    values = []
                    for other in range(2,limit):
                        x,y = (coordinate,other) if channel == 0 else (other,coordinate)
                        value = struct.unpack_from("<4f",data,(y*64+x)*16)[channel]
                        values.append(bits(value))
                    spread = max(values)-min(values)
                    nonconstant += spread != 0
                    maximum_spread = max(maximum_spread,spread)
                    if spread and example is None:
                        example = {"coordinate":coordinate,"minBits":min(values),"maxBits":max(values)}
                perpendicular.append({"span":span,"palette":palette,"channel":channel,
                    "coordinatesCompared":limit-2,"varyingAtSameCoordinate":nonconstant,
                    "maxSpreadULP":maximum_spread,"firstExample":example})
    ranking = sorted(stats,key=lambda name:(-stats[name]["exact"],stats[name]["maxAbsULP"]))
    result = {"scope":"unit-RHW axis-aligned packed-color squares, interior R/G only; duplicate axis controls included",
              "perpendicularCoordinateVariation":perpendicular,"ranking":ranking,"candidates":stats,"universalExactCandidates":[name for name in ranking if stats[name]["exact"]==stats[name]["channels"]]}
    args.output.write_text(json.dumps(result,indent=2),encoding="utf-8")
    for name in ranking:
        s = stats[name]
        print(name,"exact",s["exact"],"/",s["channels"],"maxULP",s["maxAbsULP"])
    print("perpendicular varying rows",sum(row["varyingAtSameCoordinate"]!=0 for row in perpendicular),"maxSpreadULP",max(row["maxSpreadULP"] for row in perpendicular))
    print("universal exact",result["universalExactCandidates"])


if __name__ == "__main__":
    main()
