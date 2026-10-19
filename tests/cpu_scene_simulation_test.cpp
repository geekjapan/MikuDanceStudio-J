#include "mikudancestudio/cpu_scene_simulation.hpp"
#include "btBulletDynamicsCommon.h"
#include "cpu_simulation_reference.hpp"
#include <cmath>
#include <cstdio>
#include <cstring>

using namespace mikudancestudio;
#define CHECK(x) do { if(!(x)) { std::fprintf(stderr,"line %d: %s\n",__LINE__,#x);return 1; } } while(0)
namespace {
struct World {
    btDefaultCollisionConfiguration config;
    btCollisionDispatcher dispatcher{&config};
    btDbvtBroadphase broadphase;
    btSequentialImpulseConstraintSolver solver;
    btDiscreteDynamicsWorld world{&dispatcher,&broadphase,&solver,&config};
    btSphereShape shape{0.25f};
    btDefaultMotionState motion;
    btRigidBody body{{1,&motion,&shape,btVector3(0.025f,0.025f,0.025f)}};
    World() {
        btTransform initial=btTransform::getIdentity();initial.setOrigin(btVector3(1,8,2));
        body.setWorldTransform(initial);body.setLinearVelocity(btVector3(.3f,-.7f,.2f));
        body.setAngularVelocity(btVector3(.1f,.2f,.4f));world.addRigidBody(&body);
        world.getSolverInfo().m_solverMode&=~1;
    }
    ~World() { world.removeRigidBody(&body); }
};
void Normalize(float out[3],const float in[3]) {
    const float length=std::sqrt(in[0]*in[0]+in[1]*in[1]+in[2]*in[2]);
    for(int n=0;n<3;++n) out[n]=in[n]/length;
}
void Pose(CpuModelSlots,CpuPosePhase,int,int) {}
void Physics(CpuModelSlots,CpuPhysicsModelPhase,CpuSlotOrder,int) {}
int calls=0;
int Random() { ++calls;return 16384; }
CpuSimulationContext Context(World& w) { return {{nullptr,0},&w.world,{Pose,Physics,Normalize,Random}}; }
struct Trace {
    std::vector<float> cursors,dts;
    std::vector<bool> substeps;
    int reseats=0,reads=0,before=0,after=0;
    static void Advance(void* p,CpuSimulationState& s,bool sub) {
        auto& t=*static_cast<Trace*>(p);t.cursors.push_back(s.cursorSeconds);t.substeps.push_back(sub);
    }
    static void Observe(void* p,const CpuSimulationState&,CpuSimulationEvent e,int,float dt) {
        auto& t=*static_cast<Trace*>(p);
        if(e==CpuSimulationEvent::MainStep || e==CpuSimulationEvent::ExtraStep || e==CpuSimulationEvent::SettleStep || e==CpuSimulationEvent::CatchupBeforeStep) t.dts.push_back(dt);
        if(e==CpuSimulationEvent::SettleReseat) ++t.reseats;
        if(e==CpuSimulationEvent::Readback) ++t.reads;
        if(e==CpuSimulationEvent::BeforePose) ++t.before;
        if(e==CpuSimulationEvent::AfterPose) ++t.after;
    }
    CpuSimulationHooks Hooks() { return {this,Advance,Observe}; }
};
bool Bits(float a,float b) { return std::memcmp(&a,&b,sizeof(float))==0; }
bool Same(const World& a,const World& b) {
    const auto x=cpu_reference::BodyState(a.body),y=cpu_reference::BodyState(b.body);
    return x.size()==y.size() && std::memcmp(x.data(),y.data(),x.size()*sizeof(float))==0;
}
}
int main() {
    // Real Bullet transforms AND linear/angular/interpolation velocities must
    // remain bit identical to the frozen legacy reference.
    unsigned checked=0;
    for(int mode=0;mode<=3;++mode) for(unsigned flags=0;flags<128;++flags) {
        World native,reference;CpuSimulationState s,r;s.physicsMode=mode;
        s.remainingSeconds=flags&1 ? -.003f : .041f;
        s.resetPending=(flags>>1)&1;s.bodiesMoved=(flags>>2)&1;
        CpuSimulationFrame f;f.selectionActive=flags&8;f.selectionWasActive=flags&16;
        f.accessoryEditing=flags&32;f.frameCopyPending=flags&64;r=s;
        Trace trace;CHECK(RunCpuSimulationFrame(s,Context(native),f,trace.Hooks()));
        cpu_reference::Frame(r,Context(reference),f);
        CHECK(Same(native,reference));CHECK(s.resetPending==r.resetPending && s.bodiesMoved==r.bodiesMoved);
        CHECK(s.gravityDirection==r.gravityDirection);
        CHECK(f.accessoryEditing ? trace.before==0 && trace.after==0 : trace.before==1 && trace.after==1);
        ++checked;
    }
    for(int mode=0;mode<=3;++mode) {
        World native,reference;CpuSimulationState s,r;s.physicsMode=r.physicsMode=mode;
        for(float target:{0.0f,.011f,.033333335f,.117f,.117f,.02f,.09f}) {
            s.remainingSeconds=r.remainingSeconds=.041f;
            Trace trace;CHECK(RunCpuSimulationCatchup(s,Context(native),target,-1,trace.Hooks()));
            cpu_reference::Catchup(r,Context(reference),target,-1,{});
            CHECK(Bits(s.cursorSeconds,r.cursorSeconds) && Bits(s.remainingSeconds,r.remainingSeconds));
            CHECK(Same(native,reference));CHECK(!trace.substeps.empty() && !trace.substeps.back());
            CHECK(trace.cursors.back()==target);
            CpuSimulationFrame f;f.playbackActive=true;
            CHECK(RunCpuSimulationFrame(s,Context(native),f));cpu_reference::Frame(r,Context(reference),f);
            CHECK(Same(native,reference));
        }
    }
    World w;auto c=Context(w);CpuSimulationState s;s.physicsMode=3;s.resetPending=s.bodiesMoved=1;s.remainingSeconds=.2f;
    Trace t;CHECK(RunCpuSimulationFrame(s,c,{},t.Hooks()));
    CHECK(t.dts==std::vector<float>(5,1.0f/60.0f) && t.reseats==3 && t.reads==1);
    CHECK(!s.resetPending && !s.bodiesMoved);
    t={};CHECK(RunCpuSimulationFrame(s,c,{},t.Hooks()));CHECK(t.dts.empty() && t.before==1 && t.after==1);
    for(unsigned gate=0;gate<3;++gate) {
        s.resetPending=0;CpuSimulationFrame f;f.selectionActive=true;
        f.modelMode=gate==0;f.frameStep=gate==1;f.selectionWasActive=gate==2;
        t={};CHECK(RunCpuSimulationFrame(s,c,f,t.Hooks()));CHECK(t.dts.empty() && !s.resetPending);
    }
    CpuSimulationFrame blocked;blocked.selectionActive=true;blocked.frameCopyPending=true;
    CHECK(RunCpuSimulationFrame(s,c,blocked));CHECK(s.resetPending);
    blocked={};blocked.enabled=false;const auto before=cpu_reference::BodyState(w.body);
    CHECK(RunCpuSimulationFrame(s,c,blocked));CHECK(before==cpu_reference::BodyState(w.body) && s.resetPending);
    // Gravity precedes the accessory gate; correction writes back to state.
    s.physicsMode=2;s.gravityDirection={0,0,0};blocked={};blocked.accessoryEditing=true;
    CHECK(RunCpuSimulationFrame(s,c,blocked));CHECK(s.gravityDirection[1]==.1f && w.world.getGravity().y()>0);
    s.gravityNoiseEnabled=true;s.gravityNoiseTimer=.25f;blocked.deltaSeconds=.25f;calls=0;
    const auto gravity=w.world.getGravity();CHECK(RunCpuSimulationFrame(s,c,blocked));
    CHECK(s.gravityNoiseTimer==.5f && calls==0 && w.world.getGravity()==gravity);
    blocked.deltaSeconds=.001f;CHECK(RunCpuSimulationFrame(s,c,blocked));
    CHECK(calls==4 && s.gravityNoiseTimer==0 && w.world.getGravity()!=gravity);
    s.physicsMode=0;const float timer=s.gravityNoiseTimer;const auto last=w.world.getGravity();
    CHECK(RunCpuSimulationFrame(s,c,blocked));CHECK(calls==4 && s.gravityNoiseTimer==timer && w.world.getGravity()==last);
    // Per-scene clocks cannot consume another host's budget.
    CpuSimulationState other;other.cursorSeconds=8;other.remainingSeconds=.8f;
    s.physicsMode=2;s.cursorSeconds=0;s.remainingSeconds=.05f;
    CHECK(RunCpuSimulationCatchup(s,c,.05f));CHECK(other.cursorSeconds==8 && other.remainingSeconds==.8f);
    auto invalid=c;invalid.world=nullptr;const float cursor=s.cursorSeconds,budget=s.remainingSeconds;
    CHECK(!RunCpuSimulationCatchup(s,invalid,1));CHECK(s.cursorSeconds==cursor && s.remainingSeconds==budget);
    CHECK(!RunCpuSimulationFrame(s,invalid,{}));
    std::printf("PASS portable CPU simulation: %u gate cases, frozen Bullet state, catch-up budget, seek/resume, settle, gravity/noise and per-scene isolation\n",checked);
}
