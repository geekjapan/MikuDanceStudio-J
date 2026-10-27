#include "../../rust/crates/mds-bullet-sys/shim/mds_bt.cpp"
#include "dump.hpp"
extern "C" void replay_public() {
  auto* w=mds_bt_world_create(); std::vector<mds_bt_body*> bodies;
  auto dump=[&](int row) {
    std::printf("W P %d",row);vec(w->w.getGravity());std::vector<btRigidBody*> raw;
    for(auto* b:bodies) raw.push_back(b->rb); WorldRead::nonstatic(w->w,raw);std::puts("");
    for(size_t i=0;i<bodies.size();i++) {std::printf("B P %d %zu",row,i);dump_body(bodies[i]->rb,bodies[i]->ms);std::puts("");}
    for(size_t i=0;i<w->joints.size();i++) {std::printf("J P %d %zu",row,i);dump_joint(w->joints[i]->c);std::puts("");}
#ifdef OBSERVER
    std::fprintf(stderr,"OBS P %d %zu %zu\n",row,bodies.size(),w->joints.size());
#endif
  };
  mds_bt_world_set_gravity(w,1,-7,2);dump(0);
  for(int i=0;i<7;i++) {
    mds_bt_body_desc d{};d.shape_kind=i%4; d.shape_params[0]=.5f;d.shape_params[1]=1;d.shape_params[2]=.75f;
    d.mass=i==3?0:2;d.position[0]=float(i);d.rotation[3]=1;d.friction=.5f;
    if(i==3) {d.shape_params[0]=0;d.shape_params[1]=1;d.shape_params[2]=0;}
    if(i==4) d.kinematic=1;
    if(i==5) {d.has_filter=1;d.collision_group=0x8000;d.collision_mask=0xfffe;}
    mds_bt_body* b=nullptr; int status=mds_bt_body_create(w,&d,&b);std::printf("C P %d %d\n",i,status);if(status==0)bodies.push_back(b);dump(i+1);
  }
  float p[3]={-0.f,3,4},q[4]={0,0,0,1};
  mds_bt_body_set_transform(w,bodies[0],p,q);mds_bt_body_set_transform(w,bodies[4],p,q);dump(8);
  bodies[0]->rb->forceActivationState(ISLAND_SLEEPING);bodies[1]->rb->forceActivationState(DISABLE_SIMULATION);
  bodies[2]->rb->setCollisionFlags(bodies[2]->rb->getCollisionFlags()|2);
  mds_bt_world_set_gravity(w,3,-5,6);dump(9);
  bodies[0]->rb->forceActivationState(ACTIVE_TAG);mds_bt_world_set_gravity(w,4,-6,7);dump(10);
  for(int j=0;j<3;j++) {
    mds_bt_joint_desc d{};d.body_a=bodies[0];d.body_b=bodies[1];d.frame_a_rotation[3]=d.frame_b_rotation[3]=1;
    d.angular_lower[0]=-0.f;d.angular_lower[1]=-7;d.angular_upper[1]=7;
    d.disable_collision_between_bodies=j==0;d.use_linear_reference_frame_a=j%2;
    if(j==1)for(int k=0;k<6;k++){d.spring_enabled[k]=1;d.spring_stiffness[k]=float(k+1);}
    mds_bt_joint* c=nullptr;std::printf("K P %d %d\n",j,mds_bt_joint_create(w,&d,&c));dump(11+j);
  }
  mds_bt_body_desc bad{};bad.shape_kind=0;bad.mass=1;bad.rotation[3]=1;
  mds_bt_body* out=nullptr;std::printf("R P %d %zu\n",mds_bt_body_create(w,&bad,&out),w->bodies.size());
  auto* foreign=mds_bt_world_create();std::printf("F P %d\n",mds_bt_body_set_transform(foreign,bodies[0],p,q));mds_bt_world_destroy(foreign);
  dump(14);mds_bt_world_destroy(w);
}
