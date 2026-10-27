# Native simplex snapshots

These snapshots are selected from the existing frozen native Bullet captures in
`tools/bullet-rust-simplex-check/fixtures`, never from Rust output. The Python
comparator verifies each selection against a fresh native capture.

The finite selection keeps all 286 structured scenarios and their 4,852 operations
as one contiguous prefix. This preserves native cache history, including reset
retention and per-field initialization masks. It covers every segment, triangle,
and tetrahedron usage mask, threshold ULP neighbors, winding, permutations, ties,
duplicates, independent witnesses, signed zero, degeneracy, cancellation,
subnormals, finite overflow, and cached queries. The exceptional selection keeps
all 13 scenarios and 172 operations, including its singleton cache seed.

`provenance.json` records selected and full input/output SHA-256 hashes, selected
labels, operation counts, and native coverage. The full native comparator retains
all 2,286 finite scenarios, 29,940 operations, and growth-after-reduction traces.
The pure driver also checks fifth-vertex rejection and retained-cache membership.

NaNs compare by classification only. Other floats compare their exact bits,
including signed zero and infinities. Underscores preserve native undefined-field
masks. The seeded corpus does not claim parity for an uninitialized first
tetrahedron query. GJK, EPA, and the public World remain outside this unit.
