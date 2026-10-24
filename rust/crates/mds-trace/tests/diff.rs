use mds_trace::format::parse_hex_float;
use mds_trace::{diff, Difference, Error};
use std::path::PathBuf;
use std::process::Command;

const BASE: &str = "mds-trace 1 L1\n\
0 bone 0 0x0p+0 0x1p+0 -0x1.8p-1\n\
0 morph 2 0x1.99999ap-4\n\
1 bone 0 0x1p-1074 0x1.fffffffffffffp+1023 inf\n";

fn run(a: &str, b: &str) -> Result<Option<Difference>, Error> {
    diff(a.as_bytes(), b.as_bytes())
}

#[test]
fn identical() {
    assert_eq!(run(BASE, BASE).unwrap(), None);
}

#[test]
fn identical_with_other_spelling_of_the_same_bits() {
    let b = BASE.replace("0x1p+0 ", "0x1.0000000000000p+0 ");
    assert_eq!(run(BASE, &b).unwrap(), None);
}

#[test]
fn first_difference_names_frame_track_field_and_values() {
    // Two differences: only the first one (frame 0 morph 2) is reported.
    let b = BASE
        .replace("0x1.99999ap-4", "0x1.99999bp-4")
        .replace("inf", "-inf");
    let d = run(BASE, &b).unwrap().unwrap();
    assert_eq!(
        d.to_string(),
        "frame 0 track morph/2 field f0: a=0x1.99999ap-4 b=0x1.99999bp-4"
    );
}

#[test]
fn signed_zero_and_nan_payload_differ() {
    let a = "mds-trace 1 L1\n0 bone 0 0x0p+0 nan\n";
    let neg_zero = a.replace("0x0p+0", "-0x0p+0");
    assert!(matches!(
        run(a, &neg_zero).unwrap(),
        Some(Difference::Field { field: 0, .. })
    ));
    let payload = a.replace("nan", "nan(0x8000000000001)");
    assert!(matches!(
        run(a, &payload).unwrap(),
        Some(Difference::Field { field: 1, .. })
    ));
}

#[test]
fn track_order_field_count_level_and_length() {
    let other_track = BASE.replace("0 morph 2", "0 morph 3");
    assert!(matches!(
        run(BASE, &other_track).unwrap(),
        Some(Difference::Track { line: 3, .. })
    ));
    let short = BASE.replace(" -0x1.8p-1", "");
    assert!(matches!(
        run(BASE, &short).unwrap(),
        Some(Difference::FieldCount { .. })
    ));
    let l2 = BASE.replace("L1", "L2");
    assert!(matches!(
        run(BASE, &l2).unwrap(),
        Some(Difference::Level { .. })
    ));
    let cut = BASE.lines().take(2).collect::<Vec<_>>().join("\n") + "\n";
    assert_eq!(
        run(BASE, &cut).unwrap(),
        Some(Difference::Length {
            line: 3,
            a_ended: false
        })
    );
}

fn parse_err(a: &str) -> (usize, &'static str) {
    match run(a, BASE) {
        Err(Error::Parse { line, msg, .. }) => (line, msg),
        other => panic!("expected a parse error, got {other:?}"),
    }
}

#[test]
fn bad_header() {
    for h in [
        "",
        "mds-trace 2 L1\n",
        "mds-trace 1 L3\n",
        "trace 1 L1\n",
        "mds-trace 1 L1 x\n",
    ] {
        assert_eq!(parse_err(h).0, 1, "header {h:?}");
    }
}

#[test]
fn truncated_line() {
    // Cut inside a hex float, at a token boundary, and mid-token without a newline.
    for cut in ["0 bone 0 0x1p", "0 bone 0 0x1p+0 0x", "0 bone", "0 bone 0"] {
        let (line, _) = parse_err(&format!("mds-trace 1 L1\n{cut}\n"));
        assert_eq!(line, 2, "{cut:?}");
    }
    let (line, msg) = parse_err("mds-trace 1 L1\n0 bone 0 0x1p+0");
    assert_eq!((line, msg), (2, "truncated line (no newline at end)"));
}

#[test]
fn parse_error_does_not_echo_the_content() {
    let e = run("mds-trace 1 L1\nSECRET-TOKEN\n", BASE).unwrap_err();
    assert!(!e.to_string().contains("SECRET"));
}

#[test]
fn hex_float_bits() {
    assert_eq!(parse_hex_float("0x1p+0"), Ok(1f64.to_bits()));
    assert_eq!(parse_hex_float("-0x1.8p+1"), Ok((-3f64).to_bits()));
    assert_eq!(parse_hex_float("-0x0p+0"), Ok((-0f64).to_bits()));
    assert_eq!(parse_hex_float("0x0.0000000000001p-1022"), Ok(1));
    assert_eq!(
        parse_hex_float("0x1p-1022"),
        Ok(f64::MIN_POSITIVE.to_bits())
    );
    assert_eq!(
        parse_hex_float("0x1.fffffffffffffp+1023"),
        Ok(f64::MAX.to_bits())
    );
    assert_eq!(parse_hex_float("-inf"), Ok(f64::NEG_INFINITY.to_bits()));
    assert_eq!(parse_hex_float("nan"), Ok(f64::NAN.to_bits() & !(1 << 63)));
    assert_eq!(parse_hex_float("0x10p-4"), Ok(1f64.to_bits()));
    for bad in [
        "",
        "0x",
        "0x1",
        "0x1p",
        "0x1p+",
        "0x.p+0",
        "1.0",
        "0x1.8p+1x",
        "0x1p+0 ",
        "+0x1p+0",
        "nan(0x0)",
        "0x1p+1024",
        "0x1.00000000000001p+0",
        "0x1p-1075",
    ] {
        assert!(parse_hex_float(bad).is_err(), "{bad:?}");
    }
}

fn tmp(name: &str, body: &str) -> PathBuf {
    let p = PathBuf::from(env!("CARGO_TARGET_TMPDIR")).join(name);
    std::fs::write(&p, body).unwrap();
    p
}

fn exit_code(a: &PathBuf, b: &PathBuf) -> (i32, String, String) {
    let o = Command::new(env!("CARGO_BIN_EXE_mds-trace-diff"))
        .arg(a)
        .arg(b)
        .output()
        .unwrap();
    (
        o.status.code().unwrap(),
        String::from_utf8_lossy(&o.stdout).into_owned(),
        String::from_utf8_lossy(&o.stderr).into_owned(),
    )
}

#[test]
fn binary_exit_codes() {
    let a = tmp("a.trace", BASE);
    assert_eq!(exit_code(&a, &tmp("a2.trace", BASE)).0, 0);

    let changed = tmp("c.trace", &BASE.replace("0x1.99999ap-4", "0x1.99999bp-4"));
    let (code, out, _) = exit_code(&a, &changed);
    assert_eq!(code, 1);
    assert!(out.contains("frame 0 track morph/2 field f0"), "{out}");

    let cut = tmp("cut.trace", "mds-trace 1 L1\n0 bone 0 0x0p");
    let (code, _, err) = exit_code(&a, &cut);
    assert_eq!(code, 2);
    assert!(err.contains("line 2"), "{err}");

    assert_eq!(exit_code(&a, &PathBuf::from("/nonexistent/x.trace")).0, 2);
    let o = Command::new(env!("CARGO_BIN_EXE_mds-trace-diff"))
        .output()
        .unwrap();
    assert_eq!(o.status.code(), Some(2));
}
