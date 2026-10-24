fn main() {
    let dir = std::env::var("BT_LIB_DIR").expect("BT_LIB_DIR");
    println!("cargo:rustc-link-search=native={dir}");
    println!("cargo:rustc-link-lib=static=btshim");
    let cxx = if cfg!(target_os = "macos") { "c++" } else { "stdc++" };
    println!("cargo:rustc-link-lib=dylib={cxx}");
    println!("cargo:rerun-if-env-changed=BT_LIB_DIR");
}
