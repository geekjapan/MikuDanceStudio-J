# PMM 0001 fixtures

There are no 0001 files in the repository, so `gen_pmm1.py` writes them in
the order `src/io/pmm_load_v1.cpp` reads them. A 0001 model block holds a
20-byte name and a path, not the bone, morph and IK tables, so every scene
names a PMD in this directory (`chain8.pmd` is the model of
`tests/fixtures/rust`, `rig3.pmd` has an IK chain and three morphs).

| File | What it holds | Compared with the oracle |
|---|---|---|
| `v1_rig.pmm` | one model with bone, morph and display keys, a camera with a parent, a light key, the whole tail | yes |
| `v1_scene.pmm` | camera and light keys, two accessories with keys, wave, AVI and picture records, no tail | yes |
| `v1_multi.pmm` | models in file order slots 5, 1, 3, an accessory, a tail that stops at a gate byte of 0 | yes |
| `v1_noparent.pmm` | a tail whose camera parent is -1 | no: the C++ skips the parent key list there, the portable reader does not |
| `v1_edge.pmm` | a sparse record with frame 0, six group flags for a PMD with four groups | no: Rust tests only |

`expected/*.dump` is the output of `tools/pmm1_check` on the first three. The
tool reads each scene with the portable C++ reader of `origin/next`
(`ReadPmmSceneDocument`, built from commit `9ef4817`), applies the rules of
`pmm_load_v1.cpp` on main that the portable reader does not (see the header of
`tools/pmm1_check/dump.cpp`), and prints one line per record. The test
`rust/crates/mds-formats/tests/pmm1.rs` prints the same text from the `Pmm`
that `Pmm::read_with` returns and requires the lines to be equal. A scene
whose dump is missing prints `SKIP`.

| File | sha256 |
|---|---|
| `chain8.pmd` | `3fd0f2e5b54bb3387a0e106b697ff3e27f8aed3685e9705fb18a56f63ac4bd58` |
| `rig3.pmd` | `c18610862b869afa535a1961fd920a6eca73794876063d154c123080f6f128d1` |
| `v1_rig.pmm` | `47d0b896134bf53052a65d165aaa9692787c88a17fb514bbc5e8a43a444be7e2` |
| `v1_scene.pmm` | `b9d41727aeff402aea0dffd21d1b564901b319f7ccc5c467b7c4fd10a6dea8b8` |
| `v1_multi.pmm` | `625716856e63e90bc1c74159af26cd376e693ff366850e7b2e50bb86f03e5c79` |
| `v1_noparent.pmm` | `72e7d9a5b6196aa8e00e56f6e8a991a63320f207dd77967eea9ecf33eb631b32` |
| `v1_edge.pmm` | `bad49a364f154c82816ee90980be12132aa883f4fb4767403bcc7f25d8485f73` |
| `expected/v1_rig.dump` | `d28f29e84b7a28baef1358863e972aa980782626b192b79c30165c4e1070490a` |
| `expected/v1_scene.dump` | `871c64737242d896aaeb99eb4818e73639be1d231b092773db8bf03282d0eb21` |
| `expected/v1_multi.dump` | `dd4b4342528463f4a5f10c72f42d11b330f4ef561c32d09c5fd407a4c5505289` |

## Regenerate

From the repository root, on macOS with Apple clang and cmake:

```sh
python3 -I tests/fixtures/rust/pmm1/gen_pmm1.py --write   # the PMDs and scenes
tools/pmm1_check/run.sh                                   # expected/*.dump
cd tests/fixtures/rust/pmm1 && shasum -a 256 *.pmd *.pmm expected/*.dump
```

`gen_pmm1.py --check` compares the generated files with the committed ones.
`run.sh` builds the portable reader through `tools/oracle/build_l1.sh`, so
the commit it reads is the one in `PMM1_NEXT` (default `9ef4817`).

## What the oracle does not cover

- The portable reader keeps no names, selectors or group counts, which the
  PMD supplies. `dump.cpp` takes the bone, morph and IK counts from the PMD
  bytes itself, so the names and selector bones the Rust reader derives from
  `rig3.pmd` and `chain8.pmd` are asserted by `pmm1.rs` against
  `src/model/pmd_load.cpp` and `model_init.cpp` read by hand.
- `dump.cpp` repeats the main-branch rules (flags tested as `b == 1`, the
  fresh-application defaults, `RefreshSelfShadowPanel` with `FindKeyAtOrAfter`). A
  wrong rule there would agree with the same wrong rule in the Rust reader;
  the rules were read from `pmm_load_v1.cpp` and `pmm_io_common.hpp`.
- `relink` (the chain check of the load tail) is the identity on every oracle
  fixture, whose chains are consistent. Only
  `a_broken_bone_chain_ends_at_the_last_consistent_key` runs it, against
  the reading of the C++.
- `dump.cpp` rebuilds the accessory opacity byte from the portable reader's
  float with `lround(opacity * 100)`. It round-trips for the bytes the
  fixtures use; a fixture byte that does not survive that conversion would
  show as a mismatch that is not a reader bug.
- The bytes of the 0002 file the C++ saves from a loaded 0001 are compared
  later on Windows (load a 0001, save), not here.
