use std::{env, ffi::OsStr, fs, path::Path, process::Command};

fn json(value: &OsStr) -> String {
    let mut result = String::from("\"");
    for ch in value.to_str().expect("UTF-8 diagnostic argument").chars() {
        match ch {
            '"' => result.push_str("\\\""),
            '\\' => result.push_str("\\\\"),
            ch if ch < ' ' => result.push_str(&format!("\\u{:04x}", ch as u32)),
            ch => result.push(ch),
        }
    }
    result.push('"');
    result
}

fn capture(mut command: Command, out: &Path, name: &str) {
    let argv = std::iter::once(command.get_program())
        .chain(command.get_args())
        .map(json)
        .collect::<Vec<_>>()
        .join(",");
    fs::write(
        out.join(format!("{name}-command.json")),
        format!("[{argv}]\n"),
    )
    .unwrap();
    let output = command.output().expect("execute diagnostic compiler");
    fs::write(out.join(format!("{name}.stdout")), output.stdout).unwrap();
    fs::write(out.join(format!("{name}.stderr")), output.stderr).unwrap();
    assert!(
        output.status.success(),
        "consumer probe {name} failed: {}",
        output.status
    );
}

pub fn run(build: &cc::Build, src: &Path, shim: &Path, out: &Path) {
    fs::create_dir_all(out).unwrap();
    let tool = build.get_compiler();
    let msvc = tool.is_like_msvc();
    let archive = env::var_os("OUT_DIR")
        .map(std::path::PathBuf::from)
        .unwrap()
        .join(if msvc {
            "mds_bullet_sys.lib"
        } else {
            "libmds_bullet_sys.a"
        });
    fs::write(out.join("archive-path.txt"), archive.to_str().unwrap()).unwrap();
    fs::copy(&archive, out.join(archive.file_name().unwrap())).unwrap();
    let configured = tool.to_command();
    let argv = std::iter::once(configured.get_program())
        .chain(configured.get_args())
        .map(json)
        .collect::<Vec<_>>()
        .join(",");
    fs::write(
        out.join("configured-tool-command.json"),
        format!("[{argv}]\n"),
    )
    .unwrap();
    let metadata = [
        "TARGET",
        "HOST",
        "OPT_LEVEL",
        "PROFILE",
        "CXX",
        "CXXFLAGS",
        "CL",
        "_CL_",
        "INCLUDE",
        "LIB",
        "SDKROOT",
        "MACOSX_DEPLOYMENT_TARGET",
        "MDS_BT_SYSTEM_MATH",
        "MDS_BT_ASAN",
    ]
    .into_iter()
    .filter_map(|key| env::var_os(key).map(|v| format!("{}:{}", json(OsStr::new(key)), json(&v))))
    .collect::<Vec<_>>()
    .join(",");
    let configured_env = tool
        .to_command()
        .get_envs()
        .filter(|(key, _)| {
            [
                "PATH",
                "INCLUDE",
                "LIB",
                "LIBPATH",
                "SDKROOT",
                "MACOSX_DEPLOYMENT_TARGET",
                "VSLANG",
                "SystemRoot",
                "TEMP",
                "TMP",
            ]
            .iter()
            .any(|allowed| *key == OsStr::new(allowed))
        })
        .map(|(key, value)| format!("{}:{}", json(key), value.map(json).unwrap_or("null".into())))
        .collect::<Vec<_>>()
        .join(",");
    fs::write(
        out.join("build-environment.json"),
        format!("{{\"cargo\":{{{metadata}}},\"tool\":{{{configured_env}}}}}\n"),
    )
    .unwrap();
    let mut version = tool.to_command();
    version.arg(if msvc { "/?" } else { "--version" });
    capture(version, out, "compiler-version");
    for (name, source) in [
        (
            "btDbvt",
            src.join("BulletCollision/BroadphaseCollision/btDbvt.cpp"),
        ),
        (
            "btDbvtBroadphase",
            src.join("BulletCollision/BroadphaseCollision/btDbvtBroadphase.cpp"),
        ),
        ("mds_bt", shim.join("mds_bt.cpp")),
        ("mds_mmd", shim.join("mds_mmd.cpp")),
    ] {
        let mut command = tool.to_command();
        if msvc {
            command.args(["/E", "/showIncludes"]);
        } else {
            command.args(["-E", "-H"]);
        }
        command.arg(source);
        capture(command, out, name);
    }
    let root = shim.join("../../../..");
    let oracle = fs::read_to_string(root.join("tools/bullet-rust-dbvt-check/oracle.cpp")).unwrap();
    let (body, end) = oracle.rsplit_once('}').expect("oracle main closing brace");
    assert!(end.trim().is_empty());
    let copied = format!(
        "{}return 0;\n}}\n",
        body.replace("int main(", "int consumer_oracle_main(")
            .replace("std::aligned_alloc", "::aligned_alloc")
    );
    fs::write(out.join("oracle-copy.cpp"), copied).unwrap();
    let bridge = root.join("tools/bullet-dbvt-consumer-profile/probe.cpp");
    let object = out.join(if msvc {
        "consumer-probe.obj"
    } else {
        "consumer-probe.o"
    });
    let mut command = tool.to_command();
    if msvc {
        command
            .arg("/c")
            .arg(format!("/I{}", out.display()))
            .arg(format!("/Fo{}", object.display()));
    } else {
        command.arg("-c").arg("-I").arg(out).arg("-o").arg(&object);
    }
    command.arg(bridge);
    capture(command, out, "probe-compile");
    cc::Build::new()
        .object(object)
        .compile("mds_bt_consumer_probe");
}
