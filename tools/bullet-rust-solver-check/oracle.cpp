// Test adapter: all solver arithmetic executes in vendored Bullet 2.75.
#include "BulletDynamics/ConstraintSolver/btGeneric6DofSpringConstraint.h"
#include "BulletDynamics/ConstraintSolver/btSequentialImpulseConstraintSolver.h"
#include "BulletDynamics/ConstraintSolver/btContactSolverInfo.h"
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <memory>
#include <vector>
static void word(unsigned x) { std::printf("\t%08x", x); }
static void scalar(float f) { unsigned x; std::memcpy(&x,&f,4); word(x); }
static void vector(const btVector3& v) { for(int i=0;i<3;i++)scalar(v[i]); }
static void transform(const btTransform& t) { for(int i=0;i<3;i++)vector(t.getBasis()[i]); vector(t.getOrigin()); }
static void motor(const btTranslationalLimitMotor& m,int i) {
    scalar(m.m_lowerLimit[i]);scalar(m.m_upperLimit[i]);word(m.m_enableMotor[i]);
    scalar(m.m_targetVelocity[i]);scalar(m.m_maxMotorForce[i]);scalar(m.m_currentLinearDiff[i]);
    word(m.m_currentLimit[i]);scalar(m.m_currentLimitError[i]);
}
struct SpringJoint:btGeneric6DofSpringConstraint {
    using btGeneric6DofSpringConstraint::btGeneric6DofSpringConstraint;
    bool enabled(int i)const{return m_springEnabled[i];}
    float equilibrium(int i)const{return m_equilibriumPoint[i];}
    float stiffness(int i)const{return m_springStiffness[i];}
    float damping(int i)const{return m_springDamping[i];}
};
static void state(SpringJoint& j) {
    auto& l=*j.getTranslationalLimitMotor();
    for(int i=0;i<3;i++)motor(l,i);
    for(int i=0;i<3;i++) { auto& m=*j.getRotationalLimitMotor(i);
        scalar(m.m_loLimit);scalar(m.m_hiLimit);word(m.m_enableMotor);scalar(m.m_targetVelocity);
        scalar(m.m_maxMotorForce);scalar(m.m_currentPosition);word(m.m_currentLimit);scalar(m.m_currentLimitError);
        scalar(m.m_ERP);scalar(m.m_bounce);
    }
    scalar(0.5f);
    for(int i=0;i<6;i++){word(j.enabled(i));scalar(j.equilibrium(i));scalar(j.stiffness(i));scalar(j.damping(i));}
}
struct Observer:btSequentialImpulseConstraintSolver {
    void output() {
        word(m_tmpSolverNonContactConstraintPool.size());
        for(int i=0;i<m_tmpSolverNonContactConstraintPool.size();i++) {
            const auto& r=m_tmpSolverNonContactConstraintPool[i];
            word(r.m_solverBodyIdA);word(r.m_solverBodyIdB);
            vector(r.m_contactNormal);vector(r.m_relpos1CrossNormal);vector(r.m_relpos2CrossNormal);
            vector(r.m_angularComponentA);vector(r.m_angularComponentB);
            scalar(r.m_jacDiagABInv);scalar(r.m_rhs);scalar(r.m_cfm);scalar(r.m_lowerLimit);scalar(r.m_upperLimit);scalar(r.m_appliedImpulse);
        }
    }
    void impulses() {
        for(int i=0;i<m_tmpSolverNonContactConstraintPool.size();i++)scalar(m_tmpSolverNonContactConstraintPool[i].m_appliedImpulse);
    }
    void writeback() { for(int i=0;i<m_tmpSolverBodyPool.size();i++)m_tmpSolverBodyPool[i].writebackVelocity(); }
};
static uint32_t seed=0x48152713;
static float sample() {seed^=seed<<13;seed^=seed>>17;seed^=seed<<5;return (int32_t(seed>>8)-8388608)*(1.0f/8388608.0f);}
static void factor_snapshot(btRigidBody& b) {
    vector(b.getLinearFactor());vector(b.getAngularFactor());
    vector(b.getTotalForce());vector(b.getTotalTorque());vector(b.getGravity());
    // getGravity returns acceleration; native force is mass times acceleration.
    vector(b.getLinearVelocity());vector(b.getAngularVelocity());
    for(int i=0;i<3;i++)vector(b.getInvInertiaTensorWorld()[i]);scalar(b.getInvMass());
}
static int factors() {
    for(int id=0;id<64;id++) {
        float mass=id%4==0?0.0f:float(id%3+1);
        btVector3 inertia(1,2,3);btTransform world;world.setIdentity();
        world.setRotation(btQuaternion(btVector3(1,2,3),sample()));
        btVector3 lf(id%2?0.5f:-0.0f,1.25f,-0.75f),af(1.5f,0.25f,id%2?-0.0f:0.5f);
        btVector3 force(sample(),sample(),sample()),torque(sample(),sample(),sample()),gravity(sample(),sample(),sample());
        const float dt=1.0f/60.0f;
        btRigidBody b(mass,nullptr,nullptr,inertia);b.setCenterOfMassTransform(world);
        bool kin=id%4==1;if(kin)b.setCollisionFlags(b.getCollisionFlags()|btCollisionObject::CF_KINEMATIC_OBJECT);
        std::printf("%d",id);scalar(mass);vector(inertia);transform(world);vector(lf);vector(af);vector(force);vector(torque);vector(gravity);scalar(dt);word(kin);
        b.setLinearFactor(lf);b.setAngularFactor(af);b.setGravity(gravity);factor_snapshot(b);
        b.applyCentralForce(force);b.applyTorque(torque);factor_snapshot(b);
        b.applyGravity();factor_snapshot(b);
        b.integrateVelocities(dt);factor_snapshot(b);
        b.clearForces();factor_snapshot(b);
        // Setters leave accumulated state alone; only subsequent forces use them.
        b.setLinearFactor(af);b.setAngularFactor(lf);b.applyCentralForce(force);b.applyTorque(torque);factor_snapshot(b);
        std::printf("\n");
    }
    return 0;
}
int main(int argc,char**) {
 if(argc>1)return factors();
 for(int variant=0;variant<2;variant++) for(int id=0;id<128;id++) {
    btTransform worlds[3];btVector3 inertias[3];float masses[3];
    std::vector<std::unique_ptr<btRigidBody>> bodies;
    for(int i=0;i<3;i++) {
        worlds[i].setIdentity();
        if(id>=32)worlds[i].setRotation(btQuaternion(btVector3(1,2,3),sample()*0.7f));
        worlds[i].setOrigin(btVector3(sample(),sample(),sample()));
        if(id<32) {
            const float boundary[]={-0.25f,0.25f,0.0f,-0.25000003f,0.25000003f};
            const float x=boundary[id%5];
            worlds[i].setOrigin(i==0?btVector3(0,0,0):btVector3(x,-x,0.125f*i));
        }
        masses[i]=(i==1 && id%4<2)?0.0f:float(i+1);
        inertias[i]=btVector3(i+1,i+2,i+3);
        bodies.emplace_back(new btRigidBody(masses[i],nullptr,nullptr,inertias[i]));
        auto& b=*bodies.back();b.setCenterOfMassTransform(worlds[i]);b.setCompanionId(-1);b.m_debugBodyId=i;
        if(i==1 && id%4==1)b.setCollisionFlags(b.getCollisionFlags()|btCollisionObject::CF_KINEMATIC_OBJECT);
        if(i==1 && id%4==2)b.setCollisionFlags(b.getCollisionFlags()|btCollisionObject::CF_KINEMATIC_OBJECT);
        b.setLinearVelocity(btVector3(sample(),sample(),id%8==0?-0.0f:sample()));
        b.setAngularVelocity(btVector3(sample(),sample(),sample()));
        if(id%3==0){b.setLinearFactor(btVector3(0.5f,1.25f,0.0f));b.setAngularFactor(btVector3(1.5f,0.25f,0.0f));}
    }
    btTransform frames[4];for(auto& f:frames)f.setIdentity();
    if(id%2)for(auto& f:frames)f.setOrigin(btVector3(sample()*0.2f,sample()*0.2f,sample()*0.2f));
    SpringJoint j0(*bodies[0],*bodies[1],frames[0],frames[1],true);
    SpringJoint j1(*bodies[1],*bodies[2],frames[2],frames[3],true);
    btTypedConstraint* joints[]={&j0,&j1};
    for(auto* jp:joints){auto& j=*static_cast<SpringJoint*>(jp);
        for(int i=0;i<3;i++) {
            j.getRotationalLimitMotor(i)->m_currentPosition=0;
            auto* l=j.getTranslationalLimitMotor();
            l->m_currentLinearDiff[i]=0;l->m_currentLimit[i]=0;l->m_currentLimitError[i]=0;
        }
        for(int axis=0;axis<6;axis++) {
            const int type=(id+axis)%7;
            const float lower=type==0?1.0f:(type==1?0.0f:-0.25f);
            const float upper=type==0?-1.0f:(type==1?0.0f:0.25f);
            j.setLimit(axis,lower,upper);
            if(type>=4 && id>=2){j.enableSpring(axis,true);j.setStiffness(axis,2.0f+axis);j.setDamping(axis,0.5f);}
            if(id<2)j.setLimit(axis,1,-1);
        }
    }
    if(id%8==4) {
        // MMD uses this no-argument setter. Move a body afterwards to exercise
        // restoring forces around the captured nonzero equilibrium.
        j0.setEquilibriumPoint();j1.setEquilibriumPoint();
        auto moved=bodies[1]->getCenterOfMassTransform();
        moved.getOrigin()+=btVector3(0.0625f,-0.125f,0.25f);
        bodies[1]->setCenterOfMassTransform(moved);
    }
    if(id%16==3) {
        for(auto* jp:joints) {
            auto& j=*static_cast<SpringJoint*>(jp);btTypedConstraint::btConstraintInfo1 info1;j.getInfo1(&info1);
            const float angle=j.getAngle(0);j.setLimit(3,angle,angle);
        }
    }
    const float dt=1.0f/60.0f;
    for(int repeat=0;repeat<2;repeat++) {
        std::printf("%d",variant*256+id*2+repeat);scalar(dt);word(variant?4:260);word(3);word(2);
        for(int i=0;i<3;i++) {auto& b=*bodies[i];b.setCompanionId(-1);
            scalar(masses[i]);vector(inertias[i]);transform(b.getCenterOfMassTransform());
            vector(b.getLinearVelocity());vector(b.getAngularVelocity());vector(b.getLinearFactor());vector(b.getAngularFactor());
            word(b.isKinematicObject());
        }
        for(int k=0;k<2;k++){word(k);word(k+1);transform(frames[k*2]);transform(frames[k*2+1]);state(*static_cast<SpringJoint*>(joints[k]));}
        btContactSolverInfo info;info.m_timeStep=dt;info.m_numIterations=10;info.m_solverMode=variant?4:260;
        Observer solver;solver.solveGroupCacheFriendlySetup(nullptr,0,nullptr,0,joints,2,info,nullptr,nullptr);
        solver.output();
        solver.solveGroupCacheFriendlyIterations(nullptr,0,nullptr,0,joints,2,info,nullptr,nullptr);
        solver.writeback();
        for(auto& b:bodies){vector(b->getLinearVelocity());vector(b->getAngularVelocity());}
        solver.impulses();
        std::printf("\n");
    }
 }
}
