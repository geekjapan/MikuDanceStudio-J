# Activation parity

`core/activation.rs` translates the activation methods from the vendored `btCollisionObject.cpp`, `btRigidBody.h`, and `btDiscreteDynamicsWorld.cpp`. It preserves native state integers 0 through 5, protected states 4 and 5, active state 0, the strict speed comparisons, and the strict deactivation time comparison. Defaults are linear speed 0.8, angular speed 1.0, and deactivation time 2 seconds. `DeactivationSettings` represents the two native globals. `CollisionClassification` represents the four combinations of static and kinematic bits.

`update_activation_state` processes one entry of the native world's nonstatic body array. The world owns registration and iteration. Static or kinematic flags may change after a dynamic body is registered. A sleeping dynamic entry has both velocities set to positive zero. A static or kinematic entry takes the sleeping state branch without zeroing velocities. The kernel does not create a world or connect `body.rs` or the public `World`.

Run the native recapture and focused Rust checks from the repository root.

```sh
python3 tools/bullet-rust-activation-check/check.py --out-dir /tmp/mds-activation
```

The standalone C++ oracle constructs real bodies and a real Bullet world, registers each body with `addRigidBody`, and exposes the protected native `updateActivationState` through a subclass. It calls the actual native methods. It does not copy their logic or modify native sources. No observation hooks or masked fields are needed. Only initialized scalar fields and the three initialized components of each velocity are read.

Each input operation has an output snapshot containing the native state integer, `isActive`, `wantsSleeping`, collision flags, deactivation time, both thresholds, six velocity components, and both global settings. Floats are compared as raw words, including signed zeros and NaN payloads. The deterministic corpus has 1,235 complete scenarios and 22,008 operation snapshots. Its complete directed prefix contains 829 scenarios and 5,572 snapshots. The remaining corpus includes six scenarios with opposite infinities in timer arithmetic and 400 seeded sequences. The generator moves exactly the six state variants of timer `-infinity` plus time step `+infinity` after the frozen prefix, without dropping any scenario or field. The source does not fix the generated NaN sign. The prefix therefore does not assert the stronger property of cross-host raw-bit equality for those six scenarios. No cross-host discrepancy has been measured for this kernel. Full native recapture still compares every raw word strictly against Rust on the executing host.

Directed cases cover all native states, protected and forced transitions, static, kinematic and both bits, unrelated collision bits, forced and ordinary activation, default and custom thresholds, exact speed equality and adjacent floats, exact time equality and adjacent floats, negative time steps, signed zeros, overflow, infinities, quiet and signaling NaN inputs, global deactivation disable, zero and negative global sleep time, wake, and world velocity zeroing. The compact fixture is replayed by the existing native-free test harness on all four configured targets. Native recapture is the sixteenth Linux x64 CI group.

The checker runs focused native capture, compact and full Rust replay, Clippy, and twelve isolated mutations. Every mutation must compile and fail compact replay. Mutations change sticky states 4 and 5, the strict time boundary, each strict speed boundary, static, kinematic and both flags, sleep zeroing, the sleep zeroing condition, world update order, and state 0 activity. Commands, hashes, compiler provenance, native snapshots and mutation logs remain in the output directory.

This unit does not cover island activation, registration/removal ordering, multiple-body world schedules, motion-state synchronization, or the full dynamics step. It does not claim arbitrary native integers outside 0 through 5. Cross-target runtime results must come from executed CI, not this workflow configuration. GPU checks and the repository integration gate belong to the parent integration unit.
