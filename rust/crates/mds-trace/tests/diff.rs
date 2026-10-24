use mds_trace::format::parse_hex_float;
use mds_trace::{diff, Difference, Error};
use std::path::PathBuf;
use std::process::Command;

const BASE: &str = "mds-trace 1 L1\n\
0 bone 0 3 0x0p+0 0x1p+0 -0x1.8p-1 0x0p+0 0x1p-1074 0x1.fffffffffffffp+1023 0x1p+0\n\
0 morph 1 2 0x1.99999ap-4\n\
0 camera 0x0p+0 0x1.4p+3 0x0p+0 0x0p+0 0x1.4p+3 0x0p+0 -0x1.68p+5 0x1.ep+4\n\
0 light 0x1p-1 0x1p-1 0x1p-1 -0x1p-1 -0x1p+0 0x1p-1\n\
1 bone 0 3 0x0p+0 0x1p+0 -0x1.8p-1 0x0p+0 0x0p+0 0x0p+0 0x1p+0\n";

const REAL: &str = include_str!("l1-macos.trace");

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
    // Two differences: only the first one (frame 0 morph 1/2) is reported.
    let b = BASE
        .replace("0x1.99999ap-4", "0x1.99999bp-4")
        .replace("0x1.68p+5", "0x1.69p+5");
    let d = run(BASE, &b).unwrap().unwrap();
    assert_eq!(
        d.to_string(),
        "frame 0 track morph 1/2 field weight: a=0x1.99999ap-4 b=0x1.99999bp-4"
    );
}

#[test]
fn field_names_of_every_kind() {
    // Change the last field of each line and read the name back.
    for (line, name) in [
        ("0 bone 0 3", "rw"),
        ("0 morph 1 2", "weight"),
        ("0 camera", "fov"),
        ("0 light", "dz"),
    ] {
        let b = BASE
            .lines()
            .map(|l| {
                if l.starts_with(line) {
                    format!("{} 0x1.7p+9", l.rsplit_once(' ').unwrap().0)
                } else {
                    l.to_owned()
                }
            })
            .collect::<Vec<_>>()
            .join("\n")
            + "\n";
        let msg = run(BASE, &b).unwrap().unwrap().to_string();
        assert!(msg.contains(&format!("field {name}:")), "{msg}");
    }
}

#[test]
fn track_is_kind_plus_indices() {
    let b = BASE.replacen("0 bone 0 3", "0 bone 0 4", 1);
    assert_eq!(
        run(BASE, &b).unwrap().unwrap().to_string(),
        "line 2: track differs: a=frame 0 bone 0/3 b=frame 0 bone 0/4"
    );
    let b = BASE.replace("0 camera", "1 camera");
    assert_eq!(
        run(BASE, &b).unwrap().unwrap().to_string(),
        "line 4: track differs: a=frame 0 camera b=frame 1 camera"
    );
}

#[test]
fn signed_zero_differs() {
    let neg = BASE.replacen("0 bone 0 3 0x0p+0", "0 bone 0 3 -0x0p+0", 1);
    assert!(matches!(
        run(BASE, &neg).unwrap(),
        Some(Difference::Field { field: 0, .. })
    ));
}

#[test]
fn level_and_length() {
    let l2 = BASE.replace("L1", "L2");
    assert!(matches!(
        run(BASE, &l2).unwrap(),
        Some(Difference::Level { .. })
    ));
    // L2 uses the same line kinds.
    assert_eq!(run(&l2, &l2).unwrap(), None);
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
    for cut in [
        "0 bone 0 3 0x1p",
        "0 bone 0 3 0x1p+0 0x",
        "0 bone",
        "0 bone 0",
        "0 camera 0x1p+0",
    ] {
        let (line, _) = parse_err(&format!("mds-trace 1 L1\n{cut}\n"));
        assert_eq!(line, 2, "{cut:?}");
    }
    let (line, msg) = parse_err("mds-trace 1 L1\n0 morph 0 0 0x1p+0");
    assert_eq!((line, msg), (2, "truncated line (no newline at end)"));
}

#[test]
fn bad_record() {
    for (rec, why) in [
        ("0 tail 0 0x1p+0", "unknown track kind"),
        ("0 Bone 0 3 0x0p+0", "unknown track kind"),
        ("0 morph 0 0 0x1p+0 0x1p+0", "wrong number of fields"),
        ("0 light 0x1p+0 0x1p+0", "wrong number of fields"),
        ("0 morph 0 0 nan", "float is not finite"),
        ("0 morph 0 0 -inf", "float is not finite"),
        ("0 morph 0", "missing frame or index"),
        ("0 morph 0 -1 0x1p+0", "bad frame or index number"),
        ("0 morph 0 0 0x1p+0 ", "bad hex float"),
    ] {
        let (line, msg) = parse_err(&format!("mds-trace 1 L1\n{rec}\n"));
        assert_eq!(line, 2, "{rec:?}");
        assert!(msg.contains(why), "{rec:?}: {msg}");
    }
}

#[test]
fn real_l1_trace() {
    assert!(REAL.starts_with("mds-trace 1 L1\n"));
    assert_eq!(run(REAL, REAL).unwrap(), None);
    // Frame 1 bone 1/0 translation x: change the last hex digit.
    let at = REAL.find("\n1 bone 1 0 ").unwrap() + 1;
    let end = at + REAL[at..].find('\n').unwrap();
    let line = &REAL[at..end];
    let tok = line.split(' ').nth(4).unwrap();
    let digit = tok.bytes().position(|c| c == b'p').unwrap() - 1;
    let mut changed = tok.to_owned().into_bytes();
    changed[digit] = if changed[digit] == b'0' { b'1' } else { b'0' };
    let changed = String::from_utf8(changed).unwrap();
    let b = REAL.replacen(line, &line.replacen(tok, &changed, 1), 1);
    let msg = run(REAL, &b).unwrap().unwrap().to_string();
    assert!(
        msg.starts_with(&format!(
            "frame 1 track bone 1/0 field tx: a={tok} b={changed}"
        )),
        "{msg}"
    );
    // Cut in the middle of a line: parse error naming that line.
    let cut = &REAL[..REAL.len() / 2];
    let line = cut.matches('\n').count() + 1;
    let (l, msg) = match run(REAL, cut) {
        Err(Error::Parse { line, msg, .. }) => (line, msg),
        other => panic!("expected a parse error, got {other:?}"),
    };
    assert_eq!((l, msg), (line, "truncated line (no newline at end)"));
}

#[test]
fn parse_error_does_not_echo_the_content() {
    for rec in [
        "SECRET-TOKEN",
        "0 SECRET-TOKEN 0 0",
        "0 morph 0 0 SECRET-TOKEN",
    ] {
        let e = run(&format!("mds-trace 1 L1\n{rec}\n"), BASE).unwrap_err();
        assert!(!e.to_string().contains("SECRET"), "{e}");
    }
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
    assert!(
        out.contains("frame 0 track morph 1/2 field weight"),
        "{out}"
    );

    let cut = tmp("cut.trace", "mds-trace 1 L1\n0 bone 0 3 0x0p");
    let (code, _, err) = exit_code(&a, &cut);
    assert_eq!(code, 2);
    assert!(err.contains("line 2"), "{err}");

    assert_eq!(exit_code(&a, &PathBuf::from("/nonexistent/x.trace")).0, 2);
    let o = Command::new(env!("CARGO_BIN_EXE_mds-trace-diff"))
        .output()
        .unwrap();
    assert_eq!(o.status.code(), Some(2));
}
