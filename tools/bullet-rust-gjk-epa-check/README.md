# Internal GJK/EPA parity

`core/gjk_epa.rs` translates the vendored internal GJK, EPA, and penetration adapter for sphere, box, and Y capsule shapes. It preserves identity scaling, default margins, raw dimensions, native float grouping, explicit double reciprocals, and local normals with world witnesses. The existing Voronoi simplex is not used by this kernel. The native adapter oracle supplies that real simplex only because its signature requires it.

The public query functions are `distance`, `penetration`, and `calc_pen_depth`. `QueryResult::Failure` contains the native result status without unwritten normal or distance fields. `PenDepth` distinguishes penetration, successful distance fallback, and both queries failing. The last variant represents the native adapter leaving its output references untouched. These functions require convex shapes, as do their native counterparts.

Run the complete native comparison from the repository root.

```sh
python3 tools/bullet-rust-gjk-epa-check/check.py --out-dir /tmp/mds-gjk-epa
```

The checker compiles and calls the real `btGjkEpaSolver2::Distance`, `Penetration`, and `btGjkEpaPenetrationDepthSolver::calcPenDepth`. It never duplicates their algorithm in the oracle. It compares all 6,810 independent scenarios and the frozen 1,801-scenario prefix. Every row contains all four queries, including penetration with each margin setting. A separate nine-row fixture preserves directed raw nonfinite dimensions. Values, signed zeros, and NaNs are compared as raw words. There is no NaN normalization.

The corpus covers six ordered mixed pairs and three same-shape pairs. It includes separation, exact axis touching and neighboring float values, shallow and deep penetration, containment, concentric shapes, rotated boxes and capsules, capsule cap ends, zero-height capsules, small and extreme dimensions, negative dimensions, and common large translations. Random cases use a fixed seed and rotations about all three axes. Compact replay runs in the existing four-target pure CI job. Native recapture is the fifteenth group in the Linux x64 job. The dedicated
`bullet-gjk-epa-host-profiles.yml` workflow captures original native, observed
native, and full Rust output on all four supported hosts. Windows uses the
reviewed MSVC CMake compile flags from the joint host probe. Unknown profiles
fail after the complete same-host replay and evidence capture. A captured profile
requires review before promotion.

The checker writes unmodified and observed stdout, source-copy observation patches, branch counts, compiler commands, compiler and host provenance, and source hashes. Observation must leave stdout identical. The nine required mutations compile in isolation and must fail compact replay. They remove penetration, remove Distance fallback, reject non-Valid EPA results, change face ties, remove margins, change EPA accuracy, introduce double support normalization, rotate local normals, or change simplex reduction.

Observed native returns include EPA AccuracyReached, InvalidHull, and FallBack. Internal face stock exhaustion, nonconvex faces, degenerate faces, face ties, all GJK projection ranks, reduction, EncloseOrigin ranks 2 through 4, successful Distance fallback, and untouched adapter outputs are observed. The 6,810-case capture records 97 NonConvex and 302 Degenerated status assignment hits in their respective native branches. The JSON counts are authoritative for each capture.

The following branches remain explicit coverage gaps.

- GJK iteration exhaustion is implemented but not reached by this corpus.
- EPA OutOfVertices is implemented but not returned by this corpus. Face stock exhaustion is reached first in the captured resource cases.
- EncloseOrigin rank 1 has source code but is excluded by the EPA caller's `rank > 1` condition. Recursion only increases rank.
- EPA Valid cannot escape this implementation's evaluation loop. The 64-vertex bound stops the loop before the 255-iteration bound unless another status has already terminated it.
- EPA OutOfFaces, Degenerated, and NonConvex are internal assignments. A failed expansion overwrites them with InvalidHull, while an unsuccessful initial hull reaches FallBack. They are not claimed as externally observed result statuses.
- EPA Touching has no assignment in the vendored source. Failed is initialized but both evaluation return paths replace it. The public EPA_Failed branch is retained for contract fidelity and is not claimed as reached.

Initial stock index reversal and f32 division replacing a double reciprocal followed by f32 rounding survived exploratory mutations. Reversing unused stock indices preserves logical list order. Correctly rounded reciprocal operations agree on the tested inputs. Those exploratory logs remain in the local evidence store; neither is reported as a rejected mutation.

This unit does not enable mixed-pair dispatch, change the outer pair detector, connect the public World, or complete the Bullet migration. The native comparison on one host does not prove the four CI targets passed. No GPU test is needed for this kernel.


`gjk-epa-profiles.json` fixes each fixture hash and enumerates every permitted
case and field difference. The Linux x64 profile uses artifact 12689482840 from
run 40399749981, captured at commit `012fe478b852cb21de7c0c4dd134529c2331d348`.
Its checked source tree is equivalent to `0a3f0b5880cce4008c041c2fa954f916a9c98b74`.
Its full native output equals its observed output. Compared with the accepted
ARM capture, 864 arithmetic NaN sign words differ in 55 compact cases, and 12
words differ in raw cases 6802 and 6805. All other words remain exact. The original
ARM fixtures remain unchanged. Finite values, signed zero, infinities, schemas,
row IDs, counts, and NaN payloads have no relaxed comparison.

Both compact and raw Rust tests select the matching host fixture. For the full
same-host replay, the helper supplies `MDS_GJK_EPA_INPUTS` and
`MDS_GJK_EPA_NATIVE`, plus `MDS_GJK_EPA_RAW_INPUTS` and `MDS_GJK_EPA_RAW_NATIVE`.
The raw test uses the final nine captured rows. An altered signed zero in the raw
capture must fail that test, proving that the override reaches the comparison.
The helper saves `rust.tsv`, `raw-rust.tsv`, the negative control log, and the
host-profile result alongside the native captures.

Run the profile and capture negative controls with:

```sh
python3 -m unittest discover -s tools/bullet-rust-gjk-epa-check -v
```

Windows x64 and Linux ARM64 native profiles remain unreviewed until their real
captures run. A configured workflow or cross-host native agreement does not
establish their same-host Rust replay.
