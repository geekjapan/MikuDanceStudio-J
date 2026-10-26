"""Compare actual translated variable offsetof expressions against Clang 18."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

from full_compiler import stable_env
from probe import run


# Ordered exact-source closure: no declaration body is rewritten.
SHADER = 'libs/vkd3d-shader/'
DECLARATIONS = [
    ('include/private/list.h', 'struct list'),
    ('include/private/rbtree.h', 'struct rb_entry'),
    (SHADER + 'vkd3d_shader_private.h', 'enum vsir_data_type'),
    (SHADER + 'vkd3d_shader_private.h', 'struct vkd3d_shader_location'),
    (SHADER + 'hlsl.h', 'struct hlsl_block'),
    (SHADER + 'hlsl.h', 'struct hlsl_src'),
    (SHADER + 'hlsl.h', 'struct hlsl_attribute'),
    (SHADER + 'vkd3d_shader_private.h', 'struct vkd3d_shader_immediate_constant_buffer'),
    (SHADER + 'vkd3d_shader_private.h', 'struct vkd3d_shader_param_node'),
    (SHADER + 'vkd3d_shader_private.h', 'struct vkd3d_shader_param_allocator'),
    (SHADER + 'dxil.c', 'enum dxil_well_known_structs'),
    (SHADER + 'dxil.c', 'struct sm6_struct_info'),
    (SHADER + 'dxil.c', 'struct sm6_function_info'),
    (SHADER + 'dxil.c', 'struct sm6_metadata_node'),
    (SHADER + 'hlsl_codegen.c', 'struct dse_stores_array'),
    (SHADER + 'hlsl_codegen.c', 'struct dse_var_def'),
    (SHADER + 'hlsl_codegen.c', 'struct copy_propagation_component_trace'),
    (SHADER + 'hlsl_codegen.c', 'struct copy_propagation_var_def'),
    (SHADER + 'spirv.c', 'struct vkd3d_spirv_chunk'),
]
POINTER_LEAVES = ('sm6_type', 'sm6_metadata_value', 'copy_propagation_value',
                  'hlsl_ir_node', 'hlsl_ir_store', 'hlsl_ir_var')

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


def extract_declarations(source):
    declarations, provenance, metrics = [], [], []
    for filename, name in DECLARATIONS:
        path = source / filename
        text = path.read_bytes().decode()
        matches = list(re.finditer(r'^' + re.escape(name) + r'\s*\{.*?^\};', text, re.M | re.S))
        if len(matches) != 1:
            raise ValueError('expected exactly one actual declaration ' + name)
        match = matches[0]
        body = match.group()
        declarations.append(body)
        provenance.append({'kind': 'exact-source', 'path': filename, 'name': name,
                           'line': text.count('\n', 0, match.start()) + 1,
                           'end_line': text.count('\n', 0, match.end()) + 1,
                           'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                           'declaration_sha256': hashlib.sha256(body.encode()).hexdigest()})
        metrics += ['sizeof(' + name + ')', '__alignof__(' + name + ')']
        if name.startswith('struct '):
            clean = re.sub(r'/\*.*?\*/', '', body, flags=re.S)
            for field in clean[clean.index('{') + 1:clean.rindex('}')].split(';'):
                if not field.strip():
                    continue
                for member in field.split(','):
                    found = re.search(r'(\w+)\s*(?:\[[^]]*\])?\s*$', member)
                    if not found:
                        raise ValueError('unrecognized exact-source field in ' + name)
                    metrics.append('offsetof(' + name + ', ' + found[1] + ')')
    return declarations, provenance, metrics


def fixture_bundle(source):
    shader = source / SHADER
    declarations, provenance, metrics = extract_declarations(source)
    leaves = ['struct ' + name + ' { unsigned char fixture_unused; };' for name in POINTER_LEAVES]
    definitions = ['#include <stddef.h>', '#include <stdint.h>', '#include <stdbool.h>',
                   '/* Inert pointer-only substitutes; never instantiated, dereferenced or measured. */',
                   *leaves, *declarations]
    cases, expression_provenance = [], []
    for number, (filename, expression) in enumerate(EXPRESSIONS):
        path = shader / filename
        text = path.read_bytes().decode()
        exact = 'offsetof(' + expression + ')'
        if exact not in text:
            raise ValueError('missing actual shader expression ' + expression)
        cases.append(f'case {number}: return offsetof({expression});')
        expression_provenance.append({'path': SHADER + filename, 'expression': exact,
                                      'line': text.count('\n', 0, text.index(exact)) + 1,
                                      'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    operand_declarations = '''
    unsigned int count = (unsigned int)index;
    unsigned int word_count = (unsigned int)index;
    unsigned int component_count = (unsigned int)index, icb_size = (unsigned int)index;
    /* Synthetic operand holders preserve the source scalar types. */
    struct { unsigned int operand_count; } record_value = {(unsigned int)index}, *record = &record_value;
    struct vkd3d_shader_param_allocator allocator_value = {0}, *allocator = &allocator_value;
    allocator->count = (size_t)index; allocator->stride = 8;
    struct { struct { unsigned int args_count; } initializer; } values[3], *yyvsp = &values[2];
    values[0].initializer.args_count = (unsigned int)index;
'''
    template = (Path(__file__).parent / 'offset-fixtures/translated.c').read_text()
    template = template.replace('    counter = 3;', operand_declarations + '    counter = 3;')
    body = template.replace('ACTUAL_CASES', '\n        '.join(cases))
    metric_body = '\nsize_t layout_probe(unsigned int which) { switch (which) {\n'
    metric_body += '\n'.join(f'case {i}: return {metric};' for i, metric in enumerate(metrics))
    metric_body += '\n} return (size_t)-1; }\n'
    # The independent native oracle uses original headers, not extracted header declarations.
    original = ['#include "hlsl.h"', '#include "vkd3d_shader_private.h"']
    original += [body for (filename, _), body in zip(DECLARATIONS, declarations) if filename.endswith('.c')]
    return {'translated': '\n'.join(definitions) + '\n' + body + metric_body,
            'original': '\n'.join(original) + '\n' + body + metric_body,
            'provenance': provenance, 'expression_provenance': expression_provenance,
            'pointer_substitutes': [{'kind': 'inert-pointer-only-substitute', 'name': name,
                                     'body': leaf} for name, leaf in zip(POINTER_LEAVES, leaves)],
            'synthetic_holders': ['record_value', 'values (yyvsp)'], 'metrics': metrics}


def fixture(source):
    return fixture_bundle(source)['translated']


def check(source, c2rust, artifacts, clang='/usr/bin/clang-18'):
    artifacts.mkdir(parents=True, exist_ok=False)
    translated = artifacts / 'translated.c'
    bundle = fixture_bundle(source)
    translated.write_text(bundle['translated'])
    original = artifacts / 'original.c'
    original.write_text(bundle['original'])
    (artifacts / 'provenance.json').write_text(json.dumps(
        {key: value for key, value in bundle.items() if key not in ('translated', 'original')}, indent=2) + '\n')
    flags = ['-DHAVE_CONFIG_H', '-std=c99']
    flags += ['-I' + str(source / p) for p in ('.', 'include', 'include/private', 'libs/vkd3d-shader')]
    flags += ['-I' + str(source.parent / p / 'include') for p in ('hdr', 'spv')]
    database = artifacts / 'compile_commands.json'
    database.write_text(json.dumps([{'directory': str(artifacts), 'file': str(translated),
                                    'arguments': [clang, '-std=c99', '-c', str(translated)]}], indent=2))
    result = {'status': 'incomplete', 'stages': {}, 'actual_expression_count': len(EXPRESSIONS),
              'source_sha256': hashlib.sha256(translated.read_bytes()).hexdigest(),
              'original_sha256': hashlib.sha256(original.read_bytes()).hexdigest(),
              'layout_metric_count': len(bundle['metrics'])}
    env = stable_env(artifacts / 'target')

    def stage(name, command):
        record = run(command, artifacts / (name + '.log'), cwd=artifacts, env=env, timeout=120)
        result['stages'][name] = record
        (artifacts / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        if record['exit_code'] != 0:
            raise RuntimeError(name + ' failed')

    try:
        stage('original-c-build', [clang, *flags, '-Doffset_probe=native_offset_probe',
                                   '-Dlayout_probe=native_layout_probe', '-c', str(original),
                                   '-o', str(artifacts / 'native.o')])
        stage('extracted-c-build', [clang, '-std=c99', '-Doffset_probe=extracted_offset_probe',
                                    '-Dlayout_probe=extracted_layout_probe', '-c', str(translated),
                                    '-o', str(artifacts / 'extracted.o')])
        stage('transpile', [str(c2rust.with_name('c2rust-transpile')), '--fail-on-error', '--disable-rustfmt',
                            '--edition', '2024', '--output-dir', str(artifacts / 'rust'), str(database)])
        matches = list((artifacts / 'rust').rglob('translated.rs'))
        if len(matches) != 1:
            raise RuntimeError('expected one generated translated.rs')
        generated = matches[0]
        result['generated_sha256'] = hashlib.sha256(generated.read_bytes()).hexdigest()
        stage('rust-build', ['rustc', '+1.95.0', '--edition', '2024', '--crate-type', 'staticlib',
                             str(generated), '-o', str(artifacts / 'libtranslated.a')])
        caller = Path(__file__).resolve().parent / 'offset-fixtures/caller.c'
        stage('link', [clang, '-std=c99', '-DLAYOUT_METRIC_COUNT=' + str(len(bundle['metrics'])),
                       str(caller), str(artifacts / 'native.o'), str(artifacts / 'extracted.o'),
                       str(artifacts / 'libtranslated.a'), '-ldl', '-lpthread', '-lm',
                       '-o', str(artifacts / 'offset-check')])
        stage('numeric', [str(artifacts / 'offset-check')])
        expected = f"Original/extracted/generated layout metrics {len(bundle['metrics'])}\n"
        expected += 'Variable offsetof C/Rust numeric comparisons 200; actual shader expressions 10\n'
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
