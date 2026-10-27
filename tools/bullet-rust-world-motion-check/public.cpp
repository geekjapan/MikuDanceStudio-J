#include "../../rust/crates/mds-bullet-sys/shim/mds_bt.cpp"
#include "replay.hpp"
extern "C" void replay_public() {
  for(int variant=0;variant<4;variant++) {
    auto* w=mds_bt_world_create();std::vector<btRigidBody*> bodies;std::vector<btDefaultMotionState*> motion;
    for(int j=0;j<8;j++) {
      mds_bt_body_desc d{};d.shape_kind=0;d.shape_params[0]=.5f;d.mass=(j==4||j==7)?0:2;
      d.rotation[3]=1;d.kinematic=j==3;d.linear_damping=.125f;d.angular_damping=.25f;d.friction=.5f;
      mds_bt_body* b=nullptr;if(mds_bt_body_create(w,&d,&b))std::abort();
      bodies.push_back(b->rb);motion.push_back(b->ms);
    }
    replay(w->w,bodies,motion,false,variant,[&](int j,const btTransform& t,int op){
      auto* b=w->bodies[j];
      if(op==0) {auto q=t.getRotation();float p[3]={t.getOrigin().x(),t.getOrigin().y(),t.getOrigin().z()};float r[4]={q.x(),q.y(),q.z(),q.w()};if(mds_bt_body_set_transform(w,b,p,r))std::abort();}
      else if(op==1)b->ms->setWorldTransform(t);
      else if(op==2){b->rb->setWorldTransform(t);b->rb->setLinearVelocity(btVector3(0,0,0));b->rb->setAngularVelocity(btVector3(0,0,0));b->rb->setInterpolationLinearVelocity(btVector3(0,0,0));b->rb->setInterpolationAngularVelocity(btVector3(0,0,0));}
      else {auto world=b->rb->getWorldTransform();world.setOrigin(t.getOrigin());b->rb->setWorldTransform(world);b->rb->setLinearVelocity(btVector3(0,0,0));b->rb->setAngularVelocity(btVector3(0,0,0));}
    });
    mds_bt_world_destroy(w);
  }
}
