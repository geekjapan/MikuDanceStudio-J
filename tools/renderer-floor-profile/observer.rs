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
    println!("FP {{\"stage\":\"end\",\"status\":0}}");
}
