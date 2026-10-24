//! Builds the vendored Bullet 2.75 and the C shim into one static library.
//!
//! Environment variables:
//! - `MDS_BT_SYSTEM_MATH=1` drops `shim/det_math.h`, so Bullet calls the
//!   platform libm. The result then differs between platforms; this exists to
//!   measure that difference (RM-7 lane 6).
//! - `MDS_BT_ASAN=1` builds the C++ side with `-fsanitize=address` (clang).
//!   A dependent binary must then link the ASan runtime, which a build script
//!   cannot request for its dependents. On macOS rustc links with
//!   `-nodefaultlibs`, which makes `-C link-arg=-fsanitize=address` miss the
//!   runtime, so name the dylib and its rpath instead:
//!   `RT=$(clang -print-resource-dir)/lib/darwin`
//!   `MDS_BT_ASAN=1 RUSTFLAGS="-C link-arg=$RT/libclang_rt.asan_osx_dynamic.dylib -C link-arg=-Wl,-rpath,$RT" cargo test --release`
//!   Only the macOS recipe is verified; `-C link-arg=-fsanitize=address` alone
//!   does not link on Linux either, because rustc passes `-nodefaultlibs`.
//! - Cargo feature `bench` also builds `shim/bench_main.cpp` into
//!   `<target>/<profile>/chain8_bench`.
//!
//! Non-MSVC builds need clang: the vendored sources use `__declspec`, which
//! only clang accepts through `-fdeclspec`. Set `CXX=clang++` where `c++` is gcc.

use std::env;
use std::fs;
use std::path::{Path, PathBuf};

const BULLET_DIRS: [&str; 3] = ["LinearMath", "BulletCollision", "BulletDynamics"];

fn collect_cpp(dir: &Path, out: &mut Vec<PathBuf>) {
    let entries =
        fs::read_dir(dir).unwrap_or_else(|e| panic!("cannot read {}: {e}", dir.display()));
    for entry in entries {
        let path = entry.expect("directory entry").path();
        if path.is_dir() {
            collect_cpp(&path, out);
        } else if path.extension().is_some_and(|e| e == "cpp") {
            out.push(path);
        }
    }
}

fn flag_set(name: &str) -> bool {
    println!("cargo:rerun-if-env-changed={name}");
    env::var(name).is_ok_and(|v| v == "1")
}

fn main() {
    let manifest = PathBuf::from(env::var("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR"));
    let shim = manifest.join("shim");
    // rust/crates/mds-bullet-sys -> repository root
    let src = manifest.join("../../../recipes/bullet275/bullet-src/src");
    assert!(
        src.is_dir(),
        "Bullet sources not found at {}",
        src.display()
    );

    let mut files = Vec::new();
    for d in BULLET_DIRS {
        collect_cpp(&src.join(d), &mut files);
    }
    files.sort();
    files.push(shim.join("mds_bt.cpp"));

    let system_math = flag_set("MDS_BT_SYSTEM_MATH");
    let asan = flag_set("MDS_BT_ASAN");
    let det_math = shim.join("det_math.h");

    let mut build = cc::Build::new();
    build
        .cpp(true)
        .opt_level(2)
        .debug(asan)
        .warnings(false)
        .include(&src)
        .include(&shim)
        .files(&files);

    let tool = build.get_compiler();
    if tool.is_like_msvc() {
        build.flag("/fp:precise").flag("/EHsc").flag("/W0");
        if !system_math {
            build.flag(format!("/FI{}", det_math.display()));
        }
    } else if tool.is_like_clang() {
        build
            .flag("-ffp-contract=off")
            .flag("-fno-fast-math")
            .flag("-fdeclspec")
            .flag("-w");
        if !system_math {
            build
                .flag("-include")
                .flag(det_math.to_str().expect("utf-8 path"));
        }
        if asan {
            build
                .flag("-fsanitize=address")
                .flag("-fno-omit-frame-pointer")
                .flag("-g");
        }
    } else {
        panic!(
            "mds-bullet-sys needs clang or MSVC; set CXX=clang++ (found {:?})",
            tool.path()
        );
    }

    build.compile("mds_bullet_sys");

    if env::var_os("CARGO_FEATURE_BENCH").is_some() {
        build_bench(&build, &shim);
    }

    println!("cargo:rerun-if-changed=build.rs");
    println!("cargo:rerun-if-changed=shim");
    println!("cargo:rerun-if-changed={}", src.display());
}

fn build_bench(build: &cc::Build, shim: &Path) {
    let tool = build.get_compiler();
    if tool.is_like_msvc() {
        println!(
            "cargo:warning=feature `bench` is not supported with MSVC; chain8_bench not built"
        );
        return;
    }
    let out_dir = PathBuf::from(env::var("OUT_DIR").expect("OUT_DIR"));
    let exe = out_dir.join("chain8_bench");
    let status = tool
        .to_command()
        .arg(shim.join("bench_main.cpp"))
        .arg(out_dir.join("libmds_bullet_sys.a"))
        .arg("-o")
        .arg(&exe)
        .status()
        .expect("run C++ compiler for chain8_bench");
    assert!(status.success(), "building chain8_bench failed");
    // <target>/<profile>/build/<pkg>-<hash>/out -> <target>/<profile>
    let profile_dir = out_dir.ancestors().nth(3).expect("profile dir");
    fs::copy(&exe, profile_dir.join("chain8_bench")).expect("copy chain8_bench");
}
