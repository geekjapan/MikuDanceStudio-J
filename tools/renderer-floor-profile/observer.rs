use super::*;
use std::cell::{Cell, RefCell};
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
    static LINEAGE: RefCell<([[usize; 10]; 16], usize)> = const { RefCell::new(([[0; 10]; 16], 0)) };
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
    LINEAGE.with(|c| c.borrow_mut().1 = 0);
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
pub(super) fn merge_source(vertices: &Vec<Vertex>, source: &Vertex, matrix: &Mat4) {
    if CAPTURE.with(|s| !matches!(s.get(), Capture::Idle)) {
        LINEAGE.with(|slot| {
            let mut lineage = slot.borrow_mut(); let n = lineage.1; assert!(n < lineage.0.len());
            lineage.0[n] = [vertices.as_ptr() as usize, vertices.len(), vertices.capacity(),
                source as *const Vertex as usize, matrix as *const Mat4 as usize, 0, 0, 0,
                std::mem::size_of::<Vertex>(), code_site()];
        });
    }
    CAPTURE.with(|slot| if let Capture::Armed(mut op) = slot.get() {
        if op.owner[0] == 2 {
            let [container, vertex] = MERGE_CURSOR.with(|c| c.get());
            op.owner = [2, container, vertex, vertices.len() as u32];
            slot.set(Capture::Armed(op));
        }
    });
}
pub(super) fn merge_destination(vertices: &Vec<Vertex>) {
    if CAPTURE.with(|s| !matches!(s.get(), Capture::Idle)) {
        LINEAGE.with(|slot| {
            let mut lineage = slot.borrow_mut(); let n = lineage.1; assert!(n < lineage.0.len());
            lineage.0[n][5] = vertices.as_ptr() as usize; lineage.0[n][6] = vertices.len(); lineage.0[n][7] = vertices.capacity();
            lineage.1 = n + 1;
        });
    }
    CAPTURE.with(|slot| if let Capture::Finished(mut op) = slot.get() {
        if op.owner[0] == 2 && op.sites[4] == 0 {
            op.destination = vertices.last().unwrap().position.map(f32::to_bits); op.sites[4] = code_site();
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
    if @OBSERVED@ { runtime_imports("pre", base); }
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
        let caller_before = code_site(); let mut hardware_output = hardware(p, &m, [1, id as u32, 0, 0]); let caller_after = code_site();
        hardware_output.sites[3] = caller_before; hardware_output.sites[4] = caller_after;
        emit_operation("HardwareSeedWithFrozenRefinement", hardware_output, base);
    }
    let raw = std::fs::read(@MERGE_INPUT@).expect("runtime merge fixture");
    println!("FP {{\"stage\":\"merge-read\",\"bytes\":{raw:?}}}");
    if @OBSERVED@ { arm([2, 0, 0, 0]); }
    let before = boundary(); let mesh = crate::load_x(&raw).expect("actual runtime importer"); let after = boundary();
    let output = mesh.vertices[0].position;
    if @OBSERVED@ {
        LINEAGE.with(|slot| {
        let lineage = slot.borrow();
        println!("FP {{\"stage\":\"merge-lineage\",\"caller\":[{},{}],\"rows\":{:?},\"returned\":[{},{},{},{},{},{}]}}", before.1, after.1, &lineage.0[..lineage.1],
            mesh.vertices.as_ptr() as usize, mesh.vertices.len(), mesh.vertices.capacity(),
            &mesh.vertices[0].position as *const [f32; 3] as usize, code_site(),
            std::mem::offset_of!(Vertex, position));
        });
    }
    if @OBSERVED@ { complete(output, [before.1, after.1], base); }
    else { emit_operation("RustEndpoint", Operation { owner: [2, 0, 0, 0], output: output.map(f32::to_bits), destination: output.map(f32::to_bits),
        samples: [before.0, after.0], sites: [before.1, 0, after.1, 0, 0], ..Operation::EMPTY }, base); }
    if @OBSERVED@ { runtime_imports("post", base); }
}

#[repr(C)]
struct MemoryRegion {
    base: usize, allocation_base: usize, allocation_protect: u32, partition: u16,
    size: usize, state: u32, protect: u32, kind: u32,
}
#[link(name = "kernel32")]
unsafe extern "system" {
    fn VirtualQuery(address: *const std::ffi::c_void, info: *mut MemoryRegion, size: usize) -> usize;
    fn GetModuleHandleExW(flags: u32, address: *const u16, module: *mut usize) -> i32;
    fn GetModuleFileNameW(module: usize, path: *mut u16, size: u32) -> u32;
    fn GetCurrentProcessId() -> u32;
}
fn loaded_bytes(base: usize, rva: usize, length: usize, limit: usize) -> Vec<u8> {
    assert!(length > 0 && rva.checked_add(length).is_some_and(|end| end <= limit));
    let first = base.checked_add(rva).unwrap(); let last = first.checked_add(length).unwrap();
    let mut at = first;
    while at < last {
        let mut info = std::mem::MaybeUninit::<MemoryRegion>::uninit();
        let size = unsafe { VirtualQuery(at as *const _, info.as_mut_ptr(), std::mem::size_of::<MemoryRegion>()) };
        assert_eq!(size, std::mem::size_of::<MemoryRegion>());
        let info = unsafe { info.assume_init() };
        assert!(info.allocation_base == base && info.state == 0x1000 && info.protect & 0x101 == 0);
        assert!([2, 4, 8, 0x20, 0x40, 0x80].contains(&(info.protect & 0xff)));
        let end = info.base.checked_add(info.size).unwrap(); assert!(info.base <= at && at < end);
        at = end.min(last);
    }
    unsafe { std::slice::from_raw_parts(first as *const u8, length) }.to_vec()
}
fn u16_at(raw: &[u8], at: usize) -> u16 { u16::from_le_bytes(raw[at..at + 2].try_into().unwrap()) }
fn u32_at(raw: &[u8], at: usize) -> usize { u32::from_le_bytes(raw[at..at + 4].try_into().unwrap()) as usize }
fn u64_at(raw: &[u8], at: usize) -> usize { usize::from_le_bytes(raw[at..at + 8].try_into().unwrap()) }
fn loaded_header(base: usize) -> (Vec<u8>, usize, usize) {
    let prefix = loaded_bytes(base, 0, 4096, 4096);
    assert_eq!(&prefix[..2], b"MZ"); let pe = u32_at(&prefix, 60); assert!(pe + 264 <= prefix.len());
    assert_eq!(&prefix[pe..pe + 6], b"PE\0\0d\x86"); assert_eq!(u16_at(&prefix, pe + 24), 0x20b);
    let image_size = u32_at(&prefix, pe + 24 + 56); let header_size = u32_at(&prefix, pe + 24 + 60);
    assert!(image_size <= 512 * 1024 * 1024 && header_size <= 128 * 1024);
    (loaded_bytes(base, 0, header_size, image_size), pe, image_size)
}
fn runtime_imports(phase: &str, base: usize) {
    assert_eq!(std::mem::size_of::<Operation>(), 176);
    let root = std::path::Path::new(@RUNTIME@).parent().unwrap();
    let (header, pe, image_size) = loaded_header(base); let optional = pe + 24;
    let import_rva = u32_at(&header, optional + 120); let import_size = u32_at(&header, optional + 124);
    assert!(import_size > 0 && import_size <= 128 * 1024);
    let descriptors = loaded_bytes(base, import_rva, import_size, image_size); let mut slots = Vec::new();
    for (ordinal, descriptor) in descriptors.chunks_exact(20).enumerate() {
        if descriptor.iter().all(|b| *b == 0) { break; }
        let names = u32_at(descriptor, 0); let dll_rva = u32_at(descriptor, 12); let iat = u32_at(descriptor, 16);
        assert!(names != 0 && iat != 0);
        let mut terminated = false;
        for n in 0..8192 {
            let entry = loaded_bytes(base, names + n * 8, 8, image_size); let name_rva = u64_at(&entry, 0);
            if name_rva == 0 { terminated = true; break; }
            if name_rva >> 63 != 0 { continue; }
            let name = loaded_bytes(base, name_rva + 2, 7, image_size);
            if name != b"memcpy\0" { continue; }
            let slot_rva = iat + n * 8; let slot_bytes = loaded_bytes(base, slot_rva, 8, image_size); let target = u64_at(&slot_bytes, 0);
            let mut owner = 0usize;
            assert_ne!(unsafe { GetModuleHandleExW(6, target as *const u16, &mut owner) }, 0);
            let (owner_header, owner_pe, owner_size) = loaded_header(owner);
            assert!(owner <= target && target - owner < owner_size);
            let mut path = [0u16; 32768]; let length = unsafe { GetModuleFileNameW(owner, path.as_mut_ptr(), path.len() as u32) } as usize;
            assert!(length > 0 && length < path.len());
            use std::os::windows::ffi::OsStringExt;
            let owner_path = std::ffi::OsString::from_wide(&path[..length]);
            let id = slots.len(); let prefix = format!("runtime-{phase}-{id}");
            std::fs::write(root.join(format!("{prefix}-iat.bin")), slot_bytes).unwrap();
            std::fs::write(root.join(format!("{prefix}-module.bin")), std::fs::read(&owner_path).unwrap()).unwrap();
            std::fs::write(root.join(format!("{prefix}-headers.bin")), &owner_header).unwrap();
            let count = u16_at(&owner_header, owner_pe + 6) as usize; assert!(count > 0 && count <= 96);
            let section_at = owner_pe + 24 + u16_at(&owner_header, owner_pe + 20) as usize;
            let mut sections = Vec::new(); let mut total = 0usize;
            for i in 0..count {
                let at = section_at + i * 40; let rva = u32_at(&owner_header, at + 12);
                let size = u32_at(&owner_header, at + 8).max(u32_at(&owner_header, at + 16)); let flags = u32_at(&owner_header, at + 36);
                if flags & 0x40000000 == 0 || size == 0 { continue; }
                total = total.checked_add(size).unwrap(); assert!(total <= 512 * 1024 && size <= 128 * 1024);
                let bytes = loaded_bytes(owner, rva, size, owner_size);
                std::fs::write(root.join(format!("{prefix}-section-{i}.bin")), bytes).unwrap();
                sections.push(format!("[{i},{rva},{size},{flags}]"));
            }
            slots.push(format!("{{\"descriptor_rva\":{},\"dll_rva\":{dll_rva},\"name_rva\":{name_rva},\"slot_rva\":{slot_rva},\"target_va\":{target},\"owner_base\":{owner},\"owner_size\":{owner_size},\"path_utf16\":{:?},\"sections\":[{}]}}",
                import_rva + ordinal * 20, &path[..length], sections.join(",")));
        }
        assert!(terminated);
    }
    assert!(!slots.is_empty() && slots.len() <= 8);
    println!("FP {{\"stage\":\"runtime-imports\",\"phase\":{phase:?},\"process_id\":{},\"image_base\":{base},\"image_size\":{image_size},\"slots\":[{}]}}", unsafe { GetCurrentProcessId() }, slots.join(","));
}
