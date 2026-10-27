"""Bounded all-unit experiment; generated compiler sources stay outside Git."""
import hashlib
import json
import os
from pathlib import Path
import shutil

UNITS = tuple(sorted(
    ['libs/vkd3d-shader/' + name + '.c' for name in (
        'checksum', 'd3d_asm', 'd3dbc', 'dxbc', 'dxil', 'fx', 'glsl', 'hlsl',
        'hlsl.tab', 'hlsl.yy', 'hlsl_codegen', 'hlsl_constant_ops', 'ir', 'msl',
        'preproc.tab', 'preproc.yy', 'spirv', 'tpf', 'vkd3d_shader_main')]
    + ['libs/vkd3d-common/' + name + '.c' for name in ('blob', 'debug', 'error', 'memory', 'utf8')]))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def generated_parser(working):
    matches = list((working / 'src').rglob('hlsl_tab.rs'))
    if (len(matches) != 1 or not matches[0].is_file()
            or not matches[0].resolve().is_relative_to(working.resolve())):
        raise ValueError('missing, ambiguous, or outside-owned generated parser: hlsl_tab.rs')
    return matches[0]


def stable_env(target):
    env = dict(os.environ, CARGO_TARGET_DIR=str(target))
    for key in ('RUSTC_BOOTSTRAP', 'RUSTFLAGS', 'CARGO_ENCODED_RUSTFLAGS',
                'RUSTC_WRAPPER', 'RUSTC_WORKSPACE_WRAPPER', 'RUSTDOCFLAGS', 'CARGO_BUILD_RUSTFLAGS'):
        env.pop(key, None)
    for key in list(env):
        if key.startswith("CARGO_TARGET_") and key.endswith("_RUSTFLAGS"):
            env.pop(key)
    return env


def source_manifest(root):
    return {str(path.relative_to(root)): digest(path)
            for path in sorted(root.rglob('*')) if path.is_file()}


def collect(result, args, source, output, entries, artifacts, run, checkpoint):
    result['all_unit_prototype'] = True
    result['runtime_comparison'] = {'status': 'not_run'}
    result['link'] = {'status': 'not_run', 'reason': 'no compiled all-unit static library yet'}
    env = stable_env(artifacts / 'raw-target')
    command = ['cargo', '+' + args.rust_toolchain, 'build', '--manifest-path', str(artifacts / 'rust-raw/Cargo.toml')]
    result['stable_build'] = run(command, artifacts / 'cargo-stable.log', env=env, timeout=args.build_timeout)
    checkpoint()
    working = artifacts / 'rust-working'
    try:
        generated_parser(output)
        original = source_manifest(output)
        shutil.copytree(output, working)
        generated_parser(working)
        copied = source_manifest(working)
        result['working_source_identity'] = {
            'original_sha256': original, 'working_sha256': copied,
            'equal': original == copied,
        }
        if original != copied:
            raise ValueError('working source manifest differs from emitted source')
    except (ValueError, OSError) as error:
        result['working_copy_failure'] = str(error)
        return
    command = ['cargo', '+' + args.rust_toolchain, 'build', '--manifest-path', str(working / 'Cargo.toml')]
    target = artifacts / 'working-target'
    env = stable_env(target)
    result['working_stable_build'] = run(command, artifacts / 'cargo-working-stable.log', env=env, timeout=args.build_timeout)
    checkpoint()
    for mode, flags in [('bootstrap', None), ('prototype', '-Zcrate-attr=feature(stmt_expr_attributes) -Astatic_mut_refs')]:
        if result.get('working_stable_build', {}).get('exit_code') == 0 or result.get('bootstrap_build', {}).get('exit_code') == 0:
            break
        env['RUSTC_BOOTSTRAP'] = '1'
        if flags:
            env['RUSTFLAGS'] = flags
            result['prototype_flags'] = flags
        result[mode + '_build'] = run(command, artifacts / ('cargo-' + mode + '.log'), env=env, timeout=args.build_timeout)
        checkpoint()
    archives = list((target / 'debug').glob('*.a'))
    if len(archives) != 1:
        result['link']['reason'] = 'all-unit static library unavailable; see compiler failures'
        return
    archive = archives[0]
    result['undefined_symbols'] = run(['nm', '-u', str(archive)], artifacts / 'undefined-symbols.log', timeout=60)
    result['defined_symbols'] = run(['nm', '--defined-only', str(archive)], artifacts / 'defined-symbols.log', timeout=60)
    binary = artifacts / 'shader-driver'
    driver = Path(__file__).with_name('shader_driver.rs')
    link_env = stable_env(artifacts / 'driver-target')
    result['link'] = run(['rustc', '+' + args.rust_toolchain, '--edition', '2024', str(driver),
                          '-o', str(binary), '-L', 'native=' + str(archive.parent),
                          '-l', 'static=' + archive.stem.removeprefix('lib'), '-l', 'm', '-l', 'pthread', '-l', 'dl'],
                         artifacts / 'link.log', env=link_env, timeout=args.build_timeout)
    result['link']['status'] = 'success' if result['link']['exit_code'] == 0 else 'link_failure'
    checkpoint()
    if result['link']['exit_code'] == 0:
        result['linked_dependencies'] = run(['ldd', str(binary)], artifacts / 'linked-dependencies.log', timeout=30)
        from shader_matrix import compare
        result['runtime_comparison'] = compare(binary, args.native_library, artifacts, run)


def cursor_witness_receipt(tool, database, output):
    """Bind paired files from one opt-in exporter run, without claiming job authenticity."""
    from apply_c2rust_patch import verify_tool
    verify_tool(tool.parent.parent)
    entries = json.loads(database.read_text())
    inventories = sorted(output.rglob('*.variadic.json'))
    units = {str(Path(e['file']).resolve()): e for e in entries}
    if len(units) != len(entries) or len(inventories) != len(entries):
        raise ValueError('cursor witness paired unit manifest differs')
    pairs = []
    for inventory in inventories:
        item = json.loads(inventory.read_text())
        unit = item['unit']
        if unit not in units:
            raise ValueError('cursor witness unit outside compile database')
        witness = inventory.with_name(inventory.name.removesuffix('.variadic.json') + '.cursor-witness.json')
        cbor = inventory.with_name(inventory.name.removesuffix('.variadic.json') + '.cursor.cbor')
        typed = inventory.with_name(inventory.name.removesuffix('.variadic.json') + '.typed-ast.txt')
        entry = units.pop(unit)
        pairs.append({'unit': unit, 'target': item['target'], 'compile_command': entry,
                      'files': {str(p.resolve()): digest(p) for p in (inventory, witness, cbor, typed, Path(unit))},
                      'inventory': str(inventory.resolve()), 'witness': str(witness.resolve()),
                      'cbor': str(cbor.resolve()), 'typed_ast': str(typed.resolve())})
    if units:
        raise ValueError('cursor witness missing compile database units')
    return {'schema': 1, 'authorization': 'witness_only', 'pairs': pairs,
            'files': {str(p.resolve()): digest(p) for p in
                      (tool, tool.parent.parent / 'source-receipt.json', database)},
            'database': str(database.resolve()), 'tool': str(tool.resolve()),
            'source_receipt': str((tool.parent.parent / 'source-receipt.json').resolve()),
            'authentic_job_proof': False}


def prove_bound_cursor_witness(receipt, symbol):
    from closed_variadic_plan import PlanError, prove_cursor_witness
    if receipt.get('schema') != 1 or receipt.get('authorization') != 'witness_only':
        raise PlanError('unsupported cursor binding receipt')
    if set(receipt['files']) != {receipt[k] for k in ('database', 'tool', 'source_receipt')}:
        raise PlanError('cursor witness incomplete tool binding')
    entries = json.loads(Path(receipt['database']).read_text())
    if sorted((p['compile_command'] for p in receipt['pairs']), key=lambda e: e['file']) != sorted(entries, key=lambda e: e['file']):
        raise PlanError('cursor witness command binding differs')
    inventories, witnesses = [], []
    for record in [receipt, *receipt['pairs']]:
        for name, expected in record['files'].items():
            if digest(Path(name)) != expected:
                raise PlanError('cursor witness binding differs: ' + name)
    for pair in receipt['pairs']:
        if set(pair['files']) != {pair[k] for k in ('inventory', 'witness', 'cbor', 'typed_ast', 'unit')}:
            raise PlanError('cursor witness incomplete AST binding')
        inventory = json.loads(Path(pair['inventory']).read_text())
        witness = json.loads(Path(pair['witness']).read_text())
        if inventory['unit'] != pair['unit'] or inventory['target'] != pair['target']:
            raise PlanError('cursor witness binding identity differs')
        inventories.append(inventory)
        witnesses.append(witness)
    return prove_cursor_witness(inventories, witnesses, symbol)


def collect_cursor_witness(tool, database, output, run, symbol):
    output.mkdir(parents=True, exist_ok=False)
    command = [str(tool), '--fail-on-error', '--disable-rustfmt', '--edition', '2024',
               '--emit-cursor-witness', '--output-dir', str(output / 'raw'), str(database)]
    exported = run(command, output / 'export.log', timeout=1800)
    if exported['exit_code']:
        raise ValueError('paired cursor witness export failed')
    receipt = cursor_witness_receipt(tool, database, output / 'raw')
    receipt['export_command'] = command
    (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    from closed_variadic_plan import PlanError
    try:
        proof = prove_bound_cursor_witness(receipt, symbol)
    except (PlanError, KeyError, TypeError, ValueError) as error:
        proof = {'schema': 1, 'authorization': 'witness_only', 'status': 'rejected', 'reason': str(error)}
    (output / 'proof.json').write_text(json.dumps(proof, indent=2) + '\n')
    return proof
