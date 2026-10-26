"""Small deterministic HLSL matrix against the pinned native build."""
import hashlib
import json

CASES = {
    'c4': 'uniform float4 tint : register(c4); float4 main(float4 p : POSITION) : POSITION { return p + tint; }',
    'helper': 'float4 helper(float4 p) { return p * 2.0; } float4 main(float4 p : POSITION) : POSITION { return helper(p); }',
    'branch': 'float4 main(float4 p : POSITION) : POSITION { if (p.x > 0) return p; return -p; }',
    'struct_io': 'struct IO { float4 p : POSITION; float2 uv : TEXCOORD0; }; IO main(IO v) { v.p.xy += v.uv; return v; }',
}


def compare(binary, native_library, artifacts, run):
    result = {'status': 'not_run', 'cases': [], 'scan_reflection': 'not_run'}
    if native_library is None or not native_library.is_file():
        result['reason'] = 'native baseline library unavailable'
        return result
    directory = artifacts / 'matrix'
    directory.mkdir()
    for name, source in CASES.items():
        for stage in ('vs', 'ps'):
            shader = directory / f'{name}-{stage}.hlsl'
            shader.write_text(source if stage == 'vs' else source.replace('POSITION', 'COLOR'))
            for model in ('2_0', '3_0'):
                for target in (1, 3, 4):  # SPIR-V binary, D3D assembly, legacy bytecode.
                    key = f'{name}-{stage}-{model}-{target}'
                    case = {'name': key, 'profile': stage + '_' + model, 'target': target}
                    outputs = []
                    for mode, library in [('native', str(native_library)), ('rust', '-')]:
                        output = directory / (key + '.' + mode)
                        step = run([str(binary), str(shader), case['profile'], str(target), str(output), library],
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
                    result['cases'].append(case)
                    (directory / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    result['status'] = 'success' if all(c['status'] == 'success' for c in result['cases']) else 'comparison_failure'
    (directory / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    return result
