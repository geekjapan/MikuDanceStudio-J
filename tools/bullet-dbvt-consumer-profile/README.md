# Actual Bullet DBVT consumer profile

This diagnostic observes the final `cc::Tool` in `mds-bullet-sys/build.rs`.
The normal `mds_bullet_sys` archive is built before the optional diagnostic runs.
With `MDS_BT_CONSUMER_PROBE_OUT` unset, the normal compilation receives no new flags, sources, or libraries.

The diagnostic preprocesses the actual `btDbvt.cpp`, `btDbvtBroadphase.cpp`,
`mds_bt.cpp`, and `mds_mmd.cpp` with their configured compiler arguments and environment.
It records include traces, raw preprocessor output, and extracted definitions.
`Intersect`, `Select`, `Merge`, and the virtual or template policy are classified from those definitions.
The two `.cpp` local-storage branches are classified separately. This captures the
post-header `#undef` behavior, where undefined identifiers both evaluate to zero.
Unknown or inconsistent branches fail the observation gate. No OS determines the expected profile.

The diagnostic compiles a bridge with the same configured compiler and links its
object through a separate diagnostic archive into a Rust executable. The executable
links the ordinary Bullet archive and the real `mds-crtmath` dependency. It does not
recompile `btDbvt.cpp` or use the benchmark CRT stand-ins.

The bridge reuses the existing DBVT oracle through a recorded copy. The copy renames
`main`, adds its explicit success return, and uses global `aligned_alloc` so it compiles
under the consumer's existing C++ language default. Production headers and algorithms
are unchanged. No `WIN32` definition or C++ standard flag is added.

The captures contain the finite three-insert Select witness, 51 direct AABB cases,
and the existing 2,326-operation corpus under four allocator histories. Direct AABB
cases cover finite overlap, touching, separation, both merge operand orders, signed
zero, and two quiet NaN payloads in every operand lane. NaNs stay outside tree optimization.
The existing Rust fixture tests compare topology, state, query events, and allocator
ordering against the new native captures. Rust Select and direct AABB outputs are
also saved as bytes before comparison.

`report.json` separates observation completeness, compatibility, and failures.
A measured Rust mismatch produces `observation=complete`, `compatibility=FAIL`,
`classification=compatibility-mismatch`, and a nonzero exit after capture.
An unknown branch, malformed capture, or unfinished Rust test run produces a validation gap.
Process launch failures and timeouts produce an environment failure. Neither is a pass.

The report includes source, input, capture, and archive SHA-256 hashes, native target,
compiler arguments and version, Rust version, and a compiler-environment allowlist.
The full environment is never dumped. The ordinary archive is also copied to the artifact directory.

## Reproduction

From the repository root on an Apple Silicon Mac:

```sh
CXX=clang++ python3 tools/bullet-dbvt-consumer-profile/check.py \
  --out-dir /tmp/bullet-dbvt-consumer-profile --target aarch64-apple-darwin
python3 -m unittest discover -s tools/bullet-dbvt-consumer-profile -v
```

Cargo subprocesses use Rust 1.95.0 from the repository's `rust/` directory.
The focused standalone manifest builds `mds-bullet-sys` and the diagnostic executable
with the same final native build configuration. It avoids a full application build.

`.github/workflows/bullet-dbvt-consumer-profile.yml` measures Windows x64 with
VS2022 MSVC, Apple Silicon macOS, Linux x64, and Linux ARM64. Matrix jobs do not fail
fast, and artifacts upload even when compatibility fails. Workflow configuration
alone does not establish any host result. Default Windows compatibility may fail
because Rust currently selects SSE semantics by target OS while the actual consumer
may select generic semantics. This diagnostic reports that discrepancy without changing product behavior.
