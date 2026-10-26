#!/usr/bin/env python3
"""Probe an already configured vkd3d tree without changing the input tree.

Translated sources retain vkd3d's LGPL-2.1-or-later terms; this script does
not grant a different license to them. Build artifacts belong outside Git.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess


def run(command, log, **kwargs):
    with log.open("w") as output:
        try:
            result = subprocess.run(command, stdout=output, stderr=subprocess.STDOUT, **kwargs)
        except subprocess.TimeoutExpired:
            return {"command": command, "exit_code": 124, "log": str(log), "timed_out": True}
    return {"command": command, "exit_code": result.returncode, "log": str(log)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--c2rust", type=Path, required=True)
    parser.add_argument("--clang", type=Path, required=True)
    parser.add_argument("--filter", help="Regular expression selecting C translation units")
    parser.add_argument("--timeout", type=int, default=300, help="Seconds per tool invocation")
    args = parser.parse_args()
    original = args.source.resolve()
    artifacts = args.artifacts.resolve()
    if artifacts == original or original in artifacts.parents:
        parser.error("artifacts must be outside the source tree")
    artifacts.mkdir(parents=True, exist_ok=True)
    source = artifacts / "source"
    # Refuse reuse so old Rust files cannot make a failed translation look complete.
    shutil.copytree(original, source)
    sources = sorted((source / "libs/vkd3d-shader").glob("*.c"))
    sources += sorted((source / "libs/vkd3d-common").glob("*.c"))
    required = {"hlsl.tab.c", "hlsl.yy.c", "hlsl.c", "vkd3d_shader_main.c", "debug.c"}
    assert required <= {p.name for p in sources}
    if args.filter:
        sources = [p for p in sources if re.search(args.filter, str(p))]
        if not sources:
            parser.error("filter matched no C sources")
    entries = []
    for path in sources:
        flags = ["-DHAVE_CONFIG_H", "-D_WIN32_WINNT=0x0600", "-std=c99"]
        flags += ["-I" + str(source / p) for p in (".", "include", "include/private", "libs/vkd3d-shader")]
        flags += ["-I" + str(original.parent / p / "include") for p in ("hdr", "spv")]
        if path.parent.name == "vkd3d-shader":
            flags += ["-DLIBVKD3D_SHADER_SOURCE", "-DVKD3D_DEBUG_ENV=VKD3D_SHADER_DEBUG"]
        entries.append({"directory": str(source), "file": str(path),
                        "arguments": [str(args.clang.resolve()), *flags, "-c", str(path)]})
    database = artifacts / "compile_commands.json"
    database.write_text(json.dumps(entries, indent=2) + "\n")
    result = {"source": str(original), "translation_units": len(sources),
              "input_sha256": {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in sources}}
    result["syntax"] = []
    for index, entry in enumerate(entries):
        command = entry["arguments"][:-2] + ["-fsyntax-only", entry["file"]]
        result["syntax"].append(run(command, artifacts / f"syntax-{index:02}.log", cwd=source, timeout=args.timeout))
    output = artifacts / "rust"
    transpiler = args.c2rust.resolve().with_name("c2rust-transpile")
    result["transpile"] = run([str(transpiler), "--fail-on-error", "--disable-rustfmt", "--edition", "2024",
                               "--emit-build-files", "--output-dir", str(output), str(database)],
                              artifacts / "transpile.log", cwd=source, timeout=args.timeout)
    shutil.copy2(source / "LICENSE", artifacts / "VKD3D-LICENSE")
    result["translated_sources"] = []
    for path in sources:
        matches = list(output.rglob(path.stem.replace(".", "_") + ".rs"))
        if len(matches) == 1:
            translated = matches[0]
            text = path.read_text()
            notices = [comment for comment in re.findall(r'/\*.*?\*/', text, re.S)
                       if re.search(r'copyright|general public license|special exception', comment, re.I)]
            assert notices, f"No license notice found in {path}"
            translated.write_text("\n".join(notices) + "\n" + translated.read_text())
            result["translated_sources"].append(str(path.relative_to(source)))
    result["complete_translation"] = (result["transpile"]["exit_code"] == 0
                                      and len(result["translated_sources"]) == len(sources))
    checksum = list(output.rglob("checksum.rs"))
    if len(checksum) == 1:
        module = '#[allow(dead_code, non_camel_case_types, non_upper_case_globals, unused_mut)]\n'
        module += '#[path = ' + json.dumps(str(checksum[0])) + '] pub mod checksum;\n'
        no_std = artifacts / "checksum_no_std.rs"
        no_std.write_text("#![no_std]\n" + module)
        result["checksum_no_std"] = run(["rustc", "+stable", "--edition", "2024", "--crate-type", "rlib",
                                        str(no_std), "-o", str(artifacts / "checksum_no_std.rlib")],
                                       artifacts / "checksum-no-std.log", timeout=args.timeout)
        checks = []
        for data in (b"", b"abc", b"a" * 55, b"a" * 56, b"a" * 64, b"a" * 1000):
            checks.append(f"check(&{list(data)}, &{list(hashlib.md5(data).digest())});")
        harness = artifacts / "checksum_check.rs"
        harness.write_text(module + '''
fn check(data: &[u8], expected: &[u8]) {
    let mut digest = [0u32; 4];
    unsafe { checksum::vkd3d_compute_md5(data.as_ptr().cast(), data.len(),
        digest.as_mut_ptr(), checksum::vkd3d_md5_variant::VKD3D_MD5_STANDARD); }
    let bytes: Vec<u8> = digest.iter().flat_map(|x| x.to_ne_bytes()).collect();
    assert_eq!(bytes, expected);
}
fn main() {''' + "".join(checks) + 'println!("6 MD5 vectors passed");}\n')
        binary = artifacts / "checksum_check"
        result["checksum_check_build"] = run(["rustc", "+stable", "--edition", "2024", str(harness), "-o", str(binary)],
                                              artifacts / "checksum-check-build.log", timeout=args.timeout)
        if result["checksum_check_build"]["exit_code"] == 0:
            result["checksum_check_run"] = run([str(binary)], artifacts / "checksum-check-run.log", timeout=args.timeout)
    result["rust_files"] = [str(p.relative_to(output)) for p in sorted(output.rglob("*.rs"))]
    declared, defined = set(), set()
    for path in output.rglob("*.rs"):
        text = path.read_text()
        for block in re.findall(r'(?:unsafe )?extern "C" \{(.*?)^\}', text, re.M | re.S):
            declared.update(re.findall(r'\bfn (\w+)', block))
            declared.update(re.findall(r'\bstatic (?:mut )?(\w+)', block))
        defined.update(re.findall(r'(?:unsafe )?extern "C" fn (\w+)', text))
    inventory = {"declared": sorted(declared), "defined": sorted(defined),
                 "unresolved_declared": sorted(declared - defined)}
    (artifacts / "externs.json").write_text(json.dumps(inventory, indent=2) + "\n")
    if (output / "Cargo.toml").exists():
        shutil.copy2(source / "LICENSE", output / "LICENSE")
        manifest = output / "Cargo.toml"
        manifest.write_text(manifest.read_text().replace("[package]", '[package]\nlicense = "LGPL-2.1-or-later"'))
        env = dict(os.environ, CARGO_TARGET_DIR=str(artifacts / "rust-target"))
        result["stable_build"] = run(["cargo", "+stable", "build", "--manifest-path", str(output / "Cargo.toml")],
                                      artifacts / "cargo-stable.log", env=env, timeout=args.timeout)
        if result["stable_build"]["exit_code"]:
            # Toolchain experiment only; never recommend bootstrap for production.
            env["RUSTC_BOOTSTRAP"] = "1"
            result["bootstrap_build"] = run(["cargo", "+stable", "build", "--manifest-path", str(output / "Cargo.toml")],
                                             artifacts / "cargo-bootstrap.log", env=env, timeout=args.timeout)
            if result["bootstrap_build"]["exit_code"]:
                result["prototype_flags"] = "-Zcrate-attr=feature(stmt_expr_attributes) -Astatic_mut_refs"
                env["RUSTFLAGS"] = result["prototype_flags"]
                result["prototype_build"] = run(["cargo", "+stable", "build", "--manifest-path", str(manifest)],
                                                 artifacts / "cargo-prototype.log", env=env, timeout=args.timeout)
    (artifacts / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k not in ("input_sha256", "syntax")}, indent=2))


if __name__ == "__main__":
    main()
