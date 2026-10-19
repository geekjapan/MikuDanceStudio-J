"""Exercise CPU import and the application's early DX11/DX12 startup branch."""
import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path
import cpu_import_fixture


def run(command, *, console=True):
    result = subprocess.run([str(x) for x in command], capture_output=True,
                            text=True, errors='replace', timeout=60)
    print(' '.join(str(x) for x in command), flush=True)
    print(result.stdout + result.stderr, end='', flush=True)
    if result.returncode:
        raise AssertionError(f'process failed: {result.returncode}')
    if console:
        for expected in ('cpu_import=PASS native_model_buffers=0 legacy_startup=bypassed',
                         'restored_image_exact=1 resident_after_unload=0'):
            assert expected in result.stdout, expected
    return result.stdout


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--preview', required=True, type=Path)
    parser.add_argument('--application', required=True, type=Path)
    parser.add_argument('--api', required=True, choices=('dx11', 'dx12'))
    parser.add_argument('--driver', required=True, choices=('hardware', 'warp'))
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='mds-independent-') as directory:
        root = Path(directory)
        cpu_import_fixture.write(root)
        options = ['--frames', '6', '--lifecycle']
        if args.driver == 'warp': options.append('--warp')
        filenames = ('triangle.pmd', 'sphere.pmd', 'triangle.pmx', 'v1.pmm', 'v2.pmm', 'pmx.pmm',
                     'articulated.pmd', 'articulated.pmx', 'ik-v1.pmm',
                     'physics-v2.pmm', 'sdef-physics-v2.pmm', 'bound-v1.pmm', 'bound-v2.pmm', 'passes-v2.pmm')
        for filename in filenames:
            command = [args.preview, args.api, root / filename, *options]
            if filename.startswith(('bound-', 'passes-')): command += ['--scene-passes']
            saved = root / (filename + '.saved.pmm')
            if filename.endswith('.pmm'): command += ['--save-as', saved]
            output = run(command)
            assert 'shared_cpu_world=1' in output
            if 'physics-v2' in filename:
                assert 'bodies=2 physics_mode=2' in output
            if filename.endswith('.pmm'):
                updates = re.search(r'geometry_updates=(\d+)', output)
                assert updates and int(updates[1]) > 1, 'animated CPU geometry was not updated'
                cursor = re.search(r'playback_cursor_seconds=([0-9.eE+-]+)', output)
                assert cursor and float(cursor[1]) > 4 / 30, 'playback stalled or used a delta as an absolute cursor'
                assert saved.exists() and saved.stat().st_size == (root / filename).stat().st_size
        # Same host, entered before legacy UI/InitD3D/MME in WinMain.
        run([args.application, '--rhi-preview', args.api, root / 'pmx.pmm', *options],
            console=False)
    print(json.dumps({'status': 'PASS', 'api': args.api, 'driver': args.driver,
                      'generated_fixtures': len(filenames), 'early_application_startups': 1,
                      'frames_per_run': 6, 'replacement_images_exact': True}))


if __name__ == '__main__':
    main()
