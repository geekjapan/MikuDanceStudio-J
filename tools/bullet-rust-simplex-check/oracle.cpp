#include <cstdint>
#include <cstring>
#include <iostream>
#include <string>
#include <vector>
#include <cmath>
#include "BulletCollision/NarrowPhaseCollision/btVoronoiSimplexSolver.h"
static float read_float() { uint32_t bits; std::cin >> std::hex >> bits >> std::dec; float f; std::memcpy(&f,&bits,4); return f; }
static btVector3 read_vector() { float x=read_float(), y=read_float(), z=read_float(); return btVector3(x,y,z); }
static void scalar(float f) {
    if (std::isnan(f)) { std::cout << " nan"; return; }
    uint32_t bits; std::memcpy(&bits,&f,4); std::cout << ' ' << std::hex << bits << std::dec;
}
static void vector(const btVector3& v) { scalar(v.x()); scalar(v.y()); scalar(v.z()); }
int main() {
    btVoronoiSimplexSolver s;
    s.reset();
    bool cache_defined=false, point_defined=false;
    std::string op;
    while (std::cin >> op) {
        int ret=-1;
        std::vector<btVector3> returned;
        int before=s.numVertices();
        bool update=s.m_needsUpdate;
        if (op=="R") s.reset();
        else if (op=="A") { auto w=read_vector(), p=read_vector(), q=read_vector(); s.addVertex(w,p,q); }
        else if (op=="C") { btVector3 v; ret=s.closest(v); if(cache_defined || (update && before>=1 && before<=3)) returned.push_back(v); }
        else if (op=="P") { btVector3 p,q; s.compute_points(p,q); if(cache_defined || (update && before>=1 && before<=3)) { returned.push_back(p); returned.push_back(q); } }
        else if (op=="B") { if(cache_defined) { btVector3 v; s.backup_closest(v); returned.push_back(v); } }
        else if (op=="I") { auto w=read_vector(); ret=s.inSimplex(w); }
        else return 2;
        if ((op=="C" || op=="P") && update) {
            if (before>=1 && before<=3) cache_defined=true;
            if (before>=3) point_defined=true;
        }
        std::cout << op << ' ' << ret << ' ' << s.numVertices() << ' ' << s.fullSimplex() << ' ' << s.emptySimplex() << ' ' << s.m_needsUpdate << ' ' << s.m_cachedValidClosest << ' ' << s.m_cachedBC.m_degenerate;
        auto& u=s.m_cachedBC.m_usedVertices;
        std::cout << ' ' << u.usedVertexA << ' ' << u.usedVertexB << ' ' << u.usedVertexC << ' ' << u.usedVertexD;
        for(float f:s.m_cachedBC.m_barycentricCoords) scalar(f);
        vector(s.m_lastW); scalar(s.maxVertex());
        if(cache_defined) { vector(s.m_cachedP1); vector(s.m_cachedP2); vector(s.m_cachedV); } else std::cout << " _ _ _ _ _ _ _ _ _";
        if(point_defined) vector(s.m_cachedBC.m_closestPointOnSimplex); else std::cout << " _ _ _";
        btVector3 p[5],q[5],w[5]; int count=s.getSimplex(p,q,w);
        for(int i=0;i<count;i++) { vector(w[i]); vector(p[i]); vector(q[i]); }
        for(auto& v:returned) vector(v);
        std::cout << '\n';
    }
}
