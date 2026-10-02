"""Test parameter-free 2D interpolation models partitioned by triangle ownership.

Shared-edge pixels are excluded: this script does not infer rasterizer tie rules.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import struct
from fit_native_interpolation import f32, bits


def models(span, endpoints, x, y, triangle, channel):
    vertices = ((-.5,-.5),(span-.5,-.5),(-.5,span-.5)) if triangle==0 else ((span-.5,-.5),(span-.5,span-.5),(-.5,span-.5))
    start,end = endpoints
    values = [start if vertex[channel]==-.5 else end for vertex in vertices]
    x0,y0=vertices[0];x1,y1=vertices[1];x2,y2=vertices[2]
    dx1,dy1=f32(x1-x0),f32(y1-y0)
    dx2,dy2=f32(x2-x0),f32(y2-y0)
    det=f32(f32(dx1*dy2)-f32(dx2*dy1))
    px,py=f32(x-x0),f32(y-y0)
    u=f32(f32(f32(px*dy2)-f32(dx2*py))/det)
    v=f32(f32(f32(dx1*py)-f32(px*dy1))/det)
    area0=f32(f32(f32(x1-x)*f32(y2-y))-f32(f32(x2-x)*f32(y1-y)))
    area1=f32(f32(f32(x2-x)*f32(y0-y))-f32(f32(x0-x)*f32(y2-y)))
    area2=f32(f32(f32(x0-x)*f32(y1-y))-f32(f32(x1-x)*f32(y0-y)))
    independent=[f32(area/det) for area in (area0,area1,area2)]
    result={"ideal_single_round":f32((start+(x+.5 if channel==0 else y+.5)*(end-start)/span)/255)}
    for decode in ("divide","reciprocal"):
        colors=[f32(value/255) if decode=="divide" else f32(value*f32(1/255)) for value in values]
        a,b,c=colors
        db,dc=f32(b-a),f32(c-a)
        result[decode+"_anchor_separate"]=f32(f32(a+f32(u*db))+f32(v*dc))
        result[decode+"_anchor_single_round"]=f32(a+u*db+v*dc)
        weights=[f32(1-f32(u+v)),u,v]
        for label,w in (("reconstructed",weights),("independent_area",independent)):
            terms=[f32(wi*ci) for wi,ci in zip(w,colors)]
            result[decode+"_"+label+"_left_sum"]=f32(f32(terms[0]+terms[1])+terms[2])
            result[decode+"_"+label+"_right_sum"]=f32(terms[0]+f32(terms[1]+terms[2]))
            result[decode+"_"+label+"_single_round"]=f32(sum(wi*ci for wi,ci in zip(w,colors)))
        gx=f32(f32(f32(db*dy2)-f32(dc*dy1))/det)
        gy=f32(f32(f32(dx1*dc)-f32(dx2*db))/det)
        result[decode+"_plane_anchor_separate"]=f32(f32(a+f32(px*gx))+f32(py*gy))
        result[decode+"_plane_anchor_single_round"]=f32(a+px*gx+py*gy)
        intercept=f32(f32(a-f32(x0*gx))-f32(y0*gy))
        result[decode+"_plane_global_separate"]=f32(f32(intercept+f32(x*gx))+f32(y*gy))
        result[decode+"_plane_global_single_round"]=f32(intercept+x*gx+y*gy)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root",type=Path)
    parser.add_argument("output",type=Path)
    args=parser.parse_args()
    stats={};excluded=0;ownership=Counter();spreads=[]
    for si,span in enumerate((32,48,64,63.75)):
        for palette,endpoints in enumerate(((64,64),(0,255),(255,0),(63,65))):
            image=(args.root/f"s{si}-c{palette}-f116-a0-p0.raw").read_bytes()
            if len(image)!=64*64*16:raise ValueError("invalid image dimensions")
            samples={}
            for y in range(2,int(span)-2):
                for x in range(2,int(span)-2):
                    distance=x+y+1-span
                    if abs(distance)<1e-9:
                        excluded+=1;continue
                    tri=0 if distance<0 else 1
                    ownership[tri]+=1
                    observed=struct.unpack_from("<4f",image,(y*64+x)*16)
                    for channel in (0,1):
                        coord=x if channel==0 else y
                        samples.setdefault((tri,channel,coord),[]).append(bits(observed[channel]))
                        for name,prediction in models(span,endpoints,x,y,tri,channel).items():
                            stat=stats.setdefault(name,{"channels":0,"exact":0,"maxULP":0,"groups":{},"firstMismatch":None})
                            delta=bits(prediction)-bits(observed[channel]);stat["channels"]+=1;stat["exact"]+=delta==0;stat["maxULP"]=max(stat["maxULP"],abs(delta))
                            group=stat["groups"].setdefault(f"span{si}_palette{palette}_triangle{tri}",{"channels":0,"exact":0,"maxULP":0})
                            group["channels"]+=1;group["exact"]+=delta==0;group["maxULP"]=max(group["maxULP"],abs(delta))
                            if delta and stat["firstMismatch"] is None:stat["firstMismatch"]={"span":span,"palette":palette,"triangle":tri,"x":x,"y":y,"channel":channel,"observed":observed[channel],"predicted":prediction,"ULP":delta}
            for tri in (0,1):
                for channel in (0,1):
                    groups=[values for (t,c,coord),values in samples.items() if t==tri and c==channel and len(values)>1]
                    spread=[max(values)-min(values) for values in groups]
                    spreads.append({"span":span,"palette":palette,"triangle":tri,"channel":channel,"coordinateGroups":len(spread),"varyingGroups":sum(s!=0 for s in spread),"maxSpreadULP":max(spread,default=0)})
    ranking=sorted(stats,key=lambda name:(-stats[name]["exact"],stats[name]["maxULP"]))
    result={"scope":"one axis label only; A32 interior R/G; no shared-edge pixels", "trianglePixelCounts":dict(ownership),"excludedSharedEdgePixels":excluded,"ranking":ranking,"models":stats,"withinTrianglePerpendicularSpread":spreads,"universalExactModels":[n for n in ranking if stats[n]["exact"]==stats[n]["channels"]]}
    args.output.write_text(json.dumps(result,indent=2),encoding="utf-8")
    print("ownership",dict(ownership),"excluded",excluded)
    for name in ranking:print(name,stats[name]["exact"],"/",stats[name]["channels"],"maxULP",stats[name]["maxULP"])
    print("universal exact",result["universalExactModels"])
    print("within triangle varying groups",sum(r["varyingGroups"] for r in spreads),"maxSpreadULP",max(r["maxSpreadULP"] for r in spreads))


if __name__=="__main__":main()
