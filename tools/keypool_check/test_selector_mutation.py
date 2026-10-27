"""Cheap checks of the mutation gate; the workflow also runs the real verifier."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import check_selector_mutation as mutation

from check_selector_mutation import GUARD, remove_guard, require_detection


# First complete report through SUMMARY from hosted Linux run 40355765898 and Apple clang.
LINUX_ASAN = """=================================================================
==2680==ERROR: AddressSanitizer: heap-buffer-overflow on address 0x51d000000190 at pc 0x55ad95a68df3 bp 0x7ffe63b84180 sp 0x7ffe63b83928
READ of size 1 at 0x51d000000190 thread T0
    #0 0x55ad95a68df2 in strcmp (/home/runner/work/_temp/keyframe-pool/mutation/keypool_check/keypool_check+0x46df2) (BuildId: 287715f8b4f7f66d8146af82d7c7aefd5c9a8abd)
    #1 0x55ad95b4fc8b in mikudancestudio::RegisterDisplayKeyFromRecord(unsigned char*, int, unsigned char, int, unsigned char const*, int, unsigned char const*, int)::$_0::operator()(int) const /tmp/keypool-selector-w56aagcz/repo/src/model/key_registrars.cpp:739:24
    #2 0x55ad95b4eb8e in mikudancestudio::RegisterDisplayKeyFromRecord(unsigned char*, int, unsigned char, int, unsigned char const*, int, unsigned char const*, int) /tmp/keypool-selector-w56aagcz/repo/src/model/key_registrars.cpp:788:9
    #3 0x55ad95b2fe18 in (anonymous namespace)::Paste((anonymous namespace)::Kind, int, int) /tmp/keypool-selector-w56aagcz/repo/tools/keypool_check/keypool_check.cpp:277:9
    #4 0x55ad95b2fe18 in (anonymous namespace)::Apply((anonymous namespace)::Command const&) /tmp/keypool-selector-w56aagcz/repo/tools/keypool_check/keypool_check.cpp:303:9
    #5 0x55ad95b2fe18 in (anonymous namespace)::Explore(_IO_FILE*) /tmp/keypool-selector-w56aagcz/repo/tools/keypool_check/keypool_check.cpp:676:13
    #6 0x55ad95b2fe18 in main /tmp/keypool-selector-w56aagcz/repo/tools/keypool_check/keypool_check.cpp:776:13
    #7 0x7f46bc62a1c9  (/lib/x86_64-linux-gnu/libc.so.6+0x2a1c9) (BuildId: a4a7992a8e66555c8141ab2a08a8465ff6e0ea65)
    #8 0x7f46bc62a28a in __libc_start_main (/lib/x86_64-linux-gnu/libc.so.6+0x2a28a) (BuildId: a4a7992a8e66555c8141ab2a08a8465ff6e0ea65)
    #9 0x55ad95a505c4 in _start (/home/runner/work/_temp/keyframe-pool/mutation/keypool_check/keypool_check+0x2e5c4) (BuildId: 287715f8b4f7f66d8146af82d7c7aefd5c9a8abd)

0x51d000000190 is located 624 bytes before 1248-byte region [0x51d000000400,0x51d0000008e0)
allocated by thread T0 here:
    #0 0x55ad95b29b51 in operator new[](unsigned long) (/home/runner/work/_temp/keyframe-pool/mutation/keypool_check/keypool_check+0x107b51) (BuildId: 287715f8b4f7f66d8146af82d7c7aefd5c9a8abd)
    #1 0x55ad95b36458 in (anonymous namespace)::BuildModel() /tmp/keypool-selector-w56aagcz/repo/tools/keypool_check/keypool_check.cpp:120:19
    #2 0x7f46bc62a1c9  (/lib/x86_64-linux-gnu/libc.so.6+0x2a1c9) (BuildId: a4a7992a8e66555c8141ab2a08a8465ff6e0ea65)
    #3 0x7f46bc62a28a in __libc_start_main (/lib/x86_64-linux-gnu/libc.so.6+0x2a28a) (BuildId: a4a7992a8e66555c8141ab2a08a8465ff6e0ea65)
    #4 0x55ad95a505c4 in _start (/home/runner/work/_temp/keyframe-pool/mutation/keypool_check/keypool_check+0x2e5c4) (BuildId: 287715f8b4f7f66d8146af82d7c7aefd5c9a8abd)

SUMMARY: AddressSanitizer: heap-buffer-overflow (/home/runner/work/_temp/keyframe-pool/mutation/keypool_check/keypool_check+0x46df2) (BuildId: 287715f8b4f7f66d8146af82d7c7aefd5c9a8abd) in strcmp
"""

MACOS_ASAN = """=================================================================
==96335==ERROR: AddressSanitizer: heap-buffer-overflow on address 0x61d000000b90 at pc 0x000105746f7c bp 0x00016ae446a0 sp 0x00016ae43e38
READ of size 1 at 0x61d000000b90 thread T0
    #0 0x000105746f78 in strcmp+0x47c (libclang_rt.asan_osx_dynamic.dylib:arm64e+0x16f78)
    #1 0x000104fdc324 in mikudancestudio::RegisterDisplayKeyFromRecord(unsigned char*, int, unsigned char, int, unsigned char const*, int, unsigned char const*, int)::$_0::operator()(int) const key_registrars.cpp:738
    #2 0x000104fdb468 in mikudancestudio::RegisterDisplayKeyFromRecord(unsigned char*, int, unsigned char, int, unsigned char const*, int, unsigned char const*, int) key_registrars.cpp:787
    #3 0x000104fbca1c in (anonymous namespace)::Paste((anonymous namespace)::Kind, int, int) keypool_check.cpp:277
    #4 0x000104fbca1c in (anonymous namespace)::Apply((anonymous namespace)::Command const&) keypool_check.cpp:303
    #5 0x000104fbca1c in (anonymous namespace)::Explore(__sFILE*) keypool_check.cpp:676
    #6 0x000104fbca1c in main keypool_check.cpp:776
    #7 0x000195aabe7c in start+0x1a1c (dyld:arm64e+0x31e7c)

0x61d000000b90 is located 400 bytes after 1536-byte region [0x61d000000400,0x61d000000a00)
allocated by thread T0 here:
    #0 0x000105771274 in malloc+0x78 (libclang_rt.asan_osx_dynamic.dylib:arm64e+0x41274)
    #1 0x000195c87db0 in _malloc_type_malloc_outlined+0x40 (libsystem_malloc.dylib:arm64e+0x1edb0)
    #2 0x000195a2a240 in objc::DenseMap<DisguisedPtr<objc_class>, objc::category_list, objc::DenseMapValueInfo<objc::category_list>, objc::DenseMapInfo<DisguisedPtr<objc_class>>, objc::detail::DenseMapPair<DisguisedPtr<objc_class>, objc::category_list>>::init(unsigned int)+0x5c (libobjc.A.dylib:arm64e+0x32240)
    #3 0x0001959f98d4 in _objc_init+0x638 (libobjc.A.dylib:arm64e+0x18d4)
    #4 0x000195cc1784 in _os_object_init+0x14 (libdispatch.dylib:arm64e+0x2784)
    #5 0x000195cf7428 in libdispatch_init+0x1dc (libdispatch.dylib:arm64e+0x38428)
    #6 0x0001a6a93354 in libSystem_initializer+0xf0 (libSystem.B.dylib:arm64e+0x1354)
    #7 0x000195add754 in invocation function for block in dyld4::Loader::findAndRunAllInitializers(dyld4::RuntimeState&) const::$_0::operator()() const+0x164 (dyld:arm64e+0x63754)
    #8 0x000195b11068 in invocation function for block in mach_o::Image::forEachInitializer(void (unsigned int) block_pointer) const+0x50 (dyld:arm64e+0x97068)
    #9 0x000195b08504 in mach_o::Header::SegmentInfo mach_o::Header::parse_segment_command<true>(mach_o::Header::LoadCommandInfo const&, unsigned short, void (mach_o::Header::SegmentInfo const&, mach_o::Header::SectionInfo const&) block_pointer, mach_o::Error*) const+0x240 (dyld:arm64e+0x8e504)
    #10 0x000195b0d970 in invocation function for block in mach_o::Header::forEachSection(void (mach_o::Header::SectionInfo const&, bool&) block_pointer) const+0x98 (dyld:arm64e+0x93970)
    #11 0x000195b07000 in mach_o::Header::forEachLoadCommand(void (mach_o::Header::LoadCommandInfo const&, bool&) block_pointer, mach_o::Error*) const+0xe0 (dyld:arm64e+0x8d000)
    #12 0x000195b0b078 in mach_o::Header::forEachSection(void (mach_o::Header::SectionInfo const&, bool&) block_pointer) const+0x7c (dyld:arm64e+0x91078)
    #13 0x000195b10f98 in mach_o::Image::forEachInitializer(void (unsigned int) block_pointer) const+0xf0 (dyld:arm64e+0x96f98)
    #14 0x000195ad8610 in dyld4::Loader::findAndRunAllInitializers(dyld4::RuntimeState&) const+0x2a4 (dyld:arm64e+0x5e610)
    #15 0x000195ae05a4 in dyld4::PrebuiltLoader::runInitializers(dyld4::RuntimeState&) const+0x28 (dyld:arm64e+0x665a4)
    #16 0x000195aa0e2c in dyld4::APIs::runAllInitializersForMain()+0x60 (dyld:arm64e+0x26e2c)
    #17 0x000195aadd10 in dyld4::prepare(dyld4::APIs&, mach_o::UnsafeHeader const*)+0x1270 (dyld:arm64e+0x33d10)
    #18 0x000195aaca80 in dyld4::start(dyld4::KernelArgs*, void*, void*, unsigned long long)::$_1::operator()() const+0x13c (dyld:arm64e+0x32a80)
    #19 0x000195aabe20 in start+0x19c0 (dyld:arm64e+0x31e20)

SUMMARY: AddressSanitizer: heap-buffer-overflow key_registrars.cpp:738 in mikudancestudio::RegisterDisplayKeyFromRecord(unsigned char*, int, unsigned char, int, unsigned char const*, int, unsigned char const*, int)::$_0::operator()(int) const
"""

class SelectorMutationTest(unittest.TestCase):
    def test_changes_exactly_one_guard(self):
        self.assertEqual(remove_guard("before\n" + GUARD + "after\n"), "before\nafter\n")
        for source in ("no guard", GUARD + GUARD):
            with self.assertRaises(ValueError):
                remove_guard(source)

    def test_requires_the_real_failure(self):
        log = "VIOLATION: invalid memory access\n1. paste display key at frame 0"
        asan = LINUX_ASAN
        for report in (LINUX_ASAN, MACOS_ASAN):
            require_detection(1, log, report)
        for status, stdout, stderr in (
            (0, log, asan), (2, log, asan), (-11, log, asan),
            (1, "compiler error", asan), (1, log, ""),
            (1, log, asan.replace("key_registrars.cpp", "unrelated.cpp")),
            (1, log, asan.replace("heap-buffer-overflow", "SEGV")),
            (1, log, asan.replace("RegisterDisplayKeyFromRecord", "UnrelatedFunction")),
            (1, log, asan.replace("key_registrars.cpp", "other_key_registrars.cpp")),
            (1, log, asan.split("SUMMARY:")[0]),
            (1, log, asan[asan.index("SUMMARY:"):]),
            (1, log, asan.replace("==2680==ERROR: AddressSanitizer:", "compiler error:")),
            (1, log, asan.replace("ERROR: AddressSanitizer: heap-buffer-overflow", "ERROR: AddressSanitizer: SEGV")),
            (1, log, asan.replace("SUMMARY: AddressSanitizer: heap-buffer-overflow", "SUMMARY: AddressSanitizer: SEGV")),
        ):
            with self.subTest(status=status, stdout=stdout, stderr=stderr):
                with self.assertRaises(ValueError):
                    require_detection(status, stdout, stderr)

    def test_does_not_mix_reports_or_allocation_stack(self):
        log = "VIOLATION: paste display key at frame 0"
        partial = LINUX_ASAN.split("SUMMARY:")[0]
        unrelated = LINUX_ASAN.replace("key_registrars.cpp", "unrelated.cpp")
        wrong_kind = LINUX_ASAN.replace("heap-buffer-overflow", "SEGV")
        allocation_only = (
            unrelated.split("\n\n", 1)[0] + "\n\nallocated by thread T0 here:\n"
            + LINUX_ASAN.splitlines()[4] + "\n\n"
            + LINUX_ASAN[LINUX_ASAN.index("SUMMARY:"):]
        )
        for reports in (
            partial + unrelated,
            partial + wrong_kind,
            wrong_kind + unrelated,
            LINUX_ASAN.replace("ERROR: AddressSanitizer: heap-buffer-overflow", "ERROR: AddressSanitizer: SEGV") + unrelated,
            allocation_only,
        ):
            with self.subTest(reports=reports):
                with self.assertRaises(ValueError):
                    require_detection(1, log, reports)

    def test_disposable_copy_preserves_checkout_on_success_and_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            for directory in ("include", "src/model", "tools/keypool_check", "rust/crates/mds-math/src"):
                (root / directory).mkdir(parents=True)
            source = root / "src/model/key_registrars.cpp"
            source.write_text(GUARD)
            (root / "rust/crates/mds-math/src/estimate_table.rs").write_text("fixture")
            runner = root / "tools/keypool_check/run.sh"
            artifacts = Path(temporary) / "artifacts"
            for status in (1, 2):
                runner.write_text("""#!/bin/sh
set -eu
root=$(cd "$(dirname "$0")/../.." && pwd)
if grep -q continue "$root/src/model/key_registrars.cpp"; then exit 3; fi
mkdir -p "$TMPDIR/keypool_check"
cat > "$TMPDIR/keypool_check/asan.log" <<'ASAN'
""" + LINUX_ASAN + """ASAN
echo 'VIOLATION: paste display key at frame 0'
exit """ + str(status) + "\n")
                checkout = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
                with patch.object(mutation, "__file__", str(root / "tools/keypool_check/check_selector_mutation.py")), patch(
                    "sys.argv", ["check_selector_mutation.py", str(artifacts)]
                ):
                    if status == 1:
                        mutation.main()
                    else:
                        with self.assertRaises(ValueError):
                            mutation.main()
                self.assertEqual(source.read_text(), GUARD)
                self.assertEqual(
                    {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}, checkout
                )
                self.assertEqual((artifacts / "mutation-exit.txt").read_text(), f"{status}\n")


if __name__ == "__main__":
    unittest.main()
