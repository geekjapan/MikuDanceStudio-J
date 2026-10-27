"""Exercise the actual driver executable with a safe mock compile/free ABI."""
import os
from pathlib import Path
import subprocess
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
        with tempfile.TemporaryDirectory(prefix='shader-driver-') as directory:
            root = Path(directory)
            mock = root / 'mock.rs'
            mock.write_text(MOCK)
            archive = root / 'libmock.a'
            driver = root / 'shader-driver'
            rustc = ['rustc', '+1.95.0', '--edition', '2024']
            subprocess.run(rustc + ['--crate-type', 'staticlib', str(mock), '-o', str(archive)], check=True)
            subprocess.run(rustc + [str(Path(__file__).with_name('shader_driver.rs')),
                                   '-L', str(root), '-l', 'static=mock', '-o', str(driver)], check=True)
            source = root / 'source.hlsl'
            source.write_text('mock source')
            for result in [-4, 0]:
                with self.subTest(result=result):
                    output = root / f'output-{result}'
                    frees = root / f'frees-{result}'
                    env = {**os.environ, 'MOCK_RESULT': str(result), 'MOCK_FREES': str(frees)}
                    completed = subprocess.run([str(driver), str(source), 'ps_3_0', '1', str(output), '-'], env=env)
                    self.assertEqual(completed.returncode, 0)
                    self.assertEqual(Path(str(output) + '.status').read_text(), str(result))
                    self.assertEqual(Path(str(output) + '.diagnostics').read_bytes(), b'matrix.hlsl: E2004: rejected')
                    self.assertEqual(output.read_bytes(), b'' if result < 0 else b'sentinel')
                    self.assertEqual(frees.read_text().splitlines(), ['messages'] if result < 0 else ['code', 'messages'])


if __name__ == '__main__':
    unittest.main()
