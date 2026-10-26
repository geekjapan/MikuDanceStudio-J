// Test adapter. All body operations execute in real vendored Bullet.
#include "BulletDynamics/Dynamics/btRigidBody.h"
#include "LinearMath/btDefaultMotionState.h"
#include "BulletCollision/CollisionShapes/btSphereShape.h"
#include "BulletCollision/CollisionShapes/btBoxShape.h"
#include "BulletCollision/CollisionShapes/btCapsuleShape.h"
#include "BulletCollision/CollisionShapes/btStaticPlaneShape.h"
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <iostream>
#include <memory>
#include <sstream>
#include <string>

static void scalar(float value) {
    uint32_t bits;
    std::memcpy(&bits, &value, sizeof(bits));
    std::printf(" %08x", bits);
}
static void vector(const btVector3& v) { for (int i=0; i<3; ++i) scalar(v[i]); }
static void basis(const btMatrix3x3& b) { for (int i=0; i<3; ++i) vector(b[i]); }
static void transform(const btTransform& t) { basis(t.getBasis()); vector(t.getOrigin()); }
static float read(std::istringstream& input) {
    uint32_t bits; input >> std::hex >> bits;
    float value; std::memcpy(&value, &bits, sizeof(value)); return value;
}
static btVector3 read_vector(std::istringstream& input) {
    float x=read(input), y=read(input), z=read(input);
    return btVector3(x,y,z);
}
static btTransform read_transform(std::istringstream& input) {
    btTransform t;
    for(int i=0;i<3;++i) t.getBasis()[i]=read_vector(input);
    t.setOrigin(read_vector(input)); return t;
}
static void snapshot(btRigidBody& b) {
    scalar(b.getInvMass()); vector(b.getInvInertiaDiagLocal()); basis(b.getInvInertiaTensorWorld());
    transform(b.getWorldTransform()); transform(b.getInterpolationWorldTransform());
    vector(b.getLinearVelocity()); vector(b.getAngularVelocity());
    vector(b.getInterpolationLinearVelocity()); vector(b.getInterpolationAngularVelocity());
    vector(b.getGravity());
    // Observe the otherwise private gravity force through real public operations.
    btRigidBody probe=b;
    probe.setCollisionFlags(0); probe.clearForces();
    // A negative-zero accumulator preserves the sign of a zero gravity component.
    const_cast<btVector3&>(probe.getTotalForce()).setValue(-0.0f,-0.0f,-0.0f);
    probe.applyGravity(); vector(probe.getTotalForce());
    vector(b.getTotalForce()); vector(b.getTotalTorque());
    scalar(b.getLinearDamping()); scalar(b.getAngularDamping());
    std::printf(" %08x %08x", unsigned(b.isStaticObject()), unsigned(b.isKinematicObject()));
}
int main() {
    std::unique_ptr<btCollisionShape> shape;
    std::unique_ptr<btDefaultMotionState> motion;
    std::unique_ptr<btRigidBody> body;
    std::string line;
    while(std::getline(std::cin,line)) {
        std::istringstream input(line); char op; input>>op;
        btTransform predicted; bool prediction=false;
        switch(op) {
        case 'N': {
            body.reset(); motion.reset(); shape.reset();
            const float mass=read(input), ld=read(input), ad=read(input);
            const int kind=int(read(input)); const btVector3 dimensions=read_vector(input);
            switch(kind) {
            case 0: shape.reset(new btSphereShape(dimensions[0])); break;
            case 1: shape.reset(new btBoxShape(dimensions)); break;
            case 2: shape.reset(new btCapsuleShape(dimensions[0], dimensions[1])); break;
            default: shape.reset(new btStaticPlaneShape(dimensions, .7f)); break;
            }
            const btTransform start=read_transform(input);
            const bool custom=read(input)!=0; btVector3 inertia=read_vector(input);
            if(!custom) shape->calculateLocalInertia(mass,inertia);
            motion.reset(new btDefaultMotionState(start));
            btRigidBody::btRigidBodyConstructionInfo init(mass,motion.get(),shape.get(),inertia);
            init.m_linearDamping=ld; init.m_angularDamping=ad;
            body.reset(new btRigidBody(init)); break;
        }
        case 'M': { const float mass=read(input); body->setMassProps(mass,read_vector(input)); break; }
        case 'U': body->updateInertiaTensor(); break;
        case 'G': body->setGravity(read_vector(input)); break;
        case 'F': body->applyCentralForce(read_vector(input)); break;
        case 'T': body->applyTorque(read_vector(input)); break;
        case 'A': body->applyGravity(); break;
        case 'I': body->integrateVelocities(read(input)); break;
        case 'D': body->applyDamping(read(input)); break;
        case 'P': body->predictIntegratedTransform(read(input),predicted); prediction=true; break;
        case 'C': body->setCenterOfMassTransform(read_transform(input)); break;
        case 'Z': body->clearForces(); break;
        case 'L': body->setLinearVelocity(read_vector(input)); break;
        case 'W': body->setAngularVelocity(read_vector(input)); break;
        case 'K': {
            const bool value=read(input)!=0;
            int flags=body->getCollisionFlags();
            body->setCollisionFlags(value ? flags|btCollisionObject::CF_KINEMATIC_OBJECT : flags&~btCollisionObject::CF_KINEMATIC_OBJECT);
            break;
        }
        default: return 2;
        }
        std::printf("%s |",line.c_str()); snapshot(*body);
        if(prediction) transform(predicted);
        std::printf("\n");
    }
}
