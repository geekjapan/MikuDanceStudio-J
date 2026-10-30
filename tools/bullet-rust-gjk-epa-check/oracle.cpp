// Calls the real vendored API. Failure results never read unwritten fields.
#include "BulletCollision/CollisionShapes/btSphereShape.h"
#include "BulletCollision/CollisionShapes/btBoxShape.h"
#include "BulletCollision/CollisionShapes/btCapsuleShape.h"
#include "BulletCollision/NarrowPhaseCollision/btGjkEpa2.h"
#include "BulletCollision/NarrowPhaseCollision/btGjkEpaPenetrationDepthSolver.h"
#include "BulletCollision/NarrowPhaseCollision/btVoronoiSimplexSolver.h"
#include <cstdio>
#include <cstring>
#include <memory>
static float scalar(unsigned word){float v;std::memcpy(&v,&word,4);return v;}
static void word(float v){unsigned w;std::memcpy(&w,&v,4);std::printf("\t%08x",w);}
static void vector(const btVector3& v){for(int i=0;i<3;++i)word(v[i]);}
static std::unique_ptr<btConvexShape> shape(int kind,const float* v){switch(kind){case 0:return std::unique_ptr<btConvexShape>(new btSphereShape(v[0]));case 1:return std::unique_ptr<btConvexShape>(new btBoxShape(btVector3(v[0],v[1],v[2])));case 2:return std::unique_ptr<btConvexShape>(new btCapsuleShape(v[0],v[1]));}return {};}
int main(){int id,ka,kb;unsigned bits;while(std::scanf("%d%d%d",&id,&ka,&kb)==3){float v[33];for(float& x:v){if(std::scanf("%x",&bits)!=1)return 2;x=scalar(bits);}auto a=shape(ka,v);auto b=shape(kb,v+3);if(!a||!b)return 3;
    btTransform t[2];for(int i=0;i<2;++i){const float* p=v+6+12*i;t[i].setBasis(btMatrix3x3(p[0],p[1],p[2],p[3],p[4],p[5],p[6],p[7],p[8]));t[i].setOrigin(btVector3(p[9],p[10],p[11]));}
    btVector3 guess(v[30],v[31],v[32]);std::printf("%d",id);
    for(int method=0;method<3;++method){btGjkEpaSolver2::sResults r;bool ok=method==0?btGjkEpaSolver2::Distance(a.get(),t[0],b.get(),t[1],guess,r):btGjkEpaSolver2::Penetration(a.get(),t[0],b.get(),t[1],guess,r,method==2);std::printf("\t%d\t%d",ok,r.status);if(ok){vector(r.witnesses[0]);vector(r.witnesses[1]);vector(r.normal);word(r.distance);}}
    btVoronoiSimplexSolver simplex;btGjkEpaPenetrationDepthSolver solver;btVector3 n(11,12,13),wa(21,22,23),wb(31,32,33);bool ok=solver.calcPenDepth(simplex,a.get(),b.get(),t[0],t[1],n,wa,wb,0,0);std::printf("\t%d",ok);vector(wa);vector(wb);vector(n);std::putchar('\n');}return std::ferror(stdin)?4:0;}
