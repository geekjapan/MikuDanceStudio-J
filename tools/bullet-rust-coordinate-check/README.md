# Check patched Bullet joint coordinates

Run from the repository root.

```sh
python3 tools/bullet-rust-coordinate-check/check.py --out-dir /tmp/bullet-coordinate-check
```

The driver builds the vendored `btGeneric6DofConstraint.cpp` with strict floating-point flags and the existing deterministic float CRT adapter. Its subclass calls real `getInfo1` and reads the protected calculated fields. It captures all four input transforms and compares 51 output words from Rust against native output. The golden fixture has 2,120 cases. Both calculated world frames and every `JointCoordinates` field compare bit for bit.

Case 0 is identity. Cases 1 through 71 exercise values adjacent to, equal to, and beyond both Euler gimbal thresholds, signed zero, and axis normalization at three scales. Cases 72 through 2119 use a fixed xorshift seed with rotated body and local frames. Every third random case perturbs bases to exercise inverse roundoff independently of orthogonality. The test asserts all three Euler branches occur. All matrices and expected values come from the actual native run.

Use `--cases 25000` for a larger deterministic native comparison. Counts above the golden count compare Rust directly against the new capture. They do not replace or compare the golden fixture. `--record` replaces the golden fixture only at the default count.

The output directory preserves the native TSV, native executable, Rust test executable, and CRT libraries. Native stderr reports the host's long-double mantissa and size. Capture stdout and stderr to retain a receipt. A differing result reports the case, output word, both bit patterns, and all input words. The live Rust comparison runs before the golden fixture comparison so a host precision mismatch retains its exact input.

This tool needs Clang, Python 3, and Rust 1.95.0. It does not build the full workspace or use a GPU. It leaves the production backend native. To include the new unit in the crate, root integration must declare `core::joint_coordinates`, `core::joint_rows`, and the dedicated test module. This unit deliberately does not edit those existing files.

The translated algorithm retains the native Zlib notice. Local patch ancestry remains pending audit. Apple Silicon native comparison alone does not verify Linux x64 extended `long double` or other supported hosts.
