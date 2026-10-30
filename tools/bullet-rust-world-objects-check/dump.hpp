#include <cstdio>
#include <cstring>
#include <vector>
static void word(float f) { unsigned u; std::memcpy(&u,&f,4); std::printf(" %08x",u); }
static void vec(const btVector3& v) { for(int i=0;i<3;i++) word(v[i]); }
static void trans(const btTransform& t) { for(int i=0;i<3;i++) vec(t.getBasis()[i]); vec(t.getOrigin()); }
struct SpringRead : btGeneric6DofSpringConstraint {
  static void dump(btGeneric6DofSpringConstraint& c) {
    auto enabled=&SpringRead::m_springEnabled;
    auto equilibrium=&SpringRead::m_equilibriumPoint;
    auto stiffness=&SpringRead::m_springStiffness;
    auto damping=&SpringRead::m_springDamping;
    for(int i=0;i<6;i++) { std::printf(" %d",(c.*enabled)[i]);word((c.*equilibrium)[i]);word((c.*stiffness)[i]);word((c.*damping)[i]); }
  }
};
struct WorldRead : btDiscreteDynamicsWorld {
  static void nonstatic(btDiscreteDynamicsWorld& w, const std::vector<btRigidBody*>& bodies) {
    auto member=&WorldRead::m_nonStaticRigidBodies;
    auto& list=w.*member;
    std::printf(" N %d",list.size());
    for(int i=0;i<list.size();i++) for(size_t j=0;j<bodies.size();j++) if(list[i]==bodies[j]) std::printf(" %zu",j);
  }
};
static void dump_body(btRigidBody* rb,btDefaultMotionState* ms) {
  trans(rb->getWorldTransform());trans(rb->getInterpolationWorldTransform());
  trans(ms->m_graphicsWorldTrans);trans(ms->m_centerOfMassOffset);trans(ms->m_startWorldTrans);
  btTransform t;ms->getWorldTransform(t);trans(t);
  vec(rb->getLinearVelocity());vec(rb->getAngularVelocity());
  vec(rb->getInterpolationLinearVelocity());vec(rb->getInterpolationAngularVelocity());
  vec(rb->getGravity());vec(rb->getInvInertiaDiagLocal());
  for(int i=0;i<3;i++) vec(rb->getInvInertiaTensorWorld()[i]);
  vec(rb->getTotalForce());vec(rb->getTotalTorque());
  word(rb->getInvMass());word(rb->getLinearDamping());word(rb->getAngularDamping());
  word(rb->getFriction());word(rb->getRestitution());word(rb->getContactProcessingThreshold());
  auto* p=rb->getBroadphaseHandle();
  std::printf(" %d %d %d %d %d",rb->getCollisionFlags(),rb->getActivationState(),p->m_collisionFilterGroup,p->m_collisionFilterMask,rb->getNumConstraintRefs());
}
static void dump_joint(btGeneric6DofSpringConstraint* c) {
  for(int i=0;i<3;i++) {auto* m=c->getTranslationalLimitMotor();word(m->m_lowerLimit[i]);word(m->m_upperLimit[i]);std::printf(" %d",m->m_enableMotor[i]);word(m->m_targetVelocity[i]);word(m->m_maxMotorForce[i]);}
  for(int i=0;i<3;i++) {auto* m=c->getRotationalLimitMotor(i);word(m->m_loLimit);word(m->m_hiLimit);std::printf(" %d",m->m_enableMotor);word(m->m_targetVelocity);word(m->m_maxMotorForce);word(m->m_ERP);word(m->m_bounce);}
  SpringRead::dump(*c);
}
