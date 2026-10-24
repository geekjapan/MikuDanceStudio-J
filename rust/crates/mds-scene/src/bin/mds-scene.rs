//! `mds-scene trace <pmm> [--root <dir>] (--frames <n> | --seconds <s>[,<s>...] | --half-frames <n>) [--out <file>]`
//!
//! Writes a trace in format 1, level L1, to stdout or to `--out` (written
//! under a temporary name and renamed, so the file never holds a partial
//! trace). Exit 0 on success, 2 on bad arguments, 3 when the PMM does not
//! load, 7 when the trace cannot be written.
//!
//! * `--frames n`: frames `0..n` of the stateless evaluator, as
//!   `mds_scene_cli --trace --frames n` does.
//! * `--seconds s[,s...]`: playback samples at those float cursor seconds
//!   (non-decreasing), one block per sample, labelled by sample index.
//! * `--half-frames n`: playback samples at frames 0, 0.5, ... n, labelled
//!   by sample index.
//!
//! `--root` is accepted for parity with `mds_scene_cli`. The C++ tool
//! resolves each model file under it; the PMM v2 layout is in the PMM, so
//! this tool reads no model.

use mds_scene::trace::{write_playback_trace, write_scene_trace};
use std::fs::File;
use std::io::{BufWriter, Write};
use std::path::PathBuf;
use std::process::ExitCode;

const USAGE: &str = "usage: mds-scene trace <pmm> [--root <dir>] \
(--frames <n> | --seconds <s>[,<s>...] | --half-frames <n>) [--out <file>]";

enum Samples {
    Frames(u32),
    Seconds(Vec<f32>),
}

struct Args {
    pmm: PathBuf,
    samples: Samples,
    out: Option<PathBuf>,
}

/// Same bound as `scene_cli.cpp`: an unsigned decimal up to `i32::MAX`.
fn count(text: &str) -> Option<u32> {
    if !text.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    text.parse::<u32>().ok().filter(|&n| n <= i32::MAX as u32)
}

fn seconds(text: &str) -> Option<f32> {
    text.parse::<f32>()
        .ok()
        .filter(|s| s.is_finite() && *s >= 0.0)
}

fn parse(args: &[String]) -> Option<Args> {
    let [cmd, pmm, rest @ ..] = args else {
        return None;
    };
    if cmd != "trace" {
        return None;
    }
    let (mut samples, mut out) = (None, None);
    for pair in rest.chunks(2) {
        let [name, value] = pair else {
            return None;
        };
        match name.as_str() {
            "--root" => {}
            "--out" if out.is_none() && !value.is_empty() => out = Some(PathBuf::from(value)),
            "--frames" if samples.is_none() => samples = Some(Samples::Frames(count(value)?)),
            "--seconds" if samples.is_none() => {
                let list: Option<Vec<f32>> = value.split(',').map(seconds).collect();
                samples = Some(Samples::Seconds(list?));
            }
            "--half-frames" if samples.is_none() => {
                let n = count(value).filter(|&n| n <= 1 << 20)?;
                samples = Some(Samples::Seconds(
                    (0..=2 * n).map(|k| k as f32 / 60.0f32).collect(),
                ));
            }
            _ => return None,
        }
    }
    Some(Args {
        pmm: PathBuf::from(pmm),
        samples: samples?,
        out,
    })
}

fn run(args: Args) -> ExitCode {
    let scene = match std::fs::read(&args.pmm)
        .map_err(|e| e.kind().to_string())
        .and_then(|data| mds_scene::load_scene(&data))
    {
        Ok(scene) => scene,
        Err(e) => {
            eprintln!("mds-scene: {}: {e}", args.pmm.display());
            return ExitCode::from(3);
        }
    };
    let write = |out: &mut dyn Write| {
        let mut out = BufWriter::new(out);
        match &args.samples {
            Samples::Frames(n) => write_scene_trace(&mut out, &scene, *n),
            Samples::Seconds(s) => write_playback_trace(&mut out, &scene, s),
        }?;
        out.flush().map_err(Into::into)
    };
    let result: Result<(), mds_scene::trace::Error> = match &args.out {
        None => write(&mut std::io::stdout().lock()),
        Some(path) => {
            let mut temporary = path.clone().into_os_string();
            temporary.push(".tmp");
            let temporary = PathBuf::from(temporary);
            let result = File::create(&temporary)
                .map_err(Into::into)
                .and_then(|mut f| write(&mut f))
                .and_then(|()| std::fs::rename(&temporary, path).map_err(Into::into));
            if result.is_err() {
                let _ = std::fs::remove_file(&temporary);
            }
            result
        }
    };
    match result {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("mds-scene: trace failed: {e}");
            ExitCode::from(7)
        }
    }
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match parse(&args) {
        Some(args) => run(args),
        None => {
            eprintln!("{USAGE}");
            ExitCode::from(2)
        }
    }
}
