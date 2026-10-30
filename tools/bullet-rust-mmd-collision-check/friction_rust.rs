//! Diagnostic-only sidecar; generated copies use stable owner epochs, never addresses.
use std::cell::RefCell;
use std::fmt::{self, Write as _};
use std::io::Write as _;

const LIMIT: usize = 4096;
const MAX_ID: u32 = 2_147_483_647;
#[derive(Clone, Copy, Default)]
struct Point { gid: u32, mask: u8 }
#[derive(Clone, Copy, Default)]
struct Manifold { key: u32, mid: u32, bodies: [usize; 2], points: [Point; 4], count: usize }
struct State {
    live: [Manifold; LIMIT], solver: [u32; LIMIT], solver_count: usize,
    owner: Option<u32>, next_mid: u32, next_gid: u32, next_tx: u32,
    cp: usize, commands: usize, seq: u32, closed: u32, bytes: usize,
    started: bool, observed: bool, command_open: bool, fixture_snapshot: bool, fixture_active: bool, incoming: Option<u32>,
    tx: Option<(u32, usize, u32, u32, bool, u8)>,
    refresh: Option<(u32, isize)>,
}
impl State {
    fn new() -> Self { Self { live: [Manifold::default(); LIMIT], solver: [0; LIMIT],
        solver_count: 0, owner: None, next_mid: 0, next_gid: 0, next_tx: 0,
        cp: 0, commands: 0, seq: 0, closed: 0, bytes: 0,
        started: false, observed: false, command_open: false, fixture_snapshot: false, fixture_active: false, incoming: None, tx: None, refresh: None } }
    fn index(&self, key: u32) -> usize {
        self.live.iter().position(|m| m.mid != 0 && m.key == key).expect("live owner epoch")
    }
    fn by_mid(&self, mid: u32) -> usize {
        assert_ne!(mid, 0);
        self.live.iter().position(|m| m.mid == mid).expect("live stable manifold")
    }
    fn fresh(counter: &mut u32) -> u32 { assert!(*counter < MAX_ID); *counter += 1; *counter }
    fn output(&mut self, value: &str) {
        self.bytes = self.bytes.checked_add(value.len()).expect("output byte overflow");
        assert!(self.bytes <= 64 * 1024 * 1024, "combined output capacity");
        std::io::stdout().lock().write_all(value.as_bytes()).expect("diagnostic stdout");
    }
    fn event(&mut self, tag: &str, args: fmt::Arguments<'_>) {
        assert!(self.started && self.command_open, "event in actual command");
        assert!(self.seq < 1_000_000, "event capacity"); self.seq += 1;
        let line = format!("{tag} {} {} {args}\n", self.cp, self.seq);
        assert!(line.len() <= 512 && line.is_ascii(), "sidecar line capacity"); self.output(&line);
    }
    fn close(&mut self) { Self::fresh(&mut self.closed); }
    fn binding(&self, mid: u32, slot: usize) -> Point {
        let m = &self.live[self.by_mid(mid)]; assert!(slot < m.count); m.points[slot]
    }
}
thread_local! { static STATE: RefCell<State> = RefCell::new(State::new()); }
fn state<T>(f: impl FnOnce(&mut State) -> T) -> T { STATE.with(|s| f(&mut s.borrow_mut())) }
pub fn output(args: fmt::Arguments<'_>) {
    state(|s| { let mut text = String::new(); text.write_fmt(args).unwrap(); s.output(&text); });
}
pub fn begin(variant: &str, role: &str, sha: &str, commands: usize) {
    assert!(matches!(variant, "rust-original" | "rust-observed"));
    assert!(matches!(role, "ordinary" | "ascending" | "descending" | "alternating"));
    assert!(sha.len() == 64 && sha.bytes().all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c)));
    assert!(commands > 0 && commands <= MAX_ID as usize);
    state(|s| { assert!(!s.started); *s = State::new(); s.started = true; s.observed = variant == "rust-observed";
        s.commands = commands; s.output(&format!("FH 3 {variant} {role} {sha} {commands}\n")); });
}
pub fn command(cp: usize, op: &str) { state(|s| {
    assert!(s.started && !s.command_open && cp == s.cp && cp < s.commands);
    assert!(s.owner.is_none() && s.tx.is_none() && s.incoming.is_none()); s.command_open = true; s.fixture_snapshot = op == "W";
}); }
pub fn command_end() { state(|s| { assert!(s.command_open && !s.fixture_active && s.owner.is_none() && s.tx.is_none() && s.incoming.is_none() && s.refresh.is_none());
    s.command_open = false; s.cp += 1; }); }
pub fn finish() { state(|s| {
    assert!(s.started && !s.command_open && s.cp == s.commands && s.owner.is_none() && s.tx.is_none() && s.incoming.is_none() && s.refresh.is_none());
    assert!(s.live.iter().all(|m| m.mid == 0), "closed live manifolds");
    s.output(&format!("FZ {} {} {}\n", s.seq, s.commands, s.closed));
    s.started = false;
}); }
pub fn allocate(key: u32, bodies: [usize; 2]) { state(|s| {
    assert!(s.observed && s.owner.is_none() && bodies[0] != bodies[1]);
    assert!(!s.live.iter().any(|m| m.mid != 0 && m.key == key));
    let index = s.live.iter().position(|m| m.mid == 0).expect("manifold capacity");
    let mid = State::fresh(&mut s.next_mid);
    s.live[index] = Manifold { key, mid, bodies, ..Manifold::default() };
    s.event("FM", format_args!("ALLOC {mid} {} {}", bodies[0], bodies[1]));
}); }
pub fn enter(key: u32) { state(|s| { assert!(s.observed && s.owner.is_none() && s.tx.is_none());
    s.index(key); s.owner = Some(key); }); }
pub fn leave(key: u32) { state(|s| { assert_eq!(s.owner.take(), Some(key)); assert!(s.tx.is_none() && s.refresh.is_none() && s.incoming.is_none()); }); }
pub fn incoming() { state(|s| {
    assert!(s.owner.is_some() && s.incoming.is_none());
    assert!(s.live.iter().map(|m| m.count).sum::<usize>() < 16384, "active generation capacity including incoming");
    let gid = State::fresh(&mut s.next_gid); s.incoming = Some(gid);
    s.event("FC", format_args!("RUST_CONTACT_CREATE {gid}"));
}); }
pub fn insert(slot: usize, old_count: usize, replacing: bool) { state(|s| {
    let i = s.index(s.owner.expect("contact operation owner")); let m = s.live[i];
    assert_eq!(m.count, old_count); assert!(slot < 4);
    let site = if replacing { assert!(slot < old_count); "REPLACE" }
        else if old_count == 4 { "EVICT_ADD" }
        else { assert_eq!(slot, old_count); "ADD" };
    let incoming = s.incoming.take().expect("one actual incoming construction");
    let old = if slot < old_count { m.points[slot].gid } else { 0 };
    let gid = State::fresh(&mut s.next_gid);
    s.event("FI", format_args!("{site} {} {slot} {old} {incoming} {gid} 0", m.mid));
    s.close(); if old != 0 { s.close(); }
    s.live[i].points[slot] = Point { gid, mask: 0 };
    if old_count < 4 && !replacing { s.live[i].count += 1; }
}); }
pub fn remove(slot: usize, old_count: usize) { state(|s| {
    let i = s.index(s.owner.expect("remove owner")); let m = s.live[i];
    assert_eq!(m.count, old_count); assert!(slot < old_count);
    let gid = m.points[slot].gid;
    s.event("FX", format_args!("REMOVE {} {slot} {gid}", m.mid)); s.close();
    let last = old_count - 1;
    if slot != last {
        let moved = m.points[last]; s.live[i].points[slot] = moved;
        s.event("FV", format_args!("REMOVE_MOVE {} {last} {slot} {}", m.mid, moved.gid));
    }
    s.live[i].points[last] = Point::default(); s.live[i].count = last;
}); }
pub fn clear(old_count: usize) { state(|s| {
    let i = s.index(s.owner.expect("clear owner")); let m = s.live[i]; assert_eq!(m.count, old_count);
    s.event("FM", format_args!("CLEAR_BEGIN {} {} {}", m.mid, m.bodies[0], m.bodies[1]));
    for slot in 0..m.count { s.event("FX", format_args!("CLEAR_POINT {} {slot} {}", m.mid, m.points[slot].gid)); s.close(); }
    s.live[i].points = [Point::default(); 4]; s.live[i].count = 0;
    s.event("FM", format_args!("CLEAR_END {} {} {}", m.mid, m.bodies[0], m.bodies[1]));
}); }
pub fn release(key: u32) { state(|s| {
    assert!(s.owner.is_none() && s.tx.is_none()); let i = s.index(key); let m = s.live[i]; assert_eq!(m.count, 0);
    s.event("FM", format_args!("RELEASE {} {} {}", m.mid, m.bodies[0], m.bodies[1]));
    s.live[i] = Manifold::default();
}); }
pub fn refresh_begin(count: usize) { state(|s| {
    assert!(s.refresh.is_none() && s.tx.is_none()); let m = s.live[s.index(s.owner.expect("refresh owner"))];
    assert_eq!(m.count, count); s.refresh = Some((m.mid, count as isize - 1));
    s.event("FR", format_args!("REFRESH_BEGIN {} 0 0 false false", m.mid));
}); }
pub fn refresh_point(slot: usize, distance_remove: bool, lateral_remove: bool) { state(|s| {
    let (mid, cursor) = s.refresh.expect("actual refresh loop"); assert_eq!(cursor, slot as isize);
    assert!(!(distance_remove && lateral_remove)); let p = s.binding(mid, slot);
    s.event("FR", format_args!("REFRESH_POINT {mid} {slot} {} {distance_remove} {lateral_remove}", p.gid));
    s.refresh = Some((mid, cursor - 1));
}); }
pub fn refresh_end() { state(|s| {
    let (mid, cursor) = s.refresh.take().expect("active refresh"); assert_eq!(cursor, -1);
    s.event("FR", format_args!("REFRESH_END {mid} 0 0 false false"));
}); }
pub fn solver_map(keys: impl Iterator<Item = u32>) { state(|s| {
    assert!(s.owner.is_none() && s.tx.is_none()); s.solver_count = 0;
    for key in keys { assert!(s.solver_count < LIMIT); let i = s.index(key);
        s.solver[s.solver_count] = s.live[i].mid; s.solver_count += 1; }
}); }
pub fn solver_begin(mi: usize, slot: usize, flag: bool) { state(|s| {
    assert!(s.tx.is_none() && mi < s.solver_count); let mid = s.solver[mi];
    let p = s.binding(mid, slot); let tx = State::fresh(&mut s.next_tx);
    s.event("FB", format_args!("SOLVER_BEGIN {mid} {slot} {} {tx} 260 {flag}", p.gid));
    s.tx = Some((mid, slot, p.gid, tx, false, 0));
}); }
pub fn choice(velocity: bool) { state(|s| {
    let (mid, slot, gid, tx, _, mask) = s.tx.expect("active solver"); assert_eq!(mask, 0);
    s.event("FT", format_args!("SOLVER_CHOICE {mid} {slot} {gid} {tx} true {velocity} false"));
    s.tx = Some((mid, slot, gid, tx, velocity, 0));
}); }
pub fn solver_write(velocity: bool) { state(|s| {
    let (mid, slot, gid, tx, actual, old) = s.tx.expect("active writer"); assert_eq!(actual, velocity); assert_eq!(old, 0);
    let (site, mask) = if velocity { ("VELOCITY_DIR1", 1) } else { ("PLANE_BOTH", 3) };
    let i = s.by_mid(mid); assert_eq!(s.binding(mid, slot).gid, gid); s.live[i].points[slot].mask |= mask;
    s.event("FW", format_args!("{site} {mid} {slot} {gid} {tx} {mask}"));
    s.tx = Some((mid, slot, gid, tx, actual, mask));
}); }
pub fn solver_end(flag: bool) { state(|s| {
    let (mid, slot, gid, tx, velocity, writes) = s.tx.take().expect("active completion");
    assert!(flag); assert_eq!(writes, if velocity { 1 } else { 3 });
    let p = s.binding(mid, slot); assert_eq!(p.gid, gid);
    let site = if velocity { "VELOCITY_ONE" } else { "PLANE_ONE" };
    s.event("FE", format_args!("{site} {mid} {slot} {gid} {tx} {writes} {} {flag}", p.mask));
}); }
pub fn fixture_begin() { state(|s| {
    assert!(s.observed && s.fixture_snapshot && !s.fixture_active && s.tx.is_none() && s.owner.is_none());
    s.fixture_active = true; s.event("FF", format_args!("FIXTURE_BEGIN"));
}); }
pub fn fixture_end() { state(|s| {
    assert!(s.fixture_active); s.fixture_active = false; s.event("FF", format_args!("FIXTURE_END"));
}); }
pub fn fixture(key: u32, slot: usize) { state(|s| {
    assert!(s.fixture_active && s.tx.is_none() && s.owner.is_none()); let i = s.index(key); let m = s.live[i]; assert!(slot < m.count);
    let p = m.points[slot]; s.live[i].points[slot].mask |= 3;
    s.event("FW", format_args!("FIXTURE_W {} {slot} {} 0 3", m.mid, p.gid));
}); }
pub fn snapshot(mi: usize, key: u32, count: usize) { state(|s| {
    if s.observed { let m = s.live[s.index(key)]; assert_eq!(m.count, count);
        s.event("FS", format_args!("SNAPSHOT {mi} {} {count}", m.mid)); }
}); }
pub fn snapshot_id(key: u32) -> u32 { assert!(key < MAX_ID, "canonical snapshot identity"); key + 1 }
pub fn point(mi: usize, slot: usize, key: u32, flag: bool) -> u8 { state(|s| {
    if !s.observed { return if s.fixture_snapshot { 3 } else { u8::from(flag) }; }
    let m = s.live[s.index(key)]; let p = s.binding(m.mid, slot);
    s.event("FL", format_args!("SNAPSHOT {mi} {slot} {} {} {} {flag}", m.mid, p.gid, p.mask)); p.mask
}); }
pub fn directions(mi: usize, slot: usize, mask: u8, words: [[u32; 3]; 2]) { state(|s| {
    assert!(mask <= 3);
    for (index, triple) in words.iter().enumerate() {
        let bit = 1 << index; let direction = index + 1;
        if mask & bit != 0 { s.event("FD", format_args!("SNAPSHOT {mi} {slot} {direction} D 3 {:08x} {:08x} {:08x}", triple[0], triple[1], triple[2])); }
        else { let kind = if s.observed { "U" } else { "O" }; s.event("FD", format_args!("SNAPSHOT {mi} {slot} {direction} {kind} 0")); }
    }
    for (index, triple) in words.iter().enumerate() { s.event("FP", format_args!("RUST_PHYSICAL {mi} {slot} {} {:08x} {:08x} {:08x}", index + 1, triple[0], triple[1], triple[2])); }
}); }
