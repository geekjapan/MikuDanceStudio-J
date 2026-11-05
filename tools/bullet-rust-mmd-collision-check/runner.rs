#![allow(dead_code, unused_imports)]
#[path = "../../rust/crates/mds-bullet/src/core/mod.rs"]
mod core;
mod observer;
use core::activation::ActivationState;
use core::math::{Quat, Transform, Vec3};
use core::mmd_collision_world::MmdCollisionWorld;
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
fn snapshot(w: Option<&MmdCollisionWorld>, row: usize, op: &str) {
    let Some(w) = w else { println!("O {row} {op} 0 0 0"); return; };
    let sweep = w.fixture_sweep();
    println!("O {row} {op} {} {} {}", w.objects().bodies().len(),sweep.pairs().len(),w.manifolds().len());
    for (i,b) in w.objects().bodies().iter().enumerate() {
        let key=w.fixture_proxy(i);let state=sweep.states()[key.0 as usize];let data=&w.objects().data()[i];
        let handle=sweep.handle(key).unwrap();
        print!("B {row} {i} {} {} {} {} {} {}",data.collision_flags,w.objects().objects()[i].activation.state as i32,state.uid,state.group,state.mask,handle.owner);
        let s=b.snapshot();transform(s.world);transform(s.interpolation_world);transform(data.motion.get_world_transform());
        scalar(s.inverse_mass);scalar(b.contact_body().friction);scalar(b.contact_body().restitution);
        for v in [s.linear_velocity,s.angular_velocity,s.interpolation_linear_velocity,s.interpolation_angular_velocity] {vector(v);}
        for edge in handle.min_edges.into_iter().chain(handle.max_edges) {print!(" {edge}");}println!();
    }
    for (axis,edges) in sweep.edges().iter().enumerate() {
        print!("S {row} {axis} {}",edges.len());
        for edge in edges {print!(" {} {}",edge.pos,edge.handle);}println!();
    }
    for (i,p) in sweep.pairs().iter().enumerate() {
        println!("P {row} {i} {} {} {} {} {}",p.proxies[0].0,p.proxies[1].0,sweep.handle(p.proxies[0]).unwrap().owner,sweep.handle(p.proxies[1]).unwrap().owner,p.algorithm.map(|key|observer::algorithm(key.0)).unwrap_or(0));
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
    for (i,j) in w.objects().joints().iter().enumerate() {
        let data=w.objects().joint_data()[i];
        print!("J {row} {i} {} {} {}",data.mmd_uid.unwrap_or(i32::MIN),u8::from(data.use_linear_reference_frame_a),u8::from(data.disable_collisions));
        for spring in j.state.springs {print!(" {}",u8::from(spring.enabled));scalar(spring.stiffness);scalar(spring.equilibrium);}println!();
    }
}
fn activation(state: usize) -> ActivationState {
    match state {0=>ActivationState::Moving,1=>ActivationState::Active,2=>ActivationState::IslandSleeping,3=>ActivationState::WantsDeactivation,4=>ActivationState::DisableDeactivation,5=>ActivationState::DisableSimulation,_=>panic!("activation")}
}
fn main() {
    let mut world:Option<MmdCollisionWorld>=None;let mut handles:Vec<BodyHandle>=Vec::new();let mut row=0;
    for line in io::stdin().lock().lines() {
        let line=line.unwrap();let mut words=line.split_whitespace();let op=words.next().unwrap();
        observer::row(row);
        if op=="H" {assert!(world.is_none());words.next().unwrap();words.next().unwrap();world=Some(MmdCollisionWorld::new());handles.clear();}
        else if op=="X" {drop(world.take().unwrap());observer::empty();}
        else {
            let w=world.as_mut().unwrap();
            match op {
                "C"=> {
                    let kind=number(&mut words);let mass=float(&mut words);let mode=number(&mut words) as i32;
                    let group=words.next().unwrap().parse().unwrap();let mask=words.next().unwrap().parse().unwrap();
                    let params=std::array::from_fn(|_|float(&mut words));let pose=pose(&mut words);
                    handles.push(w.create_body(BodyDesc {shape_kind:kind as i32,shape_params:params,mass,pose,kinematic:false,linear_damping:0.0,angular_damping:0.0,restitution:0.25,friction:0.5,filter:Some([group,mask])},mode).unwrap());
                }
                "D"=>w.perform_discrete_collision_detection(),
                "U"=>w.update_aabbs(),
                "F"=>w.set_floor(number(&mut words)!=0).unwrap(),
                "S"=>w.update_single_aabb(handles[number(&mut words)-1]).unwrap(),
                "A"=>{let i=number(&mut words);w.fixture_activation(i,activation(number(&mut words)));}
                "K"=>{let i=number(&mut words);w.set_kinematic(handles[i-1],number(&mut words)!=0).unwrap();}
                "M"|"R"=>{let i=number(&mut words);let t=pose(&mut words).transform();if op=="M" {w.set_motion_state(handles[i-1],t).unwrap();}else{w.reseat(handles[i-1],t).unwrap();}}
                "O"=>{let i=number(&mut words);w.stop_at(handles[i-1],Vec3(std::array::from_fn(|_|float(&mut words)))).unwrap();}
                "V"=>{let i=number(&mut words);let linear=Vec3(std::array::from_fn(|_|float(&mut words)));let angular=Vec3(std::array::from_fn(|_|float(&mut words)));w.fixture_velocities(i,linear,angular);}
                "W"=>w.fixture_warmstart(),
                "J"=> {
                    let a=number(&mut words);let b=number(&mut words);let uid=words.next().unwrap().parse().unwrap();let spring=number(&mut words)!=0;
                    let identity=Pose {position:Vec3::ZERO,rotation:Quat([0.0,0.0,0.0,1.0])};
                    w.create_joint(JointDesc {bodies:[handles[a-1],handles[b-1]],frames:[identity;2],linear_lower:Vec3::ZERO,linear_upper:Vec3::ZERO,angular_lower:Vec3::ZERO,angular_upper:Vec3::ZERO,spring_enabled:[spring;6],spring_stiffness:[if spring {2.0}else{0.0};6],use_linear_reference_frame_a:false,disable_collisions:true},uid).unwrap();
                }
                _=>panic!("unknown command"),
            }
        }
        assert!(words.next().is_none());snapshot(world.as_ref(),row,op);row+=1;
    }
    assert!(world.is_none());println!("Z {row}");
}
