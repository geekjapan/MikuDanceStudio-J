"""CPU-only native input and header ABI check; never translated acceptance."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess

from shader_matrix import CASES, shader_source

FIELDS = ('type', 'next', 'entry_point', 'environment', 'extensions', 'extension_count',
          'parameters', 'parameter_count', 'dual_source_blending', 'output_swizzles', 'output_swizzle_count')


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def spirv_layout(data):
    require(len(data) >= 20 and len(data) % 4 == 0, 'invalid SPIR-V size')
    words = struct.unpack('<' + 'I' * (len(data) // 4), data)
    require(words[0] == 0x07230203, 'invalid SPIR-V magic')
    instructions = []
    offset = 5
    while offset < len(words):
        count, opcode = words[offset] >> 16, words[offset] & 0xffff
        require(count > 0 and offset + count <= len(words), 'invalid SPIR-V instruction')
        instructions.append((opcode, words[offset + 1:offset + count]))
        offset += count
    extensions = [struct.pack('<' + 'I' * len(args), *args).split(b'\0', 1)[0].decode()
                  for opcode, args in instructions if opcode == 10]  # OpExtension.
    modes = [list(args[1:]) for opcode, args in instructions if opcode == 16]
    locations = {args[0]: args[2] for opcode, args in instructions
                 if opcode == 71 and args[1] == 30}  # OpDecorate Location.
    interfaces = {kind: sorted(locations[args[1]] for opcode, args in instructions
                              if opcode == 59 and args[2] == storage and args[1] in locations)
                  for kind, storage in [('input_locations', 1), ('output_locations', 3)]}
    return {'extensions': extensions, 'execution_modes': modes, **interfaces}


def check(args):
    root = args.artifacts
    root.mkdir(parents=True, exist_ok=False)
    commands = []

    def run(command, name):
        completed = subprocess.run([str(x) for x in command], capture_output=True, timeout=60)
        (root / (name + '.log')).write_bytes(completed.stdout + completed.stderr)
        commands.append({'command': [str(x) for x in command], 'exit_code': completed.returncode})
        (root / 'commands.json').write_text(json.dumps(commands, indent=2) + '\n')
        require(completed.returncode == 0, f'{name} failed; see log')
        return completed.stdout

    driver = Path(__file__).with_name('shader_driver.rs').resolve()
    c = '#include <stddef.h>\n#include <stdio.h>\n#include "vkd3d_shader.h"\nint main(void) {\n'
    expressions = ['sizeof(struct vkd3d_shader_spirv_target_info)', '_Alignof(struct vkd3d_shader_spirv_target_info)']
    expressions += [f'offsetof(struct vkd3d_shader_spirv_target_info, {field})' for field in FIELDS]
    expressions += ['VKD3D_SHADER_STRUCTURE_TYPE_SPIRV_TARGET_INFO', 'VKD3D_SHADER_SPIRV_ENVIRONMENT_VULKAN_1_0',
                    'VKD3D_SHADER_SPIRV_EXTENSION_KHR_FLOAT_CONTROLS']
    c += ''.join(f'printf("%zu\\n", (size_t)({expression}));\n' for expression in expressions) + '}\n'
    (root / 'layout.c').write_text(c)
    run(['cc', '-std=c11', '-I', args.header.parent, root / 'layout.c', '-o', root / 'layout-c'], 'layout-c-build')
    native_metrics = [int(x) for x in run([root / 'layout-c'], 'layout-c-run').splitlines()]
    rust_expressions = ['size_of::<SpirvTargetInfo>()', 'align_of::<SpirvTargetInfo>()']
    rust_expressions += [f'offset_of!(SpirvTargetInfo, {"ty" if field == "type" else field})' for field in FIELDS]
    rust_expressions += ['4', '2', '6']
    # Append a test to the byte-identical actual driver, so private ABI fields are measured directly.
    rust = driver.read_text() + '\n#[test] fn original_header_layout() { use std::mem::{size_of, align_of, offset_of};'
    rust += f'assert_eq!([{", ".join(rust_expressions)}], {native_metrics!r});' + '}\n'
    (root / 'layout.rs').write_text(rust)
    link = ['-C', 'link-arg=' + str(args.native_library)]
    run(['rustc', '+1.95.0', '--edition', '2024', '--test', root / 'layout.rs', *link, '-o', root / 'layout-rust'], 'layout-rust-build')
    run([root / 'layout-rust'], 'layout-rust-run')
    binary = root / 'native-driver'
    run(['rustc', '+1.95.0', '--edition', '2024', driver, *link, '-o', binary], 'driver-build')
    results = []
    for name in CASES:
        for stage in ('vs', 'ps'):
            source = root / f'{name}-{stage}.hlsl'
            source.write_text(shader_source(name, stage))
            for model in ('2_0', '3_0'):
                for target in (1, 3, 4):
                    key = f'{name}-{stage}-{model}-{target}'
                    output = root / key
                    run([binary, source, f'{stage}_{model}', target, output, args.native_library], key)
                    require(Path(str(output) + '.status').read_text() == '0' and output.stat().st_size > 0,
                            f'{key}: native normal case rejected')
                    result = {'name': key, 'status': 'native_success', 'sha256': hashlib.sha256(output.read_bytes()).hexdigest()}
                    if target == 1:
                        result['spirv'] = spirv_layout(output.read_bytes())
                        # DenormFlushToZero, 32-bit floats. Keep the shader model's denormal behavior.
                        require('SPV_KHR_float_controls' in result['spirv']['extensions']
                                and [4460, 32] in result['spirv']['execution_modes'], f'{key}: missing float controls')
                        if name == 'struct_io' and stage == 'ps':
                            require(len(result['spirv']['input_locations']) == 2
                                    and result['spirv']['output_locations'] == [0], f'{key}: invalid pixel interface')
                    results.append(result)
    negative = []
    for name, source_text, profile, target, extra, diagnostic in (
        ('missing_float_controls', CASES['c4'], 'vs_2_0', 1, ['no-float-controls'], b'E2004'),
        ('invalid_pixel_semantic', CASES['struct_io'].replace('POSITION', 'COLOR'), 'ps_3_0', 4, [], b'E5013'),
    ):
        source = root / (name + '.hlsl')
        source.write_text(source_text)
        output = root / name
        run([binary, source, profile, target, output, args.native_library, *extra], name)
        require(Path(str(output) + '.status').read_text() == '-4' and not output.read_bytes()
                and diagnostic in Path(str(output) + '.diagnostics').read_bytes(), f'{name}: missing rejection')
        negative.append({'name': name, 'status': 'expected_rejection'})
    identity = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in (driver, Path(__file__).resolve(), Path(__file__).with_name('shader_matrix.py').resolve(),
                             args.header, args.native_library)}
    result = {'status': 'native_inputs_success', 'translated_comparison': 'not_run', 'identity': identity,
              'layout_metrics': native_metrics, 'cases': results, 'negative_controls': negative}
    (root / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--header', type=Path, required=True)
    parser.add_argument('--native-library', type=Path, required=True)
    parser.add_argument('--artifacts', type=Path, required=True)
    args = parser.parse_args()
    check(args)


if __name__ == '__main__':
    main()
