#![allow(dead_code, unused_imports)]
#[path = "../../rust/crates/mds-bullet/src/core/mod.rs"]
mod core;
mod observer;
use core::activation::ActivationState;
use core::dbvt::{Aabb, DbvtPolicy};
use core::discrete_collision_world::DiscreteCollisionWorld;
use core::math::{Quat, Transform, Vec3};
use core::world_objects::{BodyDesc, BodyHandle, JointDesc, Pose};
use std::io::{self, BufRead};

fn scalar(value: f32) { print!(" {:08x}", value.to_bits()); }
fn vector(value: Vec3) { for v in value.0 { scalar(v); } }
fn transform(value: Transform) { for row in value.basis.0 { vector(Vec3(row)); } vector(value.origin); }
fn float(words: &mut std::str::SplitWhitespace<'_>) -> f32 { f32::from_bits(u32::from_str_radix(words.next().unwrap(),16).unwrap()) }
fn number(words: &mut std::str::SplitWhitespace<'_>) -> usize { words.next().unwrap().parse().unwrap() }
fn pose(words: &mut std::str::SplitWhitespace<'_>) -> Pose {
    Pose { position: Vec3(std::array::from_fn(|_|float(words))), rotation: Quat(std::array::from_fn(|_|float(words))) }
}
fn snapshot(w: Option<&DiscreteCollisionWorld>, row: usize, op: &str) {
    let Some(w) = w else { println!("O {row} {op} 0 0 0 1"); return; };
    println!("O {row} {op} {} {} {} {}", w.objects().bodies().len(),w.broadphase().pairs().len(),w.manifolds().len(),u8::from(w.fixture_force_all()));
    let leaves=w.broadphase().observation().leaves;
    for (i,b) in w.objects().bodies().iter().enumerate() {
        let key=w.fixture_proxy(i);let state=w.broadphase().states()[key.0 as usize];let data=&w.objects().data()[i];
        print!("B {row} {i} {} {} {} {} {} {}",data.collision_flags,w.objects().objects()[i].activation.state as i32,state.uid,state.group,state.mask,w.broadphase().owner(key));
        let s=b.snapshot();transform(s.world);transform(s.interpolation_world);transform(data.motion.get_world_transform());
        let requested=w.broadphase().aabb(key);let leaf=leaves.iter().find(|leaf|leaf.0==key).unwrap().2;
        for a in [requested,leaf] {vector(a.min);vector(a.max);}println!();
    }
    for (i,p) in w.broadphase().pairs().iter().enumerate() {
        println!("P {row} {i} {} {} {}",w.broadphase().owner(p.proxies[0]),w.broadphase().owner(p.proxies[1]),p.algorithm.map(|key|observer::algorithm(key.0)).unwrap_or(0));
    }
    for (i,m) in w.manifolds().iter().enumerate() {
        print!("M {row} {i} {} {} {} {}",observer::manifold(m.owner().0),observer::algorithm(m.owner().0),m.bodies[0],m.bodies[1]);
        scalar(m.processing_threshold);scalar(m.manifold.contact_breaking_threshold());println!(" {}",m.manifold.contacts().len());
        for (j,p) in m.manifold.contacts().iter().enumerate() {
            print!("Q {row} {i} {j}");for v in [p.local_a,p.local_b,p.world_a,p.world_b,p.normal_on_b] {vector(v);}
            for v in [p.distance,p.combined_friction,p.combined_restitution,p.applied_impulse,p.lateral_impulses[0],p.lateral_impulses[1]] {scalar(v);}
            print!(" {} {}",p.lifetime,u8::from(p.lateral_initialized));if p.lateral_initialized {for v in p.lateral_directions {vector(v);}}println!();
        }
    }
}
fn activation(state: usize) -> ActivationState {
    match state {0=>ActivationState::Moving,1=>ActivationState::Active,2=>ActivationState::IslandSleeping,3=>ActivationState::WantsDeactivation,4=>ActivationState::DisableDeactivation,5=>ActivationState::DisableSimulation,_=>panic!("activation")}
}
fn main() {
    let policy=match std::env::args().nth(1).as_deref() {Some("generic-reference")=>DbvtPolicy::GenericReference,Some("mmd-win64-sse")=>DbvtPolicy::MmdWin64Sse,_=>panic!("explicit policy required")};
    let mut world:Option<DiscreteCollisionWorld>=None;let mut handles:Vec<BodyHandle>=Vec::new();let mut row=0;
    for line in io::stdin().lock().lines() {
        let line=line.unwrap();let mut words=line.split_whitespace();let op=words.next().unwrap();
        if op=="BIND" {
            let mut ranks=[Vec::new(),Vec::new()];let mut frees=[None,None];
            for t in 0..2 {
                for _ in 0..number(&mut words) {
                    let owner:i64=words.next().unwrap().parse().unwrap();let rank=number(&mut words);
                    let volume=Aabb {min:Vec3(std::array::from_fn(|_|float(&mut words))),max:Vec3(std::array::from_fn(|_|float(&mut words)))};
                    ranks[t].push((if owner<0 {None}else{Some(owner as usize)},volume,rank));
                }
                let free=number(&mut words);frees[t]=if free==0 {None}else{Some(free)};
            }
            world.as_mut().unwrap().fixture_bind([(&ranks[0],frees[0]),(&ranks[1],frees[1])]);
            assert!(words.next().is_none());continue;
        }
        observer::row(row);
        if op=="H" {assert!(world.is_none());words.next().unwrap();words.next().unwrap();world=Some(DiscreteCollisionWorld::public(policy));handles.clear();}
        else if op=="X" {drop(world.take().unwrap());observer::empty();}
        else {
            let w=world.as_mut().unwrap();
            match op {
                "C"=> {
                    let kind=number(&mut words);let mass=float(&mut words);let kinematic=number(&mut words)!=0;
                    let group=words.next().unwrap().parse().unwrap();let mask=words.next().unwrap().parse().unwrap();
                    let params=std::array::from_fn(|_|float(&mut words));let pose=pose(&mut words);
                    handles.push(w.create_body(BodyDesc {shape_kind:kind as i32,shape_params:params,mass,pose,kinematic,linear_damping:0.0,angular_damping:0.0,restitution:0.0,friction:0.5,filter:Some([group,mask])}).unwrap());
                }
                "D"=>w.perform_discrete_collision_detection(),
                "U"=>w.update_aabbs(),
                "F"=>w.set_force_update_all_aabbs(number(&mut words)!=0),
                "S"=>w.update_single_aabb(handles[number(&mut words)]).unwrap(),
                "A"=>{let i=number(&mut words);w.fixture_activation(i,activation(number(&mut words)));}
                "I"=>{let i=number(&mut words);w.fixture_flags(i,words.next().unwrap().parse().unwrap());}
                "T"=>{let i=number(&mut words);w.set_public_transform(handles[i],pose(&mut words)).unwrap();}
                "V"=>{let i=number(&mut words);let which=words.next().unwrap();w.fixture_transform(i,which,pose(&mut words).transform());}
                "J"=> {
                    let a=number(&mut words);let b=number(&mut words);let disable=number(&mut words)!=0;
                    let identity=Pose {position:Vec3::ZERO,rotation:Quat([0.0,0.0,0.0,1.0])};
                    w.create_joint(JointDesc {bodies:[handles[a],handles[b]],frames:[identity;2],linear_lower:Vec3::ZERO,linear_upper:Vec3::ZERO,angular_lower:Vec3::ZERO,angular_upper:Vec3::ZERO,spring_enabled:[false;6],spring_stiffness:[0.0;6],use_linear_reference_frame_a:false,disable_collisions:disable}).unwrap();
                }
                _=>panic!("unknown command"),
            }
        }
        assert!(words.next().is_none());snapshot(world.as_ref(),row,op);row+=1;
    }
    assert!(world.is_none());println!("Z {row}");
}
