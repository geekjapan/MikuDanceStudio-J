//! `SasParse` of `third_party/mmeffect/src/mmeffect/sas_interpreter.cpp` and the script
//! compiler of `sas_exec.cpp`: the STANDARDSGLOBAL scan, the semantic and name tables, the
//! resource objects with the D3D objects the runtime creates for them, the CONTROLOBJECT
//! list, and the technique and pass records with their compiled scripts.

use std::path::Path;

use crate::fx::*;
use crate::texfile;

/// D3DFORMAT values.
pub mod fmt {
    pub const UNKNOWN: u32 = 0;
    pub const A8R8G8B8: u32 = 21;
    pub const X8R8G8B8: u32 = 22;
    pub const L8: u32 = 50;
    pub const A8L8: u32 = 51;
    pub const D24S8: u32 = 75;
    pub const A32B32G32R32F: u32 = 116;
}

const fn fourcc(s: &[u8; 4]) -> u32 {
    u32::from_le_bytes(*s)
}

/// `kFormatTable` of sas_interpreter.cpp: the names a `Format` annotation may use.
pub const FORMATS: [(&str, u32); 60] = [
    ("UNKNOWN", 0),
    ("R8G8B8", 20),
    ("A8R8G8B8", 21),
    ("X8R8G8B8", 22),
    ("R5G6B5", 23),
    ("X1R5G5B5", 24),
    ("A1R5G5B5", 25),
    ("A4R4G4B4", 26),
    ("R3G3B2", 27),
    ("A8", 28),
    ("A8R3G3B2", 29),
    ("X4R4G4B4", 30),
    ("A2B10G10R10", 31),
    ("A8B8G8R8", 32),
    ("X8B8G8R8", 33),
    ("G16R16", 34),
    ("A2R10G10B10", 35),
    ("A16B16G16R16", 36),
    ("A8P8", 40),
    ("P8", 41),
    ("L8", 50),
    ("A8L8", 51),
    ("A4L4", 52),
    ("V8U8", 60),
    ("L6V5U5", 61),
    ("X8L8V8U8", 62),
    ("Q8W8V8U8", 63),
    ("V16U16", 64),
    ("A2W10V10U10", 67),
    ("UYVY", fourcc(b"UYVY")),
    ("R8G8_B8G8", fourcc(b"RGBG")),
    ("YUY2", fourcc(b"YUY2")),
    ("G8R8_G8B8", fourcc(b"GRGB")),
    ("DXT1", fourcc(b"DXT1")),
    ("DXT2", fourcc(b"DXT2")),
    ("DXT3", fourcc(b"DXT3")),
    ("DXT4", fourcc(b"DXT4")),
    ("DXT5", fourcc(b"DXT5")),
    ("D16_LOCKABLE", 70),
    ("D32", 71),
    ("D15S1", 73),
    ("D24S8", 75),
    ("D24X8", 77),
    ("D24X4S4", 79),
    ("D16", 80),
    ("D32F_LOCKABLE", 82),
    ("D24FS8", 83),
    ("L16", 81),
    ("VERTEXDATA", 100),
    ("INDEX16", 101),
    ("INDEX32", 102),
    ("Q16W16V16U16", 110),
    ("MULTI2_ARGB8", fourcc(b"MET1")),
    ("R16F", 111),
    ("G16R16F", 112),
    ("A16B16G16R16F", 113),
    ("R32F", 114),
    ("G32R32F", 115),
    ("A32B32G32R32F", 116),
    ("CxV8U8", 117),
];

struct Entry {
    id: i32,
    name: &'static str,
    class: u8,
    ty: u8,
    count: u32,
}

const fn e(id: i32, name: &'static str, class: u8, ty: u8, count: u32) -> Entry {
    Entry {
        id,
        name,
        class,
        ty,
        count,
    }
}

/// `kSemanticTable` (0x1800B2FA0): matched by semantic, with per-semantic exceptions.
const SEMANTICS: [Entry; 56] = [
    e(0x00, "World", 2, 3, 16),
    e(0x01, "WorldInverse", 2, 3, 16),
    e(0x02, "WorldTranspose", 2, 3, 16),
    e(0x03, "WorldInverseTranspose", 2, 3, 16),
    e(0x04, "View", 2, 3, 16),
    e(0x05, "ViewInverse", 2, 3, 16),
    e(0x06, "ViewTranspose", 2, 3, 16),
    e(0x07, "ViewInverseTranspose", 2, 3, 16),
    e(0x08, "Projection", 2, 3, 16),
    e(0x09, "ProjectionInverse", 2, 3, 16),
    e(0x0A, "ProjectionTranspose", 2, 3, 16),
    e(0x0B, "ProjectionInverseTranspose", 2, 3, 16),
    e(0x0C, "WorldView", 2, 3, 16),
    e(0x0D, "WorldViewInverse", 2, 3, 16),
    e(0x0E, "WorldViewTranspose", 2, 3, 16),
    e(0x0F, "WorldViewInverseTranspose", 2, 3, 16),
    e(0x10, "ViewProjection", 2, 3, 16),
    e(0x11, "ViewProjectionInverse", 2, 3, 16),
    e(0x12, "ViewProjectionTranspose", 2, 3, 16),
    e(0x13, "ViewProjectionInverseTranspose", 2, 3, 16),
    e(0x14, "WorldViewProjection", 2, 3, 16),
    e(0x15, "WorldViewProjectionInverse", 2, 3, 16),
    e(0x16, "WorldViewProjectionTranspose", 2, 3, 16),
    e(0x17, "WorldViewProjectionInverseTranspose", 2, 3, 16),
    e(0x18, "Diffuse", 1, 3, 4),
    e(0x19, "Ambient", 1, 3, 4),
    e(0x1A, "Emissive", 1, 3, 4),
    e(0x1B, "Specular", 1, 3, 4),
    e(0x1F, "Position", 1, 3, 4),
    e(0x20, "Direction", 1, 3, 4),
    e(0x1C, "ToonColor", 1, 3, 4),
    e(0x1D, "EdgeColor", 1, 3, 4),
    e(0x1E, "SpecularPower", 1, 3, 255),
    e(0x21, "ViewportPixelSize", 1, 3, 2),
    e(0x22, "Time", 0, 3, 1),
    e(0x23, "ElapsedTime", 0, 3, 1),
    e(0x24, "Time2", 0, 3, 1),
    e(0x25, "ElapsedTime2", 0, 3, 1),
    e(0x26, "RenderColorTarget", 4, 5, 0),
    e(0x27, "RenderDepthStencilTarget", 4, 5, 0),
    e(0x28, "ControlObject", 1, 3, 255),
    e(0x29, "MaterialTexture", 4, 5, 0),
    e(0x2A, "MaterialSphereMap", 4, 5, 0),
    e(0x2B, "MaterialToonTexture", 4, 5, 0),
    e(0x2F, "MousePosition", 1, 3, 2),
    e(0x30, "LeftMouseDown", 1, 3, 4),
    e(0x31, "MiddleMouseDown", 1, 3, 4),
    e(0x32, "RightMouseDown", 1, 3, 4),
    e(0x2D, "AnimatedTexture", 4, 5, 0),
    e(0x2E, "OffScreenRenderTarget", 4, 5, 0),
    e(0x33, "TextureValue", 1, 3, 4),
    e(0x4A, "AddingTexture", 1, 3, 4),
    e(0x4B, "MultiplyingTexture", 1, 3, 4),
    e(0x4C, "AddingSphereTexture", 1, 3, 4),
    e(0x4D, "MultiplyingSphereTexture", 1, 3, 4),
    e(0x4E, "GroundShadowColor", 1, 3, 4),
];

/// `kNameTable` (0x1800B36A0): matched by parameter name, strictly.
const NAMES: [Entry; 24] = [
    e(0x34, "matWorld", 2, 3, 16),
    e(0x14, "matWorldViewProj", 2, 3, 16),
    e(0x35, "matLightViewProj", 2, 3, 16),
    e(0x36, "matRotate", 2, 3, 16),
    e(0x39, "EgColor", 1, 3, 4),
    e(0x1C, "ToonColor", 1, 3, 4),
    e(0x37, "LightDir", 1, 3, 4),
    e(0x3A, "SpcColor", 1, 3, 4),
    e(0x38, "Place", 1, 3, 4),
    e(0x3B, "DifColor", 1, 3, 4),
    e(0x3C, "parthf", 0, 1, 1),
    e(0x3D, "spadd", 0, 1, 1),
    e(0x3E, "transp", 0, 1, 1),
    e(0x3F, "use_texture", 0, 1, 1),
    e(0x40, "use_spheremap", 0, 1, 1),
    e(0x41, "use_subtexture", 0, 1, 1),
    e(0x42, "use_toon", 0, 1, 1),
    e(0x43, "VertexCount", 0, 2, 1),
    e(0x44, "SubsetCount", 0, 2, 1),
    e(0x45, "opadd", 0, 1, 1),
    e(0x46, "TexCAdd", 1, 3, 4),
    e(0x47, "TexCMul", 1, 3, 4),
    e(0x48, "SphCAdd", 1, 3, 4),
    e(0x49, "SphCMul", 1, 3, 4),
];

/// Whether `name` is in the parameter-name table (the plan lists such parameters).
pub fn in_name_table(name: &str) -> bool {
    NAMES.iter().any(|n| n.name.eq_ignore_ascii_case(name))
}

pub const SEM_RENDER_COLOR: i32 = 0x26;
pub const SEM_RENDER_DEPTH: i32 = 0x27;
pub const SEM_CONTROL: i32 = 0x28;
pub const SEM_TEXTURE: i32 = 0x2C;
pub const SEM_ANIMATED: i32 = 0x2D;
pub const SEM_OFFSCREEN: i32 = 0x2E;
pub const SEM_TEXTURE_VALUE: i32 = 0x33;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum TexKind {
    Plain,
    Cube,
    Volume,
}

/// A texture the runtime created: what `GetLevelDesc(0)` and `GetLevelCount` report.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Texture {
    pub kind: TexKind,
    pub width: u32,
    pub height: u32,
    pub levels: u32,
    pub format: u32,
    /// D3DPOOL: 0 default, 1 managed.
    pub pool: u32,
    pub usage: u32,
}

impl Texture {
    pub fn is_render_target(&self) -> bool {
        self.usage & 1 != 0
    }
}

/// `SasResource`.
#[derive(Clone, Debug)]
pub struct Resource {
    pub param: usize,
    pub name: String,
    pub semantic: i32,
    pub texture_type: i32,
    pub req_width: i32,
    pub req_height: i32,
    pub req_depth: i32,
    pub mip_levels: i32,
    pub tex_width: i32,
    pub tex_height: i32,
    pub tex_mips: i32,
    pub default_pool: bool,
    pub format: u32,
    pub clear_color: u32,
    pub clear_depth: f32,
    pub anti_alias: bool,
    pub has_clear_color: bool,
    pub has_clear_depth: bool,
    pub default_effect: Vec<(String, String)>,
    pub resource_name: String,
    /// The file `resource_name` names, for the texture load.
    pub resource_file: Option<std::path::PathBuf>,
    pub offset: f32,
    pub speed: f32,
    pub seek_variable: String,
    pub texture_value_name: String,
    pub texture_value_elements: i32,
    pub function_name: String,
    pub function_target: String,
    pub texture: Option<Texture>,
    /// The depth surface of a depth target: width, height, format.
    pub surface: Option<(u32, u32, u32)>,
    pub offscreen_depth: Option<(u32, u32, u32)>,
}

impl Resource {
    fn new(param: usize, name: &str, semantic: i32, texture_type: i32) -> Resource {
        Resource {
            param,
            name: name.to_string(),
            semantic,
            texture_type,
            req_width: 0,
            req_height: 0,
            req_depth: 0,
            mip_levels: 1,
            tex_width: -1,
            tex_height: -1,
            tex_mips: -1,
            default_pool: false,
            format: fmt::UNKNOWN,
            clear_color: 0,
            clear_depth: 0.0,
            anti_alias: false,
            has_clear_color: false,
            has_clear_depth: false,
            default_effect: Vec::new(),
            resource_name: String::new(),
            resource_file: None,
            offset: 0.0,
            speed: 1.0,
            seek_variable: String::new(),
            texture_value_name: String::new(),
            texture_value_elements: 0,
            function_name: String::new(),
            function_target: String::new(),
            texture: None,
            surface: None,
            offscreen_depth: None,
        }
    }
}

pub struct Control {
    pub param: usize,
    pub object: String,
    pub item: String,
}

pub const CMD_PASS: u8 = 0;
pub const CMD_RT0: u8 = 1;
pub const CMD_DEPTH: u8 = 5;
pub const CMD_CLEAR_SET_COLOR: u8 = 6;
pub const CMD_CLEAR_SET_DEPTH: u8 = 7;
pub const CMD_CLEAR: u8 = 8;
pub const CMD_DRAW_GEOMETRY: u8 = 10;
pub const CMD_DRAW_BUFFER: u8 = 11;
pub const CMD_SCRIPT_EXTERNAL: u8 = 12;
pub const CMD_LOOP_BY_COUNT: u8 = 13;
pub const CMD_LOOP_GET_INDEX: u8 = 14;
pub const CMD_LOOP_END: u8 = 15;

pub const CMD_NAMES: [&str; 16] = [
    "Pass",
    "RenderColorTarget0",
    "RenderColorTarget1",
    "RenderColorTarget2",
    "RenderColorTarget3",
    "RenderDepthStencilTarget",
    "ClearSetColor",
    "ClearSetDepth",
    "Clear",
    "ClearEx",
    "DrawGeometry",
    "DrawBuffer",
    "ScriptExternal",
    "LoopByCount",
    "LoopGetIndex",
    "LoopEnd",
];

/// `SasScriptCmd`.
#[derive(Clone, Debug)]
pub struct Cmd {
    pub id: u8,
    pub value: i32,
    pub param: Option<usize>,
    pub text: String,
}

pub struct PassRec {
    pub fx: usize,
    pub name: String,
    pub script: Option<String>,
    pub index: i32,
    pub needs_psize15: bool,
    pub custom_shaders: bool,
    pub shader_mix_ok: bool,
    pub cmds: Vec<Cmd>,
}

pub struct TechRec {
    /// Index into `Fx::techniques` (the handle).
    pub fx: usize,
    pub name: String,
    pub mmd_pass: i32,
    pub use_texture: i8,
    pub use_spheremap: i8,
    pub use_toon: i8,
    pub hardware_ok: bool,
    pub shader_mix_ok: bool,
    pub shader_caps_ok: bool,
    pub script: Option<String>,
    pub empty: bool,
    pub all_subsets: bool,
    pub subsets: std::collections::BTreeMap<i32, i32>,
    pub passes: Vec<PassRec>,
    pub cmds: Vec<Cmd>,
}

/// `SasEffect`.
pub struct Sas {
    pub fx: Fx,
    pub path: String,
    pub log: String,
    pub has_errors: bool,
    pub run_failed: bool,
    pub draws_geometry: bool,
    pub script_class: i32,
    pub script_order: i32,
    pub post_effect: bool,
    pub technique_order: Vec<usize>,
    pub techniques: Vec<TechRec>,
    pub resources: Vec<Resource>,
    pub controls: Vec<Control>,
    /// The texture bound to each parameter (`SetTexture`), an index into `resources`.
    pub bound: Vec<Option<usize>>,
}

/// Where the effect lives, for `_fullpath` and the existence checks.
pub struct Location<'a> {
    /// The corpus root on this host.
    pub root: &'a Path,
    /// The effect's directory below the root, `/`-separated, empty for the root itself.
    pub dir: String,
}

impl Location<'_> {
    /// `_fullpath` against the effect directory, written as `<root>/...`, and whether the
    /// file exists (matched without case, as on Windows).
    fn fullpath(&self, value: &str) -> (String, Option<std::path::PathBuf>) {
        let mut parts: Vec<&str> = self.dir.split('/').filter(|p| !p.is_empty()).collect();
        for part in value.split(['/', '\\']) {
            match part {
                "" | "." => {}
                ".." => {
                    parts.pop();
                }
                p => parts.push(p),
            }
        }
        let rel = parts.join("/");
        let file = mds_fx::preprocess::resolve_ci(self.root, &rel).filter(|p| p.is_file());
        (format!("<root>/{rel}"), file)
    }
}

/// D3D sizes of the fixed device.
pub const BACKBUFFER: (i32, i32) = (1000, 600);

/// The result of `MmeEngineLoadEffectFile`: the parsed model, or the error text.
pub fn parse(fx: Fx, path: &str, loc: &Location) -> Result<Sas, String> {
    let mut sas = Sas {
        bound: vec![None; fx.params.len()],
        technique_order: (0..fx.techniques.len()).collect(),
        fx,
        path: path.to_string(),
        log: String::new(),
        has_errors: false,
        run_failed: false,
        draws_geometry: false,
        script_class: 0,
        script_order: 0,
        post_effect: false,
        techniques: Vec::new(),
        resources: Vec::new(),
        controls: Vec::new(),
    };
    if sas.standards_global().is_err() {
        return Err(sas.log);
    }
    sas.post_effect = sas.script_class != 0 && sas.script_order == 2;
    sas.validate_parameters(loc);
    let mut seen = Vec::new();
    for &t in &sas.technique_order {
        if !seen.contains(&t) {
            seen.push(t);
        }
    }
    for t in seen {
        if sas.scan_technique(t) {
            return Err(sas.log);
        }
    }
    for i in 0..sas.resources.len() {
        sas.ensure_texture(i);
    }
    if sas.has_errors {
        return Err(sas.log);
    }
    Ok(sas)
}

impl Sas {
    fn logf(&mut self, s: String) {
        self.log.push_str(&s);
    }

    /// `SasGetAnnotationString` with mode 0, 1 (error when missing), or 2 (warning).
    fn ann_string(&mut self, owner: &Item, name: &str, mode: u8) -> Option<String> {
        let Some(a) = owner.annotation(name) else {
            if mode == 1 {
                self.logf(format!(
                    "Error: annotation '{name}' is not found. (parameter: {})\n",
                    owner.name
                ));
                self.has_errors = true;
            } else if mode == 2 {
                self.logf(format!(
                    "Warning: annotation '{name}' is not found. ignored. (parameter: {})\n",
                    owner.name
                ));
            }
            return None;
        };
        match a.get_string() {
            Some(s) => Some(s.to_string()),
            None => {
                self.logf(format!(
                    "Error: type of annotation '{name}' is invalid. (parameter: {})\n",
                    owner.name
                ));
                self.has_errors = true;
                None
            }
        }
    }

    fn standards_global(&mut self) -> Result<(), ()> {
        let Some(i) = self
            .fx
            .params
            .iter()
            .position(|p| p.semantic.eq_ignore_ascii_case("STANDARDSGLOBAL"))
        else {
            return Ok(());
        };
        let p = self.fx.params[i].clone();
        let name = &p.name;
        let version = p.get_float().unwrap_or(0.0);
        if version <= 0.0 {
            self.logf(format!(
                "Error: SAS version is invalid. (parameter: '{name}')\n"
            ));
            return Err(());
        }
        if version != 0.8f32 {
            self.logf(format!(
                "Error: SAS version '{}' is not supported. (parameter: '{name}')\n",
                crate::plan::fmt_g(f64::from(version), 6)
            ));
            return Err(());
        }
        if let Some(out) = self.ann_string(&p, "ScriptOutput", 0) {
            if !out.eq_ignore_ascii_case("color") {
                self.logf(format!(
                    "Error: output type '{out}' is not supported. (parameter: {name})\n"
                ));
                return Err(());
            }
        }
        if let Some(c) = self.ann_string(&p, "ScriptClass", 0) {
            self.script_class = match c.to_ascii_lowercase().as_str() {
                "object" => 0,
                "scene" => 1,
                "sceneorobject" => 2,
                _ => {
                    self.logf(format!(
                        "Error: effect class '{c}' is not supported. (parameter: {name})\n"
                    ));
                    return Err(());
                }
            };
        }
        if let Some(o) = self.ann_string(&p, "ScriptOrder", 0) {
            self.script_order = match o.to_ascii_lowercase().as_str() {
                "standard" => 0,
                "preprocess" => 1,
                "postprocess" => 2,
                _ => {
                    self.logf(format!(
                        "Error: effect order '{o}' is not supported. (parameter: {name})\n"
                    ));
                    return Err(());
                }
            };
        }
        if let Some(script) = self.ann_string(&p, "Script", 0) {
            self.technique_order.clear();
            let normalized = normalize_global_script(&script);
            self.global_script(&normalized, name)?;
        }
        Ok(())
    }

    /// `SasParseStandardsGlobalScript`.
    fn global_script(&mut self, script: &str, pname: &str) -> Result<(), ()> {
        let mut rest = script;
        while !rest.is_empty() {
            let (Some(eq), Some(semi)) = (rest.find('='), rest.find(';')) else {
                break;
            };
            if eq > semi {
                break;
            }
            let command = &rest[..eq];
            if command.is_empty()
                || !command
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b == b'_')
            {
                break;
            }
            let whole = &rest[..semi];
            let value = &rest[eq + 1..semi];
            rest = &rest[semi + 1..];
            if !command.eq_ignore_ascii_case("technique") {
                self.logf(format!(
                    "Warning: unsupported script command: {whole}  (parameter: {pname})\n"
                ));
                continue;
            }
            match value.find('?') {
                None => {
                    if !value.is_empty() {
                        match self.fx.technique_by_name(value) {
                            Some(h) => self.technique_order.push(h),
                            None => {
                                self.logf(format!(
                                    "Error: unknown technique name: {value}  (parameter: {pname})\n"
                                ));
                                self.has_errors = true;
                                return Err(());
                            }
                        }
                    }
                }
                Some(q) => {
                    for name in value[q + 1..].split(':') {
                        if name.is_empty() {
                            continue;
                        }
                        match self.fx.technique_by_name(name) {
                            Some(h) => self.technique_order.push(h),
                            None => self.logf(format!(
                                "Warning: unknown technique name: {name}  (parameter: {pname})\n"
                            )),
                        }
                    }
                }
            }
        }
        if !rest.is_empty() {
            let tail = rest.split(';').next().unwrap_or("");
            self.logf(format!(
                "Error: script syntax error: {tail}  (parameter: {pname})\n"
            ));
            self.has_errors = true;
            return Err(());
        }
        Ok(())
    }

    /// The parameter walk of FUN_18000c470.
    fn validate_parameters(&mut self, loc: &Location) {
        for i in 0..self.fx.params.len() {
            let p = self.fx.params[i].clone();
            let mut matched = false;
            let mut invalid = false;
            let mut id = 0;
            if let Some(e) = SEMANTICS
                .iter()
                .find(|e| e.name.eq_ignore_ascii_case(&p.semantic))
            {
                let skip = p.desc.class == CLASS_OBJECT
                    && matches!(e.id, 0x18 | 0x19 | 0x1A | 0x1B | 0x1E | 0x1F | 0x20);
                if !skip {
                    matched = true;
                    id = e.id;
                    if !valid_for(e, &p.desc, false) {
                        invalid = true;
                        self.logf(format!(
                            "Error: type of parameter '{}' is invalid (semantic: {}).\n",
                            p.name, e.name
                        ));
                    } else if self.register(id, i, loc) {
                        invalid = true;
                    }
                }
            }
            if !matched {
                if let Some(e) = NAMES.iter().find(|e| e.name.eq_ignore_ascii_case(&p.name)) {
                    if valid_for(e, &p.desc, true) {
                        matched = true;
                        id = e.id;
                        if self.register(id, i, loc) {
                            invalid = true;
                        }
                    } else if (0x3F..=0x42).contains(&e.id) {
                        invalid = true;
                        self.logf(format!(
                            "Error: type of parameter '{}' is invalid.\n",
                            p.name
                        ));
                    }
                }
            }
            if !matched && matches!(p.desc.ty, 5 | 7 | 8 | 9) && self.register(SEM_TEXTURE, i, loc)
            {
                invalid = true;
            }
            if matched && id == SEM_CONTROL && !(p.annotation("Name").is_none() && p.shared) {
                if let Some(object) = self.ann_string(&p, "Name", 1) {
                    let item = self.ann_string(&p, "Item", 0).unwrap_or_default();
                    self.controls.push(Control {
                        param: i,
                        object,
                        item,
                    });
                }
            }
            if invalid {
                self.has_errors = true;
            }
        }
    }

    /// `SasRegisterSemantic`: true on a hard error.
    fn register(&mut self, id: i32, param: usize, loc: &Location) -> bool {
        match id {
            SEM_RENDER_COLOR | SEM_RENDER_DEPTH | SEM_TEXTURE | SEM_ANIMATED | SEM_OFFSCREEN
            | SEM_TEXTURE_VALUE => self.build_resource(id, param, loc) == 1,
            _ => false,
        }
    }

    fn fail(&mut self, line: String) -> i32 {
        self.logf(line);
        self.has_errors = true;
        1
    }

    /// `SasBuildResourceObject`: 0 registered, 1 hard error, 2 skipped.
    fn build_resource(&mut self, semantic: i32, param: usize, loc: &Location) -> i32 {
        let p = self.fx.params[param].clone();
        let name = p.name.as_str();
        if p.annotations.is_empty() && p.shared {
            return 2;
        }
        let mut res = Resource::new(param, name, semantic, i32::from(p.desc.ty));

        if semantic == SEM_ANIMATED {
            if p.annotation("ResourceName").is_none() && p.shared {
                return 2;
            }
            let Some(file) = self.ann_string(&p, "ResourceName", 1) else {
                return 1;
            };
            let (resolved, found) = loc.fullpath(&file);
            if found.is_none() {
                return self.fail(format!(
                    "Error: failed to open file: {file} (parameter: {name})\n"
                ));
            }
            let ext = file
                .get(file.len().saturating_sub(4)..)
                .unwrap_or("")
                .to_ascii_lowercase();
            if file.len() < 4 || (ext != ".png" && ext != ".gif") {
                return self.fail(format!(
                    "Error: unsupported file type: {file} (parameter: '{name}')\n"
                ));
            }
            self.logf(format!("Loading texture file: {resolved}\n"));
            // ponytail: the GIF/PNG decoder of anime_texture.cpp is not ported; an existing
            // file is taken to decode, which holds for every corpus effect.
            for (key, out) in [("Offset", &mut res.offset), ("Speed", &mut res.speed)] {
                if let Some(a) = p.annotation(key) {
                    match a.get_float() {
                        Some(v) => *out = v,
                        None => {
                            return self.fail(format!(
                                "Error: failed to get '{key}' (parameter: '{name}')\n"
                            ))
                        }
                    }
                }
            }
            if let Some(seek) = self.ann_string(&p, "SeekVariable", 0) {
                match self.fx.param_by_name(&seek) {
                    None => {
                        return self.fail(format!(
                            "Error: unknown parameter name: {seek} (parameter: '{name}')\n"
                        ))
                    }
                    Some(s) if !matches!(self.fx.params[s].desc.ty, 1..=3) => {
                        return self.fail(format!(
                            "Error: type of SeekVariable must be 'float': {seek} (parameter: '{name}')\n"
                        ))
                    }
                    Some(_) => {}
                }
                res.seek_variable = seek;
            }
            res.resource_name = resolved;
            self.resources.push(res);
            return 0;
        }

        if semantic == SEM_TEXTURE_VALUE {
            if p.annotation("TextureName").is_none() && p.shared {
                return 2;
            }
            let Some(tex) = self.ann_string(&p, "TextureName", 1) else {
                return 1;
            };
            match self.fx.param_by_name(&tex) {
                None => {
                    return self.fail(format!(
                        "Error: unknown texture name: {tex} (parameter: '{name}')\n"
                    ))
                }
                Some(t) if !matches!(self.fx.params[t].desc.ty, 5 | 7) => {
                    return self.fail(format!(
                        "Error: invalid texture type: {tex} (parameter: '{name}')\n"
                    ))
                }
                Some(_) => {}
            }
            res.texture_value_name = tex;
            res.texture_value_elements = p.desc.elements as i32;
            self.resources.push(res);
            return 0;
        }

        if let Some(rt) = self.ann_string(&p, "ResourceType", 0) {
            let resolved = match rt.to_ascii_lowercase().as_str() {
                "2d" => 7,
                "3d" => 8,
                "cube" => 9,
                _ => {
                    return self.fail(format!(
                        "Error: value of annotation 'ResourceType' is invalid: {rt}  (parameter: {name})\n"
                    ))
                }
            };
            if res.texture_type != 5 && res.texture_type != resolved {
                return self.fail(format!(
                    "Error: annotation 'ResourceType' conflicts with type of parameter.  (parameter: {name})\n"
                ));
            }
            res.texture_type = resolved;
        }
        let tt = res.texture_type;
        if (semantic == SEM_RENDER_COLOR && tt == 8)
            || ((semantic == SEM_RENDER_DEPTH || semantic == SEM_OFFSCREEN) && (tt == 8 || tt == 9))
        {
            return self.fail(format!(
                "Error: invalid texture type.  (parameter: {name})\n"
            ));
        }

        let vr = p.annotation("ViewportRatio");
        let dim = p.annotation("Dimensions");
        let whd_names = ["Width", "Height", "Depth"];
        let whd = whd_names.map(|n| p.annotation(n));
        let groups = usize::from(vr.is_some())
            + usize::from(dim.is_some())
            + usize::from(whd.iter().any(Option::is_some));
        if groups > 1 {
            return self.fail(format!(
                "Error: annotations 'ViewportRatio', 'Dimensions' and ('Width','Height','Depth') are mutually exclusive.  (parameter: '{name}')\n"
            ));
        }
        let mut ratio = [1.0f32, 1.0];
        let mut has_ratio = false;
        let mut dims = [-1i32; 3];
        let mut has_dims = false;
        let mut sizes = [-1i32; 3];
        let mut has_whd = false;
        if let Some(a) = vr {
            let Some(v) = a.get_vector([0.0; 4]) else {
                return self.fail(format!(
                    "Error: failed to get 'ViewportRatio' (parameter: '{name}')\n"
                ));
            };
            ratio = [v[0], v[1]];
            has_ratio = true;
        } else if let Some(a) = dim {
            let ok = (1..=3).contains(&a.desc.columns);
            let Some(d) = a.get_array(3).filter(|_| ok) else {
                return self.fail(format!(
                    "Error: failed to get 'Dimensions' (parameter: '{name}')\n"
                ));
            };
            for (k, n) in d.iter().enumerate() {
                dims[k] = n.int().max(-1);
                if dims[k] < 0 {
                    dims[k] = -1;
                }
            }
            has_dims = true;
        } else {
            for k in 0..3 {
                if let Some(a) = whd[k] {
                    has_whd = true;
                    let Some(v) = a.get_int() else {
                        return self.fail(format!(
                            "Error: failed to get '{}' (parameter: '{name}')\n",
                            whd_names[k]
                        ));
                    };
                    sizes[k] = if v >= 0 { v } else { -1 };
                }
            }
        }
        let render = matches!(
            semantic,
            SEM_RENDER_COLOR | SEM_RENDER_DEPTH | SEM_OFFSCREEN
        );
        if render {
            let raw_w = if has_dims { dims[0] } else { sizes[0] };
            let raw_h = if has_dims { dims[1] } else { sizes[1] };
            if tt == 9 {
                if raw_w == -1 && !has_ratio {
                    if has_dims {
                        dims[0] = 256;
                    } else {
                        sizes[0] = 256;
                        has_whd = true;
                    }
                }
            } else if raw_w == -1 && raw_h == -1 && !has_ratio {
                has_ratio = true;
                ratio = [1.0, 1.0];
            }
        }
        let (sw, sh) = BACKBUFFER;
        if has_ratio {
            res.req_width = (sw as f32 * ratio[0]) as i32;
            res.req_height = (sh as f32 * ratio[1]) as i32;
            res.req_depth = 1;
        } else if has_dims {
            res.req_width = dims[0];
            res.req_height = dims[1];
            res.req_depth = if dims[2] > 0 { dims[2] } else { 1 };
        } else if has_whd {
            res.req_width = sizes[0];
            res.req_height = sizes[1];
            res.req_depth = if sizes[2] > 0 { sizes[2] } else { 1 };
        } else {
            res.req_width = sw;
            res.req_height = sh;
            res.req_depth = 1;
        }
        if res.req_width <= 0 {
            res.req_width = sw;
        }
        if res.req_height <= 0 {
            res.req_height = sh;
        }
        if has_dims {
            res.tex_width = dims[0];
            res.tex_height = dims[1];
        } else if has_whd {
            res.tex_width = sizes[0];
            res.tex_height = sizes[1];
        } else if has_ratio {
            res.tex_width = if ratio[0] < 0.0 {
                -1
            } else {
                (sw as f32 * ratio[0]) as i32
            };
            res.tex_height = if ratio[1] < 0.0 {
                -1
            } else {
                (sh as f32 * ratio[1]) as i32
            };
        }

        let mips = p.annotation("Miplevels").or_else(|| p.annotation("Levels"));
        let mut mip_raw = -1;
        if let Some(a) = mips {
            let Some(m) = a.get_int() else {
                return self.fail(format!(
                    "Error: failed to get 'Miplevels' (parameter: '{name}')\n"
                ));
            };
            if m >= 0 {
                mip_raw = m;
            }
        } else if render {
            mip_raw = 1;
        }
        res.tex_mips = mip_raw;
        res.mip_levels = if mip_raw >= 0 { mip_raw } else { 1 };

        if let Some(f) = self.ann_string(&p, "Format", 0) {
            let lower = f.to_ascii_lowercase();
            let stripped = lower
                .strip_prefix("fmt_")
                .or_else(|| lower.strip_prefix("d3dfmt_"))
                .unwrap_or(&lower);
            match FORMATS
                .iter()
                .find(|(n, _)| n.eq_ignore_ascii_case(stripped))
            {
                Some((_, v)) => res.format = *v,
                None => {
                    let raw = if f.len() >= 4 && f[..4].eq_ignore_ascii_case("FMT_") {
                        &f[4..]
                    } else if f.len() >= 7 && f[..7].eq_ignore_ascii_case("D3DFMT_") {
                        &f[7..]
                    } else {
                        &f
                    };
                    return self.fail(format!(
                        "Error: unknown texture format: {raw}  (parameter: '{name}')\n"
                    ));
                }
            }
        } else {
            // The device's own depth stencil is D24S8.
            res.format = if semantic == SEM_RENDER_DEPTH {
                fmt::D24S8
            } else {
                fmt::A8R8G8B8
            };
        }

        if semantic == SEM_OFFSCREEN {
            self.ann_string(&p, "Description", 0);
            if let Some(de) = self.ann_string(&p, "DefaultEffect", 0) {
                for token in de.split(';') {
                    let eq = token.find('=');
                    if eq.is_none() && trim_ws(token).is_empty() {
                        continue;
                    }
                    let key = trim_ws(&token[..eq.unwrap_or(token.len())]);
                    let Some(eq) = eq.filter(|_| !key.is_empty()) else {
                        return self.fail(format!(
                            "Error: 'DefaultEffect' syntax error: {token}  (parameter: {name})\n"
                        ));
                    };
                    let value = trim_ws(&token[eq + 1..]);
                    let value = match value.to_ascii_lowercase().as_str() {
                        "" | "none" => "none".to_string(),
                        "hide" => "hide".to_string(),
                        "main_default" => "main_default".to_string(),
                        _ => {
                            let (text, found) = loc.fullpath(value);
                            if found.is_none() {
                                return self.fail(format!(
                                    "Error: failed to open file: {value} (parameter: {name})\n"
                                ));
                            }
                            text
                        }
                    };
                    res.default_effect.push((key.to_string(), value));
                }
            }
            self.logf(format!("Info: new OffScreen RenderTarget: {name}\n"));
            if let Some(a) = p.annotation("ClearColor") {
                let Some(v) = a.get_vector([1.0; 4]) else {
                    return self.fail(format!(
                        "Error: annotation 'ClearColor' is invalid. (parameter: {name})\n"
                    ));
                };
                let c = v.map(|x| (x.clamp(0.0, 1.0) * 255.0) as i32);
                res.clear_color = ((c[3] as u32) << 24)
                    | (u32::from(c[0] as u8) << 16)
                    | (u32::from(c[1] as u8) << 8)
                    | u32::from(c[2] as u8);
                res.has_clear_color = true;
            }
            if let Some(a) = p.annotation("ClearDepth") {
                let Some(z) = a.get_float() else {
                    return self.fail(format!(
                        "Error: annotation 'ClearDepth' is invalid. (parameter: {name})\n"
                    ));
                };
                res.clear_depth = z;
                res.has_clear_depth = true;
            }
            if let Some(a) = p.annotation("AntiAlias") {
                let Some(v) = a.get_bool() else {
                    return self.fail(format!(
                        "Error: annotation 'ClearColor' is invalid. (parameter: {name})\n"
                    ));
                };
                res.anti_alias = v;
            }
        }

        if matches!(
            semantic,
            SEM_RENDER_COLOR | SEM_RENDER_DEPTH | SEM_TEXTURE | SEM_OFFSCREEN
        ) {
            if let Some(file) = self.ann_string(&p, "ResourceName", 0) {
                let (text, found) = loc.fullpath(&file);
                if found.is_none() {
                    self.logf(format!(
                        "Error: failed to open file: {file} (parameter: {name})\n"
                    ));
                    return 1;
                }
                res.resource_name = text;
                res.resource_file = found;
            }
        }
        res.function_name = self.ann_string(&p, "Function", 0).unwrap_or_default();
        res.function_target = self
            .ann_string(&p, "Target", 0)
            .unwrap_or_else(|| "tx_1_0".to_string());
        if semantic == SEM_TEXTURE && res.resource_name.is_empty() && res.function_name.is_empty() {
            if !p.shared {
                self.logf(format!("Warning: texture '{name}' is not available.\n"));
            }
            return 2;
        }
        self.resources.push(res);
        0
    }

    /// `SasEnsureResourceTexture`, modelled: the textures and surfaces this device creates.
    fn ensure_texture(&mut self, i: usize) {
        let res = &self.resources[i];
        if matches!(res.semantic, SEM_ANIMATED | SEM_TEXTURE_VALUE) {
            return;
        }
        if res.semantic == SEM_TEXTURE && res.resource_file.is_some() {
            let line = format!("Loading texture file: {}\n", res.resource_name);
            self.logf(line);
            let res = &self.resources[i];
            let file = res.resource_file.clone().unwrap_or_default();
            match texfile::load(
                &file,
                res.texture_type,
                res.tex_width,
                res.tex_height,
                res.tex_mips,
            ) {
                Ok(t) => {
                    let r = &mut self.resources[i];
                    r.texture = Some(t);
                    r.default_pool = false;
                    self.bound[r.param] = Some(i);
                }
                Err(e) => {
                    let name = self.resources[i].name.clone();
                    self.fail(format!(
                        "Error: failed to create texture (parameter: '{name}'): {e}\n"
                    ));
                }
            }
            return;
        }
        if res.semantic == SEM_TEXTURE && !res.function_name.is_empty() {
            // ponytail: texture shaders (`Function`) are not compiled here; no corpus effect
            // uses them. The plan then lacks the created line.
            return;
        }
        let w = if res.req_width <= 0 {
            64
        } else {
            res.req_width
        } as u32;
        let h = if res.req_height <= 0 {
            64
        } else {
            res.req_height
        } as u32;
        let mip = res.tex_mips as u32;
        let r = &mut self.resources[i];
        if r.semantic == SEM_RENDER_DEPTH {
            r.surface = Some((w, h, r.format));
            r.default_pool = true;
            r.texture = Some(Texture {
                kind: TexKind::Plain,
                width: 1,
                height: 1,
                levels: 1,
                format: fmt::A8R8G8B8,
                pool: 1,
                usage: 0,
            });
        } else {
            let rt = r.semantic == SEM_RENDER_COLOR || r.semantic == SEM_OFFSCREEN;
            let (usage, pool) = if rt { (1, 0) } else { (0, 1) };
            let tex = if r.texture_type == 9 {
                Texture {
                    kind: TexKind::Cube,
                    width: w,
                    height: w,
                    levels: levels(mip, w, w),
                    format: r.format,
                    pool,
                    usage,
                }
            } else if rt && (mip == 0 || mip == u32::MAX) {
                // CreateTexture with D3DUSAGE_AUTOGENMIPMAP reports one level.
                Texture {
                    kind: TexKind::Plain,
                    width: w,
                    height: h,
                    levels: 1,
                    format: r.format,
                    pool: 0,
                    usage: 0x401,
                }
            } else {
                Texture {
                    kind: TexKind::Plain,
                    width: w,
                    height: h,
                    levels: levels(mip, w, h),
                    format: r.format,
                    pool,
                    usage,
                }
            };
            r.texture = Some(tex);
            r.default_pool = rt;
            if r.semantic == SEM_OFFSCREEN {
                r.offscreen_depth = Some((w, h, fmt::D24S8));
            }
        }
        let param = r.param;
        self.bound[param] = Some(i);
    }

    /// FUN_1800169d0: true when the technique scan failed (the load is rejected).
    fn scan_technique(&mut self, t: usize) -> bool {
        let ft = self.fx.techniques[t].clone();
        let mut rec = TechRec {
            fx: t,
            name: ft.name.clone(),
            mmd_pass: 0,
            use_texture: -1,
            use_spheremap: -1,
            use_toon: -1,
            hardware_ok: true,
            shader_mix_ok: true,
            shader_caps_ok: true,
            script: None,
            empty: ft.passes.is_empty(),
            all_subsets: true,
            subsets: Default::default(),
            passes: Vec::new(),
            cmds: Vec::new(),
        };
        let tname = rec.name.clone();
        let mut err = false;
        for a in &ft.annotations {
            let n = a.name.to_ascii_lowercase();
            match n.as_str() {
                "mmdpass" => {
                    let Some(s) = a.get_string() else {
                        self.logf(format!(
                            "Error: type of annotation 'MmdPass' is invalid. (technique: {tname})\n"
                        ));
                        self.has_errors = true;
                        err = true;
                        continue;
                    };
                    match s.to_ascii_lowercase().as_str() {
                        "object" => rec.mmd_pass = 0,
                        "object_ss" => rec.mmd_pass = 1,
                        "shadow" => rec.mmd_pass = 2,
                        "edge" => rec.mmd_pass = 3,
                        "zplot" => rec.mmd_pass = 4,
                        _ => {
                            self.logf(format!(
                                "Error: unknown pass mode: {s}  (technique: {tname})\n"
                            ));
                            self.has_errors = true;
                            err = true;
                        }
                    }
                }
                "usetexture" | "usespheremap" | "usetoon" => {
                    let Some(v) = a.get_bool() else {
                        self.logf(format!(
                            "Error: type of annotation '{}' is invalid. (technique: {tname})\n",
                            a.name
                        ));
                        self.has_errors = true;
                        err = true;
                        continue;
                    };
                    let slot = match n.as_str() {
                        "usetexture" => &mut rec.use_texture,
                        "usespheremap" => &mut rec.use_spheremap,
                        _ => &mut rec.use_toon,
                    };
                    *slot = i8::from(v);
                }
                "subset" => {
                    let Some(s) = a.get_string() else {
                        self.logf(format!(
                            "Error: type of annotation 'Subset' is invalid. (technique: {tname})\n"
                        ));
                        self.has_errors = true;
                        err = true;
                        continue;
                    };
                    if !parse_subsets(&mut rec, s) {
                        self.logf(format!(
                            "Error: invalid subset range: '{s}' (technique: {tname})\n"
                        ));
                        self.has_errors = true;
                        err = true;
                    }
                }
                "script" => {
                    let Some(s) = a.get_string() else {
                        self.logf(format!(
                            "Error: type of annotation 'Script' is invalid. (technique: {tname})\n"
                        ));
                        self.has_errors = true;
                        err = true;
                        continue;
                    };
                    rec.script = Some(s.to_string());
                }
                _ => {}
            }
        }
        for (k, fp) in ft.passes.iter().enumerate() {
            let version = |s: &Option<(String, String)>| s.as_ref().map_or(0, |(p, _)| version(p));
            let (vs, ps) = (version(&fp.vs), version(&fp.ps));
            if vs > 0x300 || ps > 0x300 {
                rec.shader_caps_ok = false;
            }
            let mix_ok = !((vs >= 0x300 || ps >= 0x300) && vs != ps);
            if !mix_ok {
                rec.shader_mix_ok = false;
                // ponytail: the original also shows a message box here; no plan has one.
            }
            let psize15 = fp.vs.as_ref().is_some_and(|(_, f)| {
                self.fx.functions.iter().any(|(name, params)| {
                    name == f
                        && params.iter().any(|p| {
                            p.rsplit(':')
                                .next()
                                .is_some_and(|s| s.trim().eq_ignore_ascii_case("PSIZE15"))
                        })
                })
            });
            let mut pass = PassRec {
                fx: k,
                name: fp.name.clone(),
                script: None,
                index: k as i32,
                needs_psize15: psize15,
                custom_shaders: fp.vs.is_some() || fp.ps.is_some(),
                shader_mix_ok: mix_ok,
                cmds: Vec::new(),
            };
            for a in &fp.annotations {
                if a.name.eq_ignore_ascii_case("Script") {
                    match a.get_string() {
                        Some(s) => pass.script = Some(s.to_string()),
                        None => {
                            self.logf(format!(
                                "Error: type of annotation 'Script' is invalid. (pass: {}, technique: {tname})\n",
                                pass.name
                            ));
                            self.has_errors = true;
                            err = true;
                        }
                    }
                }
            }
            rec.passes.push(pass);
        }
        self.techniques.push(rec);
        let ti = self.techniques.len() - 1;
        if let Some(script) = self.techniques[ti].script.clone() {
            let mut cmds = Vec::new();
            err |= self.compile(&script, ti, None, &mut cmds);
            self.techniques[ti].cmds = cmds;
        }
        for k in 0..self.techniques[ti].passes.len() {
            if let Some(script) = self.techniques[ti].passes[k].script.clone() {
                let mut cmds = Vec::new();
                err |= self.compile(&script, ti, Some(k), &mut cmds);
                self.techniques[ti].passes[k].cmds = cmds;
            }
        }
        err
    }

    /// `SasCompileScript`: true when a hard error was logged.
    fn compile(
        &mut self,
        script: &str,
        tech: usize,
        pass: Option<usize>,
        out: &mut Vec<Cmd>,
    ) -> bool {
        let normalized = normalize_script(script);
        if normalized.is_empty() {
            return false;
        }
        let tname = self.techniques[tech].name.clone();
        let ctx = match pass {
            None => format!("(technique: {tname})"),
            Some(p) => format!(
                "(pass: {}, technique: {tname})",
                self.techniques[tech].passes[p].name
            ),
        };
        let mut errors = false;
        let mut rest = normalized.as_str();
        loop {
            if rest.is_empty() {
                break;
            }
            let Some((whole, command, value, next)) = token(rest) else {
                break;
            };
            rest = next;
            let command = command.to_ascii_lowercase();
            if !self.compile_token(&command, value, whole, tech, pass.is_some(), &ctx, out) {
                errors = true;
            }
        }
        if !rest.is_empty() {
            let tail = rest.split(';').next().unwrap_or("");
            self.logf(format!("Error: script syntax error: {tail}  {ctx}\n"));
            errors = true;
        }
        if errors {
            self.has_errors = true;
        }
        errors
    }

    #[allow(clippy::too_many_arguments)]
    fn compile_token(
        &mut self,
        command: &str,
        value: &str,
        whole: &str,
        tech: usize,
        in_pass: bool,
        ctx: &str,
        out: &mut Vec<Cmd>,
    ) -> bool {
        let mut cmd = Cmd {
            id: 0,
            value: 0,
            param: None,
            text: value.to_string(),
        };
        let target = match command {
            "rendercolortarget" | "rendercolortarget0" => Some(Some(0)),
            "rendercolortarget1" => Some(Some(1)),
            "rendercolortarget2" => Some(Some(2)),
            "rendercolortarget3" => Some(Some(3)),
            "renderdepthstenciltarget" => Some(None),
            _ => None,
        };
        if let Some(slot) = target {
            cmd.id = slot.map_or(CMD_DEPTH, |s| CMD_RT0 + s);
            if value.is_empty() {
                out.push(cmd);
                return true;
            }
            let mut name = value;
            let mut element = -1;
            if let Some(b) = value.find('[') {
                let idx = value.as_bytes().get(b + 1).copied().unwrap_or(0);
                if value.len() >= b + 3 && value.ends_with(']') && (b'0'..=b'5').contains(&idx) {
                    name = &value[..b];
                    element = i32::from(idx - b'0');
                }
            }
            let Some(param) = self.fx.param_by_name(name) else {
                self.logf(format!("Error: unknown texture name: {value}  {ctx}\n"));
                self.has_errors = true;
                return false;
            };
            let p = &self.fx.params[param];
            let t = p.desc.ty;
            let type_ok = if element >= 0 {
                t == TYPE_TEXTURE || t == TYPE_TEXTURECUBE
            } else {
                t == TYPE_TEXTURE || t == TYPE_TEXTURE2D
            };
            let (want, what) = if slot.is_some() {
                ("RENDERCOLORTARGET", "invalid render color target")
            } else {
                (
                    "RENDERDEPTHSTENCILTARGET",
                    "invalid render depth stencil target",
                )
            };
            if !type_ok || !p.semantic.eq_ignore_ascii_case(want) {
                self.logf(format!("Error: {what}: {value}  {ctx}\n"));
                self.has_errors = true;
                return false;
            }
            cmd.param = Some(param);
            cmd.value = element;
            out.push(cmd);
            return true;
        }
        match command {
            "clearsetcolor" | "clearsetdepth" => {
                let color = command == "clearsetcolor";
                let ok = self.fx.param_by_name(value).filter(|&i| {
                    let d = &self.fx.params[i].desc;
                    matches!(d.ty, 1..=3) && (!color || (d.class == CLASS_VECTOR && d.columns == 4))
                });
                match ok {
                    Some(i) => {
                        cmd.id = if color {
                            CMD_CLEAR_SET_COLOR
                        } else {
                            CMD_CLEAR_SET_DEPTH
                        };
                        cmd.param = Some(i);
                        out.push(cmd);
                        true
                    }
                    None => {
                        let what = if color {
                            "clear color must be 'float4'"
                        } else {
                            "clear depth must be 'float'"
                        };
                        self.logf(format!("Error: type of {what}: {value}  {ctx}\n"));
                        self.has_errors = true;
                        false
                    }
                }
            }
            "clear" => {
                if value.eq_ignore_ascii_case("color") {
                    cmd.id = CMD_CLEAR;
                    cmd.value = 1;
                    out.push(cmd);
                } else if value.eq_ignore_ascii_case("depth") {
                    cmd.id = CMD_CLEAR;
                    cmd.value = 6;
                    out.push(cmd);
                } else {
                    self.logf(format!("Warning: unknown clear type: {whole}  {ctx}\n"));
                }
                true
            }
            "scriptexternal" if !in_pass => {
                if value.eq_ignore_ascii_case("color") {
                    cmd.id = CMD_SCRIPT_EXTERNAL;
                    out.push(cmd);
                } else {
                    self.logf(format!(
                        "Warning: unknown script external type: {value}  {ctx}\n"
                    ));
                }
                true
            }
            "loopbycount" | "loopgetindex" if !in_pass => {
                let count = command == "loopbycount";
                let ok = self.fx.param_by_name(value).filter(|&i| {
                    let d = &self.fx.params[i].desc;
                    d.class <= CLASS_VECTOR && d.columns == 1 && matches!(d.ty, 1..=3)
                });
                match ok {
                    Some(i) => {
                        cmd.id = if count {
                            CMD_LOOP_BY_COUNT
                        } else {
                            CMD_LOOP_GET_INDEX
                        };
                        cmd.param = Some(i);
                        out.push(cmd);
                        true
                    }
                    None => {
                        let what = if count { "count" } else { "index" };
                        self.logf(format!(
                            "Error: type of loop {what} must be 'int' or 'bool': {value}  {ctx}\n"
                        ));
                        self.has_errors = true;
                        false
                    }
                }
            }
            "loopend" if !in_pass => {
                cmd.id = CMD_LOOP_END;
                out.push(cmd);
                true
            }
            "draw" if in_pass => {
                if value.eq_ignore_ascii_case("geometry") {
                    cmd.id = CMD_DRAW_GEOMETRY;
                    self.draws_geometry = true;
                    out.push(cmd);
                } else if value.eq_ignore_ascii_case("buffer") {
                    cmd.id = CMD_DRAW_BUFFER;
                    out.push(cmd);
                } else {
                    self.logf(format!("Warning: unknown draw type: {whole}  {ctx}\n"));
                }
                true
            }
            "pass" if !in_pass => {
                match self.techniques[tech]
                    .passes
                    .iter()
                    .find(|p| p.name == value)
                {
                    Some(p) => {
                        cmd.id = CMD_PASS;
                        cmd.value = p.index;
                        out.push(cmd);
                        true
                    }
                    None => {
                        self.logf(format!("Error: unknown pass name: {value}  {ctx}\n"));
                        self.has_errors = true;
                        false
                    }
                }
            }
            "renderport" => true,
            _ => {
                self.logf(format!(
                    "Warning: unsupported script command: {whole}  {ctx}\n"
                ));
                true
            }
        }
    }
}

/// The shader model of a profile as `D3DXGetShaderVersion` truncated to 16 bits: `vs_3_0` is
/// 0x300, `ps_2_a` and `ps_2_b` compile to `ps_2_x` (0x201).
fn version(profile: &str) -> u32 {
    let b = profile.as_bytes();
    let digit = |i: usize| {
        b.get(i).map_or(0, |c| match c {
            b'0'..=b'9' => u32::from(c - b'0'),
            b'a' | b'b' | b'x' => 1,
            _ => 0,
        })
    };
    (digit(3) << 8) | digit(5)
}

/// The mip count D3DX creates: 0 or `D3DX_DEFAULT` give the full chain.
pub fn levels(mip: u32, w: u32, h: u32) -> u32 {
    let full = 32 - w.max(h).max(1).leading_zeros();
    if mip == 0 || mip == u32::MAX {
        full
    } else {
        mip.min(full)
    }
}

fn valid_for(e: &Entry, d: &Desc, strict: bool) -> bool {
    let mut cls = d.class;
    if cls == CLASS_MATRIX_COLUMNS {
        cls = CLASS_MATRIX_ROWS;
    }
    let count = d.rows * d.columns;
    if cls == CLASS_MATRIX_ROWS && d.rows != 4 {
        return false;
    }
    if cls == CLASS_VECTOR && d.rows != 1 {
        return false;
    }
    if e.class != cls {
        if strict {
            return false;
        }
        let ok = match e.id {
            0x1E => cls == 0,
            0x28 => cls == 0 || cls == 2,
            _ => e.class == 0 && cls == 1 && count == 1,
        };
        if !ok {
            return false;
        }
    }
    if e.ty != d.ty {
        let ok =
            (e.ty == 5 && d.ty == 7) || (!strict && e.id == 0x28 && d.ty == 1 && d.columns == 1);
        if !ok {
            return false;
        }
    }
    if e.count != 255 && e.count != count {
        let ok = !strict
            && match e.id {
                0x1E => (1..=4).contains(&count) && count != 2,
                0x28 => (1..=4).contains(&count) && count != 2 && count != 16,
                0x18..=0x1D | 0x1F | 0x20 => e.count == 4 && count == 3,
                0x30..=0x32 => true,
                _ => false,
            };
        if !ok {
            return false;
        }
    }
    !(!strict && d.elements != 0 && e.id != 0x33)
}

fn trim_ws(s: &str) -> &str {
    s.trim_matches([' ', '\t', '\x0b', '\r', '\n'])
}

fn is_space(b: u8) -> bool {
    matches!(b, b' ' | b'\t' | b'\n' | b'\x0b' | b'\x0c' | b'\r')
}

/// The STANDARDSGLOBAL normalization: append ';', drop all whitespace, fold `;;+`, strip a
/// leading ';'.
fn normalize_global_script(s: &str) -> String {
    let mut out = String::new();
    for c in s.chars().chain(std::iter::once(';')) {
        if c.is_ascii() && is_space(c as u8) {
            continue;
        }
        if c == ';' && out.ends_with(';') {
            continue;
        }
        out.push(c);
    }
    match out.strip_prefix(';') {
        Some(s) => s.to_string(),
        None => out,
    }
}

/// `SasNormalizeScriptExec`: append ';', fold `\s*(;\s*)+` to ';', strip a leading ';'.
fn normalize_script(s: &str) -> String {
    let s = format!("{s};");
    let b = s.as_bytes();
    let mut out = Vec::with_capacity(b.len());
    let mut i = 0;
    while i < b.len() {
        let mut j = i;
        while j < b.len() && is_space(b[j]) {
            j += 1;
        }
        if j < b.len() && b[j] == b';' {
            let mut k = j;
            while k < b.len() && (b[k] == b';' || is_space(b[k])) {
                k += 1;
            }
            out.push(b';');
            i = k;
        } else {
            out.push(b[i]);
            i += 1;
        }
    }
    let out = String::from_utf8(out).unwrap_or_default();
    match out.strip_prefix(';') {
        Some(s) => s.to_string(),
        None => out,
    }
}

/// One `^\s*((\w+)\s*=\s*([^=;\s]*))\s*;\s*(.*)` match: whole, command, value, rest.
fn token(rest: &str) -> Option<(&str, &str, &str, &str)> {
    let b = rest.as_bytes();
    let skip = |mut i: usize| {
        while i < b.len() && is_space(b[i]) {
            i += 1;
        }
        i
    };
    let start = skip(0);
    let mut i = start;
    while i < b.len() && (b[i].is_ascii_alphanumeric() || b[i] == b'_') {
        i += 1;
    }
    if i == start {
        return None;
    }
    let cmd_end = i;
    i = skip(i);
    if b.get(i) != Some(&b'=') {
        return None;
    }
    let val_start = skip(i + 1);
    i = val_start;
    while i < b.len() && b[i] != b'=' && b[i] != b';' && !is_space(b[i]) {
        i += 1;
    }
    let val_end = i;
    let j = skip(i);
    if b.get(j) != Some(&b';') {
        return None;
    }
    let next = skip(j + 1);
    Some((
        &rest[start..val_end],
        &rest[start..cmd_end],
        &rest[val_start..val_end],
        &rest[next..],
    ))
}

/// `SasParseSubsetRanges`.
fn parse_subsets(t: &mut TechRec, value: &str) -> bool {
    t.subsets.clear();
    t.all_subsets = false;
    let b = value.as_bytes();
    let at = |i: usize| b.get(i).copied().unwrap_or(0);
    let mut p = 0;
    let mut start: i64 = -1;
    while at(p) != 0 || start >= 0 {
        if is_space(at(p)) {
            p += 1;
            continue;
        }
        if at(p) == b'-' {
            break;
        }
        let (v, end) = strtol(b, p);
        if v < 0 {
            break;
        }
        if end == p {
            if start < 0 || (at(end) != b',' && at(end) != 0) {
                break;
            }
            t.subsets.insert(start as i32, i32::MAX);
            start = -1;
            if at(end) == 0 {
                break;
            }
            p = end + 1;
            continue;
        }
        let mut end = end;
        while is_space(at(end)) {
            end += 1;
        }
        p = end;
        if at(end) == b',' || at(end) == 0 {
            if start >= 0 {
                t.subsets.insert(start as i32, v as i32);
                start = -1;
            } else {
                t.subsets.insert(v as i32, v as i32);
            }
            if at(end) == 0 {
                break;
            }
            p += 1;
            continue;
        }
        if at(end) != b'-' || start >= 0 {
            break;
        }
        start = v;
        p += 1;
    }
    if at(p) != 0 {
        return false;
    }
    if t.subsets.is_empty() {
        t.subsets.insert(i32::MAX, i32::MAX);
    }
    true
}

/// `strtol(s, &end, 0)`: the value and the end index (`p` when nothing was read).
fn strtol(b: &[u8], p: usize) -> (i64, usize) {
    let at = |i: usize| b.get(i).copied().unwrap_or(0);
    let mut i = p;
    while is_space(at(i)) {
        i += 1;
    }
    let neg = at(i) == b'-';
    if at(i) == b'+' || at(i) == b'-' {
        i += 1;
    }
    let (base, digits_start) =
        if at(i) == b'0' && (at(i + 1) | 0x20) == b'x' && at(i + 2).is_ascii_hexdigit() {
            (16, i + 2)
        } else if at(i) == b'0' {
            (8, i)
        } else {
            (10, i)
        };
    let mut j = digits_start;
    let mut v: i64 = 0;
    while let Some(d) = (at(j) as char).to_digit(base) {
        v = v
            .saturating_mul(i64::from(base))
            .saturating_add(i64::from(d));
        j += 1;
    }
    if j == digits_start {
        return (0, p);
    }
    (if neg { -v } else { v }, j)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tech() -> TechRec {
        TechRec {
            fx: 0,
            name: String::new(),
            mmd_pass: 0,
            use_texture: -1,
            use_spheremap: -1,
            use_toon: -1,
            hardware_ok: true,
            shader_mix_ok: true,
            shader_caps_ok: true,
            script: None,
            empty: false,
            all_subsets: true,
            subsets: Default::default(),
            passes: Vec::new(),
            cmds: Vec::new(),
        }
    }

    #[test]
    fn subsets_parse_like_the_original() {
        let mut t = tech();
        assert!(parse_subsets(&mut t, "0-1,3"));
        assert_eq!(t.subsets.iter().collect::<Vec<_>>(), [(&0, &1), (&3, &3)]);
        assert!(parse_subsets(&mut t, "5-"));
        assert_eq!(t.subsets.get(&5), Some(&i32::MAX));
        assert!(parse_subsets(&mut t, ""));
        assert_eq!(t.subsets.get(&i32::MAX), Some(&i32::MAX));
        assert!(!parse_subsets(&mut t, "1x"));
        assert!(!parse_subsets(&mut t, "-1"));
    }

    #[test]
    fn scripts_normalize_and_tokenize() {
        assert_eq!(normalize_script(" a = b ;; c=d"), " a = b;c=d;");
        assert_eq!(token("a = b;c=d"), Some(("a = b", "a", "b", "c=d")));
        assert_eq!(token("a b=c;"), None);
        assert_eq!(
            normalize_global_script("Technique = A ? B : C ;"),
            "Technique=A?B:C;"
        );
        assert_eq!(version("ps_2_a"), 0x201);
        assert_eq!(version("vs_3_0"), 0x300);
        assert_eq!(levels(0, 1024, 512), 11);
    }
}
