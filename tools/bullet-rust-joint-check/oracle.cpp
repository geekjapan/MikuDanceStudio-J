// Test adapter only. Row and spring algorithms come from the vendored .cpp files.
#include "BulletDynamics/ConstraintSolver/btGeneric6DofSpringConstraint.h"
#include "BulletDynamics/Dynamics/btRigidBody.h"
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <vector>

static std::vector<uint32_t> words;
static void scalar(float v) { uint32_t b; std::memcpy(&b, &v, 4); words.push_back(b); }
static void integer(unsigned v) { words.push_back(v); }
static void vector(const btVector3& v) { for (int i = 0; i < 3; ++i) scalar(v[i]); }

struct Joint : btGeneric6DofSpringConstraint {
    using btGeneric6DofSpringConstraint::btGeneric6DofSpringConstraint;
    void coordinates() {
        for (int i = 0; i < 3; ++i) vector(m_calculatedTransformA.getBasis()[i]);
        vector(m_calculatedTransformB.getOrigin());
        vector(m_calculatedLinearDiff); vector(m_calculatedAxisAngleDiff);
        for (int i = 0; i < 3; ++i) vector(m_calculatedAxis[i]);
    }
    void motor(int i) {
        if (i < 3) {
            scalar(m_linearLimits.m_lowerLimit[i]); scalar(m_linearLimits.m_upperLimit[i]);
            integer(m_linearLimits.m_enableMotor[i]); scalar(m_linearLimits.m_targetVelocity[i]);
            scalar(m_linearLimits.m_maxMotorForce[i]); scalar(m_linearLimits.m_currentLinearDiff[i]);
            integer(m_linearLimits.m_currentLimit[i]); scalar(m_linearLimits.m_currentLimitError[i]);
        } else {
            auto& m = m_angularLimits[i - 3];
            scalar(m.m_loLimit); scalar(m.m_hiLimit); integer(m.m_enableMotor);
            scalar(m.m_targetVelocity); scalar(m.m_maxMotorForce); scalar(m.m_currentPosition);
            integer(m.m_currentLimit); scalar(m.m_currentLimitError); scalar(m.m_ERP); scalar(m.m_bounce);
        }
    }
    void state() {
        for (int i = 0; i < 6; ++i) motor(i);
        scalar(m_linearLimits.m_restitution);
        for (int i = 0; i < 6; ++i) {
            integer(m_springEnabled[i]); scalar(m_equilibriumPoint[i]);
            scalar(m_springStiffness[i]); scalar(m_springDamping[i]);
        }
    }
    void configure(int mode) {
        m_linearLimits.m_restitution = 0.37f;
        for (int i = 0; i < 6; ++i) {
            float pos = i < 3 ? m_calculatedLinearDiff[i] : m_calculatedAxisAngleDiff[i - 3];
            float lo = -0.3f, hi = 0.3f;
            switch (mode % 12) {
                case 0: lo = 1; hi = -1; break;
                case 1: lo = hi = pos; break;
                case 2: lo = hi = 0; break;
                case 3: lo = pos; hi = pos + 0.2f; break;
                case 4: lo = pos - 0.2f; hi = pos; break;
                case 5: lo = pos + 0.05f; hi = pos + 0.2f; break;
                case 6: lo = pos - 0.2f; hi = pos - 0.05f; break;
                case 7: lo = pos - 0.01f; hi = pos + 0.01f; break;
                case 8: lo = 2.8f; hi = 3.0f; break;
                case 9: lo = -3.0f; hi = -2.8f; break;
                case 10: lo = -0.001f; hi = 0.001f; break;
                case 11: lo = 1.0f; hi = -1.0f; break;
            }
            setLimit(i, lo, hi);
            bool enabled = (mode / 12) % 3 != 0;
            enableSpring(i, enabled && mode >= 36);
            setStiffness(i, 0.1234567f * (i + 1));
            setDamping(i, 0.23f + 0.17f * i);
            m_equilibriumPoint[i] = i % 2 ? -0.125f : 0.25f;
            if (i < 3) {
                m_linearLimits.m_enableMotor[i] = enabled;
                m_linearLimits.m_targetVelocity[i] = (i - 1) * 12.34567f;
                m_linearLimits.m_maxMotorForce[i] = (i + 1) * 0.75f;
                m_linearLimits.m_currentLimit[i] = 2;
                m_linearLimits.m_currentLimitError[i] = 1.25f;
            } else {
                auto& m = m_angularLimits[i - 3];
                m.m_enableMotor = enabled;
                m.m_targetVelocity = (i - 4) * 12.34567f;
                m.m_maxMotorForce = (i - 2) * 0.75f;
                m.m_currentLimit = 1; m.m_currentLimitError = -1.25f;
                m.m_ERP = 0.13f * (i - 2);
                m.m_bounce = mode % 2 ? 0.625f : 0;
            }
        }
        // Deliberately exercise stored spring/motor independence and the zero-row guard.
        if (mode >= 60) {
            for (int i = 0; i < 6; ++i) {
                setLimit(i, 1, -1); enableSpring(i, true);
                bool active = (mode == 61 && i == 1) || (mode == 62 && (i == 2 || i == 4));
                if (i < 3) m_linearLimits.m_enableMotor[i] = active;
                else m_angularLimits[i - 3].m_enableMotor = active;
            }
        }
    }
    std::vector<unsigned> axes() {
        std::vector<unsigned> out;
        for (int i = 0; i < 3; ++i) if (m_linearLimits.needApplyForce(i)) out.push_back(i);
        for (int i = 0; i < 3; ++i) if (m_angularLimits[i].needApplyTorques()) out.push_back(i + 3);
        return out;
    }
};

static void body(const btRigidBody& b) {
    vector(b.getCenterOfMassPosition()); vector(b.getLinearVelocity()); vector(b.getAngularVelocity());
}

int main() {
    unsigned id = 0;
    for (int mode = 0; mode <= 62; ++mode) {
        btRigidBody a(1.0f, nullptr, nullptr, btVector3(1, 2, 3));
        btRigidBody b(2.0f, nullptr, nullptr, btVector3(3, 2, 1));
        btTransform fa, fb; fa.setIdentity(); fb.setIdentity();
        fa.setOrigin(btVector3(0.25f, -0.5f, 0.75f));
        fb.setOrigin(btVector3(-0.375f, 0.25f, -0.125f));
        Joint joint(a, b, fa, fb, mode % 2 == 0);
        for (int frame = 0; frame < 6; ++frame) {
            btTransform ta, tb; ta.setIdentity(); tb.setIdentity();
            if (mode % 12 != 1 || frame != 0) {
                ta.setRotation(btQuaternion(btVector3(1, 2, 3).normalized(), 0.21f));
                tb.setRotation(btQuaternion(btVector3(3, -1, 2).normalized(),
                    frame == 3 ? 0.0f : (frame == 4 ? -3.05f : 0.17f * (frame + 1))));
                ta.setOrigin(btVector3(0.3f, -0.7f, 0.15f));
                tb.setOrigin(btVector3(-0.2f * frame, 0.1f * frame, -0.3f * frame));
            }
            a.setCenterOfMassTransform(ta); b.setCenterOfMassTransform(tb);
            float sign = frame % 2 ? -1.0f : 1.0f;
            a.setLinearVelocity(btVector3(3.25f, -9.125f, 0.0625f));
            b.setLinearVelocity(btVector3(-8.75f, 4.125f, -3.5f));
            a.setAngularVelocity(btVector3(19.12345f, -27.98765f, 3.456789f) * sign);
            b.setAngularVelocity(btVector3(-21.76543f, 13.12345f, -7.567891f) * sign);
            btTypedConstraint::btConstraintInfo1 count;
            if (frame == 0) { joint.getInfo1(&count); joint.configure(mode); }
            words.clear(); joint.state(); auto prior = words;
            joint.buildJacobian(); joint.getInfo1(&count);
            words.clear(); joint.coordinates(); body(a); body(b);
            float fps = frame % 2 ? 144.0f : 59.94f;
            float erp = 0.213f; unsigned iterations = frame % 2 ? 7 : 10;
            scalar(fps); scalar(erp); integer(iterations);
            words.insert(words.end(), prior.begin(), prior.end());
            auto axes = joint.axes();
            float j1l[18] = {}, j1a[18] = {}, j2a[18] = {}, rhs[18] = {}, cfm[18] = {};
            float lower[18], upper[18];
            for (int i = 0; i < 18; ++i) { lower[i] = -SIMD_INFINITY; upper[i] = SIMD_INFINITY; }
            btTypedConstraint::btConstraintInfo2 info = {};
            info.fps = fps; info.erp = erp; info.m_numIterations = iterations; info.rowskip = 3;
            info.m_J1linearAxis = j1l; info.m_J1angularAxis = j1a; info.m_J2angularAxis = j2a;
            info.m_constraintError = rhs; info.cfm = cfm; info.m_lowerLimit = lower; info.m_upperLimit = upper;
            if (count.m_numConstraintRows) joint.getInfo2(&info);
            integer(count.m_numConstraintRows);
            for (int r = 0; r < count.m_numConstraintRows; ++r) {
                integer(axes[r]);
                for (auto values : {j1l, j1a, j2a}) for (int k = 0; k < 3; ++k) scalar(values[r * 3 + k]);
                scalar(rhs[r * 3]); scalar(cfm[r * 3]); scalar(lower[r * 3]); scalar(upper[r * 3]);
            }
            joint.state();
            std::printf("%u", id++);
            for (auto word : words) std::printf("\t%08x", word);
            std::puts("");
        }
    }
}
