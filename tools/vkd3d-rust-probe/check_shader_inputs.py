"""CPU-only native input and header ABI check; never translated acceptance."""
import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import sys
from pathlib import Path, PurePosixPath
import struct
import subprocess

from shader_matrix import CASES, shader_source

ABI = {'Code': ('vkd3d_shader_code', ('code', 'size')),
       'OptionValue': ('vkd3d_shader_compile_option', ('name', 'value')),
       'CompileInfo': ('vkd3d_shader_compile_info', ('type', 'next', 'source', 'source_type', 'target_type', 'options', 'option_count', 'log_level', 'source_name')),
       'HlslInfo': ('vkd3d_shader_hlsl_source_info', ('type', 'next', 'entry_point', 'secondary_code', 'profile'))}

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


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


EXTERNAL_INCLUDE_ROOTS = frozenset(('hdr/include', 'spv/include'))


GENERATED_FILES = frozenset([
    'include/private/spirv_grammar.h', 'include/private/vkd3d_version.h',
    *('libs/vkd3d-shader/' + name for name in
      ('hlsl.tab.c', 'hlsl.tab.h', 'hlsl.yy.c', 'preproc.tab.c', 'preproc.tab.h', 'preproc.yy.c')),
])


# Search order follows the authenticated in-tree Automake recipe; quoted includes
# first search the including file's directory.
LOCAL_INCLUDE_ROOTS = ('.', 'include', 'include/private', 'libs/vkd3d-shader')
LOCAL_INPUT_SUFFIXES = ('.h', '.l', '.y')


def input_inventory(root):
    files, links = set(), []
    if root.is_symlink():
        return files, ['.']
    if not root.exists():
        return files, links

    def failed_walk(error):
        raise error

    for directory, directories, filenames in os.walk(root, followlinks=False, onerror=failed_walk):
        for name in directories + filenames:
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                links.append(relative)
            elif name in filenames:
                files.add(relative)
    return files, sorted(links)


def include_recipe(makefile):
    logical = makefile.replace('\\\n', ' ')
    variables = dict(re.findall(r'^([A-Za-z_][A-Za-z_0-9]*) = (.*)$', logical, re.M))
    names = ('DEFAULT_INCLUDES', 'AM_CPPFLAGS', 'COMPILE', 'LTCOMPILE',
             'srcdir', 'builddir', 'top_srcdir', 'top_builddir', 'libvkd3d_shader_la_CFLAGS')
    guarded = set(names) | {'CPPFLAGS', 'INCLUDES', 'CFLAGS', 'AM_CFLAGS', 'DEFS', 'CC',
                            'AM_LIBTOOLFLAGS', 'LIBTOOLFLAGS'}
    for name in guarded:
        assignments = re.findall(r'^((?!\t)[^#=\n]*\b' + re.escape(name) + r'\s*[:+?!]?=.*)$', logical, re.M)
        require(len(assignments) <= 1 and all(line.startswith(name + ' = ') for line in assignments),
                'unsupported include recipe assignment: ' + name)
    projection = {name: ' '.join(variables.get(name, '').split()) for name in names}
    # Configured absolute vendor roots move with the retained source bundle.
    flags = variables.get('CPPFLAGS', '').split()
    require(len(flags) == 2 and all(flag.startswith('-I') and flag.endswith('/' + root)
            for flag, root in zip(flags, ('hdr/include', 'spv/include'))),
            'unsupported compiler vendor include paths')
    require(flags[0][2:-len('/hdr/include')] == flags[1][2:-len('/spv/include')]
            and flags[0].startswith('-I/'), 'vendor include roots are not siblings')
    projection['CPPFLAGS'] = ['-I../hdr/include', '-I../spv/include']
    projection['INCLUDES'] = variables.get('INCLUDES', '')
    for name in ('CFLAGS', 'AM_CFLAGS', 'DEFS', 'CC', 'AM_LIBTOOLFLAGS', 'LIBTOOLFLAGS'):
        require(not re.search(r'-(?:I|iquote|isystem|idirafter|include|imacros|iprefix|iwithprefix)|@|\$[({]',
                              variables.get(name, '')), 'unsupported include-affecting compiler flags: ' + name)
    recipes = [line.strip() for line in logical.splitlines()
               if line.startswith('\t') and re.search(r'\$\((?:CC|COMPILE|LTCOMPILE)\)', line)]
    projection['compile_recipes_sha256'] = hashlib.sha256('\n'.join(recipes).encode()).hexdigest()
    return projection


def literal_include_graph(source, production_units):
    roots = [source / root for root in LOCAL_INCLUDE_ROOTS[:-1]]
    roots += [source.parent / root for root in ('hdr/include', 'spv/include')]
    # The shader-specific -I follows CPPFLAGS, and applies only to shader units.
    visited, edges, unresolved = set(), set(), set()
    for unit in production_units:
        todo = [source / unit]
        search = roots + ([source / LOCAL_INCLUDE_ROOTS[-1]] if unit.startswith('libs/vkd3d-shader/') else [])
        local = set()
        while todo:
            path = todo.pop()
            if path in local:
                continue
            local.add(path)
            name = path.relative_to(source.parent).as_posix()
            visited.add(name)
            text = path.read_text(errors='replace').replace('\\\n', '')
            text = re.sub(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"',
                          lambda match: match[0] if match[0].startswith('"') else ' ', text, flags=re.S)
            for kind, operand in re.findall(r'^\s*#\s*(include_next|include|import)\b([^\n]*)', text, re.M):
                literal = re.fullmatch(r'\s*(?:"([^"\n]+)"|<([^>\n]+)>)\s*', operand)
                require(kind == 'include' and literal is not None, 'unsupported include directive in ' + name)
                child = literal[1] or literal[2]
                require(Path(child).suffix == '.h' and not Path(child).is_absolute()
                        and '..' not in Path(child).parts, 'unsupported include filename: ' + child)
                candidates = ([path.parent] if literal[1] else []) + search
                target = next((root / child for root in candidates if (root / child).is_file()), None)
                if target is None:
                    unresolved.add((name, child))
                else:
                    target = Path(os.path.normpath(target))
                    edges.add((name, child, target.relative_to(source.parent).as_posix()))
                    todo.append(target)
    return {'visited': sorted(visited), 'edges': sorted(map(list, edges)),
            'unresolved_system_sdk_or_disabled': sorted(map(list, unresolved))}


def source_identity(source, reference, receipt=None):
    require(set(reference['generated_files']) == GENERATED_FILES,
            'unknown or missing generated source classification')
    require(GENERATED_FILES <= reference['source_files'].keys(), 'missing generated reference input')
    identity = receipt if receipt is not None else {}
    identity.update({'files': {}, 'external_headers': {}, 'target_configuration': {},
                     'generated_source_differences': [], 'target_configuration_differences': [],
                     'identical_source_profile': False, 'identity_scope': 'reference_catalog_only', 'identical_producer_profile': False})
    local_files, local_links = input_inventory(source)
    actual_headers = {name for name in local_files if name.endswith(LOCAL_INPUT_SUFFIXES)}
    expected_headers = {name for name in reference['source_files'] if name.endswith(LOCAL_INPUT_SUFFIXES)}
    expected_headers |= {name for name in reference['target_configuration'] if name.endswith(LOCAL_INPUT_SUFFIXES)}
    actual_external, links = set(), ['vkd3d-2.1/' + name for name in local_links]
    for directory in sorted(EXTERNAL_INCLUDE_ROOTS):
        files, symlinks = input_inventory(source.parent / directory)
        actual_external.update(directory + '/' + name for name in files)
        links.extend(directory + '/' + name for name in symlinks)
    links.extend(name for name in ('hdr', 'spv') if (source.parent / name).is_symlink())
    identity['symlink_inputs'] = sorted(links)
    identity['external_include_roots'] = sorted(EXTERNAL_INCLUDE_ROOTS)
    identity['unclassified_inputs'] = sorted((actual_headers - expected_headers)
                                             | (actual_external - reference['external_headers'].keys()))
    require(not links, f'symlink producer inputs: {links}')
    missing = []
    for key, base in [('source_files', source), ('external_headers', source.parent),
                      ('target_configuration', source)]:
        output = identity['files' if key == 'source_files' else key]
        for name in reference[key]:
            path = base / name
            if path.is_file():
                output[name] = sha(path)
            else:
                missing.append(name)
    identity['missing_inputs'] = missing
    differences = [name for name, digest in identity['files'].items()
                   if digest != reference['source_files'][name]]
    identity['generated_source_differences'] = [name for name in differences if name in GENERATED_FILES]
    identity['handwritten_source_differences'] = [name for name in differences if name not in GENERATED_FILES]
    identity['external_header_differences'] = [name for name, digest in identity['external_headers'].items()
                                              if digest != reference['external_headers'][name]]
    identity['target_configuration_differences'] = [name for name, digest in identity['target_configuration'].items()
                                                   if digest != reference['target_configuration'][name]]
    require(set(reference['external_include_roots']) == EXTERNAL_INCLUDE_ROOTS,
            'unknown or missing external include root classification')
    require(all(any(name.startswith(root + '/') for name in reference['external_headers'])
                for root in EXTERNAL_INCLUDE_ROOTS)
            and all(any(name.startswith(root + '/') for root in EXTERNAL_INCLUDE_ROOTS)
                    for name in reference['external_headers']), 'unclassified external reference input')
    require(not missing, f'missing required producer inputs: {missing}')
    require(not identity['unclassified_inputs'], f'unclassified producer inputs: {identity["unclassified_inputs"]}')
    require(not identity['handwritten_source_differences'],
            f'non-generated reference source differs: {identity["handwritten_source_differences"]}')
    require(not identity['external_header_differences'],
            f'external producer headers differ: {identity["external_header_differences"]}')
    require(tuple(reference['local_include_roots']) == LOCAL_INCLUDE_ROOTS,
            'unknown or missing local include root classification')
    identity['include_recipe'] = include_recipe((source / 'Makefile').read_text())
    require(identity['include_recipe'] == reference['include_recipe'], 'producer include recipe differs')
    identity['literal_include_graph'] = literal_include_graph(source, reference['production_units'])
    require(identity['literal_include_graph'] == reference['literal_include_graph'], 'producer literal include graph differs')
    identity['identical_source_profile'] = not differences and not identity['target_configuration_differences']
    return identity



def producer_identity(record, reference, source, receipt):
    """Validate transported evidence from the reviewed fresh producer before native work."""
    path = record / 'producer-receipt.json'
    require(path.is_file(), 'missing fresh producer receipt')
    producer = json.loads(path.read_text())
    receipt['producer'] = producer
    contract = reference['producer_contract']
    require(producer.get('schema') == contract['schema'], 'untrusted producer schema')
    require(producer.get('recipe_sha256') == contract['recipe_sha256']
            and sha(record / 'build.sh') == contract['recipe_sha256'], 'untrusted producer recipe')
    require(producer.get('archives') == contract['archives'], 'untrusted producer archives')
    require(producer.get('patches') == contract['patches'], 'untrusted producer patches')
    require(producer.get('status') == 'success' and producer.get('exit_code') == 0,
            'producer did not finish successfully')
    stages = producer.get('stages', [])
    require([item.get('stage') for item in stages] ==
            ['prepared', 'configured', 'frozen', 'compiled', 'installed'], 'incomplete producer stages')
    original = PurePosixPath(producer.get('original_work_root', ''))
    require(original.is_absolute() and str(original) == producer['original_work_root']
            and '..' not in original.parts and str(original) != '/', 'invalid original producer root')
    require(producer.get('retained_work_root') == 'work', 'invalid retained producer root')
    roots = ('vkd3d-2.1', 'vkd3d-2.1/include', 'vkd3d-2.1/include/private',
             'hdr/include', 'spv/include', 'vkd3d-2.1/libs/vkd3d-shader')
    require(producer.get('include_roots') ==
            [{'original': str(original / name), 'retained': 'work/' + name} for name in roots],
            'producer include root mapping differs')
    require(source.resolve() == (record / 'work/vkd3d-2.1').resolve(),
            'source is outside retained producer mapping')
    files, links = input_inventory(record / 'work')
    require(not links and not record.is_symlink(), 'symlink producer receipt inputs')
    maps = []
    for stage in stages:
        entries = stage['files']
        mapping = {}
        for item in entries:
            name = item['path']
            relative = PurePosixPath(name)
            require(not relative.is_absolute() and str(relative) == name and '..' not in relative.parts
                    and len(relative.parts) > 1 and relative.parts[0] in ('vkd3d-2.1', 'hdr', 'spv'),
                    'invalid producer manifest path')
            require(name not in mapping, 'duplicate producer manifest path')
            require(re.fullmatch('[0-9a-f]{64}', item['sha256']) is not None
                    and type(item['executable']) is bool, 'invalid producer manifest entry')
            mapping[name] = item
        require(mapping, 'empty producer stage')
        maps.append(mapping)
    generated = {'vkd3d-2.1/' + name for name in GENERATED_FILES}
    require(all(maps[2].get(name) == item for name, item in maps[1].items() if name not in generated),
            'non-generated input changed during generation')
    require(not (maps[2].keys() - maps[1].keys() - generated), 'unexpected input added during generation')
    require(maps[2] == maps[3] == maps[4], 'frozen producer snapshot changed')
    required = {'vkd3d-2.1/' + name for name in reference['source_files']}
    required |= {'vkd3d-2.1/' + name for name in reference['target_configuration']}
    required |= set(reference['external_headers'])
    required |= {'vkd3d-2.1/config.status', 'vkd3d-2.1/libtool', 'vkd3d-2.1/Makefile'}
    require(required <= maps[2].keys(), 'incomplete frozen producer manifest')
    for name, item in maps[2].items():
        target = record / 'work' / name
        require(name in files and target.resolve().is_relative_to((record / 'work').resolve())
                and sha(target) == item['sha256'], 'frozen producer input differs: ' + name)
        # POSIX execute bits are not preserved by every Windows archive transport.
        if os.name != 'nt':
            require(bool(target.stat().st_mode & 0o111) == item['executable'],
                    'frozen producer executable mode differs: ' + name)
    makefile = (source / 'Makefile').read_text()
    expected_flags = 'CPPFLAGS = -I' + str(original / 'hdr/include') + ' -I' + str(original / 'spv/include')
    require(expected_flags in makefile.splitlines(), 'actual producer vendor prefix differs')
    require(b'--disable-dependency-tracking' in (record / 'configure-argv.nul').read_bytes().split(b'\0'),
            'producer dependency tracking was not disabled')
    commands = producer.get('make_commands', [])
    prefix = ['-f', str(original / 'vkd3d-2.1/Makefile'), 'V=1']
    generation = ['include/private/spirv_grammar.h', 'include/private/vkd3d_version.h',
                  'libs/vkd3d-shader/hlsl.tab.h', 'libs/vkd3d-shader/preproc.tab.h',
                  'libs/vkd3d-shader/hlsl.tab.c', 'libs/vkd3d-shader/hlsl.yy.c',
                  'libs/vkd3d-shader/preproc.tab.c', 'libs/vkd3d-shader/preproc.yy.c']
    argv = (record / 'configure-argv.nul').read_bytes().split(b'\0')
    windows = b'--host=x86_64-w64-mingw32' in argv
    executable = 'vkd3d-compiler.exe' if windows else 'vkd3d-compiler'
    targets = ['libvkd3d-shader.la', executable]
    install = ['install-libLTLIBRARIES', 'install-binPROGRAMS',
               'lib_LTLIBRARIES=libvkd3d-shader.la', 'bin_PROGRAMS=' + executable]
    require(len(commands) in (3, 4) and all(isinstance(command, list) and len(command) >= 4 and command[:3] == prefix for command in commands),
            'untrusted producer make invocation')
    require(commands[0][3:] == generation and commands[-1][3:] == install
            and re.fullmatch('-j[1-9][0-9]*', commands[1][3]) is not None
            and commands[1][4:] == targets and (len(commands) == 3 or commands[2][3:] == targets),
            'incomplete or unknown producer make stages')
    receipt['producer_contract_verified'] = True
    return producer

def module_identity(output, library):
    paths = Path(str(output) + '.modules').read_text(encoding='utf-8').splitlines()
    modules = {str(Path(path).resolve()): (None if sys.platform == 'darwin' and not Path(path).is_file() else sha(Path(path))) for path in paths}
    require(str(library.resolve()) in modules, 'requested native library absent from loaded modules')
    return modules


def check(args):
    root = args.artifacts
    root.mkdir(parents=True, exist_ok=False)
    commands = []
    results, negative = [], []
    result = {'status': 'incomplete', 'translated_comparison': 'not_run',
              'commands': commands, 'cases': results, 'negative_controls': negative}
    args.receipt = result
    result['host'] = {'platform': sys.platform, 'machine': platform.machine()}
    result['github'] = {key: os.environ.get(key) for key in ('GITHUB_SHA', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'ImageVersion')}
    result['input_contract'] = {'entry_point': 'main', 'source_type': 2, 'source_name': 'matrix.hlsl', 'options': [[4, 21]], 'float_controls_extension': 6}
    (root / 'result.json').write_text(json.dumps(result, indent=2) + '\n')

    def run(command, name):
        command = [str(x) for x in command]
        try:
            completed = subprocess.run(command, capture_output=True, timeout=30)
        except subprocess.TimeoutExpired as error:
            (root / (name + '.log')).write_bytes((error.stdout or b'') + (error.stderr or b''))
            commands.append({'command': command, 'exit_code': None, 'timed_out': True})
            (root / 'commands.json').write_text(json.dumps(commands, indent=2) + '\n')
            raise RuntimeError(f'{name} timed out') from error
        except OSError as error:
            commands.append({'command': command, 'exit_code': None, 'error': str(error)})
            (root / (name + '.log')).write_text(str(error))
            (root / 'commands.json').write_text(json.dumps(commands, indent=2) + '\n')
            raise
        (root / (name + '.log')).write_bytes(completed.stdout + completed.stderr)
        commands.append({'command': [str(x) for x in command], 'exit_code': completed.returncode})
        (root / 'commands.json').write_text(json.dumps(commands, indent=2) + '\n')
        require(completed.returncode == 0, f'{name} failed; see log')
        return completed.stdout

    require(not args.native_only or args.source is not None, 'native-only capture requires fresh producer source and receipt')
    driver = Path(__file__).with_name('shader_driver.rs').resolve()
    if args.source is not None:
        reference_path = Path(__file__).with_name('native-profile-reference.json')
        reference = json.loads(reference_path.read_text())
        require(sha(Path(__file__).with_name('shader_matrix.py')) == reference['matrix_sha256'], 'matrix reference differs')
        result['reference'] = reference
        result['reference_manifest_sha256'] = sha(reference_path)
        require(sha(Path(__file__).parent.parent / 'vkd3d/patches/0001-vpos-vface-io.patch') == reference['patch_sha256'], 'native patch reference differs')
        source_identity(args.source, reference, result.setdefault('source', {}))
        require(args.build_record is not None, 'source profile requires --build-record')
        record = args.build_record
        producer_identity(record, reference, args.source, result)
        require((record / 'build-exit-code').read_text().strip() == '0', 'native build did not succeed')
        require(source_identity(record / 'work/vkd3d-2.1', reference) == result['source'], 'source differs from actual build record')
        recorded_libraries = [path for path in (record / 'prefix').rglob(args.native_library.name) if path.is_file()]
        require(recorded_libraries and all(sha(path) == sha(args.native_library) for path in recorded_libraries), 'loaded library differs from native producer bundle')
        required = ['configure-argv.nul', 'compiler-path.txt', 'compiler-sha256.txt',
                    'compiler--version.txt', 'compiler-v.txt', 'compiler-dumpmachine.txt',
                    'compiler-dumpfullversion.txt', 'compiler-dumpspecs.txt', 'compiler-tools-sha256.txt']
        require(all((record / name).is_file() for name in required), 'incomplete native producer receipt')
        require((record / 'work/make.log').stat().st_size > 0, 'missing actual verbose build log')
        require(sha(args.header) == reference['source_files']['include/vkd3d_shader.h'], 'public header differs')
        result['native_producer_record'] = {str(path.relative_to(record)): sha(path)
            for path in sorted(record.rglob('*')) if path.is_file()}
        result['native_producer_compiler'] = (record / 'compiler-path.txt').read_text().strip()
    result['caller_layout_compiler'] = {'path': shutil.which(args.cc), 'version': run([args.cc, '--version'], 'caller-cc-version').decode(errors='replace')}
    run(['rustc', '+1.95.0', '-vV'], 'caller-rustc-version')
    c = '#include <stddef.h>\n#include <stdio.h>\n#include "vkd3d_shader.h"\nint main(void) {\n'
    expressions = ['sizeof(struct vkd3d_shader_spirv_target_info)', '_Alignof(struct vkd3d_shader_spirv_target_info)']
    expressions += [f'offsetof(struct vkd3d_shader_spirv_target_info, {field})' for field in FIELDS]
    expressions += ['VKD3D_SHADER_STRUCTURE_TYPE_SPIRV_TARGET_INFO', 'VKD3D_SHADER_SPIRV_ENVIRONMENT_VULKAN_1_0',
                    'VKD3D_SHADER_SPIRV_EXTENSION_KHR_FLOAT_CONTROLS']
    rust_expressions = []
    for rust_type, (c_type, fields) in ABI.items():
        expressions += [f'sizeof(struct {c_type})', f'_Alignof(struct {c_type})']
        expressions += [f'offsetof(struct {c_type}, {field})' for field in fields]
    c += ''.join(f'printf("%zu\\n", (size_t)({expression}));\n' for expression in expressions) + '}\n'
    (root / 'layout.c').write_text(c)
    run([args.cc, '-std=c11', '-I', args.header.parent, root / 'layout.c', '-o', root / ('layout-c.exe' if os.name == 'nt' else 'layout-c')], 'layout-c-build')
    native_metrics = [int(x) for x in run([root / ('layout-c.exe' if os.name == 'nt' else 'layout-c')], 'layout-c-run').splitlines()]
    rust_expressions = ['size_of::<SpirvTargetInfo>()', 'align_of::<SpirvTargetInfo>()']
    rust_expressions += [f'offset_of!(SpirvTargetInfo, {"ty" if field == "type" else field})' for field in FIELDS]
    rust_expressions += ['4', '2', '6']
    aliases = {'type': 'ty', 'entry_point': 'entry', 'secondary_code': 'secondary'}
    for rust_type, (_, fields) in ABI.items():
        rust_expressions += [f'size_of::<{rust_type}>()', f'align_of::<{rust_type}>()']
        rust_expressions += [f'offset_of!({rust_type}, {aliases.get(field, field)})' for field in fields]
    # Append a test to the byte-identical actual driver, so private ABI fields are measured directly.
    rust = driver.read_text() + '\n#[test] fn original_header_layout() { use std::mem::{size_of, align_of, offset_of};'
    rust += f'assert_eq!([{", ".join(rust_expressions)}], {native_metrics!r});' + '}\n'
    (root / 'layout.rs').write_text(rust)
    link = ['--cfg', 'native_only'] if args.native_only else ['-C', 'link-arg=' + str(args.native_library)]
    run(['rustc', '+1.95.0', '--edition', '2024', '--test', root / 'layout.rs', *link, '-o', root / ('layout-rust.exe' if os.name == 'nt' else 'layout-rust')], 'layout-rust-build')
    run([root / ('layout-rust.exe' if os.name == 'nt' else 'layout-rust')], 'layout-rust-run')
    binary = root / ('native-driver.exe' if os.name == 'nt' else 'native-driver')
    run(['rustc', '+1.95.0', '--edition', '2024', driver, *link, '-o', binary], 'driver-build')
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
                    case = {'name': key, 'profile': f'{stage}_{model}', 'target': target, 'source_sha256': sha(source), 'diagnostics_sha256': sha(Path(str(output) + '.diagnostics')), 'api_status': 0, 'loaded_modules': module_identity(output, args.native_library), 'status': 'native_success', 'sha256': hashlib.sha256(output.read_bytes()).hexdigest()}
                    if target == 1:
                        case['spirv'] = spirv_layout(output.read_bytes())
                        # DenormFlushToZero, 32-bit floats. Keep the shader model's denormal behavior.
                        require('SPV_KHR_float_controls' in case['spirv']['extensions']
                                and [4460, 32] in case['spirv']['execution_modes'], f'{key}: missing float controls')
                        if name == 'struct_io' and stage == 'ps':
                            require(len(case['spirv']['input_locations']) == 2
                                    and case['spirv']['output_locations'] == [0], f'{key}: invalid pixel interface')
                    results.append(case)
                    (root / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
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
        negative.append({'name': name, 'status': 'expected_rejection', 'sha256': sha(output), 'api_status': -4, 'profile': profile, 'target': target, 'source_sha256': sha(source), 'diagnostics_sha256': sha(Path(str(output) + '.diagnostics')), 'loaded_modules': module_identity(output, args.native_library)})
    identity = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in (driver, Path(__file__).resolve(), Path(__file__).with_name('shader_matrix.py').resolve(),
                             args.header, args.native_library)}
    result.update({'status': 'native_inputs_success', 'translated_comparison': 'not_run', 'identity': identity,
              'layout_metrics': native_metrics, 'cases': results, 'negative_controls': negative})
    if args.compare_driver is not None:
        reference = json.loads(Path(__file__).with_name('native-profile-reference.json').read_text())
        require(sha(args.compare_driver) == reference['old_driver_sha256'], 'transport reference driver differs')
        old_binary = root / 'old-driver'
        run(['rustc', '+1.95.0', '--edition', '2024', args.compare_driver, '-C',
             'link-arg=' + str(args.native_library), '-o', old_binary], 'old-driver-build')
        for case in results + negative:
            key = case['name']
            source = root / ((key if case['api_status'] < 0 else key.rsplit('-', 2)[0]) + '.hlsl')
            output = root / (key + '.old')
            extra = ['no-float-controls'] if key == 'missing_float_controls' else []
            run([old_binary, source, case['profile'], case['target'], output, args.native_library, *extra], key + '.old')
            for suffix in ('', '.status', '.diagnostics'):
                require(Path(str(output) + suffix).read_bytes() == (root / (key + suffix)).read_bytes(), f'{key}{suffix}: transport differs')
        result['transport_comparison'] = {'status': 'byte_exact', 'cases': len(results), 'controls': len(negative),
                                          'old_driver_sha256': sha(args.compare_driver), 'old_binary_sha256': sha(old_binary)}
    result['caller_binary_sha256'] = sha(binary)
    result['fixture_sha256'] = {path.stem: sha(path) for path in sorted(root.glob('*.hlsl'))}
    reference = json.loads(Path(__file__).with_name('native-profile-reference.json').read_text())
    require(result['fixture_sha256'] == reference['fixtures'], 'frozen fixture bytes differ')
    if args.build_record is not None and os.name == 'nt':
        loaded = {Path(path).name.lower(): digest for path, digest in results[0]['loaded_modules'].items()}
        for dll in (args.build_record / 'prefix/bin').glob('*.dll'):
            require(loaded.get(dll.name.lower()) == sha(dll), f'bundled DLL not loaded with recorded bytes: {dll.name}')
    (root / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--header', type=Path, required=True)
    parser.add_argument('--native-library', type=Path, required=True)
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--cc', default='cc', help='Header-layout caller compiler, not the native producer')
    parser.add_argument('--native-only', action='store_true')
    parser.add_argument('--source', type=Path)
    parser.add_argument('--build-record', type=Path)
    parser.add_argument('--compare-driver', type=Path, help='Frozen d046 POSIX driver for same-library transport comparison')
    args = parser.parse_args()
    args.header = args.header.resolve()
    args.native_library = args.native_library.resolve()
    args.artifacts = args.artifacts.resolve()
    try:
        check(args)
    except Exception as error:
        if hasattr(args, 'receipt'):
            args.receipt.update(status='failure', error=str(error))
            (args.artifacts / 'result.json').write_text(json.dumps(args.receipt, indent=2) + '\n')
        raise
    finally:
        if hasattr(args, 'receipt'):
            seal = {str(path.relative_to(args.artifacts)): sha(path) for path in sorted(args.artifacts.rglob('*')) if path.is_file() and path.name != 'seal.json'}
            (args.artifacts / 'seal.json').write_text(json.dumps(seal, indent=2) + '\n')


if __name__ == '__main__':
    main()
