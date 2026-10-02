"""Infer affine coefficients on training coordinates, then test held-out pixels.

Inferred coefficients are descriptive; they are not a renderer implementation.
"""
import argparse
import json
from pathlib import Path
import struct
from fit_native_interpolation import f32, bits


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root",type=Path)
    parser.add_argument("output",type=Path)
    parser.add_argument("--train-phase",type=int,choices=(0,1,2),default=0)
    args=parser.parse_args()
    rows=[]
    for si,span in enumerate((32,48,64,63.75)):
        for palette,(start,end) in enumerate(((64,64),(0,254),(254,0),(63,65))):
            for geometry in range(4):
                height=span/2 if geometry>=2 else span
                image=(args.root/f"g{geometry}-s{si}-c{palette}-f116-a0-p0.raw").read_bytes()
                if len(image)!=65536:raise ValueError("invalid image dimensions")
                for triangle in (0,1):
                    for channel in (0,1):
                        grouped={}
                        for y in range(2,int(height)-2):
                            for x in range(2,int(span)-2):
                                u,v=(x+.5)/span,(y+.5)/height
                                distance=u-v if geometry%2 else u+v-1
                                if abs(distance)<1e-9:continue
                                owner=(0 if distance>0 else 1) if geometry%2 else (0 if distance<0 else 1)
                                if owner!=triangle:continue
                                coord=x if channel==0 else y
                                value=struct.unpack_from("<4f",image,(y*64+x)*16)[channel]
                                grouped.setdefault(coord,[]).append(value)
                        perpendicular=max((max(bits(v) for v in values)-min(bits(v) for v in values) for values in grouped.values()),default=0)
                        coordinates=sorted(grouped)
                        if len(coordinates)<4:raise ValueError("insufficient coordinates")
                        train=coordinates[args.train_phase::3]
                        test=[c for c in coordinates if c not in train]
                        values={c:grouped[c][0] for c in coordinates}
                        avg_x=sum(train)/len(train);avg_y=sum(values[c] for c in train)/len(train)
                        slope=sum((c-avg_x)*(values[c]-avg_y) for c in train)/sum((c-avg_x)**2 for c in train)
                        intercept=avg_y-slope*avg_x
                        theoretical_slope=(end-start)/span/255
                        theoretical_intercept=start/255+.5*theoretical_slope
                        evaluations=[]
                        for model in ("double_coeff_single_round","float_coeff_single_round","float_coeff_separate"):
                            exact=maximum=0
                            for c in test:
                                if model=="double_coeff_single_round":predicted=f32(intercept+c*slope)
                                elif model=="float_coeff_single_round":predicted=f32(f32(intercept)+c*f32(slope))
                                else:predicted=f32(f32(intercept)+f32(c*f32(slope)))
                                delta=bits(predicted)-bits(values[c]);exact+=delta==0;maximum=max(maximum,abs(delta))
                            evaluations.append({"model":model,"heldOutCoordinates":len(test),"exact":exact,"maxULP":maximum})
                        rows.append({"span":span,"palette":palette,"geometry":geometry,"triangle":triangle,"channel":channel,"perpendicularSpreadULP":perpendicular,"trainingCoordinates":train,"inferredSlope":slope,"inferredIntercept":intercept,"slopeErrorByteUnits":(slope-theoretical_slope)*255,"interceptErrorByteUnits":(intercept-theoretical_intercept)*255,"heldOutEvaluations":evaluations})
    result={"trainingPhase":args.train_phase,"scope":"A32 single-sample interiors; shared edges excluded; one in three coordinates trains coefficients; remaining coordinates held out","coefficientFits":rows,"interpretation":"descriptive data-fitted coefficients, not proof of native setup or operation sequence"}
    args.output.write_text(json.dumps(result,indent=2),encoding="utf-8")
    print("coefficient planes",len(rows),"perpendicular variation",sum(r["perpendicularSpreadULP"]!=0 for r in rows))
    for model in ("double_coeff_single_round","float_coeff_single_round","float_coeff_separate"):
        a=[v for r in rows for v in r["heldOutEvaluations"] if v["model"]==model]
        print(model,"exact",sum(v["exact"] for v in a),"/",sum(v["heldOutCoordinates"] for v in a),"maxULP",max(v["maxULP"] for v in a),"exactPlanes",sum(v["exact"]==v["heldOutCoordinates"] for v in a))
    print("max slope error byteUnits",max(abs(r["slopeErrorByteUnits"]) for r in rows))


if __name__=="__main__":main()
