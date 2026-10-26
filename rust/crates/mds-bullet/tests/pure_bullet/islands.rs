use crate::core::activation::{ActivationState as A, BodyActivation, CollisionClassification as C};
use crate::core::islands::{
    IslandCallback, IslandConstraint, IslandManifold, IslandObject, SimulationIslands, SolverEvent,
    UnionFind,
};
use std::fmt::Write;

struct Input<'a>(std::str::SplitWhitespace<'a>);
impl Input<'_> {
    fn word(&mut self) -> &str {
        self.0.next().expect("truncated input")
    }
    fn n(&mut self) -> usize {
        self.word().parse().unwrap()
    }
    fn i(&mut self) -> i32 {
        self.word().parse().unwrap()
    }
    fn f(&mut self) -> f32 {
        f32::from_bits(self.word().parse().unwrap())
    }
}
fn uf(out: &mut String, u: &UnionFind) {
    write!(out, " {}", u.elements().len()).unwrap();
    for e in u.elements() {
        write!(out, " {} {}", e.id, e.size_or_body_index).unwrap();
    }
}
fn list(out: &mut String, values: &[usize]) {
    write!(out, " {}", values.len()).unwrap();
    for v in values {
        write!(out, " {v}").unwrap();
    }
}
fn island(out: &mut String, i: IslandCallback<'_>) {
    list(out, i.bodies);
    list(out, i.manifolds);
}
fn dump(
    out: &mut String,
    id: usize,
    phase: &str,
    s: &SimulationIslands,
    objects: &[IslandObject],
    count: usize,
    events: &str,
) {
    write!(out, "{id} {phase}").unwrap();
    uf(out, &s.union_find);
    write!(out, " {}", objects.len()).unwrap();
    for (index, o) in objects.iter().enumerate() {
        let flags = match o.classification {
            C::Dynamic => 0,
            C::Static => 1,
            C::Kinematic => 2,
            C::StaticAndKinematic => 3,
        };
        write!(
            out,
            " {} {} {} {} {} {} {} {}",
            index,
            o.activation.state as i32,
            flags,
            usize::from(o.contact_response),
            o.island_tag,
            o.companion_id,
            o.hit_fraction.to_bits(),
            o.activation.deactivation_time.to_bits()
        )
        .unwrap();
    }
    writeln!(out, " {count}{events}").unwrap();
}
fn replay(inputs: &str) -> String {
    let mut out = String::new();
    for line in inputs.lines() {
        let mut input = Input(line.split_whitespace());
        let id = input.n();
        let op = input.word().to_owned();
        let n = input.n();
        if op == "U" {
            let mut u = UnionFind::default();
            u.reset(n);
            write!(out, "{id} reset").unwrap();
            uf(&mut out, &u);
            out.push('\n');
            let count = input.n();
            for _ in 0..count {
                let command = input.word().to_owned();
                let mut result = -1;
                match command.as_str() {
                    "J" => {
                        let a = input.n();
                        let b = input.n();
                        u.unite(a, b);
                    }
                    "F" => {
                        result = u.find(input.n()) as i32;
                    }
                    "S" => u.sort_islands(),
                    _ => panic!("unknown UF command"),
                }
                write!(out, "{id} {command} {result}").unwrap();
                uf(&mut out, &u);
                out.push('\n');
            }
        } else {
            assert_eq!(op, "W");
            let split = input.n() != 0;
            let mode = input.n();
            let mut objects = Vec::new();
            for _ in 0..n {
                let state = match input.n() {
                    0 => A::Moving,
                    1 => A::Active,
                    2 => A::IslandSleeping,
                    3 => A::WantsDeactivation,
                    4 => A::DisableDeactivation,
                    5 => A::DisableSimulation,
                    _ => panic!("state"),
                };
                let classification = match input.n() {
                    0 => C::Dynamic,
                    1 => C::Static,
                    2 => C::Kinematic,
                    3 => C::StaticAndKinematic,
                    _ => panic!("class"),
                };
                let contact_response = input.n() != 0;
                let deactivation_time = input.f();
                let island_tag = input.i();
                let companion_id = input.i();
                let hit_fraction = input.f();
                objects.push(IslandObject {
                    activation: BodyActivation {
                        state,
                        deactivation_time,
                        ..BodyActivation::default()
                    },
                    classification,
                    contact_response,
                    island_tag,
                    companion_id,
                    hit_fraction,
                });
            }
            let count = input.n();
            let pairs: Vec<_> = (0..count).map(|_| [input.n(), input.n()]).collect();
            let count = input.n();
            let constraints: Vec<_> = (0..count)
                .map(|_| {
                    let bodies = [input.n(), input.n()];
                    let _rows = input.n();
                    let _disable = input.n();
                    IslandConstraint { bodies }
                })
                .collect();
            let count = input.n();
            let manifolds: Vec<_> = (0..count)
                .map(|_| {
                    let bodies = [input.n(), input.n()];
                    let _points = input.n();
                    let _distance = input.f();
                    IslandManifold { bodies }
                })
                .collect();
            let mut s = SimulationIslands::default();
            if mode != 0 {
                s.calculate(&mut objects, pairs, &constraints);
                dump(&mut out, id, "calculate", &s, &objects, 0, "");
            } else {
                s.update_activation_state(&mut objects, pairs);
                dump(&mut out, id, "update", &s, &objects, 0, "");
                s.unite_constraints(&objects, &constraints);
                dump(&mut out, id, "unite", &s, &objects, 0, "");
                s.store_activation_state(&mut objects);
                dump(&mut out, id, "store", &s, &objects, 0, "");
            }
            let mut events = String::new();
            let mut count = 0;
            if mode != 0 {
                s.solve_constraints(&mut objects, &manifolds, &constraints, split, |event| {
                    count += 1;
                    match event {
                        SolverEvent::Prepare {
                            num_bodies,
                            num_manifolds,
                        } => write!(events, " P {num_bodies} {num_manifolds}").unwrap(),
                        SolverEvent::AllSolved => events.push_str(" A"),
                        SolverEvent::SolveGroup {
                            island: i,
                            constraints,
                        } => {
                            events.push_str(" G");
                            island(&mut events, i);
                            list(&mut events, constraints);
                        }
                    }
                });
            } else {
                s.build_and_process(&mut objects, &manifolds, split, |i| {
                    count += 1;
                    write!(events, " C {}", i.island_id).unwrap();
                    island(&mut events, i);
                });
            }
            dump(
                &mut out,
                id,
                if mode != 0 { "solve" } else { "build" },
                &s,
                &objects,
                count,
                &events,
            );
        }
        assert!(input.0.next().is_none(), "unconsumed input");
    }
    out
}
#[test]
fn native_complete_scenarios() {
    let input = std::env::var("MDS_ISLANDS_INPUTS")
        .ok()
        .map(|p| std::fs::read_to_string(p).unwrap())
        .unwrap_or_else(|| include_str!("../islands_data/inputs.tsv").to_owned());
    let expected = std::env::var("MDS_ISLANDS_NATIVE")
        .ok()
        .map(|p| std::fs::read_to_string(p).unwrap())
        .unwrap_or_else(|| include_str!("../islands_data/native.tsv").to_owned());
    let actual = replay(&input);
    let a: Vec<_> = actual.lines().collect();
    let b: Vec<_> = expected.lines().collect();
    assert_eq!(a.len(), b.len());
    for (i, (a, b)) in a.iter().zip(&b).enumerate() {
        assert_eq!(a, b, "native snapshot {i}");
    }
}
