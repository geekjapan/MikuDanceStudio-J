//! `mds-trace-diff <a> <b>`: exit 0 identical, 1 first difference, 2 error.

use mds_trace::Side;
use std::fs::File;
use std::io::BufReader;
use std::process::ExitCode;

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let [pa, pb] = args.as_slice() else {
        eprintln!("usage: mds-trace-diff <a> <b>");
        return ExitCode::from(2);
    };
    let open = |p: &str| {
        File::open(p)
            .map(BufReader::new)
            .map_err(|e| eprintln!("mds-trace-diff: {p}: {}", e.kind()))
    };
    let (Ok(fa), Ok(fb)) = (open(pa), open(pb)) else {
        return ExitCode::from(2);
    };
    match mds_trace::diff(fa, fb) {
        Ok(None) => ExitCode::SUCCESS,
        Ok(Some(d)) => {
            println!("{d}");
            ExitCode::from(1)
        }
        Err(e) => {
            let path = if e.side() == Side::A { pa } else { pb };
            eprintln!("mds-trace-diff: {path}: {e}");
            ExitCode::from(2)
        }
    }
}
