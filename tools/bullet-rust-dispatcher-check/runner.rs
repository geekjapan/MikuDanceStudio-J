#![allow(dead_code)]
#[path = "../../rust/crates/mds-bullet/src/core/mod.rs"]
mod core;
use core::activation::{ActivationState, BodyActivation, CollisionClassification};
use core::body::{BodyInit, RigidBody};
use core::dispatcher::{CollisionDispatcher, DispatchObject, DispatcherManifold};
use core::islands::{IslandConstraint, IslandObject};
use core::math::{Transform, Vec3};
use core::pair_cache::{HashedPairCache, ProxyKey, ProxyState};
use core::shape::Shape;
use core::solver::{GroupSelection, GroupSolver, SolverMode, SolverWorkspace};
use std::collections::BTreeMap;
use std::io::{self, BufRead};

fn scalar(value: f32) { print!(" {:08x}", value.to_bits()); }
fn vector(value: Vec3) { for v in value.0 { scalar(v); } }
fn read_float(words: &mut std::str::SplitWhitespace<'_>) -> f32 { f32::from_bits(u32::from_str_radix(words.next().unwrap(),16).unwrap()) }
fn number(words: &mut std::str::SplitWhitespace<'_>) -> usize { words.next().unwrap().parse().unwrap() }
fn body(mass: f32) -> RigidBody { RigidBody::new(BodyInit { mass, local_inertia: Vec3([1.0;3]), center_of_mass: Transform::IDENTITY, linear_damping: 0.0, angular_damping: 0.0 }) }
fn island() -> IslandObject { IslandObject { activation: BodyActivation::default(), classification: CollisionClassification::Dynamic, contact_response: true, island_tag: -1, companion_id: -1, hit_fraction: 1.0 } }
fn main() {
    let mut dispatcher=CollisionDispatcher::new();
    let mut cache=HashedPairCache::new();
    let states=(1..=8).map(|uid| ProxyState {uid,group:1,mask:-1}).collect::<Vec<_>>();
    let mut bodies=(0..8).map(|_| body(1.0)).collect::<Vec<_>>();
    let mut objects=vec![island();8];
    let mut shapes=vec![Shape::Sphere {radius:0.75};8];
    let mut constraints=vec![Vec::<IslandConstraint>::new();8];
    let mut thresholds=[1e18;8];
    let mut live=[false;8];
    let mut lifetimes=BTreeMap::new();
    let mut lifetime=0;
    let mut workspace=SolverWorkspace::default();
    let mut rows=0;
    for (row,line) in io::stdin().lock().lines().enumerate() {
        let line=line.unwrap();let mut words=line.split_whitespace();let op=words.next().unwrap();
        let mut solver_alias=Vec::new();
        match op {
            "F" => {
                cache.process_all(&states, |_|true, |key|dispatcher.release(key));
                live=[false;8];constraints.iter_mut().for_each(Vec::clear);lifetimes.clear();workspace=SolverWorkspace::default();
            }
            "N" => {
                let a=number(&mut words);assert!(!live[a]);let kind=number(&mut words);
                shapes[a]=match kind {0=>Shape::Sphere {radius:0.75},1=>Shape::box_shape(Vec3([0.75,0.5,0.625])),2=>Shape::CapsuleY {radius:0.4,half_height:0.5},3=>Shape::StaticPlane {normal:Vec3([0.0,1.0,0.0]),constant:0.0},_=>panic!("shape")};
                let origin=Vec3(std::array::from_fn(|_|read_float(&mut words)));
                let state=number(&mut words);let flags=number(&mut words);thresholds[a]=read_float(&mut words);
                bodies[a]=body(if flags&3!=0 {0.0}else{1.0});
                bodies[a].set_kinematic(flags&2!=0);
                bodies[a].set_center_of_mass_transform(Transform {origin,..Transform::IDENTITY});
                objects[a]=island();objects[a].activation.state=activation(state);
                objects[a].classification=match flags&3 {0=>CollisionClassification::Dynamic,1=>CollisionClassification::Static,2=>CollisionClassification::Kinematic,_=>CollisionClassification::StaticAndKinematic};
                objects[a].contact_response=flags&4==0;live[a]=true;
            }
            "P" => {let a=number(&mut words);let b=number(&mut words);cache.add(ProxyKey(a as u32),ProxyKey(b as u32),&states);}
            "A" => {let a=number(&mut words);objects[a].activation.state=activation(number(&mut words));}
            "T" => {let a=number(&mut words);let origin=Vec3(std::array::from_fn(|_|read_float(&mut words)));let world=bodies[a].snapshot().world;bodies[a].set_center_of_mass_transform(Transform {origin,..world});}
            "E" => {let a=number(&mut words);let b=number(&mut words);let on=number(&mut words);if on==1 {constraints[a].push(IslandConstraint {bodies:[a,b]});}else{constraints[a].retain(|c|c.bodies!=[a,b]);}}
            "D" => {
                let views=(0..8).map(|i| DispatchObject {shape:shapes[i],contact:bodies[i].contact_body(),activation:&objects[i].activation,constraints:&constraints[i],processing_threshold:thresholds[i]}).collect::<Vec<_>>();
                cache.for_each_algorithm(|proxies,key| {
                    let missing=key.is_none();dispatcher.near_pair(key,proxies.map(|p|p.0 as usize),&views);
                    if missing {if let Some(key)=*key {lifetime+=1;lifetimes.insert(key.0,lifetime);}}
                });
            }
            "C" | "X" => {let a=ProxyKey(number(&mut words) as u32);cache.clean_proxy(a,|key|dispatcher.release(key));if op=="X" {cache.remove_proxy(a,&states,|key|dispatcher.release(key));}}
            "R" => {let a=number(&mut words);let b=number(&mut words);cache.remove(ProxyKey(a as u32),ProxyKey(b as u32),&states,|key|dispatcher.release(key));}
            "W" => {let a=number(&mut words);for p in dispatcher.manifolds_mut()[a].manifold.contacts_mut() {p.applied_impulse=2.0;p.lateral_impulses=[0.125,-0.25];}}
            "S" => {
                for object in &mut objects {object.companion_id=-1;}
                let ids=(0..8).filter(|&i|live[i]).collect::<Vec<_>>();
                let owned_points=dispatcher.manifolds().iter().map(|m|m.manifold.contacts().as_ptr()).collect::<Vec<_>>();
                let mut views=dispatcher.manifolds_mut().iter_mut().map(DispatcherManifold::contact_view).collect::<Vec<_>>();
                solver_alias=views.iter().zip(&owned_points).map(|(view,ptr)|view.points.as_ptr()==*ptr).collect();
                let indices=(0..views.len()).collect::<Vec<_>>();
                let selection=GroupSelection {bodies:&ids,joints:&[],manifolds:&indices};
                let mut solver=GroupSolver::setup(&mut workspace,&mut objects,&bodies,&mut [],&mut views,selection,1.0/60.0,SolverMode::Simd).unwrap();
                solver.iterate(&bodies,&[],|_,_|{}).unwrap();solver.writeback(&mut bodies,&mut views);
                drop(views);
                for i in ids {if objects[i].classification==CollisionClassification::Dynamic {let s=bodies[i].snapshot();bodies[i].set_center_of_mass_transform(s.world.integrate(s.linear_velocity,s.angular_velocity,1.0/60.0));}}
            }
            _ => panic!("unknown command"),
        }
        println!("O {row} {op} {} {}",cache.pairs().len(),dispatcher.manifolds().len());
        for (i,p) in cache.pairs().iter().enumerate() {println!("P {row} {i} {} {} {}",p.proxies[0].0,p.proxies[1].0,p.algorithm.map(|k|lifetimes[&k.0]).unwrap_or(0));}
        for (i,m) in dispatcher.manifolds().iter().enumerate() {
            print!("M {row} {i} {} {} {}",lifetimes[&m.owner().0],m.bodies[0],m.bodies[1]);scalar(m.processing_threshold);scalar(m.manifold.contact_breaking_threshold());println!(" {}",m.manifold.contacts().len());
            for (j,p) in m.manifold.contacts().iter().enumerate() {
                print!("Q {row} {i} {j}");for v in [p.local_a,p.local_b,p.world_a,p.world_b,p.normal_on_b] {vector(v);}
                for s in [p.distance,p.combined_friction,p.combined_restitution,p.applied_impulse,p.lateral_impulses[0],p.lateral_impulses[1]] {scalar(s);}
                print!(" {} {}",p.lifetime,usize::from(p.lateral_initialized));if p.lateral_initialized {for d in p.lateral_directions {vector(d);}}println!();
            }
        }
        for i in 0..8 {if live[i] {let s=bodies[i].snapshot();print!("B {row} {i}");vector(s.world.origin);vector(s.linear_velocity);vector(s.angular_velocity);println!();}}
        for (i,alias) in solver_alias.iter().enumerate() {println!("L {row} {i} {}",usize::from(*alias));}
        rows=row+1;
    }
    println!("Z {rows}");
}
fn activation(state: usize) -> ActivationState {match state {0=>ActivationState::Moving,1=>ActivationState::Active,2=>ActivationState::IslandSleeping,3=>ActivationState::WantsDeactivation,4=>ActivationState::DisableDeactivation,5=>ActivationState::DisableSimulation,_=>panic!("activation")}}
