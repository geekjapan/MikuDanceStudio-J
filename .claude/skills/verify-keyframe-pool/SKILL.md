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
| paste bone/morph/display key | `PasteSelectedKeyframes`, `src/window/frame_clipboard.cpp:506-769`: clear marks, `ResetBoneKeyCursor` + `RegisterBoneKey`, `ResetMorphKeyCursor` + `RegisterMorphKeyFromRecord`, `ResetDisplayKeyCursor` + `RegisterDisplayKeyFromRecord`. VMD load (`vmd_load.cpp`) and frame-range apply use the same reset-then-register shape. The display key is what the copy step builds: the IK bone's flag, selector 0 under the root name ルート, and selector 1 under bone0's name, with pairs that need no slot fixup. |
| reverse paste boneN | command 422, `PasteMirroredBoneKeyframes`, `frame_clipboard.cpp:782-862`: clear marks, open an undo slot, `ResetBoneKeyCursor`, `RegisterMirroredBoneKey` |
| paste a bone key to selected boneN | `MDS_CMD_PASTE_AT_DIFFERENT_FRAME`, `command_file_menu.cpp:1494-1593`: clear marks, open an undo slot, `ResetBoneKeyCursor`, `RegisterBoneKey(..., 1)` with `selectedBone = N` |
| register button: boneN | case 500 (`kRegisterFrameButton`), `src/window/command_frame_register.cpp:375` → `RegisterSelectedBoneKeys(model, frame, mode = PlaybackPhysicsMode)` → `RegisterBonePoseAtFrame`. Before it, the physics step leaves a frame-dependent `ikBackup` on bone0. |
| register morphN | cases 524-527 (`kRegisterMorphButton0-3`), `command_frame_register.cpp:496-543` → `RegisterMorphKeyCurrent` |
| register display key | case 438 (`kRegisterModelDisplayButton`), `command_frame_edit.cpp:1548-1561` → `RegisterDisplayKeyCurrent` |
| click boneN key | harness stand-in for a timeline click: clear marks, set `allocated = 1` on that key |
| delete selected keys | `DeleteMarkedModelKeys` |

The initial state replays `add_model.cpp:57-63` (memset 0, `ModelInitDefaults`,
so `searchCursor == 0`) and the pool tail of `pmx_load.cpp:1672-1709`. bone0
(右b) is a Move bone with a rigid body. bone1 (左b) is the IK bone and a
FixedAxis bone with axis (0.48, 0.6, 0.64) and `trans` (1, 0.25, 0). The two
names make reverse paste map each bone onto the other. There are two
selectors: the root (bone -1) and one for bone0, with link (2, 1). The bone
table has exactly `boneCount` records, as in the loaders. The root selector
has no bone name and is skipped during display paste.

The search runs once per configuration of (auto-interpolation checkbox 530,
physics checkbox 499, mode): {0,0,2}, {1,1,2}, {1,0,1}, {0,1,0}. Together they
reach every arm of the physics-pose test in `RegisterBonePoseAtFrame`. The
shim reads checkboxes from `g_checked`. The D3DX stand-in uses mds-math's
arithmetic and the RSQRT table that `run.sh` extracts from
`rust/crates/mds-math/src/estimate_table.rs`. The build uses
`-ffp-contract=off`, because Apple clang fuses `a*b+c` and MSVC x64 does not.

Two pool-full runs follow the search. Each fills the display pool (1000) or
the morph pool (20000) with its own-scan registrar, then pastes one key.

## Scope and bounds

- Verified: 2 bones, 2 morphs, 1 IK chain, 2 selectors, frames 0..2, 49
  commands, every command sequence up to depth 4 in each of the 4
  configurations (12319 states and 121814 transitions per configuration, 0
  cut; depth 5: 50023 states and 603631 transitions per configuration).
  Each pool is tracked over its first 24 records. A state whose cursor or
  links leave that window is cut and counted ("bound, not a finding").
- Layout: x64 only (`-D_M_X64 -D_WIN64 -fshort-wchar` on clang). The x86
  layout (`kBoneKeyCapacity` 300000) is not built.
- Not covered: undo/redo record restore (`UndoModelEdit`/`RedoModelEdit`),
  `MarkRedundantModelKeys`, the VMD byte parser itself, the bone pool at
  capacity, multi-key pastes, the PMD twist-axis normalize (the harness model
  is PMX), the effects of `NotifyBonePhysicsMode` on the physics engine (a
  stub here), mode 3 (it takes mode 2's branch), and the paste slot fixup for
  `modelIndex >= 0`.
- Not modeled as commands, though they call the covered registrars:
  `vsq_load.cpp`, `command_file_menu.cpp`, `dialog_select_ops.cpp`,
  `oni_skeleton_pump.cpp`, `audio_pose_helpers.cpp`, `frame_line_edit.cpp`,
  and `ui_editor_click.cpp`. Their call orders are not replayed.
- A pass covers this bounded model of the commands, not the whole app.

## Run

```sh
tools/keypool_check/run.sh        # depth 4, about 2.5 min on an M-series Mac
tools/keypool_check/run.sh 5      # deeper, about 15-20 min
```

Needs `clang++` with AddressSanitizer. Confirmed with Apple clang 21.0.0.
Exit 0 means PASS; exit 1 prints each violation once with its shortest trace.
Full ASan reports go to `${TMPDIR:-/tmp}/keypool_check/asan.log`.

`run.sh 4 --dump FILE` also writes every explored state with its operation
trace. `mds-edit` replays that dump in `cargo test`, so after a change to the
pools or the commands, regenerate it and rerun the Rust test:

```sh
tools/keypool_check/run.sh 4 --dump rust/crates/mds-edit/tests/data/keypool-depth4.txt
(cd rust && cargo test -p mds-edit)
```

## Baseline at the sync commit

At the sync commit the check PASSES: no violation at depth 4, and both
pool-full runs print `ok`. Depth 5 was not rerun after the selector guard
change. Any violation is a new problem.

Display paste skips selector bone indices outside `[0, boneCount)`. The root
selector has bone index -1; its pair stays unchanged. Valid bone selectors
still use the first matching clipboard name. The depth-4 dump is unchanged.
The search uses an exactly sized bone table and treats every ASan finding as
a failure. Restoring the old unguarded selector lookup fails at depth 1:
`1. paste display key at frame 0`, an ASan read before the bone table.
`run.sh` keeps `redzone=1024` so that read lands in a redzone.

These earlier findings are fixed. If one comes back, a change undid its fix:

- Display paste reading `bones[-1]` for the root selector. The selector
  lookup now skips negative and out-of-range bone indices before forming a
  pointer into the bone table.
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
  `DeleteMarkedModelKeys`, `ResetDisplayKeyCursor`, `RegisterMirroredBoneKey`,
  `FindMirroredBone`, `RebuildBoneInterpolation`.
- `src/window/command_file_menu.cpp` (paste to selected bone),
  `src/model/bone_sort.cpp` (selector bones),
  `include/mikudancestudio/bone_layout.hpp`, and
  `include/mikudancestudio/panel_controls.hpp` (checkbox ids).
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
git diff --stat 7b847da -- src/model/keyframe_common.hpp src/model/key_registrars.cpp src/model/model_keyframe_edit.cpp src/model/model_init.cpp include/mikudancestudio/model.hpp include/mikudancestudio/model_layout.hpp include/mikudancestudio/ported_funcs.hpp include/mikudancestudio/bone_layout.hpp include/mikudancestudio/panel_controls.hpp src/window/command_file_menu.cpp src/model/bone_sort.cpp src/window/command_frame_edit.cpp src/window/command_frame_register.cpp src/window/frame_clipboard.cpp src/window/frame_range_apply.cpp src/model/vmd_load.cpp src/model/add_model.cpp src/model/pmx_load.cpp src/model/pmd_load.cpp
```

Use the sync commit from the coverage record below as the base.

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

Sync commit: `7b847da`. The verification was last confirmed to describe the
files and functions listed under "Does my change touch the verified code?" at
this commit.

Move the sync commit forward only after you have run the check at the new
commit, read the diff of the covered files since the old sync commit, and
confirmed that the table, the initial state, and the baseline still describe
the code.
