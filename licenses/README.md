# Licenses

Written by `tools/package/licenses.py`; every package carries this folder.

| Path | What |
|---|---|
| `LICENSE`, `LICENSE-MIT`, `FORK.md` | The repository's files, unchanged. `FORK.md` says which paths are MIT and which are license pending. |
| `bullet-2.75/` | Bullet 2.75 (`recipes/bullet275`), linked into mds-app through mds-bullet-sys. |
| `vkd3d/` | vkd3d-shader 2.1, the library beside mds-app: its LICENSE, COPYING, AUTHORS, the applied patches, and where its source is (`SOURCE.md`). |
| `mingw-runtime/` | Windows package: the MinGW-w64 runtime DLLs beside the vkd3d-shader DLL (`mingw-copyright.sh`). |
| `mds-crtmath/` | The AOCL-LibM notice of rust/crates/mds-crtmath. |
| `rust/` | The Rust standard library of the pinned toolchain, linked into mds-app. |
| `crates.tsv`, `THIRD-PARTY.txt` | The 254 third-party crates and their license texts. |
| `fetched/` | Texts of crates that publish none, from their repositories. |
