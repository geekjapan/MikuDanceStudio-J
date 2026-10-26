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
