"""Validate accepted sample.pmm all-17-material runs and Mip provenance."""
import argparse
import csv
import json
from pathlib import Path


def read_rows(path):
    with path.open(encoding='utf-8', newline='') as stream:
        return list(csv.DictReader(stream))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('runs',nargs='+',type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    results=[]
    preparations={}
    for directory in args.runs:
        report=json.loads((directory/'run.json').read_text(encoding='utf-8'))
        assert report['status']=='PASS', str(directory)
        assert report['materials']==list(range(12,17))
        assert report['cpuPrefixFamilies']=='ground-shadow-model' and report['mipPreparation']=='dx9'
        assert report['cpuPrefixExact'] and report['mipPreparationExact'] and report['sceneHistoryExact']
        assert report['lifecycleExact'] and report['previewExact'] and report['prefixOrderExact'] and report['materialOrderExact']
        assert report['playbackSamples']>0 and report['previewCoveredPixels']>0
        assert report['applicationBackend']=='dx9' and not report['productionActivation']
        processes=[]
        for filename in directory.glob('cpu_prefix.*.csv'):
            rows=read_rows(filename)
            assert all(r['status']=='PASS' and r['geometrySource']==r['stateSource']=='cpu' for r in rows)
            boundaries=[int(r['boundary']) for r in rows]
            assert boundaries==sorted(set(boundaries))
            assert [int(r['material']) for r in rows if r['family']=='model_material']==list(range(12))
            assert {r['family'] for r in rows} >= {'ground_lines','ground_plane','model_material'}
            shadows=[int(r['material']) for r in rows if r['family']=='projected_model_shadow']
            if shadows:
                assert shadows==list(range(17))
            processes.append(len(rows))
        assert sorted(processes)==[14,31] and report['cpuPrefixChecks']==45
        mip_rows=[r for filename in directory.glob('mip_preparation.*.csv') for r in read_rows(filename)]
        assert len(mip_rows)==report['mipPreparationChecks']
        assert {int(r['material']) for r in mip_rows}=={0,1,3,4,6}
        for row in mip_rows:
            assert row['origin']=='independent_cpu_source' and row['policy']=='dx9'
            assert int(row['providerRevision']) and int(row['preparedRevision']) and int(row['decodedRevision'])
            width,height=int(row['width']),int(row['height'])
            assert width==height and width in (128,256)
            assert int(row['levels'])==width.bit_length()
            key=(Path(row['asset']).name,row['decodedRevision'],row['sourceRevision'],row['providerRevision'])
            value=(row['preparedRevision'],row['width'],row['height'],row['levels'])
            assert key not in preparations or preparations[key]==value, (key,value)
            preparations[key]=value
        results.append(dict(directory=str(directory),applicationSha256=report['applicationSha256'],
                            mode=report['inputMode'],switchToon=report['switchToon'],translucent=report['translucent'],
                            cpuDrawChecks=45,historyChecks=report['sceneHistoryChecks'],
                            lifecycleChecks=report['lifecycleChecks'],mipPreparationChecks=len(mip_rows),
                            nonemptyPreviewChecks=report['previewSamples']-report['previewEmptySamples']))
    summary=dict(status='PASS',runs=results,crossRunMipVersionsExact=True,
                 totals={key:sum(r[key] for r in results) for key in
                         ('cpuDrawChecks','historyChecks','lifecycleChecks','mipPreparationChecks','nonemptyPreviewChecks')})
    args.output.write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in summary.items() if k!='runs'}))


if __name__=='__main__':
    main()
