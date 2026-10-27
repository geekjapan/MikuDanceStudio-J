#include "../../rust/crates/mds-bullet-sys/shim/mds_mmd.cpp"
#include "dump.hpp"
extern "C" void replay_mmd() {
  auto* w=mds_mmd_world_create();
  auto dump=[&](int row) {
    std::printf("W M %d",row);vec(w->w.getGravity());std::vector<btRigidBody*> raw;
    for(auto* b:w->bodies)raw.push_back(b->rb);WorldRead::nonstatic(w->w,raw);std::puts("");
    for(size_t i=0;i<w->bodies.size();i++){std::printf("B M %d %zu",row,i);dump_body(w->bodies[i]->rb,static_cast<btDefaultMotionState*>(w->bodies[i]->ms));std::puts("");}
    for(size_t i=0;i<w->joints.size();i++){std::printf("J M %d %zu",row,i);dump_joint(w->joints[i]);std::printf(" %d\n",w->joints[i]->getUid());}
#ifdef OBSERVER
    std::fprintf(stderr,"OBS M %d %zu %zu\n",row,w->bodies.size(),w->joints.size());
#endif
  };
  dump(0);float q[4]={0,0,0,1};
  for(int i=0;i<4;i++) {
    float p[3]={float(i),0,0};mds_mmd_body* b=nullptr;
    int status=mds_mmd_body_create(w,i%3,.5f,1,.75f,p,q,i%3,i==3?0:2,0,0,0,.5f,short(0x8000),short(-2),&b);
    std::printf("C M %d %d\n",i,status);dump(i+1);
  }
  float m[16]={1,0,0,0,0,1,0,0,0,0,1,0,3,4,5,1};
  auto* b=w->bodies[2];mds_mmd_body_set_motion_state(b,m);dump(5);
  b->rb->setLinearVelocity(btVector3(1,2,3));b->rb->setAngularVelocity(btVector3(4,5,6));
  b->rb->setInterpolationLinearVelocity(btVector3(7,8,9));b->rb->setInterpolationAngularVelocity(btVector3(10,11,12));
  float p[3]={9,8,7};mds_mmd_body_stop_at(b,p);dump(6);
  mds_mmd_body_reseat(b,m);dump(7);
  mds_mmd_body_set_kinematic(b,1);mds_mmd_world_set_gravity(w,3,-4,5);dump(8);
  b->rb->forceActivationState(ISLAND_SLEEPING);mds_mmd_world_set_gravity(w,6,-7,8);dump(9);
  mds_mmd_world_set_floor(w,0);dump(10);mds_mmd_world_set_floor(w,1);dump(11);
  for(int j=0;j<3;j++) {
    float z[3]={0,0,0},lo[3]={-0.f,-7,0},hi[3]={0,7,0},s[6]={0,0,0,0,0,0};
    if(j==1)s[0]=2;if(j==2)s[4]=3;
    std::printf("K M %d %d\n",j,mds_mmd_joint_create(w,w->bodies[1],w->bodies[2],z,q,z,q,z,z,lo,hi,s,17+j));dump(12+j);
  }
  mds_mmd_world_destroy(w);
}
