#include "BulletDynamics/ConstraintSolver/btSequentialImpulseConstraintSolver.h"
#include "BulletDynamics/ConstraintSolver/btContactSolverInfo.h"
#include "BulletCollision/NarrowPhaseCollision/btPersistentManifold.h"
#include <cstdio>
#include <cstring>
#include <initializer_list>
static void word(unsigned x){std::printf("\t%08x",x);}
static void scalar(float f){unsigned x;std::memcpy(&x,&f,4);word(x);}
static void vector(const btVector3& v){for(int i=0;i<3;i++)scalar(v[i]);}
static void point(const btManifoldPoint& p){
 vector(p.m_positionWorldOnA);vector(p.m_positionWorldOnB);vector(p.m_normalWorldOnB);
 scalar(p.m_distance1);scalar(p.m_combinedFriction);scalar(p.m_combinedRestitution);scalar(p.m_appliedImpulse);
 scalar(p.m_appliedImpulseLateral1);scalar(p.m_appliedImpulseLateral2);word(p.m_lifeTime);
 word(p.m_lateralFrictionInitialized);vector(p.m_lateralFrictionDir1);vector(p.m_lateralFrictionDir2);
}
struct Observer:btSequentialImpulseConstraintSolver {
 void edges(){
  for(unsigned bits: {0x5368d4a5u,0x7fc00000u,0xbf800000u}) {
   btSolverBody a,b;initSolverBody(&a,nullptr);initSolverBody(&b,nullptr);
   btSolverConstraint r;std::memset(&r,0,sizeof(r));
   r.m_contactNormal=btVector3(1,0,0);r.m_relpos1CrossNormal=btVector3(0,0,0);r.m_relpos2CrossNormal=btVector3(0,0,0);
   r.m_angularComponentA=btVector3(0,0,0);r.m_angularComponentB=btVector3(0,0,0);
   std::memcpy(&r.m_rhs,&bits,4);r.m_jacDiagABInv=1;r.m_upperLimit=1e10f;
   std::printf("%08x",bits);resolveSingleConstraintRowLowerLimitSIMD(a,b,r);scalar(r.m_appliedImpulse);
   vector(a.m_deltaLinearVelocity);vector(a.m_deltaAngularVelocity);vector(b.m_deltaLinearVelocity);vector(b.m_deltaAngularVelocity);std::printf("\n");
  }
 }
 void output(){
  word(m_tmpSolverContactConstraintPool.size());
  for(int group=0;group<2;group++){
   auto& pool=group?m_tmpSolverContactFrictionConstraintPool:m_tmpSolverContactConstraintPool;
   for(int i=0;i<pool.size();i++){const auto& r=pool[i];word(r.m_solverBodyIdA);word(r.m_solverBodyIdB);
    vector(r.m_contactNormal);vector(r.m_relpos1CrossNormal);vector(r.m_relpos2CrossNormal);
    vector(r.m_angularComponentA);vector(r.m_angularComponentB);scalar(r.m_jacDiagABInv);scalar(r.m_rhs);
    scalar(r.m_cfm);scalar(r.m_lowerLimit);scalar(r.m_upperLimit);scalar(r.m_appliedImpulse);
   }
  }
  word(m_tmpSolverBodyPool.size());for(int i=0;i<m_tmpSolverBodyPool.size();i++){
   vector(m_tmpSolverBodyPool[i].m_deltaLinearVelocity);vector(m_tmpSolverBodyPool[i].m_deltaAngularVelocity);
  }
 }
};
static unsigned seed=0x19378412;
static float sample(){seed^=seed<<13;seed^=seed>>17;seed^=seed<<5;return (int(seed>>8)-8388608)*(1.0f/8388608.0f);}
int main(int argc,char**){
 if(argc>1){Observer solver;solver.edges();return 0;}
 for(int id=0;id<144;id++){
  btRigidBody a(id%9==0?0:1,nullptr,nullptr,btVector3(1,2,3)),b(id%7==0?0:2,nullptr,nullptr,btVector3(2,3,4)),c(3,nullptr,nullptr,btVector3(3,4,5));
  btRigidBody* bodies[]={&a,&b,&c};btCollisionObject* objects[]={&a,&b,&c};
  btVector3 initialLinear[3],initialAngular[3];
  std::printf("%d",id);scalar(1.0f/60.0f);
  for(int i=0;i<3;i++){
   auto& body=*bodies[i];btTransform world;world.setIdentity();world.setOrigin(btVector3(sample(),sample(),sample()));
   world.setRotation(btQuaternion(btVector3(1,2,3),sample()));body.setCenterOfMassTransform(world);
   body.setLinearVelocity(id%6==0?btVector3(0,0,0):btVector3(sample(),sample(),sample()));
   body.setAngularVelocity(id%6==0?btVector3(0,0,0):btVector3(sample(),sample(),sample()));
   if(id%3==0){body.setLinearFactor(btVector3(0.5f,1.25f,-0.0f));body.setAngularFactor(btVector3(1.5f,0.25f,0));}
   initialLinear[i]=body.getLinearVelocity();initialAngular[i]=body.getAngularVelocity();
   scalar(i==0?(id%9==0?0:1):i==1?(id%7==0?0:2):3);vector(btVector3(i+1,i+2,i+3));
   for(int j=0;j<3;j++)vector(world.getBasis()[j]);vector(world.getOrigin());
   vector(body.getLinearVelocity());vector(body.getAngularVelocity());vector(body.getLinearFactor());vector(body.getAngularFactor());
  }
  btPersistentManifold m0(&a,&b,0,0.04f,1e18f),m1(&b,&c,0,0.04f,1e18f);
  btPersistentManifold* manifolds[]={&m0,&m1};
  for(int mi=0;mi<2;mi++){
   word(mi);word(mi+1);word(id%5==0?0:3);
   for(int pi=0;pi<(id%5==0?0:3);pi++){
    btVector3 normal=id%6==0?btVector3(0,1,0):btVector3(sample(),sample(),sample()).normalized();
    btManifoldPoint p(btVector3(pi,0,0),btVector3(0,pi,0),normal,id%4==0?0.0125f:-0.025f*(pi+1));
    p.m_positionWorldOnA=btVector3(sample(),sample(),sample());p.m_positionWorldOnB=btVector3(sample(),sample(),sample());
    p.m_combinedFriction=id%8==0?-0.75f:id%8==1?0:0.25f;p.m_combinedRestitution=id%2?0.88f:0;
    p.m_appliedImpulse=id%4==0?0:sample();p.m_appliedImpulseLateral1=0.125f;p.m_appliedImpulseLateral2=-0.25f;
    p.m_lifeTime=id%4;p.m_lateralFrictionInitialized=id%2;p.m_lateralFrictionDir1=btVector3(1,0,0);p.m_lateralFrictionDir2=btVector3(0,0,1);
    int index=manifolds[mi]->addManifoldPoint(p);manifolds[mi]->getContactPoint(index)=p;point(p);
   }
  }
  btContactSolverInfo info;info.m_timeStep=1.0f/60.0f;
  Observer solver;solver.solveGroupCacheFriendlySetup(objects,3,manifolds,2,nullptr,0,info,nullptr,nullptr);solver.output();
  for(auto* m:manifolds)for(int i=0;i<m->getNumContacts();i++)point(m->getContactPoint(i));
  for(auto* body:bodies)body->setCompanionId(-1);
  Observer actual;actual.solveGroup(objects,3,manifolds,2,nullptr,0,info,nullptr,nullptr,nullptr);
  for(auto* body:bodies){vector(body->getLinearVelocity());vector(body->getAngularVelocity());}
  for(auto* m:manifolds)for(int i=0;i<m->getNumContacts();i++)point(m->getContactPoint(i));
  std::printf("\n");
 }
}
