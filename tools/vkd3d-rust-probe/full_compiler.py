"""Bounded all-unit experiment; generated compiler sources stay outside Git."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil

UNITS = tuple(sorted(
    ['libs/vkd3d-shader/' + name + '.c' for name in (
        'checksum', 'd3d_asm', 'd3dbc', 'dxbc', 'dxil', 'fx', 'glsl', 'hlsl',
        'hlsl.tab', 'hlsl.yy', 'hlsl_codegen', 'hlsl_constant_ops', 'ir', 'msl',
        'preproc.tab', 'preproc.yy', 'spirv', 'tpf', 'vkd3d_shader_main')]
    + ['libs/vkd3d-common/' + name + '.c' for name in ('blob', 'debug', 'error', 'memory', 'utf8')]))

# This exact token sequence is the pinned C2Rust parser output, not a general rewriter.
BAD_OFFSET = 'offset_of!(hlsl_attribute,args[(*yyvsp.offset(-2isize)).initializer.args_countasusize])assize_t'
GOOD_OFFSET = ('(offset_of!(hlsl_attribute, args) as size_t).wrapping_add('
               '(::core::mem::size_of::<hlsl_src>() as size_t).wrapping_mul('
               '(*yyvsp.offset(-2isize)).initializer.args_count as size_t))')
COUNTS = (0, 1, 31, 65535, 4294967295)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def generated_parser(working):
    matches = list((working / 'src').rglob('hlsl_tab.rs'))
    if (len(matches) != 1 or not matches[0].is_file()
            or not matches[0].resolve().is_relative_to(working.resolve())):
        raise ValueError('missing, ambiguous, or outside-owned generated parser: hlsl_tab.rs')
    return matches[0]


def patch_parser(path):
    text = path.read_text()
    # Whitespace normalization is only used for exact matching; all other bytes survive.
    compact = ''.join(text.split())
    if compact.count(BAD_OFFSET) != 1:
        raise ValueError('expected exactly one known parser array offsetof')
    attribute = re.search(r'pub struct hlsl_attribute \{.*?\n\}', text, re.S)
    initializer = re.search(r'pub struct parse_initializer \{.*?\n\}', text, re.S)
    if not attribute or not re.search(r'pub args:\s*\[hlsl_src;\s*0\]', attribute[0]):
        raise ValueError('unexpected hlsl_attribute flexible-array element type')
    if not re.search(r'pub type size_t\s*=\s*usize;', text):
        raise ValueError('unexpected native size_t representation')
    if not initializer or not re.search(r'pub args_count:\s*::core::ffi::c_uint,', initializer[0]):
        raise ValueError('unexpected initializer count representation')
    pattern = r'\s*'.join(re.escape(char) for char in BAD_OFFSET)
    patched, count = re.subn(pattern, lambda match: GOOD_OFFSET, text)
    if count != 1:
        raise ValueError('parser offset replacement count changed')
    before = digest(path)
    path.write_text(patched)
    return {'path': str(path), 'original_sha256': before, 'patched_sha256': digest(path),
            'original_occurrences': 1, 'patched_occurrences': count,
            'element_type': 'hlsl_src', 'size_t': 'usize', 'count_type': 'c_uint',
            'replacement': GOOD_OFFSET}


def stable_env(target):
    env = dict(os.environ, CARGO_TARGET_DIR=str(target))
    for key in ('RUSTC_BOOTSTRAP', 'RUSTFLAGS', 'CARGO_ENCODED_RUSTFLAGS',
                'RUSTC_WRAPPER', 'RUSTC_WORKSPACE_WRAPPER', 'RUSTDOCFLAGS', 'CARGO_BUILD_RUSTFLAGS'):
        env.pop(key, None)
    for key in list(env):
        if key.startswith("CARGO_TARGET_") and key.endswith("_RUSTFLAGS"):
            env.pop(key)
    return env


def offset_check(source, working, entry, artifacts, toolchain, run):
    c = artifacts / 'offset_check.c'
    c.write_text('''#include "hlsl.h"
#include <stddef.h>
#include <stdio.h>
int main(void) {
    unsigned int counts[] = {0, 1, 31, 65535, 4294967295U};
    printf("%zu %zu %zu\\n", offsetof(struct hlsl_attribute, args), sizeof(struct hlsl_src), sizeof(size_t));
    for (unsigned int i = 0; i < sizeof(counts)/sizeof(counts[0]); ++i)
        printf("%u %zu\\n", counts[i], offsetof(struct hlsl_attribute, args[counts[i]]));
    return 0;
}
''')
    binary = artifacts / 'offset_check_c'
    records = {'c_build': run(entry['arguments'][:-2] + [str(c), '-o', str(binary)],
                              artifacts / 'offset-c-build.log', cwd=source, timeout=60)}
    if records['c_build']['exit_code']:
        return records
    records['c_run'] = run([str(binary)], artifacts / 'offset-c-run.log', timeout=30)
    if records['c_run']['exit_code']:
        return records
    lines = (artifacts / 'offset-c-run.log').read_text().splitlines()
    base, size, width = map(int, lines[0].split())
    observed = [tuple(map(int, line.split())) for line in lines[1:]]
    expected = [(n, (base + size * n) % (1 << (8 * width))) for n in COUNTS]
    if observed != expected:
        raise ValueError('native offsetof differs from wrapping size_t arithmetic')
    # Use actual translated type definitions, not a guessed pointer substitute.
    text = generated_parser(working).read_text()
    names = ('list', 'hlsl_block', 'hlsl_src', 'hlsl_attribute', 'vkd3d_shader_location')
    definitions = []
    for name in names:
        match = re.search(r'pub struct ' + name + r' \{.*?\n\}', text, re.S)
        if not match:
            raise ValueError('missing translated layout: ' + name)
        definitions.append('#[repr(C)]\n' + match[0])
    rust = artifacts / 'offset_check.rs'
    rust.write_text('''#![allow(non_camel_case_types)]
type hlsl_ir_node = core::ffi::c_void;
''' + '\n'.join(definitions) + '\nfn main() {\n'
        + f'assert_eq!(core::mem::size_of::<usize>(), {width});\n'
        + f'assert_eq!(core::mem::offset_of!(hlsl_attribute, args), {base});\n'
        + f'assert_eq!(core::mem::size_of::<hlsl_src>(), {size});\n'
        + '\n'.join(f'assert_eq!(({base}usize).wrapping_add(core::mem::size_of::<hlsl_src>().wrapping_mul({n}usize)), {value}usize);'
                    for n, value in expected)
        + '\nprintln!("native C and translated Rust layouts: 5 offsetof vectors passed");\n}\n')
    rust_binary = artifacts / 'offset_check_rust'
    env = stable_env(artifacts / 'offset-target')
    records['rust_build'] = run(['rustc', '+' + toolchain, '--edition', '2024', str(rust), '-o', str(rust_binary)],
                                artifacts / 'offset-rust-build.log', env=env, timeout=60)
    if not records['rust_build']['exit_code']:
        records['rust_run'] = run([str(rust_binary)], artifacts / 'offset-rust-run.log', timeout=30)
    records['vectors'] = expected
    records['success'] = bool(records.get('rust_run', {}).get('exit_code') == 0)
    return records


def collect(result, args, source, output, entries, artifacts, run, checkpoint):
    result['all_unit_prototype'] = True
    result['runtime_comparison'] = {'status': 'not_run'}
    result['link'] = {'status': 'not_run', 'reason': 'no compiled all-unit static library yet'}
    env = stable_env(artifacts / 'raw-target')
    command = ['cargo', '+' + args.rust_toolchain, 'build', '--manifest-path', str(artifacts / 'rust-raw/Cargo.toml')]
    result['stable_build'] = run(command, artifacts / 'cargo-stable.log', env=env, timeout=args.build_timeout)
    checkpoint()
    working = artifacts / 'rust-working'
    shutil.copytree(output, working)
    try:
        patch_record = patch_parser(generated_parser(working))
        result['parser_patch'] = patch_record
        (artifacts / 'parser-patch.json').write_text(json.dumps(patch_record, indent=2) + '\n')
        result['offset_check'] = offset_check(source, working, entries[0], artifacts, args.rust_toolchain, run)
        if not result['offset_check'].get('success'):
            result['patch_failure'] = 'native/Rust numeric proof failed; patched compilation refused'
            return
    except (ValueError, OSError) as error:
        result['patch_failure'] = str(error)
        return
    command = ['cargo', '+' + args.rust_toolchain, 'build', '--manifest-path', str(working / 'Cargo.toml')]
    target = artifacts / 'working-target'
    env = stable_env(target)
    result['patched_stable_build'] = run(command, artifacts / 'cargo-patched-stable.log', env=env, timeout=args.build_timeout)
    checkpoint()
    for mode, flags in [('bootstrap', None), ('prototype', '-Zcrate-attr=feature(stmt_expr_attributes) -Astatic_mut_refs')]:
        if result.get('patched_stable_build', {}).get('exit_code') == 0 or result.get('bootstrap_build', {}).get('exit_code') == 0:
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
