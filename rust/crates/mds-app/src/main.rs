//! `mds-app [<pmm>]` opens the window (on the empty startup scene without a PMM);
//! `mds-app --frame-dump <pmm> <out-dir> <frame>...` writes the frames as PNG without one.

mod window;

use mds_app::dump;
use mds_render::Gpu;
use std::process::ExitCode;

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let result = match args.first().map(String::as_str) {
        Some("--frame-dump") => frame_dump(&args[1..]),
        Some(flag) if flag.starts_with('-') => {
            Err("usage: mds-app [<pmm>] | --frame-dump <pmm> <out-dir> <frame>...".into())
        }
        pmm => window::run(pmm.map(Into::into)),
    };
    match result {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("mds-app: {e}");
            ExitCode::FAILURE
        }
    }
}

fn frame_dump(args: &[String]) -> Result<(), String> {
    let mut request = dump::parse(args)?;
    if let Some(v) = std::env::var_os("MDS_FRAME_DUMP_PICTURE_VIEWPORT") {
        request.picture_viewport = Some(dump::parse_viewport(&v.to_string_lossy())?);
    }
    let gpu = Gpu::new()?.ok_or("no wgpu adapter")?;
    dump::run(&gpu, &request)
}
