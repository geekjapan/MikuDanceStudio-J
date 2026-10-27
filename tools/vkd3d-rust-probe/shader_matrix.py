"""Small deterministic HLSL matrix against the pinned native build."""
import hashlib
import json

CASES = {
    'c4': 'uniform float4 tint : register(c4); float4 main(float4 p : POSITION) : POSITION { return p + tint; }',
    'helper': 'float4 helper(float4 p) { return p * 2.0; } float4 main(float4 p : POSITION) : POSITION { return helper(p); }',
    'branch': 'float4 main(float4 p : POSITION) : POSITION { if (p.x > 0) return p; return -p; }',
    'struct_io': 'struct IO { float4 p : POSITION; float2 uv : TEXCOORD0; }; IO main(IO v) { v.p.xy += v.uv; return v; }',
}


PIXEL_STRUCT_IO = ('struct Input { float4 p : COLOR; float2 uv : TEXCOORD0; }; '
                   'struct Output { float4 p : COLOR; }; '
                   'Output main(Input v) { Output o; o.p = v.p; o.p.xy += v.uv; return o; }')


def shader_source(name, stage):
    if name == 'struct_io' and stage == 'ps':
        return PIXEL_STRUCT_IO
    return CASES[name] if stage == 'vs' else CASES[name].replace('POSITION', 'COLOR')


def run_case(binary, native_library, directory, shader, case, run, extra_args=()):
    key = case['name']
    outputs = []
    for mode, library in [('native', str(native_library)), ('rust', '-')]:
        output = directory / (key + '.' + mode)
        step = run([str(binary), str(shader), case['profile'], str(case['target']), str(output), library] + list(extra_args),
                   directory / (key + '.' + mode + '.log'), timeout=30)
        case[mode] = step
        outputs.append(output)
    if any(case[mode]['exit_code'] for mode in ('native', 'rust')):
        case['status'] = 'process_failure'
    else:
        native, rust = outputs
        statuses = [p.with_suffix(p.suffix + '.status').read_text() for p in outputs]
        case['return_codes'] = statuses
        case['output_sha256'] = [hashlib.sha256(p.read_bytes()).hexdigest() for p in outputs]
        case['diagnostics_equal'] = (native.with_suffix(native.suffix + '.diagnostics').read_bytes()
                                     == rust.with_suffix(rust.suffix + '.diagnostics').read_bytes())
        if statuses != ['0', '0']:
            case['status'] = 'compile_failure'  # Matching rejection is not a behavioral pass.
        elif native.read_bytes() == rust.read_bytes() and native.stat().st_size and case['diagnostics_equal']:
            case['status'] = 'success'
        else:
            case['status'] = 'mismatch'
    return case


def compare(binary, native_library, artifacts, run):
    result = {'status': 'not_run', 'cases': [], 'negative_controls': [], 'scan_reflection': 'not_run'}
    if native_library is None or not native_library.is_file():
        result['reason'] = 'native baseline library unavailable'
        return result
    directory = artifacts / 'matrix'
    directory.mkdir()
    for name in CASES:
        for stage in ('vs', 'ps'):
            shader = directory / f'{name}-{stage}.hlsl'
            shader.write_text(shader_source(name, stage))
            for model in ('2_0', '3_0'):
                for target in (1, 3, 4):  # SPIR-V binary, D3D assembly, legacy bytecode.
                    key = f'{name}-{stage}-{model}-{target}'
                    case = {'name': key, 'profile': stage + '_' + model, 'target': target}
                    run_case(binary, native_library, directory, shader, case, run)
                    result['cases'].append(case)
                    (directory / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    for name, source, target, extra_args, diagnostic in (
        ('missing_float_controls', CASES['c4'], 1, ['no-float-controls'], b'E2004'),
        ('invalid_pixel_semantic', CASES['struct_io'].replace('POSITION', 'COLOR'), 4, [], b'E5013'),
    ):
        shader = directory / (name + '.hlsl')
        shader.write_text(source)
        case = {'name': name, 'profile': 'ps_3_0' if target == 4 else 'vs_2_0', 'target': target}
        run_case(binary, native_library, directory, shader, case, run, extra_args)
        if (case['status'] == 'compile_failure' and case['return_codes'] == ['-4', '-4']
                and case['diagnostics_equal']
                and all(not (directory / (name + '.' + mode)).read_bytes() for mode in ('native', 'rust'))
                and diagnostic in (directory / (name + '.native.diagnostics')).read_bytes()):
            case['status'] = 'expected_rejection'
        result['negative_controls'].append(case)
    result['status'] = ('success' if all(c['status'] == 'success' for c in result['cases'])
                        and all(c['status'] == 'expected_rejection' for c in result['negative_controls'])
                        else 'comparison_failure')
    (directory / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    return result
