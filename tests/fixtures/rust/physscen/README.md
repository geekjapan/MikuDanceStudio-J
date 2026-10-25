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

## Not reached, and limits

- Frame-step playback (block 1 of `PlaybackCatchup`, `frameStepPlayback`) is
  armed only by AVI recording, which these scripts do not start.
- The selection-active input of `PhysicsFrame` (Kinect tracking) stays 0.
- Mouse drags of rigid bodies (`physicsBodiesMoved`) are not modelled.
- Physics mode 3 (`physics mode 3`, menu 270) is a command but no script uses
  it.

## Outputs

`expected/<script>/` holds `manifest.tsv` (format: `../script/README.md`),
the trace, and the saved PMM.

Build: commit `164147f` of branch `w2-script2` on `nanoha-lan` (Windows, x64
Release, VS 2022, `tools/windows/build.ps1 -Testing OFF -Targets
MikuDanceStudio`), run 2026-10-26 with

    tools\windows\runtask.ps1 -Script <checkout>\tools\oracle\script_run.ps1
        -Log <x.log> -ScriptArgs '-Root <checkout> -Out <empty dir> -Dir physscen'

Two runs gave identical bytes for every file.

## Files

| File | sha256 |
|---|---|
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
| `expected/play/manifest.tsv` | `b61f9d4e002e15d7d99c21eb043dea289adbe4cd7be542381953d5b2956dad62` |
| `expected/play/play.pmm` | `3f244f65f85de70c68e55410228db38ab7bbbdd0ec0ca103f78195b66493efc0` |
| `expected/play/play.trace` | `9456950e18563b960850f04c31d60310dbe687b29c2b995811833b8d964839a1` |
| `expected/seek/manifest.tsv` | `04c24bdfe5e558e3b133933bde8cebea6ffa282701a73f233d118757b6b374c6` |
| `expected/seek/seek.pmm` | `5a3f427443a4792004439ff69bd7f539764bd308898babaf085ac535399d5f1d` |
| `expected/seek/seek.trace` | `6505515322d8026789dca7775d4081aa30abab7f574389b05fde52e27b175593` |
| `expected/step/manifest.tsv` | `005239ab3a91579ed4b9f1f45a810ff5ada26bd84df2e169c5a0c46c295f8ae5` |
| `expected/step/step.pmm` | `437ab6b195b3388b22f2cc31b63d316b6d5250073502f01470515f74188053d9` |
| `expected/step/step.trace` | `dc86152d1859369b7e929969e849e82e17e2047e71e40aa0acb4f73532578260` |
| `expected/stop/manifest.tsv` | `3db5517f574c74f8fd8c1fcba1a45bc82c4428118ad71d9b375b6753454cc076` |
| `expected/stop/stop.pmm` | `1d3b23cc0b9cc8ad6ac3502caf7dbfd347ad30293af62854d54bbe3ec2d5b08f` |
| `expected/stop/stop.trace` | `6f9be9edd10ce9ecff3293265881f2efedb132e1bf7c9eb6e7eb6a7ae8ad7bf0` |
| `loop.txt` | `edb7f1ffab83381e254dda03959465c4aa41adccf139d7ce96083e64388fc36d` |
| `mode.txt` | `67d56003252bd95169272ff8c0217440e89571354536ce1f942a9b5370eb70df` |
| `play.txt` | `630009d3fd13154a308f28dffd72d24c7adb34fc86ebe539f8066527f4b7f4ea` |
| `seek.txt` | `22aa9301f66ef58df75f6715aebe37a359da9620c282e76ca434893fc7319645` |
| `step.txt` | `3976d43d5833bef074a941b736de04cb9b386c274caf6a3d7245fc399261fe51` |
| `stop.txt` | `cc12156e9b2a5b55a67789f0c8c8882a45d467bd83cf282418006e3729666d58` |
