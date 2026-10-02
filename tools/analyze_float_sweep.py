"""Analyze interior color precision over spans and increasing/decreasing slopes."""
import argparse
from collections import Counter
import json
from pathlib import Path
import struct


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("x64", type=Path)
    parser.add_argument("x86", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    different_arch = []
    files = sorted(args.x64.glob("s*-c*-f*-a*-p*.raw"))
    if len(files) != 384:
        raise ValueError("expected 384 baseline images")
    for file in files:
        if file.read_bytes() != (args.x86 / file.name).read_bytes():
            different_arch.append(file.name)
    rows = []
    for span_index, span in enumerate((32,48,64,63.75)):
        # Stay two pixels from raster edges; targets/coverage are not used to fit color.
        limit = int(span) - 2
        for palette in range(4):
            for fmt, layout, size in ((21,"4B",4),(113,"4e",8),(116,"4f",16)):
                for axis in (0,1):
                    prefix = f"s{span_index}-c{palette}-f{fmt}-a{axis}"
                    images = [(args.x64 / (prefix+f"-p{p}.raw")).read_bytes() for p in range(4)]
                    for path in (1,2,3):
                        signs = Counter()
                        maximum = 0
                        ulps = Counter()
                        first = None
                        count = mismatches = 0
                        for y in range(2,limit):
                            for x in range(2,limit):
                                a = struct.unpack_from("<"+layout,images[0],(y*64+x)*size)
                                b = struct.unpack_from("<"+layout,images[path],(y*64+x)*size)
                                for channel in (0,1,2):
                                    count += 1
                                    delta = b[channel]-a[channel]
                                    signs["positive" if delta>0 else "negative" if delta<0 else "zero"] += 1
                                    maximum = max(maximum,abs(delta)*(255 if fmt!=21 else 1))
                                    if delta:
                                        mismatches += 1
                                        if first is None:
                                            first = {"x":x,"y":y,"channel":channel,"fixed":a[channel],"other":b[channel]}
                                    if fmt == 116:
                                        bits_a = struct.unpack("<I",struct.pack("<f",a[channel]))[0]
                                        bits_b = struct.unpack("<I",struct.pack("<f",b[channel]))[0]
                                        ulps[bits_b-bits_a] += 1
                        rows.append({"span":span,"palette":palette,"format":fmt,"axis":axis,"path":path,
                            "channelsCompared":count,"differentChannels":mismatches,"signCounts":dict(signs),
                            "maxDeltaByteUnits":maximum,"ULPHistogram":dict(ulps),"firstDifference":first})
    result = {"baselineImagesCompared":len(files),"crossArchitectureDifferentImages":different_arch,
              "interiorOnly":True,"comparisons":rows}
    args.output.write_text(json.dumps(result,indent=2),encoding="utf-8")
    print("images",len(files),"architecture differences",len(different_arch))
    for palette in range(4):
        group = [r for r in rows if r["palette"]==palette and r["path"]==3 and r["format"]==116]
        print("palette",palette,"signs",dict(sum((Counter(r["signCounts"]) for r in group),Counter())),"maxByteDelta",max(r["maxDeltaByteUnits"] for r in group))
    print("fixed vs pass-through differing channels",sum(r["differentChannels"] for r in rows if r["path"] in (1,2)))
    print("8bit analytic differing channels",sum(r["differentChannels"] for r in rows if r["path"]==3 and r["format"]==21))
    return bool(different_arch)


if __name__ == "__main__":
    raise SystemExit(main())
