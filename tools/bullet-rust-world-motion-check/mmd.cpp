#include "../../rust/crates/mds-bullet-sys/shim/mds_mmd.cpp"
#include "replay.hpp"
extern "C" void replay_mmd() {
  for(int variant=0;variant<4;variant++) {
    auto* w=mds_mmd_world_create();std::vector<btRigidBody*> bodies;std::vector<btDefaultMotionState*> motion;
    for(int j=0;j<8;j++) {
      float p[3]={0,0,0},q[4]={0,0,0,1};mds_mmd_body* b=nullptr;
      if(mds_mmd_body_create(w,0,.5f,1,.75f,p,q,j==3?0:1,(j==4||j==7)?0:2,.125f,.25f,0,.5f,1,-1,&b))std::abort();
    }
    for(auto* b:w->bodies){bodies.push_back(b->rb);motion.push_back(static_cast<btDefaultMotionState*>(b->ms));}
    replay(w->w,bodies,motion,true,variant,[&](int j,const btTransform& t,int op){
      auto* b=w->bodies[j+1];float matrix[16]={};matrix[15]=1;
      for(int r=0;r<3;r++)for(int c=0;c<3;c++)matrix[4*c+r]=t.getBasis()[r][c];
      for(int r=0;r<3;r++)matrix[12+r]=t.getOrigin()[r];
      if(op==0||op==1)mds_mmd_body_set_motion_state(b,matrix);
      else if(op==2)mds_mmd_body_reseat(b,matrix);
      else mds_mmd_body_stop_at(b,matrix+12);
    });
    mds_mmd_world_destroy(w);
  }
}
