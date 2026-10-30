// Test adapter. All impulse arithmetic executes in the real native solveGroup.
#include "BulletDynamics/ConstraintSolver/btGeneric6DofSpringConstraint.h"
#include "BulletDynamics/ConstraintSolver/btSequentialImpulseConstraintSolver.h"
#include "BulletCollision/NarrowPhaseCollision/btPersistentManifold.h"
#include "BulletDynamics/ConstraintSolver/btContactSolverInfo.h"
#include <cstdio>
#include <cstring>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>
#include <memory>
#include <cassert>
#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif
struct SpringJoint:btGeneric6DofSpringConstraint {
 using btGeneric6DofSpringConstraint::btGeneric6DofSpringConstraint;
 void equilibrium(int axis,float value){m_equilibriumPoint[axis]=value;}
};
static FILE* output;
static int case_id, step_id;
static std::vector<btRigidBody*> bodies;
static std::vector<btPersistentManifold*> manifolds;
static void word(unsigned x){fprintf(output,"\t%08x",x);}
static void scalar(float x){unsigned w;memcpy(&w,&x,4);word(w);}
static void vector(const btVector3& v){for(int i=0;i<3;i++)scalar(v[i]);}
static void transform(const btTransform& t){for(int i=0;i<3;i++)vector(t.getBasis()[i]);vector(t.getOrigin());}
static void point(const btManifoldPoint& p){
 vector(p.m_localPointA);vector(p.m_localPointB);vector(p.m_positionWorldOnA);vector(p.m_positionWorldOnB);vector(p.m_normalWorldOnB);
 scalar(p.m_distance1);scalar(p.m_combinedFriction);scalar(p.m_combinedRestitution);scalar(p.m_appliedImpulse);scalar(p.m_appliedImpulseLateral1);scalar(p.m_appliedImpulseLateral2);
 word(p.m_lifeTime);word(p.m_lateralFrictionInitialized);vector(p.m_lateralFrictionDir1);vector(p.m_lateralFrictionDir2);
}
static void originals(bool companions){
 word(bodies.size());
 for(auto* b:bodies){
  if(companions)word(b->getCompanionId());
  transform(b->getWorldTransform());vector(b->getLinearVelocity());vector(b->getAngularVelocity());
  vector(b->getLinearFactor());vector(b->getAngularFactor());scalar(b->getInvMass());vector(b->getInvInertiaDiagLocal());
  for(int i=0;i<3;i++)vector(b->getInvInertiaTensorWorld()[i]);
  vector(b->getTotalForce());vector(b->getTotalTorque());scalar(b->getFriction());scalar(b->getRestitution());
  transform(b->getInterpolationWorldTransform());vector(b->getInterpolationLinearVelocity());vector(b->getInterpolationAngularVelocity());vector(b->getGravity());scalar(b->getLinearDamping());scalar(b->getAngularDamping());word(b->isStaticObject());word(b->isKinematicObject());
 }
 word(manifolds.size());for(auto* m:manifolds){word(m->getNumContacts());for(int i=0;i<m->getNumContacts();i++)point(m->getContactPoint(i));}
}
void mixed_trace(int kind,int iteration,int index,const btAlignedObjectArray<btSolverBody>& pool,const btAlignedObjectArray<btSolverConstraint>& joints,const btAlignedObjectArray<btSolverConstraint>& normals,const btAlignedObjectArray<btSolverConstraint>& frictions){
 if(!output)return;
 fprintf(output,"%d\t%d\t%d\t%d\t%d",case_id,step_id,kind,iteration,index);
 word(pool.size());for(int i=0;i<pool.size();i++){
  const auto& b=pool[i];word(b.m_originalBody?b.m_originalBody->m_debugBodyId:unsigned(-1));
  vector(b.m_invMass);vector(b.m_angularFactor);vector(b.m_deltaLinearVelocity);vector(b.m_deltaAngularVelocity);vector(b.m_pushVelocity);vector(b.m_turnVelocity);
 }
 const btAlignedObjectArray<btSolverConstraint>* groups[]={&joints,&normals,&frictions};
 for(int group=0;group<3;group++){
  const auto& rows=*groups[group];word(rows.size());for(int i=0;i<rows.size();i++){
   const auto& r=rows[i];word(r.m_solverBodyIdA);word(r.m_solverBodyIdB);
   vector(r.m_contactNormal);vector(r.m_relpos1CrossNormal);vector(r.m_relpos2CrossNormal);vector(r.m_angularComponentA);vector(r.m_angularComponentB);
   scalar(r.m_jacDiagABInv);scalar(r.m_rhs);scalar(r.m_cfm);scalar(r.m_lowerLimit);scalar(r.m_upperLimit);scalar(r.m_appliedImpulse);
   if(group==1){int mi=-1,pi=-1;for(int m=0;m<int(manifolds.size());m++)for(int p=0;p<manifolds[m]->getNumContacts();p++)if(&manifolds[m]->getContactPoint(p)==r.m_originalContactPoint){mi=m;pi=p;}word(mi);word(pi);scalar(r.m_friction);}
   if(group==2)word(r.m_frictionIndex);
   scalar(r.m_appliedPushImpulse);
   if(group==0){scalar(r.m_friction);scalar(r.m_rhsPenetration);word(r.m_numConsecutiveRowsPerKernel);word(r.m_frictionIndex);word(r.m_originalContactPoint==nullptr);}
   if(group==1){scalar(r.m_rhsPenetration);word(r.m_frictionIndex);}
   if(group==2){scalar(r.m_friction);scalar(r.m_rhsPenetration);word(r.m_numConsecutiveRowsPerKernel);word(r.m_originalContactPoint==nullptr);}
  }
 }
 originals(true);fprintf(output,"\n");
}
struct Reader {
 std::istringstream in;
 explicit Reader(const std::string& s):in(s){}
 unsigned word(){std::string s;assert(bool(in>>s));return unsigned(std::stoul(s,nullptr,16));}
 float scalar(){unsigned w=word();float f;memcpy(&f,&w,4);return f;}
 btVector3 vector(){float x=scalar(),y=scalar(),z=scalar();return btVector3(x,y,z);}
 btTransform transform(){btMatrix3x3 basis;for(int i=0;i<3;i++)basis[i]=vector();btVector3 origin=vector();return btTransform(basis,origin);}
};
int main(int argc,char** argv){
 assert(argc==3);
#ifdef _WIN32
 _setmode(_fileno(stdout),_O_BINARY);
#endif
 std::ifstream inputs(argv[1]);FILE* trace=fopen(argv[2],"wb");assert(trace);std::string line;
 while(std::getline(inputs,line)){
  Reader r(line);r.in>>case_id;float dt=r.scalar();int mode=r.word(),nb=r.word(),steps=r.word();bodies.clear();manifolds.clear();
  std::vector<std::unique_ptr<btRigidBody>> body_storage;
  for(int i=0;i<nb;i++){
   float mass=r.scalar();btVector3 inertia=r.vector();btTransform world=r.transform();
   btRigidBody::btRigidBodyConstructionInfo init(mass,nullptr,nullptr,inertia);init.m_startWorldTransform=world;auto b=std::make_unique<btRigidBody>(init);b->setCenterOfMassTransform(world);b->setLinearVelocity(r.vector());b->setAngularVelocity(r.vector());b->setLinearFactor(r.vector());b->setAngularFactor(r.vector());
   if(r.word())b->setCollisionFlags(b->getCollisionFlags()|btCollisionObject::CF_KINEMATIC_OBJECT);b->m_debugBodyId=i;
   bodies.push_back(b.get());body_storage.push_back(std::move(b));
  }
  int nj=r.word();std::vector<std::unique_ptr<SpringJoint>> joint_storage;std::vector<btTypedConstraint*> joints;
  for(int i=0;i<nj;i++){
   unsigned a=r.word(),b=r.word();btTransform fa=r.transform(),fb=r.transform();auto j=std::make_unique<SpringJoint>(*bodies[a],*bodies[b],fa,fb,true);
   for(int axis=0;axis<6;axis++){
    float lower=r.scalar(),upper=r.scalar();bool enabled=r.word();float velocity=r.scalar(),force=r.scalar();bool spring=r.word();float equilibrium=r.scalar(),stiffness=r.scalar(),damping=r.scalar();
    j->setLimit(axis,lower,upper);j->enableSpring(axis,spring);j->equilibrium(axis,equilibrium);j->setStiffness(axis,stiffness);j->setDamping(axis,damping);
    if(axis<3){auto* m=j->getTranslationalLimitMotor();m->m_enableMotor[axis]=enabled;m->m_targetVelocity[axis]=velocity;m->m_maxMotorForce[axis]=force;m->m_currentLinearDiff[axis]=0;m->m_currentLimit[axis]=0;m->m_currentLimitError[axis]=0;}
    else{auto* m=j->getRotationalLimitMotor(axis-3);m->m_enableMotor=enabled;m->m_targetVelocity=velocity;m->m_maxMotorForce=force;m->m_currentPosition=0;m->m_currentLimit=0;m->m_currentLimitError=0;}
   }
   joints.push_back(j.get());joint_storage.push_back(std::move(j));
  }
  int nm=r.word();std::vector<std::unique_ptr<btPersistentManifold>> manifold_storage;
  for(int i=0;i<nm;i++){
   unsigned a=r.word(),b=r.word();float threshold=r.scalar();int np=r.word();auto m=std::make_unique<btPersistentManifold>(bodies[a],bodies[b],0,.04f,threshold);
   for(int p=0;p<np;p++){
    btVector3 la=r.vector(),lb=r.vector(),wa=r.vector(),wb=r.vector(),normal=r.vector();float distance=r.scalar();btManifoldPoint pt(la,lb,normal,distance);
    pt.m_positionWorldOnA=wa;pt.m_positionWorldOnB=wb;pt.m_combinedFriction=r.scalar();pt.m_combinedRestitution=r.scalar();pt.m_appliedImpulse=r.scalar();pt.m_appliedImpulseLateral1=r.scalar();pt.m_appliedImpulseLateral2=r.scalar();pt.m_lifeTime=r.word();pt.m_lateralFrictionInitialized=r.word();pt.m_lateralFrictionDir1=r.vector();pt.m_lateralFrictionDir2=r.vector();int k=m->addManifoldPoint(pt);m->getContactPoint(k)=pt;
   }
   manifolds.push_back(m.get());manifold_storage.push_back(std::move(m));
  }
  std::string extra;assert(!(r.in>>extra));
  std::vector<btCollisionObject*> objects(bodies.begin(),bodies.end());btContactSolverInfo info;info.m_timeStep=dt;info.m_solverMode=mode;info.m_numIterations=10;
  btSequentialImpulseConstraintSolver solver;
  for(step_id=0;step_id<steps;step_id++){
   for(auto* b:bodies)b->setCompanionId(-1);
   output=trace;solver.solveGroup(objects.data(),nb,manifolds.data(),nm,joints.data(),nj,info,nullptr,nullptr,nullptr);
   output=stdout;printf("%d\t%d",case_id,step_id);originals(false);printf("\n");
   if(case_id%48>=40 && step_id==0){
    for(auto* b:bodies)if(!b->isStaticOrKinematicObject()){btTransform next;b->predictIntegratedTransform(dt,next);b->setCenterOfMassTransform(next);}
    for(auto* m:manifolds)for(int pi=0;pi<m->getNumContacts();pi++){
     auto& p=m->getContactPoint(pi);auto* b=static_cast<const btRigidBody*>(m->getBody0());
     p.m_positionWorldOnA=b->getWorldTransform().getOrigin()-p.m_normalWorldOnB*.5f;p.m_distance1=p.m_positionWorldOnA.y();p.m_positionWorldOnB=p.m_positionWorldOnA-p.m_normalWorldOnB*p.m_distance1;
    }
   }
  }
 }
 fclose(trace);
}
