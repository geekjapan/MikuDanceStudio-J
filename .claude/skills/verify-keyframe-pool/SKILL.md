---
name: verify-keyframe-pool
description: Check that a change keeps the model keyframe pools (bone/morph/display key tracks in key_registrars.cpp and model_keyframe_edit.cpp) well-formed. Use when you touch key registration, paste, VMD key insertion, key deletion, searchCursor, the Reset*KeyCursor functions, BoneKey/MorphKey/DisplayKey, or their pool capacities.
---

# Verify the keyframe pools

## What is checked

Property: after any sequence of keyframe commands, every key track is a
well-formed chain. Each track starts at its own head record (bone `i` and
morph `i` at index `i`, display at index 0). Heads stay at frame 0. `next`
and `previous` agree. Frames strictly increase. Chains end. No record sits on
two tracks or is another track's head. Every non-head record with
`frame != 0` is on a track. No pool access goes out of bounds.

Harm if it breaks: keys move to the wrong bone or vanish, the corrupted
motion is saved into .vmd/.pmm, a cyclic chain hangs playback, or a pool
access reads or writes past the heap allocation.

How: `tools/keypool_check/keypool_check.cpp` links the real, unmodified
sources and does a breadth-first search over every command sequence up to
the depth. It removes duplicate states and checks the property after each
command, so each reported trace is a shortest one. AddressSanitizer catches
out-of-bounds accesses. Each command replays the call order of the real UI
handler:

| Harness command | Real code it replays |
|---|---|
| paste bone/morph/display key | `Cmd400_FramePaste`, `src/window/command_frame_edit.cpp:2001-2179`: clear marks, `ResetBoneKeyCursor` + `RegisterBoneKey`, `ResetMorphKeyCursor` + `RegisterMorphKeyFromRecord`, `ResetDisplayKeyCursor` + `RegisterDisplayKeyFromRecord`. VMD load (`vmd_load.cpp`) and frame-range apply use the same reset-then-register shape. |
| register button: boneN | case 500, `src/window/command_frame_register.cpp:387` → `RegisterSelectedBoneKeys` → `RegisterBonePoseAtFrame` |
| register morphN | cases 524-527, `command_frame_register.cpp:503-540` → `RegisterMorphKeyCurrent` |
| register display key | case 438, `command_frame_edit.cpp:2988-2994` → `RegisterDisplayKeyCurrent` |
| click boneN key | harness stand-in for a timeline click: clear marks, set `allocated = 1` on that key |
| delete selected keys | `DeleteMarkedModelKeys` |

The initial state replays `add_model.cpp:58-64` (memset 0, `ModelInitDefaults`,
so `searchCursor == 0`) and the pool tail of `pmx_load.cpp:1725-1767`.

Two pool-full runs follow the search. Each fills the display pool (1000) or
the morph pool (20000) with its own-scan registrar, then pastes one key.

## Scope and bounds

- Verified: 2 bones, 2 morphs, 1 IK chain, 1 bone-order entry, frames 0..2,
  every command sequence up to depth 4 (8211 states, 61235 transitions).
  Each pool is tracked over its first 24 records. A state whose cursor or
  links leave that window is cut and counted ("bound, not a finding").
- Layout: x64 only (`-D_M_X64 -D_WIN64 -fshort-wchar` on clang). The x86
  layout (`kBoneKeyCapacity` 300000) is not built.
- Not covered: undo/redo record restore (`UndoModelEdit`/`RedoModelEdit`),
  `RegisterMirroredBoneKey`, `RegisterBoneKey` with `useSelected = 1`, the
  fixed-axis twist branch (needs D3DX), bones with rigid bodies, auto
  interpolation (the shim reads every checkbox as unchecked),
  `MarkRedundantModelKeys`, the VMD byte parser itself, the bone pool at
  capacity, and multi-key pastes.
- A pass covers this bounded model of the commands, not the whole app.

## Run

```sh
tools/keypool_check/run.sh        # depth 4, about 50 s on an M-series Mac
tools/keypool_check/run.sh 5      # deeper, about 5 min
```

Needs `clang++` with AddressSanitizer. Confirmed with Apple clang 21.0.0.
Exit 0 means PASS; exit 1 prints each violation once with its shortest trace.
Full ASan reports go to `${TMPDIR:-/tmp}/keypool_check/asan.log`.

## Baseline at the sync commit (known findings, not yet fixed)

At the sync commit the check FAILS with exactly these six violations. A run
that shows only these is "back to baseline". A new kind is a new problem.

1. `bone track 0: head record moved off frame 0`, from step 1 `register button: bone0 at frame 1`.
   A freshly loaded model has `searchCursor == 0`. `RegisterBonePoseAtFrame`
   (`model_keyframe_edit.cpp:319`) scans for a free record from the cursor
   without a reset. Record 0, bone 0's head, has frame 0 and so looks free.
   The new key overwrites bone 0's head, and the frame-0 key is lost.
2. `bone track 0: links into the head record of track 1`, from `paste ...` then `register button: bone0 at frame 1`.
   Every paste ends with `ResetDisplayKeyCursor`, which leaves the shared
   `searchCursor` at the first free display record (1). The next register
   button press takes record 1, bone 1's head, as its free record.
3. `bone track 1: head record moved off frame 0`, from `paste ...` then `register button: bone1 at frame 1`. Same cause as 2.
4. `invalid memory access at key_registrars.cpp:634 in RegisterMorphKeyFromRecord`, from `paste morph1 key at frame 0`.
   `mrec` is a `const MorphRecord*`, so `mrec += 136` advances 136 records,
   not one record of 136 bytes. The loaders allocate exactly `morphCount`
   records (`pmx_load.cpp:969`, `pmd_load.cpp:460`). A paste or VMD morph key
   for any morph after morph 0 is matched against records 136, 272, and so on.
   With fewer than 137 morphs, the first step already reads past the table.
   With more, the key can match the wrong morph or none.
5. `display pool full (1000)`: invalid access at `key_registrars.cpp:791`.
   `ResetDisplayKeyCursor` can stop at 1000. `RegisterDisplayKeyFromRecord`
   then reads `keys[searchCursor]` before its bound check.
6. `morph pool full (20000)`: invalid access at `key_registrars.cpp:652`.
   This is the same shape in `RegisterMorphKeyFromRecord`. `RegisterBoneKey`
   has the same shape too, but the bone pool is not run at capacity.

When a fix removes one of these, delete it from this list in the same change.

## Does my change touch the verified code?

Run the check if the diff touches any of these:

- `src/model/key_registrars.cpp`: `ResetBoneKeyCursor`, `ResetMorphKeyCursor`,
  `RegisterBoneKey`, `RegisterMorphKeyFromRecord`, `RegisterMorphKeyCurrent`,
  `RegisterDisplayKeyFromRecord`, `RegisterDisplayKeyCurrent`.
- `src/model/model_keyframe_edit.cpp`: `AppendBoneKeyToUndo`,
  `RegisterBonePoseAtFrame`, `RegisterSelectedBoneKeys`,
  `DeleteMarkedModelKeys`, `ResetDisplayKeyCursor`.
- `src/model/model_init.cpp`: `ModelInitDefaults`.
- `include/mikudancestudio/model.hpp` (`BoneKey`, `MorphKey`, `DisplayKey`,
  capacities) and `include/mikudancestudio/model_layout.hpp` (`searchCursor`).
- Any new writer of `searchCursor`, or a new caller that registers keys:
  `git grep -n "searchCursor\|Register.*Key" src`.
- The call orders in the table above (`command_frame_edit.cpp` paste,
  `command_frame_register.cpp` cases 500/524-527, case 438), and the pool
  setup in `add_model.cpp` / `pmx_load.cpp` / `pmd_load.cpp`.

List what changed in the covered files since the sync commit:

```sh
git diff --stat d7425a5 -- src/model/key_registrars.cpp src/model/model_keyframe_edit.cpp src/model/model_init.cpp include/mikudancestudio/model.hpp include/mikudancestudio/model_layout.hpp src/window/command_frame_edit.cpp src/window/command_frame_register.cpp src/model/add_model.cpp src/model/pmx_load.cpp
```

## Real bug or modeling error?

When a violation appears, open the trace and replay it by hand in the real
functions.

- Real bug: each step maps to the handler in the table, and the real call
  order produces the broken link. Report it in the code's words, for example:
  "after paste, the register button takes bone 1's head record". Do not weaken
  `CheckPool` or remove commands to make it pass, and do not change product
  code unless asked.
- Modeling error: the harness drifted from the code. Typical causes: a
  handler's call order changed but the harness `Apply`/`Paste` did not, a
  struct field was renamed, or the initial state no longer matches the
  loaders. Fix the harness, then rerun.
- `(bound, not a finding)`: the state left the 24-record window. Raise
  `kWindow` if this happens on a short trace.
- Link errors such as `Undefined symbols` mean the real `ported_funcs.hpp`
  signatures drifted from `tools/keypool_check/shim/mikudancestudio/ported_funcs.hpp`.
  Copy the new signature into the shim.
- A crash with no trace (SEGV) usually means an index escaped far out of
  bounds. Rerun with a smaller depth to find the step.

## When a change is intended

If you change a handler's call order, add a key command, or change pool
setup, update `Apply`/`Paste`/`BuildModel` in `keypool_check.cpp` and the
table above in the same change. If the property itself changes (for example,
heads no longer pinned at frame 0), edit `CheckPool` and the property text
here together.

## Coverage record

Sync commit: `d7425a5`. The verification was last confirmed to describe the
files and functions listed under "Does my change touch the verified code?" at
this commit.

Move the sync commit forward only after you have run the check at the new
commit, read the diff of the covered files since the old sync commit, and
confirmed that the table, the initial state, and the baseline still describe
the code.
