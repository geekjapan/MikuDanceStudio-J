"""Check repeatability and causal gates, without treating diagnosis as image acceptance."""
import argparse
import csv
import hashlib
import json
import math
import struct
from collections import defaultdict
from pathlib import Path


def rows(root, name):
    with (root / name).open(newline='') as stream:
        return list(csv.DictReader(stream))


def repeatable(table):
    groups = defaultdict(dict)
    for row in table:
        key = tuple((k, v) for k, v in row.items() if k != 'repeat')
        if row['repeat'] in groups[key]:
            return False
        groups[key][row['repeat']] = True
    return bool(groups) and all(set(group) == {'0', '1', '2'} for group in groups.values())


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--compare', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = args.input
    names = ('vertices.csv', 'controls.csv', 'pixels.csv', 'vertex_stages.csv',
             'camera_vertices.csv', 'power_controls.csv', 'flat_vertices.csv')
    tables = {name: rows(root, name) for name in names}
    assert all(repeatable(table) for table in tables.values()), 'incomplete or non-repeatable observations'
    assert all(math.isfinite(float(row['value'])) for row in tables['vertex_stages.csv'])
    controls = tables['controls.csv']
    original = [r for r in controls if r['mode'] == 'original']
    assert len(original) == 9 and all(int(r['coveredPixels']) > 0 for r in original)
    originals = {r['geometry']: r for r in original if r['repeat'] == '0'}
    assert set(originals) == {'saved', 'independent', 'holdout'}
    required_modes = {'original', 'shared_dx9_point_values_ps2', 'shared_dx9_point_values_ps3',
                      'shared_dx11_values_ps2', 'shared_dx11_values_ps3',
                      'mesh_dx9_point_values', 'mesh_dx11_values', 'shared_dx9_flat_values'}
    required_modes.update('camera_policy' + str(policy) for policy in range(1, 8))
    assert len(controls) == 135
    for geometry in originals:
        for repeat in ('0', '1', '2'):
            observed_modes = [r['mode'] for r in controls if r['geometry'] == geometry and r['repeat'] == repeat]
            assert len(observed_modes) == len(required_modes) and set(observed_modes) == required_modes
    assert len(tables['power_controls.csv']) == 3 * 6 * 3 * 3 * 3
    assert {r['control'] for r in tables['power_controls.csv']} == set(map(str, range(6)))
    modes = defaultdict(dict)
    for r in controls:
        if r['repeat'] == '0':
            modes[r['geometry']][r['mode']] = {k: int(r[k]) for k in
                ('coveredPixels', 'betweenApis', 'nativeVsOriginal', 'candidateVsOriginal')}
    shared = [r for r in controls if r['mode'].startswith('shared_') or r['mode'].startswith('mesh_')]
    shared_exact = all(r['betweenApis'] == '0' for r in shared)
    eleven_reproduced = all(r['candidateVsOriginal'] == '0' for r in controls
                           if r['mode'].startswith('shared_dx11_values') or r['mode'] == 'mesh_dx11_values')
    point_reproduced = all(r['nativeVsOriginal'] == '0' for r in controls
                          if r['mode'].startswith('shared_dx9_point_values'))
    flat_reproduced = all(r['nativeVsOriginal'] == '0' for r in controls if r['mode'] == 'shared_dx9_flat_values')
    flat_available = all(r['constant'] == '1' for r in tables['flat_vertices.csv'])
    flat_lookup = {(r['geometry'], int(r['rotation']), int(r['channel'])): r for r in tables['flat_vertices.csv'] if r['repeat'] == '0'}
    files = sorted(p for p in root.iterdir() if p.suffix in ('.csv', '.float', '.hlsl', '.asm'))
    comparison_names = {p.name for p in args.compare.iterdir() if p.suffix in ('.csv', '.float', '.hlsl', '.asm')}
    cross_architecture = {p.name for p in files} == comparison_names and all(
        (args.compare / p.name).is_file() and digest(p) == digest(args.compare / p.name) for p in files)
    float_groups = defaultdict(dict)
    for path in root.glob('*.float'):
        stem, rest = path.name.split('.repeat')
        repeat, side = rest.split('.', 1)
        float_groups[(stem, side)][repeat] = digest(path)
    assert float_groups and all(set(g) == {'0', '1', '2'} and len(set(g.values())) == 1 for g in float_groups.values())
    focus = {geometry: {'x': '509', 'y': '407'} if geometry == 'saved' else {'x': '24', 'y': '32'}
             for geometry in originals}
    pixels = [r for r in tables['pixels.csv'] if r['repeat'] == '0' and
              r['x'] == focus[r['geometry']]['x'] and r['y'] == focus[r['geometry']]['y']]
    bit = lambda f: struct.unpack('<I', struct.pack('<f', f))[0]
    vertex_differences = [{**r, 'signedUlps': int(r['dx11Bits'])-int(r['nativeBits'])}
                          for r in tables['vertices.csv'] if r['repeat'] == '0' and r['nativeBits'] != r['dx11Bits']]
    flat_differences = []
    for r in tables['vertices.csv']:
        if r['repeat'] != '0':
            continue
        flat = flat_lookup[(r['geometry'], int(r['vertex']), int(r['channel']))]
        if flat['bits'] != r['dx11Bits']:
            flat_differences.append(dict(geometry=r['geometry'], vertex=int(r['vertex']), channel=int(r['channel']),
                                         nativeFlat=float(flat['value']), dx11SO=float(r['dx11SO']),
                                         signedUlps=int(r['dx11Bits'])-int(flat['bits'])))
    stage_lookup = {(r['geometry'], int(r['stage']), int(r['vertex']), int(r['channel'])): float(r['value'])
                    for r in tables['vertex_stages.csv'] if r['repeat'] == '0'}
    strength = []
    for r in tables['power_controls.csv']:
        if r['repeat'] != '0' or r['channel'] != '0':
            continue
        strength.append(dict(geometry=r['geometry'], control=int(r['control']), vertex=int(r['vertex']),
                             power=float(r['power']), nativePoint=float(r['nativePoint']), dx11SO=float(r['dx11SO']),
                             nativeFlat=float(r['nativeFlat']), flatSignedUlps=int(r['dx11Bits'])-int(r['nativeFlatBits']),
                             signedUlps=int(r['dx11Bits'])-int(r['nativeBits'])))
    # Numerical verification of the captured DX11 expression, not a model of
    # the hidden native FF instructions or its intermediate precision.
    products = []
    for r in tables['vertices.csv']:
        if r['repeat'] != '0':
            continue
        g, v, c = r['geometry'], int(r['vertex']), int(r['channel'])
        predicted = bit(stage_lookup[(g, 6, v, 0)] * stage_lookup[(g, 7, v, c)])
        products.append(predicted == int(r['dx11Bits']))
    # Only the saved geometry uses Power=5. Independent geometry and holdout
    # keep other material powers, so this unit-strength product gate applies
    # solely to the saved batch, without fitting the color coefficients.
    native_products = []
    unit_strength = {int(r['vertex']): float(r['nativeFlat'])
                     for r in tables['power_controls.csv'] if r['geometry'] == 'saved'
                     and r['repeat'] == '0' and r['control'] == '3' and r['channel'] == '0'}
    for (g, v, c), flat in flat_lookup.items():
        if g == 'saved':
            native_products.append(bit(unit_strength[v] * stage_lookup[(g, 7, v, c)]) == int(flat['bits']))
    result = dict(
        evidenceComplete=True, imageAcceptance=False, productionActivation=False,
        repeats=3, geometries=sorted(originals), observations=len(controls),
        crossArchitectureExact=cross_architecture, comparedArtifacts=len(files),
        repeatedFloatImagesExact=True, sharedColorAndMeshInterpolationExact=shared_exact,
        dx11OriginalReproduced=eleven_reproduced, nativePointReproducesOriginal=point_reproduced,
        nativeFlatAvailable=flat_available, nativeFlatReproducesOriginal=flat_reproduced if flat_available else None,
        pointProjectionControlExact=all(r['nativeBits'] == r['centeredBits'] for r in tables['vertices.csv']),
        dx11StrengthTimesCoefficientExact=all(products), vertexDifferences=vertex_differences,
        savedNativeStrengthTimesCoefficientExact=len(native_products) == 9 and all(native_products),
        validatedNativeFlatVertexDifferences=flat_differences,
        controls=dict(modes), focus=pixels, powerControls=strength,
        limitations=['DX9 point/flat observations are not native pre-raster register captures.',
                     'Native point/flat values require a triangle reproduction gate before they can be used as replacement vertex inputs.',
                     'Unit-color exponent controls are observable outputs, not captures of the hidden native dot/pow intermediates.'])
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k not in ('focus', 'controls', 'vertexDifferences', 'validatedNativeFlatVertexDifferences', 'powerControls')}, indent=2))
    if (not cross_architecture or not shared_exact or not eleven_reproduced or not flat_available
            or not flat_reproduced or not all(products) or len(native_products) != 9 or not all(native_products)):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
