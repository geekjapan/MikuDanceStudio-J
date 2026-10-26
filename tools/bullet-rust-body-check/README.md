# Check the bounded Rust rigid-body kernel

Run from the repository root.

```sh
python3 tools/bullet-rust-body-check/check.py --out-dir /tmp/mds-body-check
```

The checker compiles real vendored `btRigidBody` and sphere, box, Y-capsule and plane shapes. The force-included deterministic math adapter links the actual `mds-crtmath` library. It runs supported-target float branches, excludes Win32-specific inertia and double-pow patches, and compares its output with the committed fixture before replaying it in Rust. `--record` explicitly replaces the fixture.

Every command emits the complete initialized numeric kernel state. Each float is compared by its exact 32-bit word, including signed zero. Prediction emits the predicted transform plus a snapshot that checks nonmutation. Gravity force has no getter. The oracle copies the body, clears its flags and forces, seeds the observable force accumulator with negative zero, then calls real `applyGravity` and `getTotalForce`. The seed preserves either sign of zero without changing any production method.

The 5,247 snapshots comprise 144 shape, mass, basis and damping traces of 32 operations, 14 angular-threshold traces of 13 operations, 36 custom-inertia traces of 12 operations and one gravity and mass transition trace of 10 operations, and three signed-zero COM traces of five operations. The Rust test asserts those exact family counts and coverage of every operation, all shapes, zero, positive and negative mass, zero and mixed-zero inertia for each shape, damping clamps, four basis bit patterns, all four static and kinematic flag combinations, and angular speeds below, equal to and above pi/2. Further cases cover small velocities, signed zero, repeated force accumulation, force clearing, reused force across substeps, stale gravity force after mass changes, COM interpolation and world inertia refresh.

`BodyInit.center_of_mass` is an already resolved center-of-mass transform. The oracle uses real `btRigidBodyConstructionInfo` with a null motion state and sets `m_startWorldTransform` directly. Constructor snapshots preserve the transform's exact zero signs. The three signed-zero traces cover static, dynamic and kinematic bodies. COM commits preserve the supplied world transform; dynamic interpolation takes the new transform, while static and kinematic interpolation retains the preceding transform.

The earlier 5,232 rows are byte-identical after changing the constructor path. The 15 appended snapshots expose signed-zero basis and origin inputs that the earlier corpus lacked. `btDefaultMotionState::getWorldTransform` computes `inverse(COM offset) * graphics transform`, including for an identity offset; that arithmetic can canonicalize negative zero. Resolving those offsets and preserving that lifecycle behavior remain separate future adapter work and are not verified by this numeric kernel.

`RigidBody` takes caller-provided shape inertia. `set_mass_properties` intentionally leaves world inertia and gravity force stale, matching native `setMassProps`. Call `update_inertia_tensor` and `set_gravity` when the caller needs them refreshed. Velocity integration and COM commit remain separate so the future solver can intervene. Fixed linear and angular factors are one. Additional damping is disabled.

No world, solver, sleep, activation, motion-state pointer, registration, reset or shim post-registration parity is claimed. The existing `FreeBody` implementation is byte-identical. This is an altered translation of vendored Bullet with local patches whose ancestry remains pending audit. The retained Bullet zlib notice is in `core/mod.rs`.

The existing strict standalone pilot registers `tests/pure_bullet/body_kernel.rs` as a module in `tests/pure_bullet.rs`. The combined suite also runs under Cargo. The native helper compiles that same strict suite and runs only the body-kernel case. The whole integration gate, hosted target checks and GPU checks remain with the root coordinator.
