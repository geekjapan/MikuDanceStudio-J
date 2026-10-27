#include "../bullet-rust-world-objects-check/dump.hpp"
struct MotionRead : btDiscreteDynamicsWorld {
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
}
