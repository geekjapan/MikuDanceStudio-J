"""Rust diagnostic source hooks. Full generation/inverse/compiler checks are GHA-only."""
import hashlib
from pathlib import Path

from hooks import CORE, DYNAMICS, OWNER, inverse, replace

CONTACT = CORE + 'contact.rs'
DISPATCHER = CORE + 'dispatcher.rs'
SOLVER = CORE + 'contact_solver.rs'
RUNNER = 'tools/bullet-rust-mmd-collision-check/runner.rs'
RUNTIME = 'tools/bullet-rust-mmd-collision-check/friction_rust.rs'
SOURCE_PATHS = (CONTACT, DISPATCHER, SOLVER, DYNAMICS, OWNER)
SEMANTIC_MODE = 260
SOURCE_SHA256 = {
    CONTACT: 'b473127a44fc4c4fcc381022ac0d46887e49e171cdbdbe5389e4689793a1fec4',
    DISPATCHER: '65e08dddac41b841cd1d78b0938f90e37945a5b3963e295afd805097090c1539',
    SOLVER: 'cf75cd640c429e7e3bdaf5fbacfd541beab89b8aea29f5e44f789ed1e74de73a',
    DYNAMICS: '145c6619525f3c4581962ff7ffb7fec58e6d3678fb8a618b53586228e78a389c',
    OWNER: '52870e4a8f31760951940f919a73f0e8085eaf7f9c6048468becab1b3697ecfe',
    'tools/bullet-rust-mmd-collision-check/fixture.rs': '2d21e1d2f32f3280c7fb9f5f0dd5c370ae9cef761608e193a76dfc1fbc454c4a',
    'tools/bullet-rust-mmd-collision-check/dynamics_fixture.rs': 'cb1e3d040ac39993d93172f289bef19c9aa38763f3b49e4f7a42cd853a29a4ea',
    RUNNER: '180c905dcc6695d56ba6cc9636ee4d9faba8e2e530777a4cb981b29f6ecbc66e',
}


def preflight(root):
    """Before either variant's edits, reject every unreviewed source-byte change."""
    lines = []
    for path, expected in SOURCE_SHA256.items():
        raw = (Path(root) / path).read_bytes()
        actual = hashlib.sha256(raw).hexdigest()
        if actual != expected:
            raise ValueError('frozen Rust source identity: ' + path)
        lines.append(f'{actual} {len(raw)} {path}\n')
    return ''.join(lines)


def instrument(root, here):
    """Apply after legacy hooks.instrument(..., dynamics=True), only to observed.

    AlgorithmKey plus allocation epoch identifies a manifold through Vec moves.
    Process/clear scopes bind its owner; solver indices bind before view borrowing.
    Only insert's actual incoming ContactPoint creates FC. EMPTY backing slots and
    read-only nearest/replacement/refresh copies produce no invented FC/FPY.
    """
    changes = []

    def edit(path, old, new):
        replace(root, path, old, new, changes)

    old = '        self.manifolds.push(DispatcherManifold {'
    edit(DISPATCHER, old, '        crate::friction_rust::allocate(key.0, bodies);\n' + old)
    old = '''            self.manifolds[index].manifold.process(
                objects[a].contact,
                objects[b].contact,
                &mut self.simplex,
            );'''
    edit(DISPATCHER, old, '            crate::friction_rust::enter(key.0);\n' + old +
         '\n            crate::friction_rust::leave(key.0);')
    old = '            self.manifolds[index].manifold.clear_contacts();'
    edit(DISPATCHER, old, '            crate::friction_rust::enter(key.0);\n' + old +
         '\n            crate::friction_rust::leave(key.0);\n            crate::friction_rust::release(key.0);')
    old = '''    pub(crate) fn clear_contacts(&mut self) {
        self.count = 0;
    }'''
    edit(CONTACT, old, '''    pub(crate) fn clear_contacts(&mut self) {
        let friction_old_count = self.count;
        self.count = 0;
        crate::friction_rust::clear(friction_old_count);
    }''')
    old = '    fn insert(&mut self, mut point: ContactPoint) {\n        let index = if let Some(index) = self.nearest(point) {'
    edit(CONTACT, old, '''    fn insert(&mut self, mut point: ContactPoint) {
        crate::friction_rust::incoming();
        let friction_old_count = self.count;
        let mut friction_replacing = false;
        let index = if let Some(index) = self.nearest(point) {
            friction_replacing = true;''')
    old = '        self.points[index] = point;\n    }'
    edit(CONTACT, old, '        self.points[index] = point;\n'
         '        crate::friction_rust::insert(index, friction_old_count, friction_replacing);\n    }')
    old = '''    fn remove(&mut self, index: usize) {
        self.count -= 1;
        if index != self.count {
            self.points[index] = self.points[self.count];
        }
    }'''
    edit(CONTACT, old, '''    fn remove(&mut self, index: usize) {
        let friction_old_count = self.count;
        self.count -= 1;
        if index != self.count {
            self.points[index] = self.points[self.count];
        }
        crate::friction_rust::remove(index, friction_old_count);
    }''')
    old = '    fn refresh(&mut self, a: Transform, b: Transform) {\n        for point in self.points[..self.count].iter_mut().rev() {'
    edit(CONTACT, old, '    fn refresh(&mut self, a: Transform, b: Transform) {\n'
         '        crate::friction_rust::refresh_begin(self.count);\n        for point in self.points[..self.count].iter_mut().rev() {')
    old = '''                self.remove(i);
            } else {
                let projected = point.world_a.sub(point.normal_on_b.scale(point.distance));
                if point.world_b.sub(projected).length2() > self.threshold * self.threshold {
                    self.remove(i);
                }
            }
        }
    }'''
    edit(CONTACT, old, '''                crate::friction_rust::refresh_point(i, true, false);
                self.remove(i);
            } else {
                let projected = point.world_a.sub(point.normal_on_b.scale(point.distance));
                if point.world_b.sub(projected).length2() > self.threshold * self.threshold {
                    crate::friction_rust::refresh_point(i, false, true);
                    self.remove(i);
                } else {
                    crate::friction_rust::refresh_point(i, false, false);
                }
            }
        }
        crate::friction_rust::refresh_end();
    }''')
    old = '        let mut contacts: Vec<_> = manifolds.iter_mut().map(|m| m.contact_view()).collect();'
    edit(DYNAMICS, old, '        crate::friction_rust::solver_map(manifolds.iter().map(|m| m.owner().0));\n' + old)
    old = '''            let lateral = velocity.sub(point.normal_on_b.scale(relative_velocity));
            if lateral.length2() > f32::EPSILON {
                point.lateral_directions[0] = lateral.normalize();'''
    edit(SOLVER, old, '''            crate::friction_rust::solver_begin(mi, pi, point.lateral_initialized);
            let lateral = velocity.sub(point.normal_on_b.scale(relative_velocity));
            let friction_velocity = lateral.length2() > f32::EPSILON;
            crate::friction_rust::choice(friction_velocity);
            if friction_velocity {
                point.lateral_directions[0] = lateral.normalize();
                crate::friction_rust::solver_write(true);''')
    old = '''                point.lateral_directions = [p, q];
            }
            point.lateral_initialized = true;'''
    edit(SOLVER, old, '''                point.lateral_directions = [p, q];
                crate::friction_rust::solver_write(false);
            }
            point.lateral_initialized = true;
            crate::friction_rust::solver_end(point.lateral_initialized);''')
    old = '''        for m in self.collision.dispatcher.manifolds_mut() {
            for p in m.manifold.contacts_mut() {'''
    edit(OWNER, old, '''        for m in self.collision.dispatcher.manifolds_mut() {
            let friction_key = m.owner().0;
            for (friction_slot, p) in m.manifold.contacts_mut().iter_mut().enumerate() {''')
    old = '                p.lateral_directions = [Vec3([1.0, 0.0, 0.0]), Vec3([0.0, 0.0, 1.0])];'
    edit(OWNER, old, old + '\n                crate::friction_rust::fixture(friction_key, friction_slot);')
    return changes


def original_fixtures(root, here):
    """Original core receives fixture appendages only, with no observation hooks."""
    changes = []
    for path, fixture in ((OWNER, 'fixture.rs'), (DYNAMICS, 'dynamics_fixture.rs')):
        old = (Path(root) / path).read_text()
        replace(root, path, old, old + '\n' + (Path(here) / fixture).read_text(), changes)
    return changes


def consumer(root, observed):
    """Generate safe27 Q and every physical Rust FP for either explicit variant.

    Caller places friction_rust.rs beside runner.rs and provides environment
    MMD_FRICTION_ROLE, MMD_FRICTION_CORPUS_SHA and MMD_FRICTION_COMMANDS.
    Original core stays uninstrumented; original identity correspondence is a
    separate required integration gate, not fabricated lifecycle observation.
    """
    if type(observed) is not bool:
        raise ValueError('actual observed boolean')
    changes = []

    def edit(old, new):
        replace(root, RUNNER, old, new, changes)

    edit('mod observer;', '''#[macro_use]
mod friction_output {
    macro_rules! print { ($($arg:tt)*) => { crate::friction_rust::output(format_args!($($arg)*)) }; }
    macro_rules! println {
        () => { crate::friction_rust::output(format_args!("\\n")) };
        ($($arg:tt)*) => { crate::friction_rust::output(format_args!("{}\\n", format_args!($($arg)*))) };
    }
}
mod friction_rust;
mod observer;''')
    old = '        scalar(m.processing_threshold);scalar(m.manifold.contact_breaking_threshold());println!(" {}",m.manifold.contacts().len());'
    edit(old, old + '\n        friction_rust::snapshot(i,m.owner().0,m.manifold.contacts().len());')
    old = '        for (j,p) in m.manifold.contacts().iter().enumerate() {\n            print!("Q {row} {i} {j}");'
    edit(old, '        for (j,p) in m.manifold.contacts().iter().enumerate() {\n'
         '            let friction_mask=friction_rust::point(i,j,m.owner().0,p.lateral_initialized);\n'
         '            print!("Q {row} {i} {j}");')
    old = '            print!(" {} {}",p.lifetime,u8::from(p.lateral_initialized));if p.lateral_initialized {for v in p.lateral_directions {vector(v);}}println!();'
    edit(old, '            println!(" {} {}",p.lifetime,p.lateral_initialized);\n'
         '            friction_rust::directions(i,j,friction_mask,p.lateral_directions.map(|v|v.0.map(f32::to_bits)));')
    variant = 'rust-observed' if observed else 'rust-original'
    old = 'fn main() {\n    let mut world:Option<World>=None;'
    edit(old, 'fn main() {\n'
         '    friction_rust::begin("' + variant + '",&std::env::var("MMD_FRICTION_ROLE").unwrap(),\n'
         '        &std::env::var("MMD_FRICTION_CORPUS_SHA").unwrap(),std::env::var("MMD_FRICTION_COMMANDS").unwrap().parse().unwrap());\n'
         '    let mut world:Option<World>=None;')
    edit('        observer::row(row);', '        friction_rust::command(row,op);\n        observer::row(row);')
    old = '        assert!(words.next().is_none());snapshot(world.as_ref(),row,op);row+=1;'
    edit(old, '        assert!(words.next().is_none());snapshot(world.as_ref(),row,op);friction_rust::command_end();row+=1;')
    old = '    assert!(world.is_none());println!("Z {row}");'
    edit(old, old + '\n    friction_rust::finish();')
    if not observed:
        edit('observer::algorithm(key.0)', 'friction_rust::snapshot_id(key.0)')
        edit('observer::manifold(m.owner().0),observer::algorithm(m.owner().0)',
             'friction_rust::snapshot_id(m.owner().0),friction_rust::snapshot_id(m.owner().0)')
    return changes


def originals(root, paths):
    return {path: (Path(root) / path).read_bytes() for path in paths}


def source_binding():
    """Source obligations in text, without a new authority JSON record type."""
    return '''RUST_FRICTION_SOURCE_BINDING 1
semantic_mode 260
recompute unconditional
two false
anisotropy no fields/calls/assignments in contact_solver.rs
incoming add_contact ContactPoint-EMPTY -> insert once
backing EMPTY no FC
readonly nearest replacement refresh no incoming FPY
identity AlgorithmKey allocation-epoch-mid
owner_scope dispatcher near_pair-process release-clear
solver_map mmd_dynamics_world before-contact-view-collection
writers contact_solver velocity-dir1 plane-both; fixture warmstart-both
refresh contact.rs actual descending branch-taken FR; no Rust callback FG
physical original observed all-six-words every-Q
inverse hooks.inverse complete-original-bytes
original_identity_correspondence required-independent-integration-gate
result DIAGNOSTIC_ONLY
final_parity BLOCK
admission BLOCK
seal BLOCK
'''
