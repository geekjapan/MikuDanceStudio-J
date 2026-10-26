# Physics scenarios (`--mds-script`)

These scripts drive playback and physics on `../swing600.pmm` through the C++
application's own handlers and frame loop, and record every Bullet rigid body
after each frame. They are the oracle for playback with physics in the Rust
application (`mds-app`). The runner, the script language, and the regenerating
steps are those of `../script/README.md`; this file adds the commands and
describes the scripts.

## Commands

| Command | What the runner does | Notes |
|---|---|---|
| `settle <n>` | Sets the number of frames the runner runs after every later step (default 2, at 1/30 s and 33 ms each). | Every script here starts with `settle 0`, so only `pump` runs frames. |
| `pump <n> <ms>` | n passes of the loop body of `src/main/winmain.cpp`: drain the message queue, advance the clock `TimeNowLow/High` by ms milliseconds, set `DeltaTime` to `(float)ms * 0.001f`, call `FrameDriver`. | The clock is the integer-millisecond `timeGetTime` reading of the real loop. The frame-rate limit's `Sleep` is not modelled. |
| `trace <name>` | Writes `<out-dir>\<name>`: the header `mds-trace 1 L2`, block 0 at once, then block k after the k-th pump pass of the script. | One trace per script. Its manifest line comes last and carries the line of the `trace` command. |
| `frame <n>` | Edit 417 and Enter (the seek). | The command of `../script/`. |
| `play <start> <end>` | Sets the play-range edits 409 and 410 (`SetWindowTextA`, as typing does), then clicks button 408. | `ApplyPlaybackRangeEdits` in `src/window/command_frame_edit.cpp`. Fails when playback is running. |
| `stop` | Clicks button 408 while playback runs. | `StopPlayback`. Fails when playback is not running. |
| `loop on` / `loop off` | Checks or unchecks box 411 and sends its click, only when the state differs. | `PlaybackLoopEnabled`. |
| `step forward` / `step back` | Buttons 419 / 418. | `StepFrame` in `src/window/ui_frame_step.cpp`. |
| `physics mode <0-3>` | Menu 272 (off), 265 (always), 269 (on/off), 270 (trace). | `PlaybackPhysicsMode`; sets the physics reset flag except for 272. |
| `physics playback toggle` | Menu 271. | `playbackAlwaysOnOffMode`: while playing, the mode is 2 (on/off) whatever the menu says. |
| `physics reset` | Menu 268. | Sets the physics reset flag. |

A trace block holds the `rigid` lines of `src/tools/trace_l2.hpp` only:
`<block> rigid <slot> <index> px py pz qx qy qz qw`, for every rigid body of
every loaded model, by slot and then by the model's rigid body order. Block 0
is the state when the `trace` command ran. No `bone`, `bonew`, or `morph`
lines are written.

## Scripts

| Script | Covers |
|---|---|
| `seek.txt` | A tick after a seek: `frame 300`, then three 33 ms passes. |
| `play.txt` | Play frames 100..200: one 33 ms pass, one 500 ms pass (the catch-up loop runs about 30 substeps), ten 33 ms passes, stop, one idle pass. |
| `stop.txt` | Stop mid-playback: play 0..300, 15 passes, stop, 5 idle passes. |
| `loop.txt` | Loop restart: loop on, play 0..20, 30 passes (the cursor passes frame 20 and restarts at the start edit's frame), stop, loop off. |
| `step.txt` | Frame step forward twice and back three times from frame 50, a pass after each. |
| `mode.txt` | Physics mode always (265), play 0..60 for 10 passes, the playback ON/OFF override (271) on for a second playback, then modes on/off (269) and off (272), and physics reset (268). |
| `budget.txt` | A negative main-step budget: play 0..120 with 50 ms passes (below). |
| `negstep.txt` | A negative main step that Bullet's substep clock keeps: play 15..120 with 50 ms passes (below). |
| `seeksettle.txt` | The settle a seek requests: three passes, `frame 300`, three passes. |
| `playsettle.txt` | The settle at play start: three passes, play 0..30 from the current frame 0, stop, three passes, play 100..200 from another frame. |
| `mode3.txt` | Physics mode 3 (menu 270): idle passes, a seek, a step forward and back, play 300..360. |
| `toggle.txt` | The playback ON/OFF override (menu 271) forcing mode 2: play 100..200 in mode 1 and in mode 0. |
| `reset.txt` | Physics reset (menu 268) alone: three passes, the reset, three passes. |

Each script saves the scene as a PMM at the end. The saved PMMs come with no
`.emm`, because the models of `swing600.pmm` have no effect assignment.

### The main-step budget

During playback `PlaybackCatchup` (`src/app/playback_catchup.cpp`, block 2)
runs one 1/60 s substep per cursor bump below the target time, and subtracts
1/60 from `g_CatchupDtBudget`, which starts at `DeltaTime`. `PhysicsFrame`
steps the world by what is left. The cursor is a float sum of 1/60 steps, so
when a pass's time is a whole number of 1/60 s steps the sum can land just
below the target and run one more substep than the time covers. `budget.py`
models that arithmetic in float32: with 50 ms passes from frame 0, passes
1 to 10, 16, and 20 run two substeps and keep +0x1.11110ep-6 s, and passes
11 to 15 and 17 to 19 run three and leave -0x1p-28 s for the main step. With
25 ms or 33 ms passes it finds no negative pass. The model is a reading of
the C++; the trace is the oracle.

### What each later script tells apart

The first seven scripts do not tell these behaviors apart: in each, the
trace stays the same whether the behavior is there or not. Each later script
makes one of them change the trace. The argument for each is read from the
C++. The Rust replay with the behavior removed gave a different trace from
the first changed block on (the block is in brackets); that replay is a
local check, not committed.

- `negstep.txt`: the main step of `PhysicsFrame`
  (`src/physics/physics_frame.cpp`) steps `g_CatchupDtBudget` as it is,
  negative too, and no clamp to 0. Bullet's `stepSimulation` adds the step
  to its substep remainder `m_localTime` and steps only when that reaches
  1/60 s. The runner's frames are whole 1/60 s steps, so the load leaves the
  remainder at 0. From frame 15 with 50 ms passes, the first pass runs three
  catch-up substeps (`budget.py 50 1 15` prints them) and leaves -0x1p-28 s,
  so the remainder goes below 0. The first settle step of that pass (the
  load's settle and the settle at play start) then runs no substep. With a
  clamp it runs one, and the remainder after that is a whole substep
  different [1]. In `budget.txt` passes 1 to 10 already move the remainder
  to just below 1/60 s, so a -0x1p-28 s change at pass 11 changes no
  substep count.
- `seeksettle.txt`: the frame edit's seek (`RefreshAfterFrameApply`,
  `src/window/ui_frame_step.cpp`) requests a settle. In `seek.txt` and
  `step.txt` the seek comes before the first pass, and the load's own
  settle (`pmm_load_v2.cpp`) is still pending. Here three passes spend the
  load's settle first [4].
- `playsettle.txt`: `UpdateBoneFrames` (`src/app/playback_state.cpp`)
  requests a settle unless `ApplyPlaybackRangeEdits`
  (`src/window/command_frame_edit.cpp`) set `PlaybackFrameChanged`, which
  it sets when the start edit equals the current frame. The other scripts
  that play from another frame (`play.txt`) play before the load's settle
  is spent. Here
  play 0..30 (start equals current) runs with no settle [4 if it did], and
  play 100..200 (start differs) settles [12].
- `mode3.txt`: in mode 3 `PhysicsFrame` runs the world pass only on a
  settle, a moved body or playback. `StepFrame`
  (`src/window/ui_frame_step.cpp`) requests a settle forward and back, only
  in mode 3. No other script uses mode 3. The idle passes after the menu's
  settle do not step [2 if mode 3 stepped like 1 and 2; 1 if it never
  stepped], and the steps settle [6].
- `toggle.txt`: with the override on, `UpdateBoneFrames` sets the playback
  mode to 2 whatever the menu says. Mode 2 differs from mode 1 only at a
  physics-off key. `swing600.pmm` has one, on bone 髪2 (a dynamic body) at
  frame 120 (`tools/fixtures/gen_fixtures.py`, `PHYSICS_OFF`). `mode.txt`
  plays 0..60 and never reaches the key. From frame 100 the bone's key
  cursor is on that key, so `InitModelTrackCursors` turns the bone's body
  kinematic at play start in mode 2 [4 with the override ignored, and 4
  if it forced mode 1]. The second play, in mode 0, runs physics only
  because of the override.
- `reset.txt`: menu 268 (`command_view_menu.cpp`) requests a settle. In
  `mode.txt` it follows menu 269, which has already requested one. Here
  three passes spend the load's settle first [4].

## Not reached, and limits

- Frame-step playback (block 1 of `PlaybackCatchup`, `frameStepPlayback`) is
  armed only by AVI recording, which these scripts do not start.
- The selection-active input of `PhysicsFrame` (Kinect tracking) stays 0.
- Mouse drags of rigid bodies (`physicsBodiesMoved`) are not modelled.

## Outputs

`expected/<script>/` holds `manifest.tsv` (format: `../script/README.md`),
the trace, and the saved PMM.

Build: commit `164147f` of branch `w2-script2` on `nanoha-lan` (Windows, x64
Release, VS 2022, `tools/windows/build.ps1 -Testing OFF -Targets
MikuDanceStudio`), run 2026-10-26 with

    tools\windows\runtask.ps1 -Script <checkout>\tools\oracle\script_run.ps1
        -Log <x.log> -ScriptArgs '-Root <checkout> -Out <empty dir> -Dir physscen'

Two runs gave identical bytes for every file.

The last six scripts (`negstep` to `reset` in the table above) came from
commit `16f7ce8` of branch `w2-physscen2`, whose C++ is that of main
`bd12f5f`, run 2026-10-26 the same way with `-Exclusive`. That run
regenerated the first seven too, byte for byte the files below. Two runs
gave identical bytes for every file. The Rust replay of
`rust/crates/mds-physics/tests/physscen.rs` gives the six new traces bit
for bit, but that test does not gate them yet.

## Files

| File | sha256 |
|---|---|
| `__pycache__/budget.cpython-313.pyc` | `e4b4124973ed9bbe838ddebc7ea30083f9e150e3d29ed0ad02147010d41d5008` |
| `budget.py` | `aff2407b824078e55d0910e82a6602d77ec5457bf9c7e8d4380d962600478742` |
| `budget.txt` | `0b25b54c56362be52a6d2aa142620a3ea2f90f58557db0f670435420e2ad8cff` |
| `expected/budget/budget.pmm` | `f67d751f34ebad744770d590ebf2d71b8e718cfa3e20c51ecc2f6b5fc6184a43` |
| `expected/budget/budget.trace` | `1e1fcca3d0d3fb85e9c06f54e0b14dd761517b1d1e6399361786cf246c028bfe` |
| `expected/budget/manifest.tsv` | `1e043d0753ca6f8441dafe6f94fb5f18eb1b6f2c4dd0c185bb5949fa5a17c679` |
| `expected/loop/loop.pmm` | `2fef94df9e9a59128cf0135e624d7ce477dbb096928ce26e659bcc7a3e38b904` |
| `expected/loop/loop.trace` | `a0aa16996c17194623714137c1b5743683f8e01c7f413aeb102e3e94854e96b4` |
| `expected/loop/manifest.tsv` | `810f598aac03cc77657534ce69ba06b1a1ea813642b415a6fc3e80c9a67a7880` |
| `expected/mode/manifest.tsv` | `8a2a0dd3b4b5e49f6a9441c1419fde0fcd753ce82cc8eb3d583d8c843ae9d146` |
| `expected/mode/mode.pmm` | `2e56a7a2a4ad928b49586a776d2f74dd3135dab6d09be9204ffb2304a8a8d1f1` |
| `expected/mode/mode.trace` | `7bffdc5425283cb4d2b245db2ad52f41572a859cd80b44f2c1c75a74cffee49c` |
| `expected/mode3/manifest.tsv` | `e3bce6b6cb3b6e8a73ad5446254da222381330211281b776d7882fe34f30c6c4` |
| `expected/mode3/mode3.pmm` | `57f7e1765f97dd149b05cb8e7c8cae96cb56d0a54b3e025344630e3147203374` |
| `expected/mode3/mode3.trace` | `d59d05a138acfdc4eb573c1b5ded89ce362c09bd5c11fd2e8cdec3f22eac40dc` |
| `expected/negstep/manifest.tsv` | `ceec2945bfa8c0bd30fe7e9bf630a74b94575af7d8c31f5846f5b36bccb52a2e` |
| `expected/negstep/negstep.pmm` | `d9596bc112d12e1cddc50973ed2a6a24ba026ac7aed09ce89b2c7b7542c0d2b8` |
| `expected/negstep/negstep.trace` | `65036f348fc013e8d5c253c6adbfb896a522ffea508c0dff3836941265fb02ad` |
| `expected/play/manifest.tsv` | `b61f9d4e002e15d7d99c21eb043dea289adbe4cd7be542381953d5b2956dad62` |
| `expected/play/play.pmm` | `3f244f65f85de70c68e55410228db38ab7bbbdd0ec0ca103f78195b66493efc0` |
| `expected/play/play.trace` | `9456950e18563b960850f04c31d60310dbe687b29c2b995811833b8d964839a1` |
| `expected/playsettle/manifest.tsv` | `fb6601776e18bb80e084dc13dd3539df6dfd46303f573096156db40ee39b314e` |
| `expected/playsettle/playsettle.pmm` | `3f244f65f85de70c68e55410228db38ab7bbbdd0ec0ca103f78195b66493efc0` |
| `expected/playsettle/playsettle.trace` | `67323b3d5eab2603177bf28b482a5b8c23ba352139afcdfc028f592e5c625210` |
| `expected/reset/manifest.tsv` | `9f5abb78806084d563e7c4959a90d13d1964f26cce6efda3fc1770501f0f3a7f` |
| `expected/reset/reset.pmm` | `52d7f6985db28540db94e286f615731f1b1c8532b7e129115effd84e28d25eea` |
| `expected/reset/reset.trace` | `82d421ac5255f5d13f381eeedd0ca5079d6c594080046ba342cd473a5dd764b4` |
| `expected/seek/manifest.tsv` | `04c24bdfe5e558e3b133933bde8cebea6ffa282701a73f233d118757b6b374c6` |
| `expected/seek/seek.pmm` | `5a3f427443a4792004439ff69bd7f539764bd308898babaf085ac535399d5f1d` |
| `expected/seek/seek.trace` | `6505515322d8026789dca7775d4081aa30abab7f574389b05fde52e27b175593` |
| `expected/seeksettle/manifest.tsv` | `9448e122d814379a20d5c51ad55a487103816e66494785c0b0adfe319679cae6` |
| `expected/seeksettle/seeksettle.pmm` | `5a3f427443a4792004439ff69bd7f539764bd308898babaf085ac535399d5f1d` |
| `expected/seeksettle/seeksettle.trace` | `da8232bbeda02583580ff6602e147ada8bc65fe9ab00deb3d99621db3c587dd2` |
| `expected/step/manifest.tsv` | `005239ab3a91579ed4b9f1f45a810ff5ada26bd84df2e169c5a0c46c295f8ae5` |
| `expected/step/step.pmm` | `437ab6b195b3388b22f2cc31b63d316b6d5250073502f01470515f74188053d9` |
| `expected/step/step.trace` | `dc86152d1859369b7e929969e849e82e17e2047e71e40aa0acb4f73532578260` |
| `expected/stop/manifest.tsv` | `3db5517f574c74f8fd8c1fcba1a45bc82c4428118ad71d9b375b6753454cc076` |
| `expected/stop/stop.pmm` | `1d3b23cc0b9cc8ad6ac3502caf7dbfd347ad30293af62854d54bbe3ec2d5b08f` |
| `expected/stop/stop.trace` | `6f9be9edd10ce9ecff3293265881f2efedb132e1bf7c9eb6e7eb6a7ae8ad7bf0` |
| `expected/toggle/manifest.tsv` | `7db46266ad948564b802da3c837a05337302539078232f56e18a7c1f5c3e108d` |
| `expected/toggle/toggle.pmm` | `de4ebb7924aff5661966c95d5c76a29af61bfd83332372e659237d6f7e200b92` |
| `expected/toggle/toggle.trace` | `fc6be782bbb6a4ca3ca0eb4b73a8aae2797be2e336b84a63b67e13d8d306398c` |
| `loop.txt` | `edb7f1ffab83381e254dda03959465c4aa41adccf139d7ce96083e64388fc36d` |
| `mode.txt` | `67d56003252bd95169272ff8c0217440e89571354536ce1f942a9b5370eb70df` |
| `mode3.txt` | `ba69cd863f74779747a2dfda5038265d6a248dbc83f15769047551c22842f7ea` |
| `negstep.txt` | `fb2c136223008b170e0bcdaedb2e4f2f6e7ed3af5839071bcac5d9b3d8d4ca2a` |
| `play.txt` | `630009d3fd13154a308f28dffd72d24c7adb34fc86ebe539f8066527f4b7f4ea` |
| `playsettle.txt` | `80a232e69129091615409bc35ae4d66c0a02d4ed96326ec4a13b3076aa864464` |
| `reset.txt` | `7feabee51c56a3a2b42ac8b990ebae282275025bb5a32d7856dfd15a6548f061` |
| `seek.txt` | `22aa9301f66ef58df75f6715aebe37a359da9620c282e76ca434893fc7319645` |
| `seeksettle.txt` | `82c1c3f0671100ed98e8c46068ebc01dc52012896cbb20c7bfab2503ffbbac77` |
| `step.txt` | `3976d43d5833bef074a941b736de04cb9b386c274caf6a3d7245fc399261fe51` |
| `stop.txt` | `cc12156e9b2a5b55a67789f0c8c8882a45d467bd83cf282418006e3729666d58` |
| `toggle.txt` | `4072029bcaf0eef4ae278ac10a571a60be510f8be9908c9517572ab53e4cc897` |
