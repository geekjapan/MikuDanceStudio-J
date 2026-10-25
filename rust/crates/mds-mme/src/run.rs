//! The interpreted run of a technique: `SasCreateRunState`, `SasExecuteTechniqueStep`, and
//! `SasResumeTechnique` of `sas_exec.cpp` against a model of the D3D9 device state the walk
//! touches (four color targets, the depth stencil, the viewport) and the host draw callback
//! that records each draw.

use crate::sas::*;

pub const S_OK: u32 = 0;
pub const E_FAIL: u32 = 0x8000_4005;
const INVALIDCALL: u32 = 0x8876_086C;
/// The runtime's synthetic failure code.
const CODE_1: u32 = 1;

pub struct Surface {
    pub name: String,
    pub width: u32,
    pub height: u32,
    pub render_target: bool,
    pub depth: bool,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct Viewport {
    x: u32,
    y: u32,
    width: u32,
    height: u32,
}

/// The device: surfaces it knows, and the bound targets.
pub struct Device {
    pub surfaces: Vec<Surface>,
    rt: [Option<usize>; 4],
    ds: Option<usize>,
    vp: Viewport,
    /// Surfaces of each resource's texture: level 0, or the six cube faces.
    tex_surfaces: Vec<Vec<usize>>,
    /// The depth surface each depth target's texture registered.
    depth_of: Vec<Option<usize>>,
}

const MAIN: usize = 0;
const MAIN_DEPTH: usize = 1;
const SCRATCH: usize = 2;

impl Device {
    /// The fixed device with the objects of `sas`, as `CollectKnown` names them.
    pub fn new(sas: &Sas) -> Device {
        let s = |name: &str, (width, height): (u32, u32), render_target, depth| Surface {
            name: name.to_string(),
            width,
            height,
            render_target,
            depth,
        };
        let mut surfaces = vec![
            s("main", (1000, 600), true, false),
            s("main.depth", (1000, 600), false, true),
            s("scratch", (16, 16), true, false),
        ];
        let mut tex_surfaces = Vec::new();
        let mut depth_of = Vec::new();
        for r in &sas.resources {
            let mut depth = None;
            if let (Some((w, h, _)), SEM_RENDER_DEPTH) = (r.surface, r.semantic) {
                surfaces.push(s(&r.name, (w, h), false, true));
                depth = Some(surfaces.len() - 1);
            }
            if let Some((w, h, _)) = r.offscreen_depth {
                surfaces.push(s(&format!("{}.depth", r.name), (w, h), false, true));
            }
            let mut mine = Vec::new();
            if let Some(t) = r.texture {
                let rt = t.is_render_target();
                match t.kind {
                    TexKind::Plain => {
                        surfaces.push(s(&r.name, (t.width, t.height), rt, false));
                        mine.push(surfaces.len() - 1);
                    }
                    TexKind::Cube => {
                        for face in 0..6 {
                            surfaces.push(s(
                                &format!("{}[{face}]", r.name),
                                (t.width, t.height),
                                rt,
                                false,
                            ));
                            mine.push(surfaces.len() - 1);
                        }
                    }
                    TexKind::Volume => {}
                }
            }
            tex_surfaces.push(mine);
            depth_of.push(depth);
        }
        Device {
            surfaces,
            rt: [Some(MAIN), None, None, None],
            ds: Some(MAIN_DEPTH),
            vp: Viewport {
                x: 0,
                y: 0,
                width: 1000,
                height: 600,
            },
            tex_surfaces,
            depth_of,
        }
    }

    /// `rt0=.. rt1=.. rt2=.. rt3=.. ds=.. viewport=WxH+X+Y`.
    pub fn bindings(&self) -> String {
        let name = |s: Option<usize>| s.map_or("none", |i| self.surfaces[i].name.as_str());
        format!(
            "rt0={} rt1={} rt2={} rt3={} ds={} viewport={}x{}+{}+{}",
            name(self.rt[0]),
            name(self.rt[1]),
            name(self.rt[2]),
            name(self.rt[3]),
            name(self.ds),
            self.vp.width,
            self.vp.height,
            self.vp.x,
            self.vp.y
        )
    }

    fn set_render_target(&mut self, slot: usize, s: Option<usize>) -> u32 {
        if slot >= 4
            || (slot == 0 && s.is_none())
            || s.is_some_and(|i| !self.surfaces[i].render_target)
        {
            return INVALIDCALL;
        }
        self.rt[slot] = s;
        if let (0, Some(i)) = (slot, s) {
            self.vp = self.full(i);
        }
        S_OK
    }

    fn full(&self, i: usize) -> Viewport {
        Viewport {
            x: 0,
            y: 0,
            width: self.surfaces[i].width,
            height: self.surfaces[i].height,
        }
    }

    fn set_depth(&mut self, s: Option<usize>) -> u32 {
        if s.is_some_and(|i| !self.surfaces[i].depth) {
            return INVALIDCALL;
        }
        self.ds = s;
        S_OK
    }

    fn set_viewport(&mut self, vp: Viewport) {
        let rt0 = &self.surfaces[self.rt[0].unwrap_or(MAIN)];
        if vp.x + vp.width <= rt0.width && vp.y + vp.height <= rt0.height {
            self.vp = vp;
        }
    }
}

/// `SasRunState`.
pub struct RunState {
    command: usize,
    mask: u32,
    saved_color: [Option<usize>; 4],
    saved_depth: Option<usize>,
    saved_vp: Viewport,
    current_vp: Viewport,
    loops: Vec<(usize, i32, i32)>,
}

impl RunState {
    pub fn new(d: &Device) -> RunState {
        RunState {
            command: 0,
            mask: 0,
            saved_color: d.rt,
            saved_depth: d.ds,
            saved_vp: d.vp,
            current_vp: d.vp,
            loops: Vec::new(),
        }
    }
}

/// One plan run: the device, the run state, and the lines the draw callback writes.
pub struct Run<'a> {
    pub sas: &'a mut Sas,
    pub dev: &'a mut Device,
    pub tech: usize,
    pub draws: u32,
    pub out: &'a mut String,
}

impl Run<'_> {
    fn restore(&mut self, st: &mut RunState) {
        if st.mask == 0 {
            return;
        }
        for i in 0..4 {
            if st.mask & (1 << (i + 1)) != 0 && (i != 0 || st.saved_color[0].is_some()) {
                self.dev.set_render_target(i, st.saved_color[i]);
            }
        }
        if st.mask & 1 != 0 {
            self.dev.set_depth(st.saved_depth);
        }
        self.dev.set_viewport(st.saved_vp);
        st.mask = 0;
    }

    fn draw(&mut self, kind: u8, pass: usize) -> u32 {
        self.draws += 1;
        let t = &self.sas.techniques[self.tech];
        let p = &t.passes[pass];
        let line = format!(
            "    draw {} pass={} {} {}\n",
            if kind == 0 { "geometry" } else { "buffer" },
            p.index,
            crate::plan::q(&p.name),
            self.dev.bindings()
        );
        self.out.push_str(&line);
        S_OK
    }

    fn report_target(&mut self, param: Option<usize>, slot: Option<usize>, hr: u32) {
        let pname = param
            .map_or("", |p| self.sas.fx.params[p].name.as_str())
            .to_string();
        let tname = self.sas.techniques[self.tech].name.clone();
        let code = if hr == CODE_1 {
            String::new()
        } else {
            format!(" [{hr:08X}]")
        };
        let target = match slot {
            Some(s) => format!("RenderColorTarget{s}"),
            None => "RenderDepthStencilTarget".to_string(),
        };
        let path = self.sas.path.clone();
        self.sas.log.push_str(&format!(
            "{path}:\nError: invalid render target: {target}={pname}{code}  (technique: {tname})\n"
        ));
    }

    /// `SasApplyCommandImpl`.
    fn apply(&mut self, cmd: &Cmd, st: &mut RunState, pass: Option<usize>) -> u32 {
        match cmd.id {
            CMD_RT0..=4 => {
                let slot = usize::from(cmd.id - CMD_RT0);
                let bit = 1 << (slot + 1);
                let Some(param) = cmd.param else {
                    if slot != 0 || st.saved_color[0].is_some() {
                        let hr = self.dev.set_render_target(slot, st.saved_color[slot]);
                        if hr != S_OK {
                            self.report_target(None, Some(slot), hr);
                            return hr;
                        }
                        st.mask &= !bit;
                        if slot == 0 {
                            st.current_vp = st.saved_vp;
                        }
                        self.dev.set_viewport(st.current_vp);
                        return hr;
                    }
                    self.report_target(None, Some(slot), CODE_1);
                    return CODE_1;
                };
                let surf = match self.sas.bound[param] {
                    None if slot == 0 => Some(SCRATCH),
                    None => None,
                    Some(r) => {
                        let tex = self.sas.resources[r].texture.map(|t| t.kind);
                        let faces = &self.dev.tex_surfaces[r];
                        let pick = match (cmd.value, tex) {
                            (e, Some(TexKind::Cube)) if e >= 0 => faces.get(e as usize).copied(),
                            (e, Some(TexKind::Plain)) if e < 0 => faces.first().copied(),
                            _ => None,
                        };
                        match pick {
                            Some(s) => Some(s),
                            None => {
                                self.report_target(Some(param), Some(slot), CODE_1);
                                return CODE_1;
                            }
                        }
                    }
                };
                let hr = self.dev.set_render_target(slot, surf);
                if hr != S_OK {
                    self.report_target(Some(param), Some(slot), hr);
                    return hr;
                }
                st.mask |= bit;
                if let (0, Some(s)) = (slot, surf) {
                    let full = self.dev.full(s);
                    st.current_vp = full;
                }
                self.dev.set_viewport(st.current_vp);
                hr
            }
            CMD_DEPTH => {
                let Some(param) = cmd.param else {
                    let hr = self.dev.set_depth(st.saved_depth);
                    if hr != S_OK {
                        self.report_target(None, None, hr);
                        return hr;
                    }
                    st.mask &= !1;
                    self.dev.set_viewport(st.current_vp);
                    return hr;
                };
                let surf = match self.sas.bound[param] {
                    None => None,
                    Some(r) => match self.dev.depth_of[r] {
                        Some(s) => Some(s),
                        None => {
                            self.report_target(Some(param), None, CODE_1);
                            return CODE_1;
                        }
                    },
                };
                let hr = self.dev.set_depth(surf);
                if hr != S_OK {
                    self.report_target(Some(param), None, hr);
                    return hr;
                }
                st.mask |= 1;
                self.dev.set_viewport(st.current_vp);
                hr
            }
            CMD_DRAW_GEOMETRY | CMD_DRAW_BUFFER => match pass {
                Some(p) => self.draw(cmd.id - CMD_DRAW_GEOMETRY, p),
                None => S_OK,
            },
            // Clears and clear staging change nothing the plan records.
            _ => S_OK,
        }
    }

    fn report_error(&mut self, pass: usize, hr: u32) {
        let t = &self.sas.techniques[self.tech];
        let line = format!(
            "technique: {}, pass: {}:\nDirectX Error: Unknown [{hr:08X}]\nFailed to run the effect script:\n",
            t.name, t.passes[pass].name
        );
        self.sas.log.push_str(&line);
    }

    /// `SasRunPassCommands`.
    fn run_pass(&mut self, pass: usize, st: &mut RunState) -> u32 {
        let p = &self.sas.techniques[self.tech].passes[pass];
        if p.script.is_none() {
            let hr = self.draw(0, pass);
            if hr != S_OK {
                self.report_error(pass, hr);
            }
            return hr;
        }
        let cmds = p.cmds.clone();
        for c in &cmds {
            let hr = self.apply(c, st, Some(pass));
            if hr != S_OK {
                if c.id == CMD_DRAW_GEOMETRY || c.id == CMD_DRAW_BUFFER {
                    self.report_error(pass, hr);
                }
                return hr;
            }
        }
        S_OK
    }

    /// `SasRunTechniqueWalk`: the result, and whether the walk suspended.
    pub fn walk(&mut self, st: &mut RunState, step: bool) -> (u32, bool) {
        let t = &self.sas.techniques[self.tech];
        if t.script.is_none() {
            if step {
                return (S_OK, false);
            }
            let mut hr = S_OK;
            for p in 0..t.passes.len() {
                hr = self.run_pass(p, st);
                if hr != S_OK {
                    break;
                }
            }
            self.restore(st);
            if hr != S_OK {
                self.sas.run_failed = true;
            }
            return (hr, false);
        }
        let cmds = t.cmds.clone();
        while st.command < cmds.len() {
            let cmd = &cmds[st.command];
            let mut advance = true;
            match cmd.id {
                CMD_PASS => {
                    let pass = self.sas.techniques[self.tech]
                        .passes
                        .iter()
                        .position(|p| p.index == cmd.value);
                    if let Some(p) = pass {
                        let hr = self.run_pass(p, st);
                        if hr != S_OK {
                            self.sas.run_failed = true;
                            self.restore(st);
                            return (hr, false);
                        }
                    }
                }
                CMD_SCRIPT_EXTERNAL if step => return (S_OK, true),
                CMD_LOOP_BY_COUNT => {
                    let count = cmd
                        .param
                        .and_then(|p| self.sas.fx.params[p].get_int())
                        .unwrap_or(0);
                    if count <= 0 {
                        st.command = skip_loop(&cmds, st.command);
                        advance = false;
                    } else {
                        st.loops.push((st.command, 0, count));
                    }
                }
                CMD_LOOP_GET_INDEX => {
                    let i = st.loops.last().map_or(0, |l| l.1);
                    if let Some(p) = cmd.param {
                        self.sas.fx.params[p].set_int(i);
                    }
                }
                CMD_LOOP_END => {
                    if let Some(top) = st.loops.last_mut() {
                        top.1 += 1;
                        if top.1 >= top.2 {
                            st.loops.pop();
                        } else {
                            st.command = top.0;
                        }
                    }
                }
                CMD_RT0..=9 => {
                    let hr = self.apply(cmd, st, None);
                    if hr != S_OK {
                        self.sas.run_failed = true;
                        self.restore(st);
                        return (hr, false);
                    }
                }
                _ => {}
            }
            if advance {
                st.command += 1;
            }
        }
        self.restore(st);
        (S_OK, false)
    }
}

fn skip_loop(cmds: &[Cmd], at: usize) -> usize {
    let mut depth = 1;
    for (i, c) in cmds.iter().enumerate().skip(at + 1) {
        if c.id == CMD_LOOP_BY_COUNT {
            depth += 1;
        } else if c.id == CMD_LOOP_END {
            depth -= 1;
            if depth == 0 {
                return i + 1;
            }
        }
    }
    cmds.len()
}
