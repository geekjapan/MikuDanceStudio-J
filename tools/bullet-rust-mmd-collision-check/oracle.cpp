#include "../../rust/crates/mds-bullet-sys/shim/mds_mmd.cpp"
#include "BulletCollision/BroadphaseCollision/btCollisionAlgorithm.h"
#include <cstring>
#include <cstdio>
#include <iostream>
#include <map>
#include <sstream>
#include <string>
#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif

static size_t row;
#include "allocator.hpp"
static unsigned next_algorithm, next_manifold;
struct Ledger {
    struct Entry { const void* pointer; unsigned generation; bool live; } entries[16384]{};
    unsigned count=0;
    unsigned at(const void* p) const { for(unsigned i=0;i<count;++i)if(entries[i].live && entries[i].pointer==p)return entries[i].generation;std::abort(); }
    void add(const void* p,unsigned generation) { if(count==16384)std::abort();for(unsigned i=0;i<count;++i)if(entries[i].live && entries[i].pointer==p)std::abort();entries[count++]={p,generation,true}; }
    void erase(const void* p) { for(unsigned i=0;i<count;++i)if(entries[i].live && entries[i].pointer==p){entries[i].live=false;return;}std::abort(); }
    bool empty() const {for(unsigned i=0;i<count;++i)if(entries[i].live)return false;return true;}
};
static Ledger algorithms, manifolds;
static int owner(const void* p) {return int(reinterpret_cast<intptr_t>(static_cast<const btCollisionObject*>(p)->getUserPointer()))-1;}
extern "C" void* dw_algorithm_alloc(void* p) {algorithms.add(p,++next_algorithm);std::cout<<"E "<<row<<" A+ "<<next_algorithm<<'\n';return p;}
extern "C" void dw_algorithm_free(void* p) {std::cout<<"E "<<row<<" A- "<<algorithms.at(p)<<'\n';algorithms.erase(p);}
extern "C" void dw_manifold_alloc(void* p,const void* a,const void* b) {manifolds.add(p,++next_manifold);std::cout<<"E "<<row<<" M+ "<<next_manifold<<' '<<owner(a)<<' '<<owner(b)<<'\n';}
extern "C" void dw_manifold_free(void* p) {std::cout<<"E "<<row<<" M- "<<manifolds.at(p)<<'\n';manifolds.erase(p);}
extern "C" void dw_unregister(const void* p) {std::cout<<"E "<<row<<" U "<<owner(p)<<'\n';}
extern "C" void dw_update(const void* p,int start) {std::cout<<"E "<<row<<(start?" U+ ":" U- ")<<owner(p)<<'\n';}
extern "C" void dw_physical(const char* kind,const void* p) {std::fprintf(stderr,"PHYSICAL %zu %s %llu\n",row,kind,static_cast<unsigned long long>(reinterpret_cast<uintptr_t>(p)));}
static unsigned bits(float f) {unsigned u;std::memcpy(&u,&f,4);return u;}
static void scalar(float f) {char text[10];std::snprintf(text,sizeof(text),"%08x",bits(f));std::cout<<' '<<text;}
static void vector(const btVector3& v) {for(int i=0;i<3;++i)scalar(v[i]);}
static void transform(const btTransform& t) {for(int i=0;i<3;++i)vector(t.getBasis()[i]);vector(t.getOrigin());}
static float number(std::istringstream& in) {std::string s;in>>s;unsigned u=std::stoul(s,nullptr,16);float f;std::memcpy(&f,&u,4);return f;}
static void pose(std::istringstream& in,float p[3],float q[4]) {for(int i=0;i<3;++i)p[i]=number(in);for(int i=0;i<4;++i)q[i]=number(in);}
static void matrix(const float p[3],const float q[4],float m[16]) {frame(p,q).getOpenGLMatrix(m);}
static void snapshot(mds_mmd_world* w,const std::string& op) {
    if(!w) {std::cout<<"O "<<row<<' '<<op<<" 0 0 0\n";return;}
    auto& pairs=w->bp.getOverlappingPairCache()->getOverlappingPairArray();
    std::cout<<"O "<<row<<' '<<op<<' '<<w->bodies.size()<<' '<<pairs.size()<<' '<<w->disp.getNumManifolds()<<'\n';
    for(size_t i=0;i<w->bodies.size();++i) {
        auto* b=w->bodies[i];auto* p=b->rb->getBroadphaseHandle();auto* h=w->bp.getHandle(p->m_uniqueId);
        std::cout<<"B "<<row<<' '<<i<<' '<<b->rb->getCollisionFlags()<<' '<<b->rb->getActivationState()<<' '<<p->m_uniqueId<<' '<<p->m_collisionFilterGroup<<' '<<p->m_collisionFilterMask<<' '<<owner(p->m_clientObject);
        transform(b->rb->getWorldTransform());transform(b->rb->getInterpolationWorldTransform());btTransform motion;b->ms->getWorldTransform(motion);transform(motion);
        scalar(b->rb->getInvMass());scalar(b->rb->getFriction());scalar(b->rb->getRestitution());
        vector(b->rb->getLinearVelocity());vector(b->rb->getAngularVelocity());vector(b->rb->getInterpolationLinearVelocity());vector(b->rb->getInterpolationAngularVelocity());
        for(int j=0;j<3;++j)std::cout<<' '<<h->m_minEdges[j];for(int j=0;j<3;++j)std::cout<<' '<<h->m_maxEdges[j];std::cout<<'\n';
    }
#ifdef DW_OBSERVED
    if(!w->bp.mdsAcceleratorEnabled())std::abort();
    for(int axis=0;axis<3;++axis) {
        unsigned count=w->bp.getHandle(0)->m_maxEdges[axis]+1;std::cout<<"S "<<row<<' '<<axis<<' '<<count;
        auto* edges=w->bp.mdsEdges(axis);for(unsigned i=0;i<count;++i)std::cout<<' '<<edges[i].m_pos<<' '<<edges[i].m_handle;std::cout<<'\n';
    }
#endif
    std::map<const void*,unsigned> manifold_owners;
    for(int i=0;i<pairs.size();++i) {
        auto& p=pairs[i];unsigned generation=0;
        if(p.m_algorithm) {
#ifdef DW_OBSERVED
            generation=algorithms.at(p.m_algorithm);
#else
            generation=1;
#endif
            btManifoldArray all;p.m_algorithm->getAllContactManifolds(all);for(int j=0;j<all.size();++j)manifold_owners[all[j]]=generation;
        }
        std::cout<<"P "<<row<<' '<<i<<' '<<p.m_pProxy0->m_uniqueId<<' '<<p.m_pProxy1->m_uniqueId<<' '<<owner(p.m_pProxy0->m_clientObject)<<' '<<owner(p.m_pProxy1->m_clientObject)<<' '<<generation<<'\n';
    }
    for(int i=0;i<w->disp.getNumManifolds();++i) {
        auto* m=w->disp.getManifoldByIndexInternal(i);unsigned generation=1;
#ifdef DW_OBSERVED
        generation=manifolds.at(m);
#endif
        std::cout<<"M "<<row<<' '<<i<<' '<<generation<<' '<<manifold_owners.at(m)<<' '<<owner(m->getBody0())<<' '<<owner(m->getBody1());scalar(m->getContactProcessingThreshold());scalar(m->getContactBreakingThreshold());std::cout<<' '<<m->getNumContacts()<<'\n';
        for(int j=0;j<m->getNumContacts();++j) {
            auto& p=m->getContactPoint(j);std::cout<<"Q "<<row<<' '<<i<<' '<<j;
            vector(p.m_localPointA);vector(p.m_localPointB);vector(p.m_positionWorldOnA);vector(p.m_positionWorldOnB);vector(p.m_normalWorldOnB);
            scalar(p.m_distance1);scalar(p.m_combinedFriction);scalar(p.m_combinedRestitution);scalar(p.m_appliedImpulse);scalar(p.m_appliedImpulseLateral1);scalar(p.m_appliedImpulseLateral2);
            std::cout<<' '<<p.m_lifeTime<<' '<<int(p.m_lateralFrictionInitialized);if(p.m_lateralFrictionInitialized){vector(p.m_lateralFrictionDir1);vector(p.m_lateralFrictionDir2);}std::cout<<'\n';
        }
    }
#ifdef DW_OBSERVED
    for(size_t i=0;i<w->joints.size();++i) {
        auto* j=w->joints[i];std::cout<<"J "<<row<<' '<<i<<' '<<j->getUid()<<" 1 0";
        for(int axis=0;axis<6;++axis){std::cout<<' '<<int(j->mdsEnabled(axis));scalar(j->mdsStiffness(axis));scalar(j->mdsEquilibrium(axis));}std::cout<<'\n';
    }
#endif
}
int main() {
#ifdef _WIN32
    _setmode(_fileno(stdout),_O_BINARY);
#endif
    mds_mmd_world* w=nullptr;std::string line;
    while(std::getline(std::cin,line)) {
        std::istringstream in(line);std::string op;in>>op;
        if(op=="H") {if(w)return 3;std::string name,scope;in>>name>>scope;w=mds_mmd_world_create();if(!w)return 3;w->bodies[0]->rb->setUserPointer(reinterpret_cast<void*>(intptr_t(1)));}
        else if(!w)return 3;
        else if(op=="C") {
            int kind,mode,group,mask;in>>kind;float mass=number(in);in>>mode>>group>>mask;float params[4],p[3],q[4];for(auto& f:params)f=number(in);pose(in,p,q);mds_mmd_body* b=nullptr;
            if(mds_mmd_body_create(w,kind,params[0],params[1],params[2],p,q,mode,mass,0,0,.25f,.5f,short(group),short(mask),&b))return 4;
            b->rb->setUserPointer(reinterpret_cast<void*>(intptr_t(w->bodies.size())));
        } else if(op=="D")w->w.performDiscreteCollisionDetection();
        else if(op=="U")w->w.updateAabbs();
        else if(op=="F") {int on;in>>on;if(mds_mmd_world_set_floor(w,on))return 4;}
        else if(op=="S") {size_t i;in>>i;w->w.updateSingleAabb(w->bodies.at(i)->rb);}
        else if(op=="A") {size_t i;int state;in>>i>>state;w->bodies.at(i)->rb->forceActivationState(state);}
        else if(op=="K") {size_t i;int on;in>>i>>on;if(mds_mmd_body_set_kinematic(w->bodies.at(i),on))return 4;}
        else if(op=="M" || op=="R") {size_t i;in>>i;float p[3],q[4],m[16];pose(in,p,q);matrix(p,q,m);int result=op=="M"?mds_mmd_body_set_motion_state(w->bodies.at(i),m):mds_mmd_body_reseat(w->bodies.at(i),m);if(result)return 4;}
        else if(op=="O") {size_t i;in>>i;float p[3];for(auto& f:p)f=number(in);if(mds_mmd_body_stop_at(w->bodies.at(i),p))return 4;}
        else if(op=="V") {size_t i;in>>i;float a[3],b[3];for(auto& f:a)f=number(in);for(auto& f:b)f=number(in);w->bodies.at(i)->rb->setInterpolationLinearVelocity(vec3(a));w->bodies.at(i)->rb->setInterpolationAngularVelocity(vec3(b));}
        else if(op=="W") {
            for(int i=0;i<w->disp.getNumManifolds();++i) {auto* m=w->disp.getManifoldByIndexInternal(i);for(int j=0;j<m->getNumContacts();++j) {auto& p=m->getContactPoint(j);p.m_appliedImpulse=1.25f;p.m_appliedImpulseLateral1=.5f;p.m_appliedImpulseLateral2=-.25f;p.m_lateralFrictionInitialized=true;p.m_lateralFrictionDir1=btVector3(1,0,0);p.m_lateralFrictionDir2=btVector3(0,0,1);}}
        } else if(op=="J") {size_t a,b;int uid,spring;in>>a>>b>>uid>>spring;float zero[3]={},q[4]={0,0,0,1},springs[6];for(auto& f:springs)f=spring?2.0f:0.0f;if(mds_mmd_joint_create(w,w->bodies.at(a),w->bodies.at(b),zero,q,zero,q,zero,zero,zero,zero,springs,uid))return 4;}
        else if(op=="X") {mds_mmd_world_destroy(w);w=nullptr;
#ifdef DW_OBSERVED
            if(!algorithms.empty() || !manifolds.empty())return 5;
#endif
        } else return 2;
        if(!in || (in>>std::ws,!in.eof()))return 2;snapshot(w,op);++row;
    }
    if(w)return 3;std::cout<<"Z "<<row<<'\n';
}
