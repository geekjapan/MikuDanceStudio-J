use std::process::Command;

#[test]
fn an_option_in_place_of_a_file_prints_the_usage() {
    for args in [
        &["roundtrip", "--help"][..],
        &["inspect", "-h"],
        &["roundtrip", "--out", "x"],
    ] {
        let out = Command::new(env!("CARGO_BIN_EXE_mds-formats"))
            .args(args)
            .output()
            .unwrap();
        let stderr = String::from_utf8_lossy(&out.stderr);
        assert_eq!(out.status.code(), Some(2), "{args:?}");
        assert!(
            stderr.contains("usage: mds-formats roundtrip"),
            "{args:?}: {stderr}"
        );
    }
}
