#!/usr/bin/env python3
"""Capture unmodified btDbvt with controlled real addresses, then compare Rust."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent.parent


def run(command,**kwargs):
    return subprocess.run(list(map(str,command)),cwd=ROOT,check=True,**kwargs)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir',type=Path,required=True)
    args=parser.parse_args()
    out=args.out_dir.resolve()
    out.mkdir(parents=True,exist_ok=True)
    src=ROOT/'recipes/bullet275/bullet-src/src'
    command=[os.environ.get('CXX','clang++'),'-std=c++17','-O2','-fdeclspec','-DBT_NO_PROFILE=1','-I',src,HERE/'oracle.cpp',src/'BulletCollision/BroadphaseCollision/btDbvt.cpp',src/'LinearMath/btAlignedAllocator.cpp','-o',out/'oracle']
    (out/'native-command.txt').write_text(' '.join(map(str,command))+'\n')
    run(command)
    inputs=subprocess.check_output([sys.executable,HERE/'cases.py'])
    (out/'inputs.tsv').write_bytes(inputs)
    for order in range(4):
        captured=subprocess.check_output([out/'oracle',str(order)],input=inputs)
        (out/f'native-{order}.tsv').write_bytes(captured)
    env=dict(os.environ,DBVT_FIXTURES=str(out))
    run(['rustup','run','1.95.0','cargo','test','--manifest-path',HERE/'Cargo.toml','--release'],env=env)
    print(f'{len(inputs.splitlines())} operations x 3 actual native address histories compared.')


if __name__=='__main__':
    main()
