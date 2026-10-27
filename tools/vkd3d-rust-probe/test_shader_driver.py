"""Exercise the actual driver executable with a safe mock compile/free ABI."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


MOCK = r'''
use std::ffi::{c_char, c_void};
#[repr(C)]
pub struct Code { code: *const c_void, size: usize }
#[unsafe(no_mangle)]
pub unsafe extern "C" fn vkd3d_shader_compile(
    _: *const c_void, out: *mut Code, messages: *mut *mut c_char,
) -> i32 {
    unsafe {
        *out = Code { code: b"sentinel".as_ptr().cast(), size: 8 };
        *messages = c"matrix.hlsl: E2004: rejected".as_ptr().cast_mut();
    }
    std::env::var("MOCK_RESULT").unwrap().parse().unwrap()
}
fn record(kind: &str) {
    use std::io::Write;
    let mut file = std::fs::OpenOptions::new().create(true).append(true)
        .open(std::env::var("MOCK_FREES").unwrap()).unwrap();
    writeln!(file, "{kind}").unwrap();
}
#[unsafe(no_mangle)]
pub extern "C" fn vkd3d_shader_free_shader_code(_: *mut Code) { record("code"); }
#[unsafe(no_mangle)]
pub extern "C" fn vkd3d_shader_free_messages(_: *mut c_char) { record("messages"); }
'''


class ShaderDriverTest(unittest.TestCase):
    def test_compile_output_ownership(self):
        with tempfile.TemporaryDirectory(prefix='shader-driver-ユニコード-') as directory:
            root = Path(directory)
            mock = root / 'mock.rs'
            mock.write_text(MOCK)
            archive = root / ('mock.lib' if os.name == 'nt' else 'libmock.a')
            driver = root / ('shader-driver.exe' if os.name == 'nt' else 'shader-driver')
            rustc = ['rustc', '+1.95.0', '--edition', '2024']
            subprocess.run(rustc + ['--crate-type', 'staticlib', str(mock), '-o', str(archive)], check=True)
            subprocess.run(rustc + [str(Path(__file__).with_name('shader_driver.rs')),
                                   '-L', str(root), '-l', 'static=mock', '-o', str(driver)], check=True)
            source = root / 'source.hlsl'
            source.write_text('mock source')
            library = root / ('mock.dll' if os.name == 'nt' else 'libmock.dylib' if sys.platform == 'darwin' else 'libmock.so')
            subprocess.run(rustc + ['--crate-type', 'cdylib', str(mock), '-o', str(library)], check=True)
            native_driver = root / ('native-driver.exe' if os.name == 'nt' else 'native-driver')
            subprocess.run(rustc + ['--cfg', 'native_only', str(Path(__file__).with_name('shader_driver.rs')),
                                   '-o', str(native_driver)], check=True)
            for executable, mode in [(driver, '-'), (driver, str(library)), (native_driver, str(library))]:
                for result in [-4, 0]:
                    with self.subTest(result=result, mode=mode, executable=executable):
                        output = root / f'output-{executable.name}-{mode == "-"}-{result}'
                        frees = root / f'frees-{executable.name}-{mode == "-"}-{result}'
                        env = {**os.environ, 'MOCK_RESULT': str(result), 'MOCK_FREES': str(frees)}
                        completed = subprocess.run([str(executable), str(source), 'ps_3_0', '1', str(output), mode], env=env)
                        self.assertEqual(completed.returncode, 0)
                        self.assertEqual(Path(str(output) + '.status').read_text(), str(result))
                        self.assertEqual(Path(str(output) + '.diagnostics').read_bytes(), b'matrix.hlsl: E2004: rejected')
                        self.assertEqual(output.read_bytes(), b'' if result < 0 else b'sentinel')
                        self.assertEqual(frees.read_text().splitlines(), ['messages'] if result < 0 else ['code', 'messages'])
                        if mode != '-':
                            modules = Path(str(output) + '.modules').read_text(encoding='utf-8').splitlines()
                            self.assertIn(library.resolve(), [Path(path).resolve() for path in modules])
            for mode in ['-', str(root / 'missing.dll')]:
                completed = subprocess.run([str(native_driver), str(source), 'ps_3_0', '1',
                                            str(root / 'rejected'), mode], capture_output=True)
                self.assertNotEqual(completed.returncode, 0)
                self.assertFalse((root / 'rejected').exists())
            if os.name == 'nt':
                completed = subprocess.run([str(native_driver), str(source), 'ps_3_0', '1',
                                            str(root / 'rejected'), library.name], capture_output=True)
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn(b'native DLL path must be absolute', completed.stderr)
            incomplete = root / 'incomplete.rs'
            incomplete.write_text(MOCK.replace('fn vkd3d_shader_free_messages', 'fn other_free_messages'))
            missing_api = root / library.name.replace('mock', 'missing-api')
            subprocess.run(rustc + ['--crate-type', 'cdylib', str(incomplete), '-o', str(missing_api)], check=True)
            completed = subprocess.run([str(native_driver), str(source), 'ps_3_0', '1',
                                        str(root / 'rejected'), str(missing_api)], capture_output=True)
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn(b'native API missing', completed.stderr)


if __name__ == '__main__':
    unittest.main()
