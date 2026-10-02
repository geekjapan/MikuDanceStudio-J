"""Compare equal-color-plane geometries over their common interior."""
import argparse
import json
from pathlib import Path
import struct


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("x64",type=Path)
    parser.add_argument("x86",type=Path)
    parser.add_argument("output",type=Path)
    args=parser.parse_args()
    files=sorted(args.x64.glob("g*-s*-c*-f*-a0-p*.raw"))
    if len(files)!=768:raise ValueError(f"expected 768 images, found {len(files)}")
    arch=[f.name for f in files if f.read_bytes()!=(args.x86/f.name).read_bytes()]
    rows=[]
    for si,span in enumerate((32,48,64,63.75)):
        for palette in range(4):
            for fmt,layout,size in ((21,"4B",4),(113,"4e",8),(116,"4f",16)):
                for path in range(4):
                    suffix=f"s{si}-c{palette}-f{fmt}-a0-p{path}.raw"
                    images=[(args.x64/(f"g{g}-"+suffix)).read_bytes() for g in range(4)]
                    for ga,gb in ((0,1),(2,3),(0,2),(1,3)):
                        height=span/2 if max(ga,gb)>=2 else span
                        count=diff=0;max_byte=max_ulp=0;first=None
                        for y in range(2,int(height)-2):
                            for x in range(2,int(span)-2):
                                # Exclude every involved diagonal to avoid ownership ties.
                                def on_edge(g):
                                    h=span/2 if g>=2 else span
                                    u,v=(x+.5)/span,(y+.5)/h
                                    return abs((u-v) if g%2 else (u+v-1))<1e-9
                                if on_edge(ga) or on_edge(gb):continue
                                count+=1;at=(y*64+x)*size
                                a=struct.unpack_from("<"+layout,images[ga],at);b=struct.unpack_from("<"+layout,images[gb],at)
                                if a!=b:
                                    diff+=1
                                    max_byte=max(max_byte,max(abs(v-w) for v,w in zip(a,b))*(255 if fmt!=21 else 1))
                                    if fmt==116:max_ulp=max(max_ulp,max(abs(struct.unpack("<I",struct.pack("<f",v))[0]-struct.unpack("<I",struct.pack("<f",w))[0]) for v,w in zip(a,b)))
                                    if first is None:first={"x":x,"y":y,"reference":a,"other":b}
                        rows.append({"span":span,"palette":palette,"format":fmt,"path":path,"geometries":[ga,gb],"pixelsCompared":count,"differentPixels":diff,"maxDeltaByteUnits":max_byte,"maxULP":max_ulp,"firstDifference":first})
    result={"crossArchitectureDifferentImages":arch,"baselineImages":len(files),"comparisons":rows,
            "scope":"single sampling; common interior excluding both diagonals; same integer endpoint affine plane"}
    args.output.write_text(json.dumps(result,indent=2),encoding="utf-8")
    print("images",len(files),"arch differences",len(arch))
    for path in range(4):
        for fmt in (21,113,116):
            group=[r for r in rows if r["path"]==path and r["format"]==fmt]
            print("path",path,"format",fmt,"differentCases",sum(r["differentPixels"]!=0 for r in group),"/",len(group),"maxByteDelta",max(r["maxDeltaByteUnits"] for r in group),"maxULP",max(r["maxULP"] for r in group))
    return bool(arch)


if __name__=="__main__":raise SystemExit(main())
