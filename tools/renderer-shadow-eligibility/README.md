# Conditional shadow call eligibility

This tooling compares source-extracted Windows native call eligibility with calls observed immediately before the Rust self-shadow `draw_indexed` endpoint. It does not execute native PMM loading, renderer resources, effect passes, MME, or GPU submission. Geometry equivalence and the receiver, primitive, UV, depth, filter and MSAA causes of the existing pixel failures remain unproven.

The native wrapper executes the original model and accessory predicates against typed SDK/layout records. All candidate materials, including rejected materials, appear in its trace. Accessory endpoint range and cull are `NOT_APPLICABLE`. Rust range and order come from the actual endpoint hook. Its cull value is bound to the original shadow pipeline's default primitive state, whose cull mode is None.

The actual scene capture records the canonical helper's 30 successful physics steps, PMM slot/path mapping, posed model alpha and edge alpha, all model and accessory candidates before selection, sample shifts and actual draws. Native-specific fields remain labelled projections of fixed fixture bytes through original assignments. The capture must reconcile every used projection before native execution. Native and Rust sidedness have separate meanings.

The comparison checks candidate input domain before eligibility, then order and range/cull. Its first difference is within this comparison contract. It is not an earliest temporal divergence in the application. A witnessed difference does not authorize renderer changes or establish golden parity.

## Read-only verification

```sh
python3 -B tools/renderer-shadow-eligibility/run.py --out /absolute/existing/evidence
python3 -B -O tools/renderer-shadow-eligibility/run.py --out /absolute/existing/evidence
```

Verification reads retained source, input, binary, command receipts, raw stdout, images and metadata. It runs no binaries and writes no files. Linux capture without native evidence reports `CAPTURE_VALID_NATIVE_EXECUTION_UNPROVEN`. An incomplete native execution fails verification. Missing or malformed evidence cannot become a policy difference.

For evidence transported from another host, provide its TAR to validate and recover the retained Unix modes in memory:

```sh
python3 -B tools/renderer-shadow-eligibility/run.py --archive /absolute/complete.tar --out /absolute/extracted/evidence
```

## Explicit writers and execution

`--prepare` writes a fixture-only preflight into a fresh external directory. That packet is not an actual scene capture or comparison.

`--run capture --out DIR --build-root DIR` runs only in hosted Linux. It archives the fixed original Git source, creates generated copies, builds retained canonical test binaries, and runs control and observed suites once each. The workflow holds the existing GPU lock for both sequential suites. Both variants include actual adapter telemetry. The observed variant also includes the scene and endpoint hooks. All 14 outcomes, the same 11 passes and 3 failures, all 11 final RGBA images, diff images, masks and exact computed metrics must agree.

`--run native --archive CAPTURE.tar --out FRESH_DIR` runs only in hosted Windows with an actual MSVC x64 environment. It safely extracts the Linux capture, verifies it, compiles the SDK-only native console and a narrow source-semantic mutant, and executes canonical and separate directed inputs. The mutant must compile, exit normally, emit a valid trace and differ semantically. Compiler version, include and link diagnostics, selected nonsecret environment, timing, return codes, source identities, input bytes and original/retained binary hashes remain in the evidence.

`--unpack --archive TAR --out FRESH_DIR` safely extracts and then verifies without executing binaries. `--bundle FRESH_TAR` explicitly writes a mode-preserving TAR after verification. These options are writers; omit them for read-only replay.

The workflow initially triggers only on pushes to `w4-renderer-shadow-eligibility-probe`. Linux capture and Windows native execution are separate jobs using the same captured source and inputs. Actual hosted compilation and execution remain unrun until that workflow completes and its artifacts pass independent audit.

## Focused checks

```sh
python3 -B tools/renderer-shadow-eligibility/test_run.py
python3 -B -O tools/renderer-shadow-eligibility/test_run.py
```

The small historical Cargo terminal and canonical stdout fixtures test parsers only. They are not execution evidence for this diagnostic. Synthetic capture and one-pixel PNG fixtures likewise exercise rejection behavior, not renderer behavior.
