"""Evaluate finite coefficient and block accumulation candidates on held-out coordinates."""
import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import struct
from fit_native_interpolation import f32,bits


def quantize(value, precision):
    if value==0:return value
    mantissa, exponent=math.frexp(value)
    return math.ldexp(round(mantissa*2**precision)/2**precision,exponent)


def predictions(intercept,slope,coordinate):
    out={"double_direct":f32(intercept+coordinate*slope)}
    for precision in (16,20,24,28,32):
        a,b=quantize(intercept,precision),quantize(slope,precision)
        out[f"coeff{precision}_direct"]=f32(a+coordinate*b)
    for block in (1,2,4,8,16):
        for origin in (0,1):
            base=(coordinate-origin)//block*block+origin
            for start in ("double","float"):
                value=f32(intercept+base*slope) if start=="double" else f32(f32(intercept)+f32(base*f32(slope)))
                for _ in range(coordinate-base):value=f32(value+f32(slope))
                out[f"block{block}_origin{origin}_{start}_accumulate"]=value
    return out


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root",type=Path);parser.add_argument("fits",type=Path);parser.add_argument("output",type=Path)
    parser.add_argument("--capture",type=Path)
    args=parser.parse_args()
    fits=json.loads(args.fits.read_text())["coefficientFits"]
    stats=defaultdict(lambda:{"exact":0,"total":0,"maxULP":0});proposals=[]
    for row in fits:
        span=row["span"];si=(32,48,64,63.75).index(span);g=row["geometry"];pal=row["palette"];tri=row["triangle"];ch=row["channel"]
        name=f"g{g}-s{si}-c{pal}-f116-a0-p0.raw"
        image=(args.root/name).read_bytes();height=span/2 if g>=2 else span
        locations={}
        for y in range(2,int(height)-2):
            for x in range(2,int(span)-2):
                d=(x+.5)/span-(y+.5)/height if g%2 else (x+.5)/span+(y+.5)/height-1
                if abs(d)<1e-9:continue
                owner=(0 if d>0 else 1) if g%2 else (0 if d<0 else 1)
                if owner==tri:locations.setdefault(x if ch==0 else y,(x,y))
        for coordinate,(x,y) in locations.items():
            if coordinate in row["trainingCoordinates"]:continue
            actual=struct.unpack_from("<4f",image,(y*64+x)*16)[ch]
            pred=predictions(row["inferredIntercept"],row["inferredSlope"],coordinate)
            for model,value in pred.items():
                s=stats[model];delta=abs(bits(value)-bits(actual));s["exact"]+=delta==0;s["total"]+=1;s["maxULP"]=max(s["maxULP"],delta)
            if len(proposals)<32 and pal!=0 and len({bits(v) for v in pred.values()})>=5:
                proposals.append({"image":name,"x":x,"y":y,"channel":ch,"triangle":tri,"observedBits":bits(actual),"predictedBits":{n:bits(v) for n,v in pred.items()}})
    ranking=sorted(stats,key=lambda n:(-stats[n]["exact"],stats[n]["maxULP"]))
    capture=[]
    if args.capture:
        for row in proposals:
            file=args.capture/row["image"]
            if not file.exists():capture.append({"image":row["image"],"status":"missing"});continue
            data=file.read_bytes();actual=bits(struct.unpack_from("<4f",data,(row["y"]*64+row["x"])*16)[row["channel"]])
            capture.append({"image":row["image"],"x":row["x"],"y":row["y"],"channel":row["channel"],"recapturedBits":actual,"matchesPrevious":actual==row["observedBits"],"matchingModels":[n for n,v in row["predictedBits"].items() if v==actual]})
    result={"scope":"data-fitted coefficients from training subset; model scores use held-out coordinates only","models":dict(stats),"ranking":ranking,"universalExact": [n for n in ranking if stats[n]["exact"]==stats[n]["total"]],"discriminatingPixels":proposals,"recaptureChecks":capture}
    args.output.write_text(json.dumps(result,indent=2),encoding="utf-8")
    for n in ranking[:8]:print(n,stats[n])
    print("universal exact",result["universalExact"],"proposals",len(proposals))
    if args.capture:print("recaptured",len(capture),"matches",sum(r.get("matchesPrevious",False) for r in capture))
    return bool(args.capture and any(not row.get("matchesPrevious",False) for row in capture))


if __name__=="__main__":raise SystemExit(main())
