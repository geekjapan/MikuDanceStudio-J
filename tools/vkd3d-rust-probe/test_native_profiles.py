"""Native profile boundary checks without a native compiler build."""
import argparse
import copy
import os
from unittest.mock import patch
import hashlib
import io
import json
import tarfile
import zipfile
from pathlib import Path
import subprocess
import sys
import tempfile
import shlex
import shutil
import unittest

from check_shader_inputs import source_identity, sha, include_recipe, literal_include_graph, input_inventory, producer_identity


class NativeProfileTest(unittest.TestCase):
    def test_frozen_reference_and_generated_difference(self):
        reference = json.loads(Path(__file__).with_name('native-profile-reference.json').read_text())
        def content(name):
            if name == 'Makefile':
                return 'CPPFLAGS = -I/fixture/hdr/include -I/fixture/spv/include\nCFLAGS = -O2\n\t$(COMPILE)\n'
            return 'original'

        self.assertEqual(len(reference['production_units']), 24)
        self.assertEqual(sha(Path(__file__).with_name('shader_matrix.py')), reference['matrix_sha256'])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'vkd3d-2.1'
            for key, base in [('source_files', root), ('target_configuration', root),
                              ('external_headers', root.parent)]:
                for name in reference[key]:
                    path = base / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(content(name))
                    reference[key][name] = sha(path)
            reference['include_recipe'] = include_recipe((root / 'Makefile').read_text())
            reference['literal_include_graph'] = literal_include_graph(root, reference['production_units'])
            self.assertTrue(source_identity(root, reference)['identical_source_profile'])
            for name in reference['source_files']:
                with self.subTest(changed=name):
                    path = root / name
                    path.write_text('changed')
                    if name in reference['generated_files']:
                        result = source_identity(root, reference)
                        self.assertFalse(result['identical_source_profile'])
                        self.assertEqual(result['generated_source_differences'], [name])
                        self.assertEqual(result['files'][name], sha(path))
                    else:
                        receipt = {}
                        with self.assertRaisesRegex(RuntimeError, 'non-generated reference source differs'):
                            source_identity(root, reference, receipt)
                        self.assertFalse(receipt['identical_source_profile'])
                        self.assertEqual(receipt['files'][name], sha(path))
                    path.write_text(content(name))
            for key, base in [('source_files', root), ('external_headers', root.parent),
                              ('target_configuration', root)]:
                for name in reference[key]:
                    with self.subTest(missing=name):
                        path = base / name
                        path.unlink()
                        receipt = {}
                        with self.assertRaisesRegex(RuntimeError, 'missing required producer inputs'):
                            source_identity(root, reference, receipt)
                        self.assertIn(name, receipt['missing_inputs'])
                        self.assertFalse(receipt['identical_source_profile'])
                        path.write_text(content(name))
            for name in reference['target_configuration']:
                path = root / name
                path.write_text(content(name) + '\n# new target\n')
                result = source_identity(root, reference)
                self.assertFalse(result['identical_source_profile'])
                self.assertEqual(result['generated_source_differences'], [])
                self.assertEqual(result['target_configuration_differences'], [name])
                self.assertEqual(result['target_configuration'][name], sha(path))
                path.write_text(content(name))
            for name in reference['external_headers']:
                path = root.parent / name
                path.write_text('new external header')
                with self.assertRaisesRegex(RuntimeError, 'external producer headers differ'):
                    source_identity(root, reference)
                path.write_text(content(name))
            for vendor_root in reference['external_include_roots']:
                unknown_external = root.parent / vendor_root / 'unclassified/input.inc'
                unknown_external.parent.mkdir(parents=True, exist_ok=True)
                unknown_external.write_text('unclassified')
                receipt = {}
                with self.assertRaisesRegex(RuntimeError, 'unclassified producer inputs'):
                    source_identity(root, reference, receipt)
                self.assertIn(unknown_external.relative_to(root.parent).as_posix(), receipt['unclassified_inputs'])
                unknown_external.unlink()
            original_roots = reference['external_include_roots']
            reference['external_include_roots'] = ['spv/include']
            with self.assertRaisesRegex(RuntimeError, 'external include root classification'):
                source_identity(root, reference)
            reference['external_include_roots'] = original_roots
            original_local_roots = reference['local_include_roots']
            reference['local_include_roots'] = ['include', 'include/private', 'libs/vkd3d-shader']
            with self.assertRaisesRegex(RuntimeError, 'local include root classification'):
                source_identity(root, reference)
            reference['local_include_roots'] = original_local_roots
            omitted_local = 'demos/demo.h'
            digest = reference['source_files'].pop(omitted_local)
            with self.assertRaisesRegex(RuntimeError, 'unclassified producer inputs'):
                source_identity(root, reference)
            reference['source_files'][omitted_local] = digest
            omitted = 'hdr/include/vulkan/vulkan.h'
            digest = reference['external_headers'].pop(omitted)
            with self.assertRaisesRegex(RuntimeError, 'unclassified producer inputs'):
                source_identity(root, reference)
            reference['external_headers'][omitted] = digest
            unknown = root / 'libs/vkd3d-shader/unknown.tab.h'
            unknown.write_text('unclassified')
            with self.assertRaisesRegex(RuntimeError, 'unclassified producer inputs'):
                source_identity(root, reference)
            reference['source_files']['libs/vkd3d-shader/unknown.tab.h'] = sha(unknown)
            unknown.write_text('changed')
            with self.assertRaisesRegex(RuntimeError, 'non-generated reference source differs'):
                source_identity(root, reference)
            reference['generated_files'].append('libs/vkd3d-shader/unknown.tab.h')
            with self.assertRaisesRegex(RuntimeError, 'unknown or missing generated source classification'):
                source_identity(root, reference)

    def test_failure_keeps_partial_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts = root / 'capture'
            completed = subprocess.run([sys.executable, str(Path(__file__).with_name('check_shader_inputs.py')),
                '--header', str(root / 'missing.h'), '--native-library', str(root / 'missing-library'),
                '--artifacts', str(artifacts), '--native-only', '--cc', 'missing-caller-compiler'], capture_output=True)
            self.assertNotEqual(completed.returncode, 0)
            result = json.loads((artifacts / 'result.json').read_text())
            self.assertEqual(result['status'], 'failure')
            self.assertEqual(result['translated_comparison'], 'not_run')
            self.assertEqual(result['cases'], [])
            self.assertEqual(result['commands'], [])
            self.assertIn('requires fresh producer', result['error'])
            seal = json.loads((artifacts / 'seal.json').read_text())
            self.assertEqual(seal['result.json'], sha(artifacts / 'result.json'))
            partial = root / 'source-failure'
            completed = subprocess.run([sys.executable, str(Path(__file__).with_name('check_shader_inputs.py')),
                '--header', str(root / 'missing.h'), '--native-library', str(root / 'missing-library'),
                '--artifacts', str(partial), '--native-only', '--source', str(root / 'missing-source')],
                capture_output=True)
            self.assertNotEqual(completed.returncode, 0)
            result = json.loads((partial / 'result.json').read_text())
            self.assertEqual(result['status'], 'failure')
            self.assertFalse(result['source']['identical_source_profile'])
            self.assertIn('libs/vkd3d-shader/hlsl.h', result['source']['missing_inputs'])
            self.assertEqual(result['cases'], [])
            self.assertEqual(result['commands'], [])
            seal = json.loads((partial / 'seal.json').read_text())
            self.assertEqual(seal['result.json'], sha(partial / 'result.json'))


class FreshProducerTest(unittest.TestCase):
    def test_receipt_boundary_and_arm_workflow_mapping(self):
        reference = json.loads(Path(__file__).with_name('native-profile-reference.json').read_text())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'native-arm64'
            record = root / 'record'
            source = record / 'work/vkd3d-2.1'
            names = {'vkd3d-2.1/' + name for key in ('source_files', 'target_configuration')
                     for name in reference[key]}
            names |= set(reference['external_headers'])
            names |= {'vkd3d-2.1/config.status', 'vkd3d-2.1/libtool'}
            original = str(root / 'build/work-linux-native')
            for name in names:
                path = record / 'work' / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('synthetic producer fixture')
            (source / 'Makefile').write_text(f'CPPFLAGS = -I{original}/hdr/include -I{original}/spv/include\n')
            recipe = Path(__file__).parent.parent / 'vkd3d/build.sh'
            (record / 'build.sh').write_bytes(recipe.read_bytes())
            (record / 'configure-argv.nul').write_bytes(b'./configure\0--disable-dependency-tracking\0')
            entries = [{'path': name, 'sha256': sha(record / 'work' / name), 'executable': False}
                       for name in sorted(names)]
            contract = reference['producer_contract']
            receipt = {**{key: contract[key] for key in ('schema', 'recipe_sha256', 'archives', 'patches')},
                       'status': 'success', 'exit_code': 0, 'original_work_root': original,
                       'retained_work_root': 'work',
                       'include_roots': [{'original': original + '/' + name, 'retained': 'work/' + name}
                           for name in ('vkd3d-2.1', 'vkd3d-2.1/include', 'vkd3d-2.1/include/private',
                                        'hdr/include', 'spv/include', 'vkd3d-2.1/libs/vkd3d-shader')],
                       'stages': [{'stage': stage, 'files': copy.deepcopy(entries)} for stage in
                                  ('prepared', 'configured', 'frozen', 'compiled', 'installed')]}
            prefix = ['-f', original + '/vkd3d-2.1/Makefile', 'V=1']
            receipt['make_commands'] = [prefix + ['include/private/spirv_grammar.h', 'include/private/vkd3d_version.h',
                'libs/vkd3d-shader/hlsl.tab.h', 'libs/vkd3d-shader/preproc.tab.h',
                'libs/vkd3d-shader/hlsl.tab.c', 'libs/vkd3d-shader/hlsl.yy.c',
                'libs/vkd3d-shader/preproc.tab.c', 'libs/vkd3d-shader/preproc.yy.c'],
                prefix + ['-j2', 'libvkd3d-shader.la', 'vkd3d-compiler'],
                prefix + ['install-libLTLIBRARIES', 'install-binPROGRAMS',
                          'lib_LTLIBRARIES=libvkd3d-shader.la', 'bin_PROGRAMS=vkd3d-compiler']]
            path = record / 'producer-receipt.json'
            def verify(value):
                path.write_text(json.dumps(value))
                return producer_identity(record, reference, source, {})
            verify(receipt)  # Original Linux paths need not exist on the capture host.
            shutil.copytree(record / 'work', original)
            original_source = Path(original) / 'vkd3d-2.1'
            for name in names:
                self.assertEqual((record / 'work' / name).read_bytes(), (Path(original) / name).read_bytes())
            workflow = Path(__file__).resolve().parents[2] / '.github/workflows/vkd3d-native-profiles.yml'
            arm_job = workflow.read_text().split('  capture-linux-arm64:', 1)[1]
            source_line = next(line for line in arm_job.splitlines() if '--source ' in line)
            arguments = shlex.split(source_line.removesuffix('\\'))
            with patch.dict(os.environ, {'MDS_VKD3D_OUT': str(root / 'build'),
                                         'MDS_VKD3D_RECORD_DIR': str(record)}):
                workflow_source = Path(os.path.expandvars(arguments[arguments.index('--source') + 1]))
            self.assertEqual(workflow_source.resolve(), source.resolve())
            producer_identity(record, reference, workflow_source, {})
            with self.assertRaisesRegex(RuntimeError, 'source is outside retained producer mapping'):
                producer_identity(record, reference, original_source, {})
            variants = []
            for key, value in [('schema', 'unknown'), ('recipe_sha256', '0' * 64),
                               ('archives', {}), ('patches', {}), ('status', 'incomplete'),
                               ('original_work_root', '/different/root'), ('retained_work_root', '../work')]:
                changed = copy.deepcopy(receipt); changed[key] = value; variants.append((key, changed))
            for count in range(5):
                changed = copy.deepcopy(receipt); changed['stages'] = changed['stages'][:count]
                variants.append(('missing stage ' + str(count), changed))
            for index, label in ((2, 'frozen'), (3, 'compiled'), (4, 'installed')):
                changed = copy.deepcopy(receipt); changed['stages'][index]['files'][0]['sha256'] = '0' * 64
                variants.append((label, changed))
            for name in ('duplicate', 'missing', 'escaping'):
                changed = copy.deepcopy(receipt)
                entries = changed['stages'][2]['files']
                if name == 'duplicate': entries.append(entries[0])
                elif name == 'missing': entries.pop()
                else: entries[0]['path'] = '../escape'
                variants.append((name, changed))
            changed = copy.deepcopy(receipt); changed['make_commands'][1].remove('-f')
            variants.append(('unfrozen make', changed))
            for label, changed in variants:
                with self.subTest(label=label), self.assertRaises(RuntimeError): verify(changed)
            verify(receipt)
            for name in ('include/config.h', 'libtool', 'libs/vkd3d-shader/hlsl.tab.c'):
                target = source / name; original_bytes = target.read_bytes()
                target.write_bytes(original_bytes + b'\n%:include "untracked.inc"\n')
                with self.subTest(changed=name), self.assertRaisesRegex(RuntimeError, 'frozen producer input differs'):
                    verify(receipt)
                target.write_bytes(original_bytes)
            path.unlink()
            with self.assertRaisesRegex(RuntimeError, 'missing fresh producer receipt'):
                producer_identity(record, reference, source, {})


def verify_authenticated_archive(archive, artifacts):
    reference = json.loads(Path(__file__).with_name('native-profile-reference.json').read_text())

    def check(condition, message):
        if not condition:
            raise RuntimeError(message)

    check(sha(archive) == reference['zip_sha256'], 'authenticated ZIP differs')
    with zipfile.ZipFile(archive) as bundle:
        prepared = bundle.read('prepared.tar.gz')
    check(hashlib.sha256(prepared).hexdigest() == reference['prepared_tar_sha256'], 'authenticated tar differs')
    prefix = 'prepared/work-linux-native/'
    with tarfile.open(fileobj=io.BytesIO(prepared), mode='r:gz') as bundle:
        files = {member.name[len(prefix):]: bundle.extractfile(member).read()
                 for member in bundle if member.isfile() and member.name.startswith(prefix)}
    roots = ('hdr/include', 'spv/include')
    vendor = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()
              if any(name.startswith(root + '/') for root in roots)}
    check(set(reference['external_include_roots']) == set(roots), 'archive roots differ')
    check(vendor == reference['external_headers'], 'vendor manifest is not exhaustive for authenticated archive')
    makefile = files['vkd3d-2.1/Makefile'].decode()
    cppflags = next(line for line in makefile.splitlines() if line.startswith('CPPFLAGS ='))
    check(all('/' + root in cppflags for root in roots), 'actual compiler vendor include paths differ')
    check('VKD3D_NO_VULKAN_H' not in makefile, 'actual Makefile disables Vulkan')
    check('define VKD3D_NO_VULKAN_H' not in files['vkd3d-2.1/include/config.h'].decode(), 'configuration disables Vulkan')
    for name, directive in [('vkd3d-2.1/libs/vkd3d-common/blob.c', b'#include "vkd3d.h"'),
                            ('vkd3d-2.1/include/vkd3d.h', b'# include <vulkan/vulkan.h>'),
                            ('hdr/include/vulkan/vulkan.h', b'#include "vulkan_core.h"'),
                            ('hdr/include/vulkan/vulkan_core.h', b'#include "vk_video/vulkan_video_codec_h264std.h"')]:
        check(directive in files[name], 'actual include chain differs at ' + name)
    local = {name[len('vkd3d-2.1/'):]: hashlib.sha256(data).hexdigest()
             for name, data in files.items() if name.startswith('vkd3d-2.1/') and name.endswith(('.h', '.l', '.y'))}
    expected_local = {name: digest for key in ('source_files', 'target_configuration')
                      for name, digest in reference[key].items() if name.endswith(('.h', '.l', '.y'))}
    check(local == expected_local, 'local manifest is not exhaustive for authenticated archive')
    check(include_recipe(makefile) == reference['include_recipe'], 'actual Makefile include recipe differs')
    artifacts.mkdir(parents=True, exist_ok=False)
    source = artifacts / 'work/vkd3d-2.1'
    for key, base in [('source_files', source), ('target_configuration', source), ('external_headers', source.parent)]:
        for name, digest in reference[key].items():
            data = files[('vkd3d-2.1/' if base == source else '') + name]
            check(hashlib.sha256(data).hexdigest() == digest, 'authenticated input differs at ' + name)
            path = base / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    for name, data in files.items():
        if name.startswith(('vkd3d-2.1/', 'hdr/include/', 'spv/include/')):
            path = source.parent / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    graph = literal_include_graph(source, reference['production_units'])
    check(graph == reference['literal_include_graph'], 'complete actual include graph differs')
    check(len(graph['visited']) == 84, 'actual include closure differs')
    check(len({name for _, name in graph['unresolved_system_sdk_or_disabled']}) == 40, 'unresolved include inventory differs')
    check(source_identity(source, reference)['identical_source_profile'], 'unchanged authenticated source rejected')
    checks = []
    for key, base in [('source_files', source), ('target_configuration', source), ('external_headers', source.parent)]:
        for name in reference[key]:
            path = base / name
            original = path.read_bytes()
            try:
                path.write_bytes(original + b'\n#error authenticated input mutation\n')
                receipt = {}
                try:
                    source_identity(source, reference, receipt)
                    check(key == 'target_configuration' or name in reference['generated_files'], 'mutation accepted at ' + name)
                except RuntimeError as error:
                    check(('external producer headers differ' if key == 'external_headers' else 'non-generated reference source differs') in str(error), str(error))
                check(not receipt['identical_source_profile'], 'mutation claimed identical at ' + name)
                check(receipt['files' if key == 'source_files' else key][name] == sha(path), 'mutation hash lost')
                path.unlink()
                receipt = {}
                try:
                    source_identity(source, reference, receipt)
                except RuntimeError as error:
                    check('missing required producer inputs' in str(error), str(error))
                else:
                    raise RuntimeError('omission accepted at ' + name)
                check(name in receipt['missing_inputs'], 'missing path lost')
                checks.append(name)
            finally:
                path.write_bytes(original)
    for root in roots:
        unknown = source.parent / root / 'unclassified.inc'
        unknown.write_text('unclassified input')
        try:
            receipt = {}
            try:
                source_identity(source, reference, receipt)
            except RuntimeError as error:
                check('unclassified producer inputs' in str(error), str(error))
            else:
                raise RuntimeError('unclassified vendor input accepted')
            check(unknown.relative_to(source.parent).as_posix() in receipt['unclassified_inputs'], 'unclassified path lost')
        finally:
            unknown.unlink()
    boundary_checks = []

    def rejected(label, expected):
        receipt = {}
        try:
            source_identity(source, reference, receipt)
        except RuntimeError as error:
            check(expected in str(error), label + ': ' + str(error))
        else:
            raise RuntimeError('boundary bypass accepted: ' + label)
        check(not receipt['identical_source_profile'], label + ': claimed identical')
        boundary_checks.append({'attack': label, 'receipt': receipt})

    shadows = [(source / name) for name in ('config.h', 'vulkan/vulkan.h', 'spirv/unified1/spirv.h')]
    shadows += [source / root / 'stdio.h' for root in
                ('include', 'include/private', 'libs/vkd3d-shader', 'libs/vkd3d-common',
                 'demos', 'tests', 'libs/vkd3d')]
    shadows += [source.parent / root / 'stdio.h' for root in roots]
    for path in shadows:
        check(not path.exists(), 'shadow fixture already exists')
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.write_text('#error first search root shadow\n')
            rejected(path.relative_to(source.parent).as_posix(), 'unclassified producer inputs')
        finally:
            path.unlink()
    outside = artifacts / 'outside'
    outside.mkdir()
    (outside / 'shadow.h').write_text('#error outside symlink root\n')
    link_paths = [source, source / 'unknown-link', source / 'include', source / 'include/private',
                  source / 'libs/vkd3d-common', source / 'libs/vkd3d-shader',
                  *(source.parent / root / 'unknown-link' for root in roots),
                  source.parent / 'hdr/include/vulkan', source.parent / 'spv/include/spirv',
                  *(source.parent / root for root in roots), source.parent / 'hdr', source.parent / 'spv']
    for index, path in enumerate(link_paths):
        saved = artifacts / ('saved-directory-' + str(index))
        existed = path.exists()
        if existed:
            path.rename(saved)
        try:
            path.symlink_to(outside, target_is_directory=True)
            rejected(path.relative_to(source.parent).as_posix(), 'symlink producer inputs')
        finally:
            path.unlink()
            if existed:
                saved.rename(path)
    cycle = source / 'cycle'
    try:
        cycle.symlink_to(source, target_is_directory=True)
        rejected('source symlink cycle', 'symlink producer inputs')
    finally:
        cycle.unlink()
    make_path = source / 'Makefile'
    make_changes = [
        ('default order', makefile.replace('DEFAULT_INCLUDES = -I. -I$(top_builddir)/include',
                                          'DEFAULT_INCLUDES = -I$(top_builddir)/include -I.')),
        ('appended root', makefile + '\nCPPFLAGS += -Iextra\n'),
        ('target-specific root', makefile + '\nlibs/vkd3d-shader/hlsl.lo: CPPFLAGS = -Iextra\n'),
        ('extra root', makefile.replace('AM_CPPFLAGS = ', 'AM_CPPFLAGS = -Iextra ')),
        ('shader root', makefile.replace('-I$(srcdir)/libs/vkd3d-shader', '-Iextra')),
        ('compile order', makefile.replace('$(DEFAULT_INCLUDES) $(INCLUDES)', '$(INCLUDES) $(DEFAULT_INCLUDES)')),
        ('actual compile recipe', makefile.replace('$(AM_V_CC)$(LIBTOOL)', '$(AM_V_CC)$(LIBTOOL) -Iextra', 1)),
        ('source directory', makefile.replace('srcdir = .\n', 'srcdir = other\n')),
        ('forced include', makefile.replace('CFLAGS = -g -O2', 'CFLAGS = -g -O2 -include outside.h')),
        ('vendor order', makefile.replace('CPPFLAGS = ', 'CPPFLAGS = -Ioutside ')),
    ]
    for label, changed in make_changes:
        check(changed != makefile, 'ineffective Makefile test: ' + label)
        try:
            make_path.write_text(changed)
            rejected(label, 'include')
        finally:
            make_path.write_text(makefile)
    generated = source / 'libs/vkd3d-shader/hlsl.tab.c'
    original = generated.read_bytes()
    for directive in ('#include DYNAMIC_HEADER', '#include "future.inc"',
                      '#include_next <stdio.h>', '#import <stdio.h>'):
        try:
            generated.write_bytes(original + ('\n' + directive + '\n').encode())
            rejected(directive, 'unsupported include')
        finally:
            generated.write_bytes(original)
    # Target configuration bytes remain separate even when the include graph is unchanged.
    config = source / 'include/config.h'
    original = config.read_bytes()
    try:
        config.write_bytes(original + b'\n/* target configuration drift */\n')
        receipt = source_identity(source, reference)
        check(receipt['target_configuration_differences'] == ['include/config.h']
              and not receipt['identical_source_profile'], 'target config lost separate identity')
    finally:
        config.write_bytes(original)
    captures = []
    for name in ('hdr/include/vulkan/vulkan.h', 'hdr/include/vulkan/vulkan_core.h',
                 'hdr/include/vk_video/vulkan_video_codec_h264std.h',
                 'vkd3d-2.1/config.h', 'vkd3d-2.1/vulkan/vulkan.h', 'vkd3d-2.1/spirv/unified1/spirv.h'):
        path = source.parent / name
        existed = path.exists()
        original = path.read_bytes() if existed else b''
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.write_bytes(original + b'\n#error authenticated Vulkan mutation\n')
            capture = artifacts / ('capture-' + name.replace('/', '-'))
            command = [sys.executable, *(['-O'] if sys.flags.optimize else []),
                       str(Path(__file__).with_name('check_shader_inputs.py')), '--source', str(source),
                       '--header', str(source / 'include/vkd3d_shader.h'), '--native-library', str(artifacts / 'never-loaded'),
                       '--native-only', '--artifacts', str(capture)]
            completed = subprocess.run(command, capture_output=True, text=True)
            check(completed.returncode != 0, 'mutated CLI accepted')
            result = json.loads((capture / 'result.json').read_text())
            check(result['status'] == 'failure' and result['commands'] == [] and result['cases'] == [], 'native command executed')
            if existed:
                check(result['source']['external_header_differences'] == [name], 'CLI lost vendor difference')
                check(result['source']['external_headers'][name] == sha(path), 'CLI lost vendor hash')
            else:
                check(name[len('vkd3d-2.1/'):] in result['source']['unclassified_inputs'], 'CLI lost root shadow')
            seal = json.loads((capture / 'seal.json').read_text())
            check(seal['result.json'] == sha(capture / 'result.json'), 'CLI receipt seal differs')
            captures.append({'command': command, 'exit_code': completed.returncode, 'result_sha256': seal['result.json']})
        finally:
            if existed:
                path.write_bytes(original)
            else:
                path.unlink()
    # Historical authenticated inputs are a catalog control, never a fresh producer receipt.
    producer_rejections = []
    additions = ('GNUmakefile', 'makefile', 'extra-override.mk',
                 'libs/vkd3d-shader/.deps/libvkd3d_shader_la-hlsl.Plo')
    changes = ('include/config.h', 'libtool', 'libs/vkd3d-shader/hlsl.tab.c')
    for name in ('unchanged historical tree', *additions, *changes):
        target = source / name
        existed = target.is_file()
        original = target.read_bytes() if existed else None
        try:
            if name != 'unchanged historical tree':
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((original or b'') + b'\n%:include "untracked.inc"\n')
            capture = artifacts / ('producer-reject-' + name.replace('/', '-'))
            command = [sys.executable, *(['-O'] if sys.flags.optimize else []),
                       str(Path(__file__).with_name('check_shader_inputs.py')),
                       '--source', str(source), '--build-record', str(artifacts),
                       '--header', str(source / 'include/vkd3d_shader.h'),
                       '--native-library', str(artifacts / 'never-loaded'), '--native-only', '--artifacts', str(capture)]
            completed = subprocess.run(command, capture_output=True, text=True)
            result = json.loads((capture / 'result.json').read_text())
            check(completed.returncode != 0 and result['commands'] == [] and result['cases'] == [],
                  'historical tree admitted without fresh receipt: ' + name)
            check('missing fresh producer receipt' in result['error'], result['error'])
            producer_rejections.append(name)
        finally:
            if name != 'unchanged historical tree':
                if existed: target.write_bytes(original)
                else: target.unlink()
    check(source_identity(source, reference)['identical_source_profile'], 'authenticated source restoration differs')
    report = {'zip_sha256': reference['zip_sha256'], 'prepared_tar_sha256': reference['prepared_tar_sha256'],
              'reference_sha256': sha(Path(__file__).with_name('native-profile-reference.json')),
              'vendor_inventory': vendor, 'local_inventory': local, 'include_graph': graph, 'include_recipe': include_recipe(makefile), 'mutated_and_omitted_inputs': checks, 'sealed_cli_captures': captures,
              'boundary_checks': boundary_checks, 'fresh_producer_rejections': producer_rejections, 'native_commands_executed': 0, 'optimized': bool(sys.flags.optimize)}
    (artifacts / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')
    print('Authenticated archive verified; mutated and omitted', len(checks), 'inputs;', len(captures), 'sealed CLI rejections before native commands.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--artifacts', type=Path)
    args, remaining = parser.parse_known_args()
    if args.archive:
        if args.artifacts is None:
            parser.error('--archive requires --artifacts for retained receipts')
        verify_authenticated_archive(args.archive, args.artifacts)
    unittest.main(argv=[sys.argv[0], *remaining])
