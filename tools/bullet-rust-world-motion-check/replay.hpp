#include "../bullet-rust-world-objects-check/dump.hpp"
struct MotionRead : btDiscreteDynamicsWorld {
  static void activation(btDiscreteDynamicsWorld& w, float dt) {
    auto member = &MotionRead::updateActivationState;
    (w.*member)(dt);
  }
  static void save(btDiscreteDynamicsWorld& w, float dt) {
    auto member = &MotionRead::saveKinematicState;
    (w.*member)(dt);
  }
  static void predict(btDiscreteDynamicsWorld& w, float dt) {
    auto member = &MotionRead::predictUnconstraintMotion;
    (w.*member)(dt);
  }
  static void sync(btDiscreteDynamicsWorld& w, float dt, bool all) {
    auto member = &MotionRead::m_localTime;
    w.*member = dt;
    w.setSynchronizeAllMotionStates(all);
    w.synchronizeMotionStates();
  }
};
static btTransform fixture(int variant, int i, bool next, bool mmd) {
  btTransform t;
  t.setIdentity();
  float p = float(i + (next ? 3 : 0));
  t.setOrigin(btVector3(p, next ? -2.f : 1.f, .5f));
  btQuaternion q;
  switch ((variant + i + (next ? (variant % 2 == 0 ? 2 : 3) : 0)) % 5) {
    case 0: q = btQuaternion(0,0,0,1); break;
    case 1: q = btQuaternion(1,0,0,0); break;
    case 2: q = btQuaternion(0,1,0,0); break;
    case 3: q = btQuaternion(0,0,1,0); break;
    default: q = btQuaternion(.25f,.5f,-.125f,1); break;
  }
  t.setRotation(q);
  if (mmd && variant == 3) {
    if (next) t.getBasis().setValue(.75f,.125f,-.25f, .25f,1.25f,.5f, -.125f,.25f,1.5f);
    else t.getBasis().setValue(1.25f,.25f,-.125f, .125f,.75f,.25f, .5f,-.125f,1.5f);
  }
  return t;
}
extern "C" void activation_public();
extern "C" void activation_mmd();
static void activation_dump(btDiscreteDynamicsWorld& w, const std::vector<btRigidBody*>& bodies,
    const std::vector<btDefaultMotionState*>& motion, const char* k, int c, int r) {
  std::printf("W %s %d %d",k,c,r);vec(w.getGravity());WorldRead::nonstatic(w,bodies);std::puts("");
  for(size_t i=0;i<bodies.size();i++) {
    std::printf("B %s %d %d %zu",k,c,r,i);dump_body(bodies[i],motion[i]);word(bodies[i]->getHitFraction());std::puts("");
  }
#ifdef OBSERVER
  std::fprintf(stderr,"OBS %s %d %d %zu\n",k,c,r,bodies.size());
#endif
  for(size_t i=0;i<bodies.size();i++) {
    auto* b=bodies[i];
    std::printf("A %s %d %d %zu %d",k,c,r,i,b->getCollisionFlags()&3);
    word(b->getDeactivationTime());word(b->getLinearSleepingThreshold());word(b->getAngularSleepingThreshold());std::puts("");
  }
}
#ifdef MDS_MMD_H
extern "C" void activation_mmd() {
  const bool mmd=true;const char* k="AM";
#else
extern "C" void activation_public() {
  const bool mmd=false;const char* k="AP";
#endif
  for(int c=0;c<13;c++) {
    gDeactivationTime=2.f;gDisableDeactivation=false;
#ifdef MDS_MMD_H
    auto* owner=mds_mmd_world_create();
#else
    auto* owner=mds_bt_world_create();
#endif
    auto& w=owner->w;
    if(c!=0)for(int j=0;j<13;j++) {
#ifdef MDS_MMD_H
      float p[3]={0,0,0},q[4]={0,0,0,1};mds_mmd_body* b=nullptr;
      if(mds_mmd_body_create(owner,0,.5f,1,.75f,p,q,j==7?0:1,j==8?0:2,0,0,0,.5f,1,-1,&b))std::abort();
#else
      mds_bt_body_desc d{};d.shape_kind=0;d.shape_params[0]=.5f;d.mass=j==8?0:2;d.rotation[3]=1;d.kinematic=j==7;d.friction=.5f;
      mds_bt_body* b=nullptr;if(mds_bt_body_create(owner,&d,&b))std::abort();
#endif
    }
    std::vector<btRigidBody*> bodies;std::vector<btDefaultMotionState*> motion;
    for(auto* b:owner->bodies){bodies.push_back(b->rb);motion.push_back(static_cast<btDefaultMotionState*>(b->ms));}
    activation_dump(w,bodies,motion,k,c,0);
    float dt=c==1?0.f:.25f;
    gDeactivationTime=c>=10?0.f:(c>=4&&c<=6)?1.f:2.f;gDisableDeactivation=c>=7&&c<=9;
    for(int j=0;c!=0&&j<13;j++) {
      auto* b=bodies[int(mmd)+j];
      if(j==6||j==9)b->setCollisionFlags(b->getCollisionFlags()|2);
      int state=j==0?0:j==2?ISLAND_SLEEPING:j==3?WANTS_DEACTIVATION:j==4?DISABLE_DEACTIVATION:j==5?DISABLE_SIMULATION:ACTIVE_TAG;
      b->forceActivationState(state);
      b->setDeactivationTime(j==12?gDeactivationTime-dt+float((c-1)%3)*.25f-.25f:3.f);
      b->setSleepingThresholds(.5f,1.f);
      float speed=(c-1)%3==0?.25f:(c-1)%3==1?.5f:.75f;
      b->setLinearVelocity(btVector3(j==4||j==5?2.f:j==10?speed:.125f,0,0));
      b->setAngularVelocity(btVector3(j==4||j==5?3.f:j==11?speed*2.f:.25f,0,0));
      b->setWorldTransform(fixture(c%4,j,false,mmd));
      b->setInterpolationWorldTransform(fixture(c%4,j+1,false,mmd));
      b->setInterpolationLinearVelocity(btVector3(-2,1,.25f));b->setInterpolationAngularVelocity(btVector3(.25f,.125f,-.5f));
      b->applyCentralForce(btVector3(3,-2,1));b->applyTorque(btVector3(.5f,.25f,-.125f));b->setHitFraction(.25f);
      motion[int(mmd)+j]->setWorldTransform(fixture(c%4,j,true,mmd));
    }
#ifdef MDS_MMD_H
    mds_mmd_world_set_floor(owner,0);
#endif
    activation_dump(w,bodies,motion,k,c,1);
    MotionRead::activation(w,dt);activation_dump(w,bodies,motion,k,c,2);
    if(c!=0)bodies[int(mmd)+9]->setCollisionFlags(bodies[int(mmd)+9]->getCollisionFlags()&~2);
#ifdef MDS_MMD_H
    mds_mmd_world_set_floor(owner,1);
#endif
    MotionRead::activation(w,.25f);activation_dump(w,bodies,motion,k,c,3);
    MotionRead::activation(w,.25f);activation_dump(w,bodies,motion,k,c,4);
#ifdef MDS_MMD_H
    mds_mmd_world_destroy(owner);
#else
    mds_bt_world_destroy(owner);
#endif
    gDeactivationTime=2.f;gDisableDeactivation=false;
  }
}
template<class Set> static void replay(btDiscreteDynamicsWorld& w,
    const std::vector<btRigidBody*>& bodies, const std::vector<btDefaultMotionState*>& motion,
    bool mmd, int variant, Set set) {
  int base = mmd ? 1 : 0;
  const char* kind = mmd ? "M" : "P";
  int states[8] = {ACTIVE_TAG,ISLAND_SLEEPING,DISABLE_SIMULATION,DISABLE_SIMULATION,
                   DISABLE_DEACTIVATION,ACTIVE_TAG,WANTS_DEACTIVATION,ACTIVE_TAG};
  for (int j=0;j<8;j++) {
    int i=base+j; auto* b=bodies[i];
    if(j==4 || j==5) b->setCollisionFlags(b->getCollisionFlags()|2);
    b->forceActivationState(states[j]);
    b->setWorldTransform(fixture(variant,j,false,mmd));
    b->setInterpolationWorldTransform(fixture(variant,j+1,false,mmd));
    b->setLinearVelocity(btVector3(1,.5f,-.25f));
    b->setAngularVelocity(btVector3(.125f,-.25f,.5f));
    b->setInterpolationLinearVelocity(btVector3(-2,1,.25f));
    b->setInterpolationAngularVelocity(btVector3(.25f,.125f,-.5f));
    b->applyCentralForce(btVector3(3,-2,1));b->applyTorque(btVector3(.5f,.25f,-.125f));
    b->setHitFraction(j%3==0?0.f:j%3==1?.25f:1.f);
    set(j,fixture(variant,j,true,mmd),1);
  }
  auto dump=[&](int row) {
    std::printf("W %s %d %d",kind,variant,row);vec(w.getGravity());WorldRead::nonstatic(w,bodies);std::puts("");
    for(size_t i=0;i<bodies.size();i++) {
      std::printf("B %s %d %d %zu",kind,variant,row,i);dump_body(bodies[i],motion[i]);word(bodies[i]->getHitFraction());std::puts("");
    }
#ifdef OBSERVER
    std::fprintf(stderr,"OBS %s %d %d %zu\n",kind,variant,row,bodies.size());
#endif
  };
  dump(0);MotionRead::save(w,0);dump(1);
  MotionRead::save(w,1.f/60.f);dump(2);
  w.applyGravity();dump(3);
  MotionRead::predict(w,0);dump(4);
  MotionRead::predict(w,1.f/60.f);dump(5);
  MotionRead::sync(w,0,false);dump(6);
  MotionRead::sync(w,.007f,false);dump(7);
  MotionRead::sync(w,.007f,true);dump(8);
  set(0,fixture(variant,7,true,mmd),0);dump(9);
  set(0,fixture(variant,4,false,mmd),2);dump(10);
  MotionRead::sync(w,.007f,false);dump(11);
  set(0,fixture(variant,6,true,mmd),3);dump(12);
  MotionRead::predict(w,.007f);dump(13);
  w.clearForces();dump(14);
  bodies[base+3]->forceActivationState(ISLAND_SLEEPING);
  set(3,fixture(variant,5,false,mmd),1);
  MotionRead::save(w,.007f);dump(15);
  bodies[base+3]->forceActivationState(DISABLE_SIMULATION);
  MotionRead::save(w,.007f);dump(16);
  w.clearForces();dump(17);
  if(mmd && variant==3) {activation_public();activation_mmd();}
}
