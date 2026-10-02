"""Compare standalone triangle orders with a paired draw, excluding shared edges."""
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
    files=sorted(args.x64.glob("o*-s*-c*-f*-a0-p*.raw"))
    if len(files)!=2496:raise ValueError(f"expected 2496 images, found {len(files)}")
    architecture=[f.name for f in files if f.read_bytes()!=(args.x86/f.name).read_bytes()]
    results=[]
    for si,span in enumerate((32,48,64,63.75)):
        for palette in range(4):
            for fmt,layout,size in ((21,"4B",4),(113,"4e",8),(116,"4f",16)):
                for path in range(4):
                    suffix=f"s{si}-c{palette}-f{fmt}-a0-p{path}.raw"
                    pair=(args.x64/("o0-"+suffix)).read_bytes()
                    for tri in (0,1):
                        reference=(args.x64/(f"o{1+tri*6}-"+suffix)).read_bytes()
                        for permutation in range(6):
                            image=(args.x64/(f"o{1+tri*6+permutation}-"+suffix)).read_bytes()
                            diff=pair_diff=0;maximum=0;first=None;coverage_diff=0
                            for at in range(0,len(image),size):
                                a=struct.unpack_from("<"+layout,image,at)
                                b=struct.unpack_from("<"+layout,reference,at)
                                coverage_diff+=(a[3]!=0)!=(b[3]!=0)
                            for y in range(2,int(span)-2):
                                for x in range(2,int(span)-2):
                                    d=x+y+1-span
                                    if abs(d)<1e-9 or (d<0)!=(tri==0):continue
                                    at=(y*64+x)*size
                                    a=struct.unpack_from("<"+layout,image,at);b=struct.unpack_from("<"+layout,reference,at);c=struct.unpack_from("<"+layout,pair,at)
                                    pair_diff+=a!=c
                                    if a!=b:
                                        diff+=1
                                        maximum=max(maximum,max(abs(v-w) for v,w in zip(a,b))*(255 if fmt!=21 else 1))
                                        if first is None:first={"x":x,"y":y,"reference":b,"permuted":a}
                            results.append({"span":span,"palette":palette,"format":fmt,"path":path,"triangle":tri,"permutation":permutation,"differentInteriorPixels":diff,"differentFromPairInteriorPixels":pair_diff,"coverageDifferentPixels":coverage_diff,"maxDeltaByteUnits":maximum,"firstDifference":first})
    result={"imagesCompared":len(files),"crossArchitectureDifferentImages":architecture,"scope":"unit RHW, single sampling; shared-edge excluded from interior comparisons","comparisons":results}
    args.output.write_text(json.dumps(result,indent=2),encoding="utf-8")
    print("architecture differences",len(architecture))
    for path in range(4):
        group=[r for r in results if r["path"]==path]
        print("path",path,"permutationDifferentCases",sum(r["differentInteriorPixels"]!=0 for r in group),"pairDifferentCases",sum(r["differentFromPairInteriorPixels"]!=0 for r in group),"coverageDifferentCases",sum(r["coverageDifferentPixels"]!=0 for r in group))
    return bool(architecture)


if __name__=="__main__":raise SystemExit(main())
