"""Compare actual translated variable offsetof expressions against Clang 18."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

from full_compiler import stable_env
from probe import run


DECLARATIONS = {
    'dxil.c': ['enum dxil_well_known_structs', 'struct sm6_struct_info',
               'struct sm6_function_info', 'struct sm6_metadata_node'],
    'hlsl_codegen.c': ['struct dse_stores_array', 'struct dse_var_def',
                       'struct copy_propagation_component_trace', 'struct copy_propagation_var_def'],
    'spirv.c': ['struct vkd3d_spirv_chunk'],
}
EXPRESSIONS = [
    ('dxil.c', 'struct sm6_function_info, param_types[count]'),
    ('dxil.c', 'struct sm6_struct_info, elem_types[count]'),
    ('dxil.c', 'struct vkd3d_shader_immediate_constant_buffer, data[count]'),
    ('dxil.c', 'struct sm6_metadata_node, operands[record->operand_count]'),
    ('hlsl_codegen.c', 'struct dse_var_def, possible_stores[component_count]'),
    ('hlsl_codegen.c', 'struct copy_propagation_var_def, traces[component_count]'),
    ('hlsl.tab.c', 'struct hlsl_attribute, args[(yyvsp[-2].initializer).args_count]'),
    ('ir.c', 'struct vkd3d_shader_param_node, param[allocator->count * allocator->stride]'),
    ('spirv.c', 'struct vkd3d_spirv_chunk, words[word_count]'),
    ('tpf.c', 'struct vkd3d_shader_immediate_constant_buffer, data[icb_size]'),
]


def fixture(source):
    shader = source / 'libs/vkd3d-shader'
    definitions = ['#include "hlsl.h"', '#include "vkd3d_shader_private.h"']
    for filename, names in DECLARATIONS.items():
        text = (shader / filename).read_text()
        for name in names:
            match = re.search(r'^' + re.escape(name) + r'\s*\{.*?^\};', text, re.M | re.S)
            if match is None:
                raise ValueError('missing actual declaration ' + name)
            definitions.append(match.group())
    cases = []
    for number, (filename, expression) in enumerate(EXPRESSIONS):
        text = (shader / filename).read_text()
        if 'offsetof(' + expression + ')' not in text:
            raise ValueError('missing actual shader expression ' + expression)
        cases.append(f'case {number}: return offsetof({expression});')
    declarations = '''
    unsigned int count = (unsigned int)index;
    size_t word_count = (size_t)index;
    unsigned int component_count = (unsigned int)index, icb_size = (unsigned int)index;
    struct { unsigned int operand_count; } record_value = {(unsigned int)index}, *record = &record_value;
    struct vkd3d_shader_param_allocator allocator_value = {0}, *allocator = &allocator_value;
    allocator->count = (size_t)index; allocator->stride = 8;
    struct { struct { unsigned int args_count; } initializer; } values[3], *yyvsp = &values[2];
    values[0].initializer.args_count = (unsigned int)index;
'''
    template = (Path(__file__).parent / 'offset-fixtures/translated.c').read_text()
    template = template.replace('    counter = 3;', declarations + '    counter = 3;')
    return '\n'.join(definitions) + '\n' + template.replace('ACTUAL_CASES', '\n        '.join(cases))


def check(source, c2rust, artifacts, clang='/usr/bin/clang-18'):
    artifacts.mkdir(parents=True, exist_ok=False)
    translated = artifacts / 'translated.c'
    translated.write_text(fixture(source))
    flags = ['-DHAVE_CONFIG_H', '-std=c99']
    flags += ['-I' + str(source / p) for p in ('.', 'include', 'include/private', 'libs/vkd3d-shader')]
    flags += ['-I' + str(source.parent / p / 'include') for p in ('hdr', 'spv')]
    database = artifacts / 'compile_commands.json'
    database.write_text(json.dumps([{'directory': str(artifacts), 'file': str(translated),
                                    'arguments': [clang, *flags, '-c', str(translated)]}], indent=2))
    result = {'status': 'incomplete', 'stages': {}, 'actual_expression_count': len(EXPRESSIONS),
              'source_sha256': hashlib.sha256(translated.read_bytes()).hexdigest()}
    env = stable_env(artifacts / 'target')

    def stage(name, command):
        record = run(command, artifacts / (name + '.log'), cwd=artifacts, env=env, timeout=120)
        result['stages'][name] = record
        (artifacts / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        if record['exit_code'] != 0:
            raise RuntimeError(name + ' failed')

    try:
        stage('c-build', [clang, *flags, '-Doffset_probe=native_offset_probe', '-c', str(translated),
                          '-o', str(artifacts / 'native.o')])
        stage('transpile', [str(c2rust.with_name('c2rust-transpile')), '--fail-on-error', '--disable-rustfmt',
                            '--edition', '2024', '--output-dir', str(artifacts / 'rust'), str(database)])
        matches = list((artifacts / 'rust').rglob('translated.rs'))
        if len(matches) != 1:
            raise RuntimeError('expected one generated translated.rs')
        generated = matches[0]
        result['generated_sha256'] = hashlib.sha256(generated.read_bytes()).hexdigest()
        if re.search(r'offset_of!\([^\n]*\[', generated.read_text()):
            raise RuntimeError('unsupported indexed offset_of macro remains')
        stage('rust-build', ['rustc', '+1.95.0', '--edition', '2024', '--crate-type', 'staticlib',
                             str(generated), '-o', str(artifacts / 'libtranslated.a')])
        caller = Path(__file__).resolve().parent / 'offset-fixtures/caller.c'
        stage('link', [clang, '-std=c99', str(caller), str(artifacts / 'native.o'),
                       str(artifacts / 'libtranslated.a'), '-ldl', '-lpthread', '-lm',
                       '-o', str(artifacts / 'offset-check')])
        stage('numeric', [str(artifacts / 'offset-check')])
        expected = 'Variable offsetof C/Rust numeric comparisons 200; actual shader expressions 10\n'
        if (artifacts / 'numeric.log').read_text() != expected:
            raise RuntimeError('missing numeric comparison receipt')
        result['status'] = 'success'
    except (RuntimeError, OSError, ValueError) as error:
        result.update(status='failure', error=str(error))
    finally:
        (artifacts / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--c2rust', type=Path, required=True)
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--clang', default='/usr/bin/clang-18')
    args = parser.parse_args()
    result = check(args.source.resolve(), args.c2rust.resolve(), args.artifacts.resolve(), args.clang)
    sys.exit(0 if result['status'] == 'success' else 1)
