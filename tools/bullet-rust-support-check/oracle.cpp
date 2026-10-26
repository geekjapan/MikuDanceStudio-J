// Direct calls to the real vendored nonvirtual support APIs.
#include "BulletCollision/CollisionShapes/btSphereShape.h"
#include "BulletCollision/CollisionShapes/btBoxShape.h"
#include "BulletCollision/CollisionShapes/btCapsuleShape.h"
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <memory>
static float scalar(unsigned word) { float v; std::memcpy(&v, &word, 4); return v; }
static void vector(const btVector3& v) {
    for (int i=0;i<3;++i) { unsigned w; float f=v[i]; std::memcpy(&w,&f,4); std::printf("\t%08x",w); }
}
int main() {
    int id, kind; unsigned bits[6];
    while(std::scanf("%d%d", &id, &kind)==2) {
        float v[6];
        for(int i=0;i<6;++i) { if(std::scanf("%x",&bits[i])!=1) return 2; v[i]=scalar(bits[i]); }
        std::unique_ptr<btConvexShape> s;
        switch(kind) {
            case 0: s.reset(new btSphereShape(v[0])); break;
            case 1: s.reset(new btBoxShape(btVector3(v[0],v[1],v[2]))); break;
            case 2: s.reset(new btCapsuleShape(v[0],v[1])); break;
            default: return 3;
        }
        btVector3 d(v[3],v[4],v[5]);
        std::printf("%d",id);
        vector(s->localGetSupportVertexWithoutMarginNonVirtual(d));
        vector(s->localGetSupportVertexNonVirtual(d));
        vector(s->localGetSupportingVertex(d));
        std::putchar('\n');
    }
    return std::ferror(stdin)?4:0;
}
