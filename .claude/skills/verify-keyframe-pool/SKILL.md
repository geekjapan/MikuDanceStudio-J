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
| paste bone/morph/display key | `PasteSelectedKeyframes`, `src/window/frame_clipboard.cpp:506-769`: clear marks, `ResetBoneKeyCursor` + `RegisterBoneKey`, `ResetMorphKeyCursor` + `RegisterMorphKeyFromRecord`, `ResetDisplayKeyCursor` + `RegisterDisplayKeyFromRecord`. VMD load (`vmd_load.cpp`) and frame-range apply use the same reset-then-register shape. |
| register button: boneN | case 500 (`kRegisterFrameButton`), `src/window/command_frame_register.cpp:375` → `RegisterSelectedBoneKeys` → `RegisterBonePoseAtFrame` |
| register morphN | cases 524-527 (`kRegisterMorphButton0-3`), `command_frame_register.cpp:496-543` → `RegisterMorphKeyCurrent` |
| register display key | case 438 (`kRegisterModelDisplayButton`), `command_frame_edit.cpp:1548-1561` → `RegisterDisplayKeyCurrent` |
| click boneN key | harness stand-in for a timeline click: clear marks, set `allocated = 1` on that key |
| delete selected keys | `DeleteMarkedModelKeys` |

The initial state replays `add_model.cpp:57-63` (memset 0, `ModelInitDefaults`,
so `searchCursor == 0`) and the pool tail of `pmx_load.cpp:1672-1709`.

Two pool-full runs follow the search. Each fills the display pool (1000) or
the morph pool (20000) with its own-scan registrar, then pastes one key.

## Scope and bounds

- Verified: 2 bones, 2 morphs, 1 IK chain, 1 bone-order entry, frames 0..2,
  every command sequence up to depth 4 (10989 states, 83509 transitions;
  depth 5: 43703 states).
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
tools/keypool_check/run.sh        # depth 4, about 20 s on an M-series Mac
tools/keypool_check/run.sh 5      # deeper, about 75 s
```

Needs `clang++` with AddressSanitizer. Confirmed with Apple clang 21.0.0.
Exit 0 means PASS; exit 1 prints each violation once with its shortest trace.
Full ASan reports go to `${TMPDIR:-/tmp}/keypool_check/asan.log`.

## Baseline at the sync commit

At the sync commit the check PASSES: no violation at depth 4 or 5, and both
pool-full runs print `ok`. Any violation is a new problem.

These earlier findings are fixed. If one comes back, a change undid its fix:

- A bone head record taken as a free record (`head record moved off frame 0`,
  `links into the head record of track N`). The shared `searchCursor` can hold
  another pool's position. `kfa::AllocateFromCursor`
  (`src/model/keyframe_common.hpp`) never starts below the first non-head
  record. All cursor-based registrars and `RegisterBonePoseAtFrame` use it.
- A read one past a full pool. `AllocateFromCursor` stops at capacity before
  it reads.
- An invalid access in `RegisterMorphKeyFromRecord`'s name scan. The scan now
  steps one `MorphRecord` at a time (`++mrec`).

## Does my change touch the verified code?

Run the check if the diff touches any of these:

- `src/model/keyframe_common.hpp`: `AllocateFromCursor`.
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
- The call orders in the table above (`frame_clipboard.cpp` paste,
  `command_frame_register.cpp` cases 500/524-527, `command_frame_edit.cpp`
  case 438), and the pool
  setup in `add_model.cpp` / `pmx_load.cpp` / `pmd_load.cpp`.

List what changed in the covered files since the sync commit:

```sh
git diff --stat 699ce59 -- src/model/keyframe_common.hpp src/model/key_registrars.cpp src/model/model_keyframe_edit.cpp src/model/model_init.cpp include/mikudancestudio/model.hpp include/mikudancestudio/model_layout.hpp src/window/command_frame_edit.cpp src/window/command_frame_register.cpp src/window/frame_clipboard.cpp src/window/frame_range_apply.cpp src/model/vmd_load.cpp src/model/add_model.cpp src/model/pmx_load.cpp
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

Sync commit: `699ce59`. The verification was last confirmed to describe the
files and functions listed under "Does my change touch the verified code?" at
this commit.

Move the sync commit forward only after you have run the check at the new
commit, read the diff of the covered files since the old sync commit, and
confirmed that the table, the initial state, and the baseline still describe
the code.
