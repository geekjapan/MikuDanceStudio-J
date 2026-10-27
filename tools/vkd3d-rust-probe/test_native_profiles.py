"""Native profile boundary checks without a native compiler build."""
import argparse
import hashlib
import io
import json
import tarfile
import zipfile
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from check_shader_inputs import source_identity, sha


class NativeProfileTest(unittest.TestCase):
    def test_frozen_reference_and_generated_difference(self):
        reference = json.loads(Path(__file__).with_name('native-profile-reference.json').read_text())
        self.assertEqual(len(reference['production_units']), 24)
        self.assertEqual(sha(Path(__file__).with_name('shader_matrix.py')), reference['matrix_sha256'])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'vkd3d-2.1'
            for key, base in [('source_files', root), ('target_configuration', root),
                              ('external_headers', root.parent)]:
                for name in reference[key]:
                    path = base / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text('original')
                    reference[key][name] = sha(path)
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
                    path.write_text('original')
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
                        path.write_text('original')
            for name in reference['target_configuration']:
                path = root / name
                path.write_text('new target')
                result = source_identity(root, reference)
                self.assertFalse(result['identical_source_profile'])
                self.assertEqual(result['generated_source_differences'], [])
                self.assertEqual(result['target_configuration_differences'], [name])
                self.assertEqual(result['target_configuration'][name], sha(path))
                path.write_text('original')
            for name in reference['external_headers']:
                path = root.parent / name
                path.write_text('new external header')
                with self.assertRaisesRegex(RuntimeError, 'external producer headers differ'):
                    source_identity(root, reference)
                path.write_text('original')
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
            self.assertEqual(result['commands'][0]['command'], ['missing-caller-compiler', '--version'])
            self.assertIsNone(result['commands'][0]['exit_code'])
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
    artifacts.mkdir(parents=True, exist_ok=False)
    source = artifacts / 'work/vkd3d-2.1'
    for key, base in [('source_files', source), ('target_configuration', source), ('external_headers', source.parent)]:
        for name, digest in reference[key].items():
            data = files[('vkd3d-2.1/' if base == source else '') + name]
            check(hashlib.sha256(data).hexdigest() == digest, 'authenticated input differs at ' + name)
            path = base / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
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
    captures = []
    for name in ('hdr/include/vulkan/vulkan.h', 'hdr/include/vulkan/vulkan_core.h',
                 'hdr/include/vk_video/vulkan_video_codec_h264std.h'):
        path = source.parent / name
        original = path.read_bytes()
        try:
            path.write_bytes(original + b'\n#error authenticated Vulkan mutation\n')
            capture = artifacts / ('capture-' + path.stem)
            command = [sys.executable, *(['-O'] if sys.flags.optimize else []),
                       str(Path(__file__).with_name('check_shader_inputs.py')), '--source', str(source),
                       '--header', str(source / 'include/vkd3d_shader.h'), '--native-library', str(artifacts / 'never-loaded'),
                       '--native-only', '--artifacts', str(capture)]
            completed = subprocess.run(command, capture_output=True, text=True)
            check(completed.returncode != 0, 'mutated CLI accepted')
            result = json.loads((capture / 'result.json').read_text())
            check(result['status'] == 'failure' and result['commands'] == [] and result['cases'] == [], 'native command executed')
            check(result['source']['external_header_differences'] == [name], 'CLI lost vendor difference')
            check(result['source']['external_headers'][name] == sha(path), 'CLI lost vendor hash')
            seal = json.loads((capture / 'seal.json').read_text())
            check(seal['result.json'] == sha(capture / 'result.json'), 'CLI receipt seal differs')
            captures.append({'command': command, 'exit_code': completed.returncode, 'result_sha256': seal['result.json']})
        finally:
            path.write_bytes(original)
    check(source_identity(source, reference)['identical_source_profile'], 'authenticated source restoration differs')
    report = {'zip_sha256': reference['zip_sha256'], 'prepared_tar_sha256': reference['prepared_tar_sha256'],
              'reference_sha256': sha(Path(__file__).with_name('native-profile-reference.json')),
              'vendor_inventory': vendor, 'mutated_and_omitted_inputs': checks, 'sealed_cli_captures': captures,
              'native_commands_executed': 0, 'optimized': bool(sys.flags.optimize)}
    (artifacts / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')
    print('Authenticated archive verified; mutated and omitted', len(checks), 'inputs; three sealed CLI rejections before native commands.')


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
