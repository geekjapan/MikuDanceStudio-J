#pragma once
#include "mikudancestudio/cpu_scene_simulation.hpp"
#include "btBulletDynamicsCommon.h"
#include <vector>

// Frozen pre-extraction playback_catchup.cpp / physics_frame.cpp control flow.
// Does not call the new scheduler. Noise has separate measured tests; this
// reference covers the deterministic, normal-gravity path.
namespace cpu_reference {
using namespace mikudancestudio;
inline void Catchup(CpuSimulationState& s,const CpuSimulationContext& c,float target,
                    int skip,CpuSimulationHooks h) {
    const int count=s.physicsMode;
    if(count>=1) {
        s.cursorSeconds+=1.0f/60.0f;
        if(target>s.cursorSeconds) do {
            if(h.advance) h.advance(h.user,s,true);
            c.ops.pose(c.models,CpuPosePhase::BeforePhysics,count,skip);
            c.ops.physics(c.models,CpuPhysicsModelPhase::KinematicSync,CpuSlotOrder::Forward,skip);
            c.world->stepSimulation(1.0f/60.0f,10,1.0f/60.0f);
            s.remainingSeconds-=1.0f/60.0f;
            s.cursorSeconds+=1.0f/60.0f;
        } while(s.cursorSeconds<target);
    }
    s.cursorSeconds=target;
    if(h.advance) h.advance(h.user,s,false);
}
inline void Frame(CpuSimulationState& s,const CpuSimulationContext& c,const CpuSimulationFrame& f) {
    if(!f.enabled) return;
    const int count=s.physicsMode;
    if(count>0) {
        float dir[3]={s.gravityDirection[0],s.gravityDirection[1],s.gravityDirection[2]};
        if(dir[0]==0 && dir[1]==0 && dir[2]==0) s.gravityDirection[1]=dir[1]=0.1f;
        c.ops.normalize(dir,dir);
        c.world->setGravity(btVector3((dir[0]*s.gravityMagnitude)*10.0f,
                                     (dir[1]*s.gravityMagnitude)*10.0f,
                                     (dir[2]*s.gravityMagnitude)*10.0f));
    }
    if(f.selectionActive && !f.modelMode && !f.frameStep && !f.selectionWasActive) s.resetPending=1;
    if(f.accessoryEditing) return;
    c.ops.pose(c.models,CpuPosePhase::BeforePhysics,s.resetPending ? 0 : count,-1);
    const bool moved=s.bodiesMoved!=0,settle=s.resetPending!=0,frameAdv=f.playbackActive;
    const bool runWorldPass=count==1 || count==2 || (count==3 && (moved || settle || frameAdv));
    const bool idleNoStep=f.skipIdleWorld && !(moved || settle || frameAdv);
    if(runWorldPass && !idleNoStep && !f.frameCopyPending) {
        c.ops.physics(c.models,CpuPhysicsModelPhase::KinematicSync,CpuSlotOrder::Forward,-1);
        const float mainTimeStep=f.overrideMainTimeStep ? f.mainTimeStep : s.remainingSeconds;
        const float mainDt=moved && count==3 ? 1.0f/60.0f : mainTimeStep;
        c.world->stepSimulation(mainDt,10,1.0f/60.0f);
        if(moved && count==3) c.world->stepSimulation(1.0f/60.0f,10,1.0f/60.0f);
        if(settle) {
            for(int iter=3;iter>=1;--iter) {
                c.ops.physics(c.models,CpuPhysicsModelPhase::DynamicReseat,CpuSlotOrder::Forward,-1);
                c.world->stepSimulation(1.0f/60.0f,10,1.0f/60.0f);
            }
            s.resetPending=0;
        }
        c.ops.physics(c.models,CpuPhysicsModelPhase::Readback,CpuSlotOrder::Forward,-1);
        s.bodiesMoved=0;
    }
    c.ops.pose(c.models,CpuPosePhase::AfterPhysics,count,-1);
}
inline std::vector<float> BodyState(const btRigidBody& body) {
    std::vector<float> out;
    for(const auto& transform:{body.getWorldTransform(),body.getInterpolationWorldTransform()}) {
        for(int row=0;row<3;++row) for(int col=0;col<3;++col) out.push_back(transform.getBasis()[row][col]);
        for(int n=0;n<3;++n) out.push_back(transform.getOrigin()[n]);
    }
    for(const auto& vector:{body.getLinearVelocity(),body.getAngularVelocity(),
                           body.getInterpolationLinearVelocity(),body.getInterpolationAngularVelocity()})
        for(int n=0;n<3;++n) out.push_back(vector[n]);
    out.push_back(float(body.getActivationState()));
    return out;
}
}
