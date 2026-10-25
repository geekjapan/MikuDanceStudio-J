//! The plan text of `tools/oracle/mme_passplan.cpp`, line for line. The format is described in
//! `tests/fixtures/rust/mme/README.md`.

use std::fmt::Write;

use crate::fx::*;
use crate::run::{Device, Run, RunState, E_FAIL};
use crate::sas::*;

/// A quoted string: `\` and `"` escaped, bytes below 0x20 and from 0x7f up as `\xNN`.
/// Non-ASCII text is written in Shift-JIS, the encoding of the effect files.
pub fn q(s: &str) -> String {
    let (bytes, _, _) = encoding_rs::SHIFT_JIS.encode(s);
    let mut out = String::from("\"");
    for &c in bytes.iter() {
        match c {
            b'"' | b'\\' => {
                out.push('\\');
                out.push(c as char);
            }
            0x20..=0x7e => out.push(c as char),
            _ => {
                let _ = write!(out, "\\x{c:02x}");
            }
        }
    }
    out.push('"');
    out
}

/// C `printf("%.<prec>g", v)`.
pub fn fmt_g(v: f64, prec: usize) -> String {
    if v.is_nan() {
        return if v.is_sign_negative() {
            "-nan(ind)"
        } else {
            "nan"
        }
        .to_string();
    }
    if v.is_infinite() {
        return if v < 0.0 { "-inf" } else { "inf" }.to_string();
    }
    let p = prec.max(1);
    if v == 0.0 {
        return if v.is_sign_negative() { "-0" } else { "0" }.to_string();
    }
    let e = format!("{:.*e}", p - 1, v);
    let (mantissa, exp) = e.split_once('e').unwrap_or((&e, "0"));
    let x: i32 = exp.parse().unwrap_or(0);
    let strip = |s: String| {
        if s.contains('.') {
            s.trim_end_matches('0').trim_end_matches('.').to_string()
        } else {
            s
        }
    };
    if x < -4 || x >= p as i32 {
        let m = strip(mantissa.to_string());
        format!("{m}e{}{:02}", if x < 0 { '-' } else { '+' }, x.abs())
    } else {
        strip(format!("{:.*}", (p as i32 - 1 - x).max(0) as usize, v))
    }
}

const READ_ANNOTATIONS: [&str; 28] = [
    "ScriptOutput",
    "ScriptClass",
    "ScriptOrder",
    "Script",
    "ResourceName",
    "ResourceType",
    "Offset",
    "Speed",
    "SeekVariable",
    "TextureName",
    "ViewportRatio",
    "Dimensions",
    "Width",
    "Height",
    "Depth",
    "Miplevels",
    "Levels",
    "Format",
    "Description",
    "DefaultEffect",
    "ClearColor",
    "ClearDepth",
    "AntiAlias",
    "Function",
    "Target",
    "Name",
    "Item",
    "Object",
];

fn is_read(name: &str) -> bool {
    READ_ANNOTATIONS
        .iter()
        .any(|n| n.eq_ignore_ascii_case(name))
}

fn class_name(c: u8) -> &'static str {
    [
        "scalar",
        "vector",
        "matrix_rows",
        "matrix_columns",
        "object",
        "struct",
    ]
    .get(usize::from(c))
    .copied()
    .unwrap_or("?")
}

fn type_name(t: u8) -> &'static str {
    match t {
        0 => "void",
        1 => "bool",
        2 => "int",
        3 => "float",
        4 => "string",
        5 => "texture",
        6 => "texture1d",
        7 => "texture2d",
        8 => "texture3d",
        9 => "texturecube",
        10..=14 => "sampler",
        15 => "pixelshader",
        16 => "vertexshader",
        _ => "?",
    }
}

/// `FormatName` of the oracle: the names it knows, else `0x%08x`.
fn format_name(f: u32) -> String {
    const KNOWN: [&str; 44] = [
        "UNKNOWN",
        "R8G8B8",
        "A8R8G8B8",
        "X8R8G8B8",
        "R5G6B5",
        "X1R5G5B5",
        "A1R5G5B5",
        "A4R4G4B4",
        "R3G3B2",
        "A8",
        "A8R3G3B2",
        "X4R4G4B4",
        "A2B10G10R10",
        "A8B8G8R8",
        "X8B8G8R8",
        "G16R16",
        "A2R10G10B10",
        "A16B16G16R16",
        "L8",
        "A8L8",
        "V8U8",
        "Q8W8V8U8",
        "V16U16",
        "D16_LOCKABLE",
        "D32",
        "D15S1",
        "D24S8",
        "D24X8",
        "D24X4S4",
        "D16",
        "D32F_LOCKABLE",
        "D24FS8",
        "L16",
        "R16F",
        "G16R16F",
        "A16B16G16R16F",
        "R32F",
        "G32R32F",
        "A32B32G32R32F",
        "DXT1",
        "DXT2",
        "DXT3",
        "DXT4",
        "DXT5",
    ];
    FORMATS
        .iter()
        .find(|(n, v)| *v == f && KNOWN.contains(n))
        .map_or_else(|| format!("0x{f:08x}"), |(n, _)| n.to_string())
}

fn annotation_value(a: &Item) -> String {
    if a.desc.ty == TYPE_STRING && a.desc.elements == 0 {
        return a.get_string().map_or("?".to_string(), q);
    }
    let count = a.desc.rows * a.desc.columns * a.desc.elements.max(1);
    if a.desc.class > CLASS_MATRIX_COLUMNS || count == 0 || count > 64 {
        return "?".to_string();
    }
    let Some(nums) = a.get_array(count as usize) else {
        return "?".to_string();
    };
    nums.iter()
        .map(|n| match a.desc.ty {
            TYPE_FLOAT => fmt_g(f64::from(n.float()), 9),
            TYPE_INT => n.int().to_string(),
            TYPE_BOOL => u8::from(n.bool()).to_string(),
            _ => "?".to_string(),
        })
        .collect::<Vec<_>>()
        .join(",")
}

struct Out(String);

impl Out {
    fn line(&mut self, s: impl AsRef<str>) {
        self.0.push_str(s.as_ref());
        self.0.push('\n');
    }

    /// `TextLines`: one quoted line per non-empty text line.
    fn text_lines(&mut self, tag: &str, indent: &str, text: &str) {
        for l in text.split(['\r', '\n']).filter(|l| !l.is_empty()) {
            self.line(format!("{indent}{tag} {}", q(l)));
        }
    }
}

/// The plan of one load: `path` is the effect as the plan names it (`<root>/...`).
pub fn write(path: &str, loaded: Result<Sas, String>) -> String {
    let mut o = Out(String::new());
    o.line("passplan 1");
    o.line(format!("file {}", q(path)));
    o.line("device HAL backbuffer=1000x600 format=A8R8G8B8 depthstencil=D24S8 vs=3.0 ps=3.0 mipfilter=1");
    let mut engine_log = format!("Loading effect file: {path}\n");
    match loaded {
        Err(error) => {
            o.line("load rejected");
            o.text_lines("error", "  ", &error);
        }
        Ok(mut sas) => {
            o.line("load ok");
            o.line(format!(
                "effect scriptclass={} scriptorder={} posteffect={} drawsgeometry={} errors={}",
                sas.script_class,
                sas.script_order,
                u8::from(sas.post_effect),
                u8::from(sas.draws_geometry),
                u8::from(sas.has_errors)
            ));
            engine_log.push_str(&sas.log);
            parameters(&mut o, &sas.fx);
            resources(&mut o, &sas);
            techniques(&mut o, &sas);
            selection(&mut o, &sas);
            runs(&mut o, &mut sas);
        }
    }
    o.text_lines("enginelog", "", &engine_log);
    o.line("end");
    o.0
}

fn parameters(o: &mut Out, fx: &Fx) {
    o.line(format!("parameters {}", fx.params.len()));
    for p in &fx.params {
        let read = p.annotations.iter().any(|a| is_read(&a.name));
        if p.semantic.is_empty() && !p.desc.is_texture() && !in_name_table(&p.name) && !read {
            continue;
        }
        let d = &p.desc;
        o.line(format!(
            "param {} {} {} {} {}x{}{}{}",
            q(&p.name),
            q(&p.semantic),
            class_name(d.class),
            type_name(d.ty),
            d.rows,
            d.columns,
            if d.elements != 0 {
                format!("[{}]", d.elements)
            } else {
                String::new()
            },
            if p.shared { " literal" } else { "" }
        ));
        for a in p.annotations.iter().filter(|a| is_read(&a.name)) {
            o.line(format!(
                "  ann {} {}{} = {}",
                q(&a.name),
                type_name(a.desc.ty),
                a.desc.rows * a.desc.columns,
                annotation_value(a)
            ));
        }
    }
}

fn resources(o: &mut Out, sas: &Sas) {
    o.line(format!("resources {}", sas.resources.len()));
    for r in &sas.resources {
        let sem = match r.semantic {
            SEM_RENDER_COLOR => "RenderColorTarget",
            SEM_RENDER_DEPTH => "RenderDepthStencilTarget",
            SEM_TEXTURE => "Texture",
            SEM_ANIMATED => "AnimatedTexture",
            SEM_OFFSCREEN => "OffScreenRenderTarget",
            SEM_TEXTURE_VALUE => "TextureValue",
            _ => "?",
        };
        o.line(format!(
            "resource {} semantic={sem} texture={}",
            q(&r.name),
            r.texture_type
        ));
        o.line(format!(
            "  request {}x{}x{} mips={} rawsize={}x{} rawmips={} format={} defaultpool={}",
            r.req_width,
            r.req_height,
            r.req_depth,
            r.mip_levels,
            r.tex_width,
            r.tex_height,
            r.tex_mips,
            format_name(r.format),
            u8::from(r.default_pool)
        ));
        if r.semantic == SEM_OFFSCREEN {
            o.line(format!(
                "  clear color={} depth={} antialias={}",
                if r.has_clear_color {
                    format!("0x{:08x}", r.clear_color)
                } else {
                    "-".into()
                },
                if r.has_clear_depth {
                    fmt_g(f64::from(r.clear_depth), 9)
                } else {
                    "-".into()
                },
                u8::from(r.anti_alias)
            ));
            for (k, v) in &r.default_effect {
                o.line(format!("  defaulteffect_row {} {}", q(k), q(v)));
            }
        }
        if !r.resource_name.is_empty() {
            o.line(format!("  resourcename {}", q(&r.resource_name)));
        }
        if !r.function_name.is_empty() {
            o.line(format!(
                "  function {} target {}",
                q(&r.function_name),
                q(&r.function_target)
            ));
        }
        if r.semantic == SEM_ANIMATED {
            o.line(format!(
                "  animated offset={} speed={} seekvariable={}",
                fmt_g(f64::from(r.offset), 9),
                fmt_g(f64::from(r.speed), 9),
                q(&r.seek_variable)
            ));
        }
        if r.semantic == SEM_TEXTURE_VALUE {
            o.line(format!(
                "  texturevalue texture={} elements={}",
                q(&r.texture_value_name),
                r.texture_value_elements
            ));
        }
        if let Some(t) = r.texture {
            match t.kind {
                TexKind::Volume => o.line("  created type=4"),
                kind => o.line(format!(
                    "  created {} {}x{} levels={} format={} pool={} usage=0x{:x}",
                    if kind == TexKind::Cube {
                        "cube"
                    } else {
                        "texture"
                    },
                    t.width,
                    t.height,
                    t.levels,
                    format_name(t.format),
                    t.pool,
                    t.usage
                )),
            }
        }
        if let (Some((w, h, f)), SEM_RENDER_DEPTH) = (r.surface, r.semantic) {
            o.line(format!(
                "  created depthsurface {w}x{h} format={}",
                format_name(f)
            ));
        }
        if r.texture.is_none() && r.surface.is_none() {
            o.line("  created none");
        }
        if r.semantic == SEM_OFFSCREEN {
            match r.offscreen_depth {
                Some((w, h, f)) => o.line(format!(
                    "  offscreendepth {w}x{h} format={}",
                    format_name(f)
                )),
                None => o.line("  offscreendepth none"),
            }
        }
    }
    o.line(format!("controls {}", sas.controls.len()));
    for c in &sas.controls {
        o.line(format!(
            "control {} name={} item={}",
            q(&sas.fx.params[c.param].name),
            q(&c.object),
            q(&c.item)
        ));
    }
}

fn find_tech(sas: &Sas, fx: usize) -> Option<&TechRec> {
    sas.techniques.iter().find(|t| t.fx == fx)
}

fn commands(o: &mut Out, sas: &Sas, t: &TechRec, cmds: &[Cmd], indent: &str) {
    for (i, c) in cmds.iter().enumerate() {
        let operand = if c.id == CMD_PASS {
            let name = t
                .passes
                .iter()
                .rev()
                .find(|p| p.index == c.value)
                .map_or("?", |p| p.name.as_str());
            format!("pass={} index={}", q(name), c.value)
        } else {
            let name = c.param.map_or("-", |p| sas.fx.params[p].name.as_str());
            format!("param={} value={}", q(name), c.value)
        };
        o.line(format!(
            "{indent}cmd {i} {} {operand} text={}",
            CMD_NAMES[usize::from(c.id)],
            q(&c.text)
        ));
    }
}

fn use_name(v: i8) -> &'static str {
    match v {
        v if v < 0 => "any",
        0 => "0",
        _ => "1",
    }
}

const PASS_MODES: [&str; 5] = ["object", "object_ss", "shadow", "edge", "zplot"];

fn techniques(o: &mut Out, sas: &Sas) {
    let mut order = String::from("technique_order");
    for &h in &sas.technique_order {
        let _ = write!(order, " {}", q(find_tech(sas, h).map_or("?", |t| &t.name)));
    }
    o.line(order);
    o.line(format!("techniques {}", sas.techniques.len()));
    for t in &sas.techniques {
        let subset = if t.all_subsets {
            "all".to_string()
        } else if t.subsets.is_empty() {
            "none".to_string()
        } else {
            t.subsets
                .iter()
                .map(|(a, b)| format!("{a}-{b}"))
                .collect::<Vec<_>>()
                .join(",")
        };
        o.line(format!(
            "technique {} mmdpass={} usetexture={} usespheremap={} usetoon={} subset={subset} hardware={} shadercaps={} shadermix={} script={} empty={} passes={}",
            q(&t.name),
            PASS_MODES.get(t.mmd_pass as usize).unwrap_or(&"?"),
            use_name(t.use_texture),
            use_name(t.use_spheremap),
            use_name(t.use_toon),
            u8::from(t.hardware_ok),
            u8::from(t.shader_caps_ok),
            u8::from(t.shader_mix_ok),
            u8::from(t.script.is_some()),
            u8::from(t.empty),
            t.passes.len()
        ));
        if let Some(s) = &t.script {
            o.line(format!("  script {}", q(s)));
        }
        commands(o, sas, t, &t.cmds, "  ");
        for p in &t.passes {
            o.line(format!(
                "  pass {} {} script={} custom={} psize15={} shadermix={}",
                p.index,
                q(&p.name),
                u8::from(p.script.is_some()),
                u8::from(p.custom_shaders),
                u8::from(p.needs_psize15),
                u8::from(p.shader_mix_ok)
            ));
            if let Some(s) = &p.script {
                o.line(format!("    script {}", q(s)));
            }
            commands(o, sas, t, &p.cmds, "    ");
        }
    }
}

/// `SasSelectTechnique`: the technique and whether it is valid.
pub fn select(
    sas: &Sas,
    mode: i32,
    subset: i32,
    tex: bool,
    sphere: bool,
    toon: bool,
) -> (Option<usize>, bool) {
    let mut fallback = None;
    for &h in &sas.technique_order {
        let Some(t) = find_tech(sas, h) else {
            continue;
        };
        if t.mmd_pass != mode {
            continue;
        }
        if !t.all_subsets && !t.subsets.iter().any(|(&a, &b)| subset >= a && subset <= b) {
            continue;
        }
        let ok = |f: i8, state: bool| f < 0 || (f != 0) == state;
        if !ok(t.use_texture, tex) || !ok(t.use_spheremap, sphere) || !ok(t.use_toon, toon) {
            continue;
        }
        if t.hardware_ok {
            return (Some(h), true);
        }
        fallback = Some(h);
    }
    (fallback, fallback.is_none())
}

fn selection(o: &mut Out, sas: &Sas) {
    let clamped = sas.script_class == 1 || sas.script_order != 0;
    let materials = if clamped {
        1
    } else {
        let max_end = sas
            .techniques
            .iter()
            .flat_map(|t| t.subsets.values())
            .copied()
            .fold(0, i32::max);
        // The C++ adds in 32 bits: an open range (`5-`) wraps to a negative count.
        let m = max_end.wrapping_add(2);
        if m > 256 {
            256
        } else {
            m
        }
    };
    o.line(format!(
        "selection subsets={materials} clamped={}",
        u8::from(clamped)
    ));
    o.line("  # name! = the technique matched but is invalid (fallback); - = no technique");
    o.line("  # modes 0 and 1 list the eight Use* states: index = usetexture | usespheremap<<1 | usetoon<<2");
    for mode in 0..5 {
        if mode != 0 && sas.script_order != 0 {
            continue;
        }
        let mut previous = String::new();
        let mut start = 0;
        for subset in 0..=materials {
            let mut row = String::new();
            if subset < materials {
                let combos = if mode <= 1 { 8 } else { 1 };
                for combo in 0..combos {
                    let bit = |b| mode <= 1 && combo & b != 0;
                    let (h, valid) = select(sas, mode, subset, bit(1), bit(2), bit(4));
                    if combo > 0 {
                        row.push(' ');
                    }
                    match h {
                        None => row.push('-'),
                        Some(h) => {
                            row.push_str(&q(find_tech(sas, h).map_or("?", |t| &t.name)));
                            if !valid {
                                row.push('!');
                            }
                        }
                    }
                }
            }
            if subset == 0 {
                previous = row;
                continue;
            }
            if row != previous || subset == materials {
                o.line(format!(
                    "  select {} {start}-{} {previous}",
                    PASS_MODES[mode as usize],
                    subset - 1
                ));
                start = subset;
                previous = row;
            }
        }
    }
}

fn runs(o: &mut Out, sas: &mut Sas) {
    o.line("runs");
    let mut dev = Device::new(sas);
    for tech in 0..sas.techniques.len() {
        if sas.techniques[tech].empty {
            continue;
        }
        sas.run_failed = false;
        let log_before = sas.log.len();
        o.line(format!("  run {}", q(&sas.techniques[tech].name)));
        let mut st = RunState::new(&dev);
        o.line(format!("    start {}", dev.bindings()));
        let mut run = Run {
            sas,
            dev: &mut dev,
            tech,
            draws: 0,
            out: &mut o.0,
        };
        let (_, suspended) = run.walk(&mut st, true);
        if suspended {
            let b = run.dev.bindings();
            run.out.push_str(&format!("    suspend {b}\n"));
        }
        let hr = if run.sas.run_failed {
            E_FAIL
        } else {
            run.walk(&mut st, false).0
        };
        let draws = run.draws;
        o.line(format!("    end {}", dev.bindings()));
        o.line(format!(
            "    result suspended={} draws={draws} hr=0x{hr:08x} runfailed={}",
            u8::from(suspended),
            u8::from(sas.run_failed)
        ));
        let log = sas.log[log_before..].to_string();
        o.text_lines("log", "    ", &log);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn printf_g() {
        assert_eq!(fmt_g(f64::from(0.3333f32), 9), "0.333299994");
        assert_eq!(fmt_g(1.0, 9), "1");
        assert_eq!(fmt_g(0.5, 9), "0.5");
        assert_eq!(fmt_g(f64::from(0.9f32), 6), "0.9");
        assert_eq!(fmt_g(1e-5, 9), "1e-05");
        assert_eq!(fmt_g(123456789012.0, 9), "1.23456789e+11");
        assert_eq!(fmt_g(2048.0, 9), "2048");
    }

    #[test]
    fn quoting() {
        assert_eq!(q("a\"b\\\t"), "\"a\\\"b\\\\\\x09\"");
    }
}
