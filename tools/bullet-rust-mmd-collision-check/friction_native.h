// Diagnostic generated-copy hooks. No fields are added to Bullet objects.
#ifndef MDS_FRICTION_NATIVE_DECLARATIONS
#define MDS_FRICTION_NATIVE_DECLARATIONS
class btManifoldPoint;
class btPersistentManifold;
extern "C" {
void fn_guard(const char*, const btManifoldPoint* = nullptr);
void fn_ctor(const btManifoldPoint*, bool);
void fn_incoming(const btManifoldPoint*);
void fn_allocate(btPersistentManifold*, const void*, const void*);
void fn_release(btPersistentManifold*);
void fn_insert(btPersistentManifold*, int, const btManifoldPoint*, bool);
void fn_remove(btPersistentManifold*, int);
void fn_clear_begin(btPersistentManifold*);
void fn_clear_point(btPersistentManifold*, int);
void fn_clear_end(btPersistentManifold*);
void fn_added(btPersistentManifold*, int);
void fn_solver_begin(btManifoldPoint*, int);
void fn_choice(btManifoldPoint*, bool, bool, bool);
void fn_write(btManifoldPoint*, const char*, unsigned);
void fn_solver_end(btManifoldPoint*);
void fn_no_anisotropy(bool);
void fn_refresh_begin(btPersistentManifold*);
void fn_refresh_point(btPersistentManifold*, int, bool, bool);
void fn_refresh_end(btPersistentManifold*);
}
#endif

// Included a second time by the consumer, after Bullet and standard headers.
#if defined(MDS_FRICTION_NATIVE_IMPLEMENTATION) && !defined(MDS_FRICTION_NATIVE_IMPLEMENTED)
#define MDS_FRICTION_NATIVE_IMPLEMENTED
#include <cstdarg>
#include <cstdlib>
#include <streambuf>
#include "BulletCollision/NarrowPhaseCollision/btPersistentManifold.h"
#include "BulletCollision/CollisionDispatch/btManifoldResult.h"
extern ContactProcessedCallback gContactProcessedCallback;
namespace friction_native {
constexpr unsigned limit = 2147483647;
static bool observed, running;
static unsigned checkpoint, sequence, commands, next_mid, next_gid, next_tx, closed;
static unsigned pending_mid, pending_slot, pending_gid, pending_stage;
static const char* scopes[256];
static unsigned depth;
static std::streambuf* original_output;
static unsigned result_counter, active_result, pending_result;
static unsigned backing_ctors;
static bool allocating, allocated, fixture_active;
static const btManifoldPoint* constructed_incoming;
static_assert(MANIFOLD_CACHE_SIZE == 4, "reviewed four backing constructors");
struct Point {
    unsigned gid=0, mask=0, tx=0, branch=0, writes=0;
    bool recompute=false, velocity=false, two=false, chosen=false;
};
struct Manifold {
    btPersistentManifold* pointer=nullptr;
    unsigned mid=0, a=0, b=0, count=0;
    Point points[4];
};
struct Temporary { const btManifoldPoint* pointer=nullptr; unsigned gid=0; };
static Manifold manifold_slots[4096];
static Temporary temporary[256];
struct Refresh {
    btPersistentManifold* pointer=nullptr;
    int cursor=-1;
    unsigned visited[4]{}, count=0, pending=0, slot=0, gid=0;
};
static Refresh refresh;
static void need(bool ok) { if(!ok) {std::fputs("FRICTION_DIAGNOSTIC_REJECT\n",stderr);std::abort();} }
static unsigned fresh(unsigned& n) {need(n<limit);return ++n;}
static const char* boolean(bool b) {return b?"true":"false";}
class BoundedOutput final : public std::streambuf {
    std::streambuf* destination;
    unsigned bytes=0;
public:
    explicit BoundedOutput(std::streambuf* p):destination(p) {}
    int_type overflow(int_type c) override {
        if(traits_type::eq_int_type(c,traits_type::eof()))return traits_type::not_eof(c);
        need(bytes<64u*1024u*1024u);++bytes;
        need(!traits_type::eq_int_type(destination->sputc(traits_type::to_char_type(c)),traits_type::eof()));
        return c;
    }
    std::streamsize xsputn(const char* p,std::streamsize n) override {
        need(n>=0 && static_cast<unsigned long long>(n)<=64u*1024u*1024u-bytes);
        bytes+=static_cast<unsigned>(n);need(destination->sputn(p,n)==n);return n;
    }
    int sync() override {return destination->pubsync();}
};
static void raw(const char* format,...) {
    char line[512];va_list ap;va_start(ap,format);int n=std::vsnprintf(line,sizeof(line),format,ap);va_end(ap);
    need(n>0 && n<512 && line[n-1]=='\n');std::cout.write(line,n);need(bool(std::cout));
}
static unsigned seq() {need(sequence<1000000 && pending_stage==0);return ++sequence;}
static unsigned guard_seq() {need(sequence<1000000);return ++sequence;}
static Manifold& manifold(const btPersistentManifold* p) {
    for(auto& m:manifold_slots)if(m.pointer==p)return m;need(false);return manifold_slots[0];
}
static Point& binding(const btManifoldPoint* p,Manifold*& found,unsigned& slot) {
    for(auto& m:manifold_slots)if(m.pointer)for(unsigned j=0;j<m.count;++j)
        if(&m.pointer->getContactPoint(j)==p){found=&m;slot=j;need(m.points[j].gid!=0);return m.points[j];}
    need(false);found=nullptr;slot=0;return manifold_slots[0].points[0];
}
static void caches(const btManifoldPoint* p) {
    need(!gContactAddedCallback && !gContactProcessedCallback && !gContactDestroyedCallback);
    if(p)need(p->m_userPersistentData==nullptr);
    for(auto& m:manifold_slots)if(m.pointer)for(int j=0;j<m.pointer->getNumContacts();++j)
        need(m.pointer->getContactPoint(j).m_userPersistentData==nullptr);
    for(auto& t:temporary)if(t.pointer)need(t.pointer->m_userPersistentData==nullptr);
}
static void scope(const char* site) {
    const size_t n=std::strlen(site);
    const bool enter=(n>=6 && std::strcmp(site+n-6,"_ENTER")==0)||std::strcmp(site,"SOLVER_BEGIN")==0||std::strcmp(site,"FIXTURE_BEGIN")==0;
    const bool exit=(n>=5 && std::strcmp(site+n-5,"_EXIT")==0 && std::strcmp(site,"CTOR_EXIT")!=0)||std::strcmp(site,"SOLVER_END")==0||std::strcmp(site,"FIXTURE_END")==0;
    if(enter){need(depth<256);scopes[depth++]=site;}
    if(exit){need(depth>0);const char* a=scopes[depth-1];const char* u=std::strrchr(a,'_');const char* v=std::strrchr(site,'_');need(u && v && u-a==v-site && std::strncmp(a,site,u-a)==0);--depth;}
}
static void start(bool obs,const char* role,const char* sha,unsigned count) {
    need(!running && count && count<=limit && std::strlen(sha)==64);
    need(std::strcmp(role,"ordinary")==0||std::strcmp(role,"ascending")==0||std::strcmp(role,"descending")==0||std::strcmp(role,"alternating")==0);
    for(unsigned i=0;i<64;++i)need((sha[i]>='0'&&sha[i]<='9')||(sha[i]>='a'&&sha[i]<='f'));
    observed=obs;commands=count;running=true;
    original_output=std::cout.rdbuf();static BoundedOutput output(original_output);std::cout.rdbuf(&output);
    raw("FH 3 native-%s %s %s %u\n",observed?"observed":"original",role,sha,count);
    fn_guard("STARTUP");
}
static void command_begin(unsigned cp) {need(running && cp<commands && !depth && !pending_stage);checkpoint=cp;fn_guard("COMMAND_BEGIN");}
static void command_end() {fn_guard("COMMAND_END");need(!depth && !pending_stage);}
static void fixture(const char* site) {
    need(observed && depth && std::strcmp(scopes[depth-1],"FIXTURE_BEGIN")==0);
    const bool begin=std::strcmp(site,"FIXTURE_BEGIN")==0;
    need(begin?!fixture_active:fixture_active);fixture_active=begin;
    raw("FF %u %u %s\n",checkpoint,seq(),site);
}
static void finish(unsigned actual) {
    need(actual==commands && !depth && !pending_stage);
    for(auto& m:manifold_slots)need(!m.pointer);for(auto& t:temporary)need(!t.pointer);
    need(!refresh.pointer && !active_result && !allocating && !constructed_incoming && !fixture_active);
    raw("FZ %u %u %u\n",sequence,commands,closed);std::cout.flush();need(bool(std::cout));std::cout.rdbuf(original_output);running=false;
}
static void snapshot_manifold(btPersistentManifold* p,unsigned mi) {
    caches(nullptr);if(!observed)return;auto& m=manifold(p);need(m.count==unsigned(p->getNumContacts()));
    raw("FS %u %u SNAPSHOT %u %u %u\n",checkpoint,seq(),mi,m.mid,m.count);
}
static void snapshot_point(btPersistentManifold* m,unsigned mi,unsigned slot) {
    caches(&m->getContactPoint(slot));if(!observed)return;auto& x=manifold(m);need(slot<x.count);
    raw("FL %u %u SNAPSHOT %u %u %u %u %u %s\n",checkpoint,seq(),mi,slot,x.mid,x.points[slot].gid,x.points[slot].mask,boolean(m->getContactPoint(slot).m_lateralFrictionInitialized));
}
static void directions(btPersistentManifold* m,unsigned mi,unsigned slot,bool immediate_w) {
    const auto& p=m->getContactPoint(slot);caches(&p);
    const unsigned mask=observed?manifold(m).points[slot].mask:(immediate_w?3u:(p.m_lateralFrictionInitialized?1u:0u));
    for(unsigned d=1;d<=2;++d) {
        const bool defined=(mask&d)!=0;
        if(!defined)raw("FD %u %u SNAPSHOT %u %u %u %s 0\n",checkpoint,seq(),mi,slot,d,observed?"U":"O");
        else {
            // Permission precedes even evaluating a direction getter or scalar argument.
            const btVector3& v=d==1?p.m_lateralFrictionDir1:p.m_lateralFrictionDir2;
            unsigned words[3];for(int k=0;k<3;++k){float f=v[k];std::memcpy(&words[k],&f,4);}
            raw("FD %u %u SNAPSHOT %u %u %u D 3 %08x %08x %08x\n",checkpoint,seq(),mi,slot,d,words[0],words[1],words[2]);
        }
    }
}
} // namespace friction_native
extern "C" void fn_guard(const char* site,const btManifoldPoint* p) {
    using namespace friction_native;caches(p);if(!observed)return;
    if(std::strcmp(site,"MANIFOLD_ALLOC_ENTER")==0){need(!allocating);allocating=true;allocated=false;backing_ctors=0;}
    if(std::strcmp(site,"MANIFOLD_ALLOC_EXIT")==0){need(allocating && allocated && backing_ctors==4);allocating=false;}
    if(std::strcmp(site,"RESULT_ENTER")==0){need(!active_result);active_result=fresh(result_counter);}
    if(std::strcmp(site,"RESULT_EXIT")==0){need(active_result && !pending_stage);active_result=0;}
    if(std::strcmp(site,"PROCESSED_PRECALL")==0){
        need(refresh.pointer && refresh.pending==1 && p==&refresh.pointer->getContactPoint(refresh.slot));
        auto& m=manifold(refresh.pointer);need(m.points[refresh.slot].gid==refresh.gid);refresh.pending=0;--refresh.cursor;
    }
    if(std::strcmp(site,"REMOVE_ENTER")==0 && refresh.pointer){
        need(refresh.pending==2 && p==&refresh.pointer->getContactPoint(refresh.slot));refresh.pending=3;
    }
    if(std::strcmp(site,"REMOVE_EXIT")==0 && refresh.pointer){need(refresh.pending==3);refresh.pending=0;--refresh.cursor;}
    if(pending_stage==1){need(depth && active_result==pending_result);need(std::strcmp(site,"ADD_EXIT")==0||std::strcmp(site,"REPLACE_EXIT")==0);pending_stage=2;}
    else if(pending_stage==2){need(std::strcmp(site,"ADDED_PRECALL")==0);pending_stage=0;}
    scope(site);raw("FG %u %u %s true true true true\n",checkpoint,guard_seq(),site);
}
extern "C" void fn_ctor(const btManifoldPoint* p,bool geometric) {
    using namespace friction_native;need(observed && depth);
    if(geometric){need(active_result && !constructed_incoming && std::strcmp(scopes[depth-1],"RESULT_ENTER")==0);constructed_incoming=p;}
    else {need(allocating && !allocated && backing_ctors<4 && std::strcmp(scopes[depth-1],"MANIFOLD_ALLOC_ENTER")==0);++backing_ctors;}
    fn_guard("CTOR_EXIT",p);
}
extern "C" void fn_incoming(const btManifoldPoint* p) {
    using namespace friction_native;need(observed && active_result && constructed_incoming==p);constructed_incoming=nullptr;caches(p);
    for(auto& t:temporary)need(t.pointer!=p);
    unsigned live=0;for(auto& m:manifold_slots)if(m.pointer)live+=m.count;for(auto& t:temporary)if(t.pointer)++live;need(live<16384);
    for(auto& t:temporary)if(!t.pointer){t={p,fresh(next_gid)};raw("FC %u %u CTOR_GEOMETRIC %u\n",checkpoint,seq(),t.gid);return;}need(false);
}
extern "C" void fn_allocate(btPersistentManifold* p,const void* a,const void* b) {
    using namespace friction_native;need(allocating && !allocated && backing_ctors==4);allocated=true;caches(nullptr);for(auto& m:manifold_slots)need(m.pointer!=p);
    for(auto& m:manifold_slots)if(!m.pointer){m=Manifold{};m.pointer=p;m.mid=::manifolds.at(p);need(m.mid==fresh(next_mid));m.a=owner(a);m.b=owner(b);need(m.a!=m.b && m.a<=limit && m.b<=limit && p->getNumContacts()==0);raw("FM %u %u ALLOC %u %u %u\n",checkpoint,seq(),m.mid,m.a,m.b);return;}need(false);
}
extern "C" void fn_release(btPersistentManifold* p) {
    using namespace friction_native;auto& m=manifold(p);need(m.count==0 && p->getNumContacts()==0);
    raw("FM %u %u RELEASE %u %u %u\n",checkpoint,seq(),m.mid,m.a,m.b);m=Manifold{};
}
extern "C" void fn_insert(btPersistentManifold* p,int slot,const btManifoldPoint* incoming,bool replace) {
    using namespace friction_native;auto& m=manifold(p);need(slot>=0 && slot<4 && !pending_stage);
    for(auto& t:temporary)if(t.pointer==incoming){
        need(slot<=int(m.count) && (replace?slot<int(m.count):true));
        const bool eviction=!replace && m.count==4;need(replace||eviction||unsigned(slot)==m.count);
        auto& point=m.points[slot];const unsigned old=point.gid,gid=fresh(next_gid),in=t.gid;
        need((replace||eviction)==(old!=0) && point.tx==0);if(old)++closed;++closed;
        point=Point{};point.gid=gid;t=Temporary{};if(!replace&&!eviction)++m.count;
        need(m.count==unsigned(p->getNumContacts()));
        raw("FI %u %u %s %u %d %u %u %u 0\n",checkpoint,seq(),replace?"REPLACE":eviction?"EVICT_ADD":"ADD",m.mid,slot,old,in,gid);
        need(active_result);pending_result=active_result;pending_mid=m.mid;pending_slot=slot;pending_gid=gid;pending_stage=1;return;
    }need(false);
}
extern "C" void fn_added(btPersistentManifold* p,int slot) {
    using namespace friction_native;auto& m=manifold(p);need(pending_stage==2 && active_result==pending_result && slot>=0 && unsigned(slot)<m.count && pending_mid==m.mid && pending_slot==unsigned(slot) && pending_gid==m.points[slot].gid);
    fn_guard("ADDED_PRECALL",&p->getContactPoint(slot));pending_mid=pending_slot=pending_gid=0;
}
extern "C" void fn_remove(btPersistentManifold* p,int slot) {
    using namespace friction_native;auto& m=manifold(p);need(slot>=0 && unsigned(slot)<m.count && !m.points[slot].tx);
    if(refresh.pointer)need(refresh.pointer==p && refresh.pending==3 && refresh.slot==unsigned(slot) && refresh.gid==m.points[slot].gid);
    const unsigned last=m.count-1;raw("FX %u %u REMOVE %u %d %u\n",checkpoint,seq(),m.mid,slot,m.points[slot].gid);++closed;
    if(unsigned(slot)!=last){m.points[slot]=m.points[last];raw("FV %u %u REMOVE_MOVE %u %u %d %u\n",checkpoint,seq(),m.mid,last,slot,m.points[slot].gid);}
    m.points[last]=Point{};--m.count;need(m.count==unsigned(p->getNumContacts()));
}
extern "C" void fn_clear_begin(btPersistentManifold* p) {using namespace friction_native;auto& m=manifold(p);raw("FM %u %u CLEAR_BEGIN %u %u %u\n",checkpoint,seq(),m.mid,m.a,m.b);}
extern "C" void fn_clear_point(btPersistentManifold* p,int slot) {
    using namespace friction_native;auto& m=manifold(p);need(slot>=0 && unsigned(slot)<m.count && m.points[slot].gid && !m.points[slot].tx);
    raw("FX %u %u CLEAR_POINT %u %d %u\n",checkpoint,seq(),m.mid,slot,m.points[slot].gid);m.points[slot]=Point{};++closed;
}
extern "C" void fn_clear_end(btPersistentManifold* p) {
    using namespace friction_native;auto& m=manifold(p);need(p->getNumContacts()==0);for(auto& x:m.points)need(x.gid==0);m.count=0;
    raw("FM %u %u CLEAR_END %u %u %u\n",checkpoint,seq(),m.mid,m.a,m.b);
}
extern "C" void fn_solver_begin(btManifoldPoint* p,int mode) {
    using namespace friction_native;fn_guard("SOLVER_BEGIN",p);Manifold* m;unsigned slot;auto& x=binding(p,m,slot);need(!x.tx && mode==260);
    x.tx=fresh(next_tx);x.branch=x.writes=0;x.chosen=false;
    raw("FB %u %u SOLVER_BEGIN %u %u %u %u %d %s\n",checkpoint,seq(),m->mid,slot,x.gid,x.tx,mode,boolean(p->m_lateralFrictionInitialized));
}
extern "C" void fn_choice(btManifoldPoint* p,bool recompute,bool velocity,bool two) {
    using namespace friction_native;Manifold* m;unsigned slot;auto& x=binding(p,m,slot);need(x.tx && !x.chosen && (recompute||!velocity));
    need(x.writes==(recompute?1u:0u));if(!recompute)need((x.mask&(two?3u:1u))==(two?3u:1u));x.chosen=true;x.recompute=recompute;x.velocity=velocity;x.two=two;
    raw("FT %u %u SOLVER_CHOICE %u %u %u %u %s %s %s\n",checkpoint,seq(),m->mid,slot,x.gid,x.tx,boolean(recompute),boolean(velocity),boolean(two));
}
extern "C" void fn_write(btManifoldPoint* p,const char* site,unsigned mask) {
    using namespace friction_native;Manifold* m;unsigned slot;auto& x=binding(p,m,slot);
    const bool fixture=std::strcmp(site,"FIXTURE_W")==0;
    if(fixture)need(fixture_active && !x.tx && mask==3 && depth && std::strcmp(scopes[depth-1],"FIXTURE_BEGIN")==0);
    else {
        need(x.tx);const char* expected=x.writes==0?"DIR1_RAW":x.writes==1?(x.velocity?"VELOCITY_DIR1":"PLANE_BOTH"):"VELOCITY_DIR2";
        need(std::strcmp(site,expected)==0 && (x.writes==0?!x.chosen:x.chosen&&x.recompute));
        need(mask==(std::strcmp(site,"PLANE_BOTH")==0?3u:std::strcmp(site,"VELOCITY_DIR2")==0?2u:1u));++x.writes;x.branch|=mask;
    }
    x.mask|=mask;raw("FW %u %u %s %u %u %u %u %u\n",checkpoint,seq(),site,m->mid,slot,x.gid,fixture?0:x.tx,mask);
}
extern "C" void fn_solver_end(btManifoldPoint* p) {
    using namespace friction_native;Manifold* m;unsigned slot;auto& x=binding(p,m,slot);need(x.tx && x.chosen);
    need(x.writes==(x.recompute?(x.velocity&&x.two?3u:2u):0u));
    const char* site=x.recompute?(x.velocity?(x.two?"VELOCITY_TWO":"VELOCITY_ONE"):(x.two?"PLANE_TWO":"PLANE_ONE")):(x.two?"CACHED_TWO":"CACHED_ONE");
    raw("FE %u %u %s %u %u %u %u %u %u %s\n",checkpoint,seq(),site,m->mid,slot,x.gid,x.tx,x.branch,x.mask,boolean(p->m_lateralFrictionInitialized));x.tx=0;fn_guard("SOLVER_END",p);
}
extern "C" void fn_no_anisotropy(bool active) {friction_native::need(!active);}
extern "C" void fn_refresh_begin(btPersistentManifold* p) {
    using namespace friction_native;auto& m=manifold(p);need(!refresh.pointer && m.count==unsigned(p->getNumContacts()));
    refresh=Refresh{};refresh.pointer=p;refresh.cursor=int(m.count)-1;
    raw("FR %u %u REFRESH_BEGIN %u 0 0 false false\n",checkpoint,seq(),m.mid);
}
extern "C" void fn_refresh_point(btPersistentManifold* p,int slot,bool distance_remove,bool lateral_remove) {
    using namespace friction_native;auto& m=manifold(p);need(refresh.pointer==p && !refresh.pending && refresh.cursor==slot && slot>=0 && unsigned(slot)<m.count && !(distance_remove&&lateral_remove));
    const unsigned gid=m.points[slot].gid;for(unsigned i=0;i<refresh.count;++i)need(refresh.visited[i]!=gid);
    need(refresh.count<4);refresh.visited[refresh.count++]=gid;refresh.slot=slot;refresh.gid=gid;refresh.pending=distance_remove||lateral_remove?2:1;
    raw("FR %u %u REFRESH_POINT %u %d %u %s %s\n",checkpoint,seq(),m.mid,slot,gid,boolean(distance_remove),boolean(lateral_remove));
}
extern "C" void fn_refresh_end(btPersistentManifold* p) {
    using namespace friction_native;auto& m=manifold(p);need(refresh.pointer==p && !refresh.pending && refresh.cursor==-1);
    raw("FR %u %u REFRESH_END %u 0 0 false false\n",checkpoint,seq(),m.mid);refresh=Refresh{};
}
#endif
