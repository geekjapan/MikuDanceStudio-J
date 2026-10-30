import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import job_transport as T


class TransportTests(unittest.TestCase):
    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))

    def fixture(self, root):
        native = root / 'prepared/work-linux-native/header.h'
        native.parent.mkdir(parents=True)
        native.write_text('int x;\n')
        tool = root / 'tool/bin/compiler'
        tool.parent.mkdir(parents=True)
        tool.write_text('#!/bin/sh\nexit 0\n')
        tool.chmod(0o755)
        packet = root / 'evidence/result/closed-format-facts'
        report = dict(schema=1, status='complete_coverage', authorization='analysis_only',
                      units=24, symbols=40, incoming_calls=4865, unclassified=5, authentic_job_proof=False)
        self.write(packet / 'report.json', report)
        self.write(packet / 'native-files.json', {str(native): T.digest(native)})
        seal = {p.name: dict(bytes=p.stat().st_size, sha256=T.digest(p)) for p in packet.iterdir()}
        self.write(packet / 'seal.json', seal)
        self.write(packet.parent / 'result.json', dict(status='complete_coverage', translation_units=24,
                   closed_format_facts=report, syntax=[dict(exit_code=0, timed_out=False)] * 24))
        return packet

    def test_round_trip_preserves_final_seal_namespace_and_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            root = base / 'format-facts'
            packet = self.fixture(root)
            seal = (packet / 'seal.json').read_bytes()
            anchor = T.pack(root, base / 'packet.tar')
            root.rename(base / 'producer')
            T.unpack(root, base / 'packet.tar', **anchor)
            self.assertEqual((packet / 'seal.json').read_bytes(), seal)
            self.assertEqual((root / 'tool/bin/compiler').stat().st_mode & 0o777, 0o755)
            T.check_packet(root)

    def test_producer_status_and_types_are_required(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve() / 'format-facts'
            packet = self.fixture(root)
            result_path = packet.parent / 'result.json'
            original = T.read_json(result_path)
            for changes in (dict(status='incomplete'), dict(translation_units=True), dict(syntax=[])):
                self.write(result_path, dict(original, **changes))
                with self.assertRaises(ValueError):
                    T.pack(root, root.parent / 'must-not-exist.tar')
                self.assertFalse((root.parent / 'must-not-exist.tar').exists())

    def test_strict_small_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'input.json'
            for data in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}', '{"x":1e999}'):
                path.write_text(data)
                with self.assertRaises(ValueError):
                    T.read_json(path)

    def test_bad_archive_metadata_is_rejected_before_any_payload_write(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            root = base / 'format-facts'
            archive = base / 'bad.tar'
            for bad_name, kind in (('../escape', tarfile.REGTYPE), ('/absolute', tarfile.REGTYPE),
                                   ('tool/first', tarfile.REGTYPE), ('tool/link', tarfile.SYMTYPE),
                                   ('tool/hard', tarfile.LNKTYPE), ('tool/fifo', tarfile.FIFOTYPE),
                                   ('tool/../escape', tarfile.REGTYPE)):
                with self.subTest(name=bad_name, kind=kind):
                    with tarfile.open(archive, 'w') as output:
                        first = tarfile.TarInfo('tool/first')
                        first.size = 1
                        output.addfile(first, io.BytesIO(b'x'))
                        bad = tarfile.TarInfo(bad_name)
                        bad.type = kind
                        bad.linkname = 'tool/first' if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE) else ''
                        output.addfile(bad)
                    with self.assertRaises(ValueError):
                        T.unpack(root, archive, archive.stat().st_size, T.digest(archive), str(root))
                    self.assertFalse(root.exists())

    def test_external_anchor_and_namespace_are_required(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            root = base / 'format-facts'
            self.fixture(root)
            archive = base / 'packet.tar'
            anchor = T.pack(root, archive)
            for size, sha256, namespace in ((True, anchor['sha256'], str(root)),
                                           (anchor['size'], '0' * 64, str(root)),
                                           (anchor['size'] + 1, anchor['sha256'], str(root)),
                                           (anchor['size'], anchor['sha256'], str(base / 'other'))):
                with self.assertRaises(ValueError):
                    T.unpack(root, archive, size, sha256, namespace)

    def test_changed_seal_or_system_header_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve() / 'format-facts'
            packet = self.fixture(root)
            (root / 'prepared/work-linux-native/header.h').write_text('changed')
            with self.assertRaisesRegex(ValueError, 'system header'):
                T.check_packet(root)
            (packet / 'report.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'seal member'):
                T.check_packet(root)

    def test_tar_byte_and_metadata_bounds_precede_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            root = base / 'format-facts'
            archive = base / 'bad.tar'
            for kind, size, message in ((tarfile.REGTYPE, T.MAX_FILE + 1, 'member byte'),
                                        (tarfile.XHDTYPE, T.MAX_JSON + 1, 'metadata read')):
                header = tarfile.TarInfo('tool/large')
                header.type, header.size = kind, size
                archive.write_bytes(header.tobuf())
                with self.assertRaisesRegex(ValueError, message):
                    T.unpack(root, archive, archive.stat().st_size, T.digest(archive), str(root))
                self.assertFalse(root.exists())

    def test_tar_parent_conflicts_and_total_bounds_precede_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            root = base / 'format-facts'
            archive = base / 'bad.tar'
            with tarfile.open(archive, 'w') as output:
                for name in ('tool/parent', 'tool/parent/child'):
                    member = tarfile.TarInfo(name)
                    member.size = 1
                    output.addfile(member, io.BytesIO(b'x'))
            with self.assertRaisesRegex(ValueError, 'parent kind'):
                T.unpack(root, archive, archive.stat().st_size, T.digest(archive), str(root))
            with patch.object(T, 'MAX_MEMBERS', 1):
                with self.assertRaisesRegex(ValueError, 'total bound'):
                    T.unpack(root, archive, archive.stat().st_size, T.digest(archive), str(root))
            with patch.object(T, 'MAX_TOTAL', 1):
                with self.assertRaisesRegex(ValueError, 'total bound'):
                    T.unpack(root, archive, archive.stat().st_size, T.digest(archive), str(root))
            self.assertFalse(root.exists())

    def test_json_parse_checks_the_same_anchored_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'control.json'
            path.write_text('{"x":1}')
            expected_size, expected_sha = path.stat().st_size, T.digest(path)
            path.write_text('{"x":2}')
            with self.assertRaisesRegex(ValueError, 'parsed JSON external anchor'):
                T.read_json(path, expected_size, expected_sha)

    def test_complete_report_rejects_numeric_boolean_aliases_and_missing_coverage(self):
        report = dict(schema=1, status='complete_coverage', authorization='analysis_only',
                      units=24, symbols=40, incoming_calls=4865, unclassified=5, authentic_job_proof=False)
        T.complete_report(report)
        for changes in (dict(schema=True), dict(units=True), dict(authentic_job_proof=0),
                        dict(status='AnalysisFailure'), dict(incoming_calls=4864)):
            with self.assertRaises(ValueError):
                T.complete_report(dict(report, **changes))


if __name__ == '__main__':
    unittest.main()
