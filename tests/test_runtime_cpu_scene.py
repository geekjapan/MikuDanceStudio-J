"""Generate redistributable inputs and run native CPU scene acceptance."""
import argparse
import subprocess
import tempfile
import os
import cpu_import_fixture

parser = argparse.ArgumentParser()
parser.add_argument('--test')
parser.add_argument('--bridge')
parser.add_argument('--passes')
parser.add_argument('--assets')
parser.add_argument('--native-x', action='store_true')
args = parser.parse_args()
if not args.test and not args.bridge and not args.passes:
    parser.error('provide --test, --bridge or --passes')
with tempfile.TemporaryDirectory(prefix='mds-cpu-scene-') as root:
    cpu_import_fixture.write(root)
    if args.test:
        subprocess.run([args.test, root], check=True, timeout=60)
    if args.passes:
        command = ([args.passes, '--native-x', os.path.join(root, 'bound.x')]
                   if args.native_x else [args.passes, root, args.assets])
        subprocess.run(command, check=True, timeout=60)
        if args.native_x:
            subprocess.run([args.passes, '--native-x', os.path.join(root, 'bound-varied.x')], check=True, timeout=60)
    if args.bridge:
        env = os.environ.copy()
        env.setdefault('MDS_PMM_SCENE_SESSION_FIXTURE', os.path.join(root, 'v2.pmm'))
        subprocess.run([args.bridge], check=True, timeout=60, env=env)
