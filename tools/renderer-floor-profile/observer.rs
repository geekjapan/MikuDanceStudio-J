use super::*;
use std::cell::Cell;
thread_local! { static ACTIVE: Cell<bool> = const { Cell::new(false) }; }
fn emit(value: String) { ACTIVE.with(|a| if a.get() { println!("FP {value}"); }); }
fn bits(v: &[f32]) -> Vec<u32> { v.iter().map(|x| x.to_bits()).collect() }
fn mxcsr_snapshot() -> u32 {
    let mut raw = 0u32;
    unsafe { std::arch::asm!("stmxcsr [{out}]", out = in(reg) &mut raw, options(nostack, preserves_flags)); }
    raw
}
fn positions(v: &[Vertex]) -> Vec<Vec<u32>> { v.iter().map(|v| bits(&v.position)).collect() }
pub(super) fn parsed(nodes: &[Node]) {
    if !ACTIVE.with(|a| a.get()) { return; }
    fn walk(nodes: &[Node], parent: Vec<usize>) {
        for (i, n) in nodes.iter().enumerate() {
            let mut path = parent.clone(); path.push(i);
            let values: Vec<String> = n.values.iter().map(|v| match v {
                Value::Int(i) => format!("[\"int\",{i}]"),
                Value::Float(f) => format!("[\"float\",{}]", f.to_bits()),
                Value::Str(s) => format!("[\"bytes\",{s:?}]"),
            }).collect();
            emit(format!("{{\"stage\":\"parsed\",\"path\":{path:?},\"kind\":{:?},\"name\":{},\"values\":[{}]}}", n.kind,
                n.name.as_ref().map_or("null".into(), |s| format!("{s:?}")), values.join(",")));
            for (j, child) in n.children.iter().enumerate() {
                let mut p = path.clone(); p.push(j);
                match child {
                    Child::Node(child) => walk(std::slice::from_ref(child), p),
                    Child::Ref(r) => emit(format!("{{\"stage\":\"reference\",\"path\":{p:?},\"name\":{r:?}}}")),
                }
            }
        }
    }
    walk(nodes, Vec::new());
    emit("{\"stage\":\"parsed-end\"}".into());
}
pub(super) fn premerge(containers: &[Container]) {
    if !ACTIVE.with(|a| a.get()) { return; }
    for (i, c) in containers.iter().enumerate() {
        emit(format!("{{\"stage\":\"premerge\",\"ordinal\":{i},\"positions\":{:?},\"indices\":{:?},\"attributes\":{:?},\"matrix\":{:?},\"material_count\":{}}}", positions(&c.vertices), c.indices, c.face_material, bits(&c.transform.0), c.materials.len()));
    }
    emit("{\"stage\":\"premerge-end\"}".into());
}
pub(super) fn merged(m: &XMesh) {
    if !ACTIVE.with(|a| a.get()) { return; }
    emit(format!("{{\"stage\":\"merged-raw\",\"positions\":{:?},\"indices\":{:?},\"attributes\":{:?},\"material_count\":{},\"table\":{:?}}}",
        positions(&m.vertices), m.indices, m.face_material, m.materials.len(),
        m.attribute_table.iter().map(|t| [t.id,t.face_start,t.face_count,t.vertex_start,t.vertex_count]).collect::<Vec<_>>()));
}
#[test]
fn diagnostic() {
    let cases: &[(&str, &[u8])] = &[@CASES@];
    println!("\nFP {{\"stage\":\"begin\",\"language\":\"rust\"}}");
    for (id, data) in cases {
        println!("FP {{\"stage\":\"case\",\"id\":{id:?},\"mxcsr\":{}}}", mxcsr_snapshot());
        ACTIVE.with(|a| a.set(true));
        let loaded = crate::load_x(data).expect("fixed input load_x");
        ACTIVE.with(|a| a.set(false));
        let m = &loaded;
        println!("FP {{\"stage\":\"final-adjusted\",\"id\":{id:?},\"positions\":{:?},\"indices\":{:?},\"attributes\":{:?},\"material_count\":{},\"table\":{:?},\"mxcsr\":{}}}", positions(&m.vertices),m.indices,m.face_material,m.materials.len(),m.attribute_table.iter().map(|t| [t.id,t.face_start,t.face_count,t.vertex_start,t.vertex_count]).collect::<Vec<_>>(),mxcsr_snapshot());
    }
    let matrices: [[f32;16];3] = @MATRICES@;
    let points: [[f32;3];5] = @POINTS@;
    for (mi,m) in matrices.iter().enumerate() {
        for (pi,p) in points.iter().enumerate() {
            let sample_a = mxcsr_snapshot(); let q = transform_coord(*p, &Mat4(*m)); let sample_b = mxcsr_snapshot();
            println!("FP {{\"stage\":\"direct\",\"operation\":\"TransformCoord\",\"matrix\":{mi},\"point\":{pi},\"words\":{:?},\"sample_a\":{sample_a},\"sample_b\":{sample_b}}}", bits(&q));
        }
    }
    operation_diagnostic();
    println!("FP {{\"stage\":\"end\",\"status\":0}}");
}

#[derive(Clone, Copy)]
struct Operation {
    owner: [u32; 4], input: [u32; 19], values: [u32; 3], output: [u32; 3],
    destination: [u32; 3], samples: [u32; 2], sites: [usize; 5],
}
impl Operation {
    const EMPTY: Self = Self { owner: [0; 4], input: [0; 19], values: [0; 3],
        output: [0; 3], destination: [0; 3], samples: [0; 2], sites: [0; 5] };
}
#[derive(Clone, Copy)]
enum Capture { Idle, Armed(Operation), Running(Operation), Finished(Operation) }
thread_local! {
    static CAPTURE: Cell<Capture> = const { Cell::new(Capture::Idle) };
    static MERGE_CURSOR: Cell<[u32; 2]> = const { Cell::new([u32::MAX, 0]) };
}
#[inline(always)]
fn boundary() -> (u32, usize) {
    let mut sample = 0u32; let site: usize;
    unsafe { std::arch::asm!("stmxcsr [{sample}]", "lea {site}, [rip + 2f]", "2:",
        sample = in(reg) &mut sample, site = out(reg) site, options(nostack, preserves_flags)); }
    (sample, site)
}
#[inline(always)]
fn code_site() -> usize {
    let site: usize;
    unsafe { std::arch::asm!("lea {site}, [rip + 2f]", "2:", site = out(reg) site, options(nostack, preserves_flags)); }
    site
}
fn input_words(p: [f32; 3], m: &Mat4) -> [u32; 19] {
    let mut input = [0; 19];
    for (i, value) in p.iter().chain(m.0.iter()).enumerate() { input[i] = value.to_bits(); }
    input
}
fn arm(owner: [u32; 4]) {
    CAPTURE.with(|slot| { assert!(matches!(slot.get(), Capture::Idle));
        slot.set(Capture::Armed(Operation { owner, ..Operation::EMPTY })); });
    MERGE_CURSOR.with(|c| c.set([u32::MAX, 0]));
}
#[inline(always)]
pub(super) fn begin_operation(p: [f32; 3], m: &Mat4) {
    CAPTURE.with(|slot| if let Capture::Armed(mut op) = slot.get() {
        op.input = input_words(p, m);
        let (sample, site) = boundary(); op.samples[0] = sample; op.sites[0] = site;
        slot.set(Capture::Running(op));
    });
}
#[inline(always)]
pub(super) fn intermediates(w: f32, e: f32, r: f32) {
    CAPTURE.with(|slot| if let Capture::Running(mut op) = slot.get() {
        op.values = [w.to_bits(), e.to_bits(), r.to_bits()]; op.sites[1] = code_site();
        slot.set(Capture::Running(op));
    });
}
#[inline(always)]
pub(super) fn finish_operation(output: [f32; 3]) {
    let (sample, site) = boundary();
    CAPTURE.with(|slot| if let Capture::Running(mut op) = slot.get() {
        op.output = output.map(f32::to_bits); op.samples[1] = sample; op.sites[2] = site;
        slot.set(Capture::Finished(op));
    });
}
pub(super) fn merge_container() {
    if CAPTURE.with(|s| matches!(s.get(), Capture::Armed(Operation { owner: [2, _, _, _], .. }))) {
        MERGE_CURSOR.with(|c| c.set([c.get()[0].wrapping_add(1), 0]));
    }
}
pub(super) fn merge_source(destination: usize) {
    CAPTURE.with(|slot| if let Capture::Armed(mut op) = slot.get() {
        if op.owner[0] == 2 {
            let [container, vertex] = MERGE_CURSOR.with(|c| c.get());
            op.owner = [2, container, vertex, destination as u32];
            slot.set(Capture::Armed(op));
        }
    });
}
pub(super) fn merge_destination(output: [f32; 3]) {
    CAPTURE.with(|slot| if let Capture::Finished(mut op) = slot.get() {
        if op.owner[0] == 2 && op.sites[4] == 0 {
            op.destination = output.map(f32::to_bits); op.sites[4] = code_site();
            slot.set(Capture::Finished(op));
        }
    });
}
fn emit_operation(kind: &str, op: Operation, base: usize) {
    println!("FP {{\"stage\":\"operation\",\"kind\":{kind:?},\"owner\":{:?},\"input\":{:?},\"values\":{:?},\"output\":{:?},\"destination\":{:?},\"samples\":{:?},\"sites\":{:?},\"base\":{base}}}",
        op.owner, op.input, op.values, op.output, op.destination, op.samples, op.sites);
}
fn complete(output: [f32; 3], caller: [usize; 2], base: usize) {
    let mut op = CAPTURE.with(|slot| { let old = slot.replace(Capture::Idle);
        match old { Capture::Finished(op) => op, _ => panic!("missing actual operation") } });
    assert_eq!(op.output, output.map(f32::to_bits));
    op.sites[3] = caller[0];
    if op.owner[0] == 1 { op.sites[4] = caller[1]; }
    else { assert_eq!(op.destination, op.output); assert_ne!(op.sites[4], 0); }
    emit_operation("RustTable", op, base);
}
#[inline(never)]
fn hardware(p: [f32; 3], m: &Mat4, owner: [u32; 4]) -> Operation {
    let mut op = Operation { owner, input: input_words(p, m), ..Operation::EMPTY };
    unsafe { std::arch::asm!(
        "stmxcsr [{samples}]", "lea {start}, [rip + 2f]", "2:",
        "movss xmm5, [{p}]", "movss xmm6, [{p} + 4]", "movss xmm7, [{p} + 8]",
        "movss xmm0, [{m} + 12]", "mulss xmm0, xmm5",
        "movss xmm4, [{m} + 28]", "mulss xmm4, xmm6", "addss xmm0, xmm4",
        "movss xmm4, [{m} + 44]", "mulss xmm4, xmm7", "addss xmm0, xmm4", "addss xmm0, [{m} + 60]",
        "movss [{values}], xmm0", "rcpss xmm1, xmm0", "movss [{values} + 4], xmm1",
        "movaps xmm2, xmm1", "addss xmm2, xmm1", "mulss xmm1, xmm1", "mulss xmm0, xmm1",
        "subss xmm2, xmm0", "movss [{values} + 8], xmm2",
        "movss xmm0, [{m}]", "mulss xmm0, xmm5", "movss xmm4, [{m} + 16]", "mulss xmm4, xmm6", "addss xmm0, xmm4",
        "movss xmm4, [{m} + 32]", "mulss xmm4, xmm7", "addss xmm0, xmm4", "addss xmm0, [{m} + 48]", "mulss xmm0, xmm2", "movss [{out}], xmm0",
        "movss xmm0, [{m} + 4]", "mulss xmm0, xmm5", "movss xmm4, [{m} + 20]", "mulss xmm4, xmm6", "addss xmm0, xmm4",
        "movss xmm4, [{m} + 36]", "mulss xmm4, xmm7", "addss xmm0, xmm4", "addss xmm0, [{m} + 52]", "mulss xmm0, xmm2", "movss [{out} + 4], xmm0",
        "movss xmm0, [{m} + 8]", "mulss xmm0, xmm5", "movss xmm4, [{m} + 24]", "mulss xmm4, xmm6", "addss xmm0, xmm4",
        "movss xmm4, [{m} + 40]", "mulss xmm4, xmm7", "addss xmm0, xmm4", "addss xmm0, [{m} + 56]", "mulss xmm0, xmm2", "movss [{out} + 8], xmm0",
        "lea {end}, [rip + 3f]", "3:", "stmxcsr [{samples} + 4]",
        p = in(reg) p.as_ptr(), m = in(reg) m.0.as_ptr(), values = in(reg) op.values.as_mut_ptr(),
        out = in(reg) op.output.as_mut_ptr(), samples = in(reg) op.samples.as_mut_ptr(),
        start = out(reg) op.sites[0], end = out(reg) op.sites[2],
        out("xmm0") _, out("xmm1") _, out("xmm2") _, out("xmm4") _, out("xmm5") _, out("xmm6") _, out("xmm7") _,
        options(nostack, preserves_flags)); }
    op
}
fn operation_diagnostic() {
    unsafe extern "system" { fn GetModuleHandleW(name: *const u16) -> *mut std::ffi::c_void; }
    let base = unsafe { GetModuleHandleW(std::ptr::null()) } as usize;
    assert_ne!(base, 0);
    let raw = std::fs::read(@RUNTIME@).expect("post-build runtime corpus"); assert_eq!(raw.len(), 152);
    let words: Vec<u32> = raw.chunks_exact(4).map(|b| u32::from_le_bytes(b.try_into().unwrap())).collect();
    println!("FP {{\"stage\":\"runtime-read\",\"words\":{words:?}}}");
    for (id, input) in words.chunks_exact(19).enumerate() {
        let p: [f32; 3] = std::array::from_fn(|i| f32::from_bits(input[i]));
        let m = Mat4(std::array::from_fn(|i| f32::from_bits(input[i + 3])));
        if @OBSERVED@ { arm([1, id as u32, 0, 0]); }
        let before = boundary(); let output = transform_coord(p, &m); let after = boundary();
        if @OBSERVED@ { complete(output, [before.1, after.1], base); }
        else { emit_operation("RustEndpoint", Operation { owner: [1, id as u32, 0, 0], input: input_words(p, &m), output: output.map(f32::to_bits),
            samples: [before.0, after.0], sites: [before.1, 0, after.1, 0, 0], ..Operation::EMPTY }, base); }
        emit_operation("HardwareSeedWithFrozenRefinement", hardware(p, &m, [1, id as u32, 0, 0]), base);
    }
    let raw = std::fs::read(@MERGE_INPUT@).expect("runtime merge fixture");
    println!("FP {{\"stage\":\"merge-read\",\"bytes\":{raw:?}}}");
    if @OBSERVED@ { arm([2, 0, 0, 0]); }
    let before = boundary(); let mesh = crate::load_x(&raw).expect("actual runtime importer"); let after = boundary();
    let output = mesh.vertices[0].position;
    if @OBSERVED@ { complete(output, [before.1, after.1], base); }
    else { emit_operation("RustEndpoint", Operation { owner: [2, 0, 0, 0], output: output.map(f32::to_bits), destination: output.map(f32::to_bits),
        samples: [before.0, after.0], sites: [before.1, 0, after.1, 0, 0], ..Operation::EMPTY }, base); }
}
