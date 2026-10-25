use mds_app::dump;
use mds_render::Gpu;
use std::process::ExitCode;

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let result = match args.first().map(String::as_str) {
        Some("--frame-dump") => frame_dump(&args[1..]),
        _ => Err("usage: mds-app --frame-dump <pmm> <out-dir> <frame>...".into()),
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
    let request = dump::parse(args)?;
    let gpu = Gpu::new()?.ok_or("no wgpu adapter")?;
    dump::run(&gpu, &request)
}
