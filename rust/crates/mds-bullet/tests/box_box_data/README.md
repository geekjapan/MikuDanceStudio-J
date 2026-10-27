# Native box-box fixture

These expected rows came from the unmodified vendored Bullet 2.75 detector and
owned collision algorithm, captured on Apple Silicon macOS with Clang and Rust
1.95.0. The observed detector produced byte-identical stdout. Rust output was
never used as fixture data.

`tools/bullet-rust-box-box-check/check.py` recaptures the full deterministic corpus
and checks these selected inputs, native rows, and coverage without a record mode.
Selection retains complete `N`-delimited owned scenarios. The first six retain
scale sweeps, touching, repeated contacts, impulses, sliding, separation, re-entry,
and explicit refresh. A deterministic greedy selection adds the earliest groups
covering the remaining selected SAT codes, polygon sizes, and candidate counts.
`coverage.txt` identifies zero-based full-corpus group numbers and observed native
coverage. Candidate counts above four exercise angular culling and output order.

The shared pure test compares every candidate bit and every initialized manifold
field through production `PairManifold::new/process`. The full native comparator
also characterizes borrowed manifolds with the existing private add/refresh logic.
No production borrowed-manifold API is added.

The selected fixture has 177 operations and 382 ordered candidates.

Full native capture SHA-256 values at selection time.

```text
ff21d525becf3d57f4a695ed8c6df3b13982beb8463e674c0a7ac7dfe9bb2ae3  inputs.tsv
7c102319fb2a39b26134dad94c5e8572c43b8cb94f5766d0da6c6c34ab6bf45b  native.tsv
69f1bdaab9d86945fb213f3fd8f98b03e1d83777eb9e45b4332f8a201b90d9da  observation.diff
7f2ad65f97fcb2ef6274ff9470713c900fde54e9e399ba6dd73e61de5b83a85a  detector.sha256
```

Vendored detector SHA-256.

```text
67c357bd7008dd6a92122c46e55cd6c5d2590de5eb87df9451e19d04e8981e60
```
