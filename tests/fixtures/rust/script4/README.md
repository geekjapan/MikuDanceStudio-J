# Document commands (`--mds-script`, slice script4)

These scripts run the document commands that `rust/crates/mds-doc` added in
slice `doccmds3` (PR #114) through the C++ application's own handlers, and
save the scene after each command: the outside-parent dialog, the three order
dialogs, the view offset, the physics record drag and the physics dialog's
edit boxes, and the background media. They are the oracle for those
commands. `pmx263.txt` pins the fix of menu 263 on a PMX model (below).

The runner, the script language, and the regenerating steps are those of
`../script/README.md`, with `-Dir script4`; `../script3/README.md` has the
dialog commands this file builds on. `script_run.ps1` also stages
`../script3/inputs/*` and the AVIs of
`../../../../rust/crates/mds-media/tests/fixtures/bgmovie/` next to the exe
for this directory, and the scripts name them as `.\lips.pmd`, `.\tri2.x`,
`.\toonx.bmp`, and `.\raw24_bottomup.avi`.

## Commands

| Command | What the runner sends | C++ handler | Notes |
|---|---|---|---|
| `outside parent open` | button 442 | `EditAccessoryAttachments` (`src/window/command_frame_edit.cpp` 1345), `SelectNavDlgProc` (`src/window/dialog_procs.cpp`), modal | The `dialog` lines after it run inside the dialog (below). 630 `ApplyBoneAttach`, 632 `ResetModelSelection` (`src/window/dialog_select_ops.cpp` 379, 334), 670/671 previous/next, combos 669 (bone), 673 (none, ground, then the models in calculation order, the selected one in parentheses), 677 (target bone). Its Cancel (2) ends the dialog with IDOK. |
| `accessory order open` | menu 249 | `AccessorySettingsDlgProc` (`src/window/command_file_menu.cpp` 741), modal | List 628, up 630, down 631, OK 632, rename 633 (edit 629), render split count edit 635. |
| `model draw order open` | menu 288 | `ModelDisplayOrderDlgProc` (`src/window/model_order_dialog.cpp`), modal | List 628, up 630, down 631, OK 632. |
| `model calc order open` | menu 289 | `ModelCalculateOrderDlgProc` (`src/window/model_order_dialog.cpp`), modal | As the draw order. |
| `dialog edit <id> <text>` | `SetWindowTextA` on control `<id>` of the open dialog, then `WM_KEYDOWN VK_RETURN` to it | `PhysicsEditSubclassProc` (`src/window/physics_model_dialog.cpp` 360) | Typing a value and pressing Enter: the physics model dialog applies it to the selected body or joint at once (sizes below 0.1 become 0.1). `dialog text` only sets the text. |
| `view drag <right/middle> <none/shift/ctrl> <dx> <dy>` | the button pressed at the viewport centre with the modifier held, one frame, `WM_MOUSEMOVE` by (dx, dy), one frame, the release, one frame | `ConsumeRightButtonDrag`, `ConsumeMiddleButtonPan` (`src/app/pump_navigation.cpp`) | Model mode: shift + right and the middle drag move the view offset (`camera_state[3..5]` of the PMM), plain right orbits, ctrl + right changes the distance. Below. |
| `physics drag <rotate/move> <x/y/z> <none/shift/ctrl> <dy>` | `WM_LBUTTONDOWN` on the cell of the viewport tool (the rotate row or the move row), one frame, the mouse moves of the drag, one frame, the release, one frame | `BeginOrEndViewportToolDrag` (`src/app/frame_modes.cpp`), `EditModeRecord` (`src/app/frame_modes_bone.cpp` 158) | Needs the physics model dialog open and model mode. Moves the selected body by -0.05 * dy along the axis (shift: changes its size by as much), or rotates it by -0.01 * dy rad. On the joint page (radio 801) it edits the selected joint instead: move changes its position by -0.05 * dy (shift makes no difference), rotate its rotation by -0.01 * dy rad. Below. |
| `load background movie <path>` | menu 213 | `CmdLoadAvi` (`src/window/command_impl.cpp`), `LoadAviFile` (`src/media/media_load.cpp`) | |
| `load background picture <path>` | menu 232 | `LoadBackgroundPicture` (`src/media/media_load.cpp`) | |
| `toggle background movie` | menu 216 | `src/window/command_dispatch.cpp` 541 | Shows or hides the AVI; does nothing before an AVI is loaded. |
| `toggle background picture` | menu 233 | `src/window/command_file_menu.cpp` 1893 | The picture; does nothing before a picture is loaded. |
| `toggle black background` | menu 282 | `src/window/command_view_menu.cpp` 1401 | |
| `save pmd refused <name>` | menu 263, the save dialog answered with `.\<name>` | `SaveEnhancedModel` (`src/window/enhance_model_io.cpp`) | The handler must show a box (answered and written to `messages.tsv`) and write no file. |

### Modal dialogs

The handler of an `... open` command blocks in `DialogBoxParamA`. The
runner's `WH_CALLWNDPROCRET` hook sees the dialog's `WM_INITDIALOG` and arms a
timer on it; the dialog's own modal loop calls the timer, which runs the
`dialog` lines that follow the `open` line in the script, up to the first
line of another command. Each of those lines writes its own `start` line
and keeps its line number. The frame loop does not run while the dialog is
up, as in the GUI. The last line must close the dialog (the main window,
its owner, is enabled again); a dialog still open after it, or a line that
fails inside it, ends the process with exit code 1 and the reason on
stderr, because the handler cannot be unwound. A `dialog click` in a modal
dialog focuses the button first, as a mouse click does; the accessory
order dialog's rename (633) acts only when the focus is not on edit 635.
`dialog select` on a list box sets the item and sends `LBN_SELCHANGE` when
the list has `LBS_NOTIFY`, as a click does.

The order dialogs close on 632 (OK) and 2 (`dialog cancel`); `dialog ok`
sends 1, which they ignore, so it fails. The outside-parent dialog closes on
2 only, and its opener then seeks the model when 630 or 632 ran
(`AccessoryApplyGate`).

### Viewport drags

The frame loop reads the mouse buttons and modifiers with `GetKeyState`
(`PollKeyboardStates`, `src/model/model_query_helpers.cpp`) and acts on them
only when `GetForegroundWindow()` is the main window (`ViewportInputActive`).
The main window stays hidden, so during a `view drag` or `physics drag` step
the runner sets the thread's key state with `SetKeyboardState` and its
import of `GetForegroundWindow` answers the main window; both are reset when
the step ends. The step runs its own frames (1/30 s each), so the button
goes pressed (1), held (3, the drag acts), released (2).

`physics drag` presses the cell centre that `RestoreViewportToolCursor`
(`src/app/frame_modes.cpp`) uses: x = view.right - (110, 70, 30) * scale for
x, y, z, y = view.bottom - 65 * scale (rotate) or 25 * scale (move). The
press starts the drag with `BeginCenteredDrag`, which moves the cursor to
the viewport centre (the run holds `runtask.ps1 -Exclusive`) and sets
`separateWindowMouseSeen`, so `HandleMouseMove` (`src/window/ui_mousemove.cpp`)
counts no distance for the first move after it; it also ignores the moves
right of view.right - 200 * scale until one lands left of that line. The
runner sends the moves a user's drag makes: one pixel down from the centre
(or from just left of that line, when the hidden window is narrower), then
dy more. The step fails when the press starts no drag of the expected mode,
or when those gates stay set.

## Scripts

| Script | Inputs | Covers |
|---|---|---|
| `outsideparent.txt` | `../script3/inputs/lips.pmd`, `chain8.pmx` | `outside parent open` at frame 10: bone item 1 of chain8 attached to bone item 3 of lips (673 item 2), 630, 632, cancel; at frame 20 the same bone on the ground; at frame 30 a selection closed without 630 or 632. |
| `accessoryorder.txt` | `tri.x`, `../script3/inputs/tri2.x` | `accessory order open`: tri2.x up, renamed `renamed.x`, render split 1, OK; again with a move down, split 5, and cancel. |
| `modelorder.txt` | `chain8.pmx`, `lips.pmd`, `morph4.pmx` | `model draw order open`: morph4 up twice, OK; `model calc order open`: chain8 down, OK; again with a move and cancel. |
| `viewoffset.txt` | `chain8.pmx` | `view drag`: shift + right (40, -20), middle (10, 30), middle shift (-4, 2), middle ctrl (0, 100), right (15, 5), ctrl + right (0, 10). |
| `physicsdrag.txt` | `lips.pmd` | `dialog edit` of the mass and the linear damping of body 0; `physics drag` of body 0 (move y 10, shift move x -4, rotate z 25); body 3 renamed (`dialog edit 705`) and moved (z 3); the joint page (801) and a joint position edit (744); OK; `save pmd` and the PMM; a drag and cancel. |
| `background.txt` | `raw24_bottomup.avi`, `toonx.bmp` | The three toggles before any media, `load background movie`, `load background picture`, the toggles again, and the movie shown once more. |
| `jointdrag.txt` | `lips.pmd` | The record drag on the joint page: `nodrag.pmd` (joint page opened, OK, no drag), then joint 2 (move y 10, shift move x -4, rotate z 25) and joint 4 (rotate x -15) dragged, OK; `save pmd` and the PMM; the dialog opened again, a move y 5 drag on its body page, OK. |
| `pmx263.txt` | `chain8.pmx`, `lips.pmd` | `save pmd refused` on chain8.pmx, `save pmd` of lips.pmd, and the PMM with chain8's path unchanged. |

## Menu 263 on a PMX model

`SaveEnhancedModel` is the PMD writer: it writes the `Pmd` header, its save
dialog offers `*.pmd`, and it reads `rawVertices`, which only the PMD loader
fills (`src/model/pmd_load.cpp` 215; `model_init.cpp` sets it to null). On a
PMX model the first vertex `_write` got a null buffer, and the CRT's invalid
parameter handler ended the process with 0xC0000409. The GUI does not offer
it: the help menu's "モデル拡張" popup, which holds 259, 261, 262, and 263, is
grayed for a PMX model (`physicsMode == 2`, `SetPhysicsMenuState` in
`src/window/ui_model_reload.cpp` 553 and `src/app/playback_state.cpp` 129);
the runner sends `WM_COMMAND 263` and checks the item, not its popup. So the
C++ is meant to write PMD only, and `SaveEnhancedModel` now refuses a PMX
model with a box (`PMXモデルは拡張モデル保存できません` / `A PMX model cannot be
saved as a PMD.`) before it creates the file, as `mds-app` refuses it
(`rust/crates/mds-app/src/ui/help.rs` `save_enhanced`).

Before the fix (commit `f9f0ac2` with `enhance_model_io.cpp` of `ad955cc`,
2026-10-26), `load model chain8.pmx` and `save pmd crash.pmd` exited with
0xC0000409 and left a 287-byte `crash.pmd` (the 283-byte header and the
vertex count).

## C++ behavior the outputs record

- **Outside parent.** 630 (`ApplyBoneAttach`) writes the target into the
  model's display key at the current frame (a new key, `allocated` 1) and its
  `selector_pose`: `attached.pmm` has chain8's selector 1 at `[10, 0, 0, 3]`
  and display key 10 at `[0, 3]` (model 0, lips, bone 3), `ground.pmm` adds
  key 20 at `[-2, 0]` (the ground). Combo 673 lists none, ground, then the
  models in calculation order. `closed.pmm` (no 630 or 632) differs from
  `ground.pmm` in the current frame (30) and one pose flag (offset 2500): the
  opener seeks only when 630 or 632 ran.
- **Accessory order.** The OK writes each slot's render order and the rename;
  the list name of a slot (`accessory list` in the PMM) follows the render
  order, so in `ordered.pmm` slot 0 lists `renamed.x` (tri2.x, order 0) and
  slot 1 lists `tri.x`, while the names stay with their slots. A cancel keeps
  nothing: `cancelled.pmm` equals `ordered.pmm`.
- **Model order.** The draw order changes only the combo index of each model
  (`draw.pmm`: morph4 1, chain8 2, lips 3); the calculation order changes the
  `display_order` bytes (`calc.pmm`: lips 0, chain8 1, morph4 2).
  `calc-cancelled.pmm` equals `calc.pmm`.
- **View offset.** Model mode, view scale 1: shift + right (40, -20) moves the
  offset (`camera_state[3..4]`) from (0, 10) to (-4, 8); middle (10, 30) by
  (-0.5, 1.5); middle shift (-4, 2) and middle ctrl (0, 100) by (2, 1.5) in
  all; right (15, 5) turns the camera (pitch -0.05, yaw -0.15) and ctrl +
  right (0, 10) changes the distance from -45 to -46.
- **Physics record drag.** On body 0 of lips.pmd (size [0.25, 0, 0]): move y
  10 gives position y -0.5, shift move x -4 size x 0.45, rotate z 25 rotation
  z -0.24993116, not -0.25: each drag echoes the value into its edit box with
  `%3.2f` (degrees for the rotation), and the OK reads the boxes back. The
  same read raises any size below 0.1 to 0.1 (`ReadEditFloatClamped`), so
  sizes y and z are 0.1. Body 3 (renamed `body3`) moves z 3 to -0.15 with
  size z 0.1. Joint 0's position x is 0.5 from edit 744, and its rotation
  limits become ±0.50003684 and ±0.5000367 by the same degree round trip. The
  OK shows the box in `physicsdrag/messages.tsv` (caption `モデル拡張`, from
  `physics_model_dialog.cpp` `kCaptionEnhanceModelJp`). `save pmd` makes
  the file the model's path (`dragged.pmm` names `.\dragged.pmd`). A drag and a cancel
  leave the model as it was: `cancelled.pmd` equals `dragged.pmd`.
- **Joint page.** On the joint page the same drags edit the selected joint
  (`jointdrag/`). `nodrag.pmd` differs from `before.pmd` only in body 0's
  sizes y and z (0 to 0.1, the clamp of the OK read above). `joints.pmd`
  differs from `nodrag.pmd` in joints 2 and 4 only, no body: joint 2's
  position goes from (0, 2.5, 0) to (0.2, 2, 0) (move y 10 gives -0.5; shift
  move x -4 gives +0.2, shift makes no difference) and its rotation to z
  -0.24993116; joint 4's rotation to x 0.14992379 (rotate x -15). The dialog
  opened again starts on the body page: `body.pmd` differs from `joints.pmd`
  in body 0's position y only (-0.25).
- **Background.** 216 and 233 do nothing before a load; 282 toggles
  `black_background` (`none.pmm`: 1). Loading sets the AVI to offset
  (0, -214), scale 40, and the picture to (0, -500), scale 640, both shown;
  the toggles hide them and clear the black background (`hidden.pmm`), and
  216 shows the movie again (`shown.pmm`).
- **Menu 263.** `pmx263/messages.tsv` holds the refusal at step 5; no
  `refused.pmd` is written, and `after.pmm` keeps chain8's path
  `chain8.pmx` (lips names `.\saved.pmd`); `saved.pmd` of lips.pmd equals
  `physicsdrag/before.pmd`.

## The joint page of the physics dialog

`EditModeRecord` (`src/app/frame_modes_bone.cpp` 166, 196) edits the selected
joint instead of the selected body when `state.physicsEditorJointPage` is set,
but nothing wrote that field: the page radios (800, 801) reach
`FlipPhysicsDialogPage` (`src/window/physics_model_dialog.cpp`), which set
only the file-local `s_jointPageVisible`, so a record drag on the joint page
moved the selected body. `FlipPhysicsDialogPage` and the dialog's init now
write `state.physicsEditorJointPage` (the file-local flag is gone), and the
OK and Cancel paths clear it with the dialog's pointer, so the bone edit's
direct mode (`frame_modes_bone.cpp` 468) and the debug geometry
(`debug_geometry.cpp` 319), which read it, never see it set after the dialog.
The same commit corrects the OK box's caption in that file from `モデル括張`
(`\x8a\x87`) to `モデル拡張` (`\x8a\x67`), as `enhanced_model_messages.hpp`
has it. `jointdrag.txt` is the oracle; `physicsdrag/messages.tsv` changes by
the caption only. The caption also changes the pmdedit box of
`../script3/expected/pmdedit/messages.tsv` (step 13), which this directory
does not own; its text and its sha256 in `../script3/README.md` are updated
by the root (`23706d3f...72ce97c`).

## Not reached

- **The pan tool of the viewport header** (`ViewportToolAtPoint` operation 2,
  a left drag that moves the view offset by `DragScale`,
  `src/app/frame_modes.cpp`) is not in a script; `view drag` covers the
  pump's right and middle drags.
- **The previous and next buttons (670, 671) of the outside-parent dialog**
  run through `dialog click` but are not in a script; they move combo 669's
  selection and refresh the dialog, which `dialog select 669` does too.
- **Menu 263 through its menu on a PMX model.** The GUI grays the popup that
  holds it, so a user cannot reach the refusal; `save pmd refused` sends
  `WM_COMMAND 263`, which the C++ handles whatever the popup's state.
## Outputs

`expected/<script>/` holds `manifest.tsv` (format: `../script/README.md`),
`messages.tsv` where a box was answered, and the saved files. A PMM saved
from a loaded model or accessory also writes `<name>.emm`, which holds
absolute paths on the host (`C:\mds\w2-script4\repo\out\ci\build\Release\...`);
nothing else depends on the checkout.

Build: commit `67a50d1` of branch `w2-cppfix2` on `nanoha-lan` (Windows, x64
Release, VS 2022, `tools/windows/build.ps1 -Testing OFF -Targets
MikuDanceStudio`; the later commits change only this directory), run
2026-10-26 with

    tools\windows\runtask.ps1 -Script <checkout>\tools\oracle\script_run.ps1
        -Log <x.log> -Exclusive -ScriptArgs '-Root <checkout> -Out <empty dir> -Dir script4'

`-Exclusive` is required: the drags move the cursor. Two runs gave identical
bytes for every file. The same build reran the scripts of `../script/`,
`../script2/`, `../script2/pmm1/`, `../physscen/`, and `../script3/` with no
failure and identical run1 and run2 bytes, and saved the files of their
committed manifests byte for byte, the `.emm` files (the checkout path) and
`script3/expected/pmdedit/messages.tsv` (the caption above) excepted. The
`.emm` of `jointdrag` holds `C:\mds\w2-cppfix2\repo\...`.

## Files

| File | sha256 |
|---|---|
| `accessoryorder.txt` | `e00d667816dba4eb75a837beae00cb2b93a4d4156fd0f171253260d3e9b0298a` |
| `background.txt` | `5ad8b635cec610169621f5217c512ce54690b48db13e4a4716135be87ecb90ab` |
| `jointdrag.txt` | `34ef890014c00e1b3a3cc2decf04431511d25b4ffdee12365c9065773dee65c0` |
| `modelorder.txt` | `50958d919cae35877172b5458d7498a77952b525418cfb3d8e14d02600c67aa0` |
| `outsideparent.txt` | `f9f14a6e3a6b08eabdb5d7199dec0ea45395d11a0951f66632f8cacbce084f04` |
| `physicsdrag.txt` | `5613a8307a6476b99c1e4ee30825017fb408a210f8ef66158ed112efc2b848c8` |
| `pmx263.txt` | `93a3332cc787d4c72a80eff27bde34c38be80cfd1ea36b8dc92ab36689bcef57` |
| `viewoffset.txt` | `912079f939424e104acd2932243f9d8e5eb98aff24e52b40005eaa8fe340bbdf` |
| `expected/accessoryorder/before.emm` | `76af5dcf7f15e3b7e289ae1e761f0575c84db3665ab826f0d0a65bacb6fef4f0` |
| `expected/accessoryorder/before.pmm` | `22f62cd21c6257e02de5efecd0d24b0997027becef5fd1b1fc7cae3ad4a94697` |
| `expected/accessoryorder/cancelled.emm` | `76af5dcf7f15e3b7e289ae1e761f0575c84db3665ab826f0d0a65bacb6fef4f0` |
| `expected/accessoryorder/cancelled.pmm` | `6cd97a55ccd73f42ef3058721a22e2678bb0e52ca191ea4ea1e2a46e8889bf4f` |
| `expected/accessoryorder/manifest.tsv` | `e63883b18cea0d58bcfa9a8e30cb291643578425471c8c7b2bfb09957bf27513` |
| `expected/accessoryorder/ordered.emm` | `76af5dcf7f15e3b7e289ae1e761f0575c84db3665ab826f0d0a65bacb6fef4f0` |
| `expected/accessoryorder/ordered.pmm` | `6cd97a55ccd73f42ef3058721a22e2678bb0e52ca191ea4ea1e2a46e8889bf4f` |
| `expected/background/hidden.emm` | `096ea09ec3f32e8e55db3f589da7f2ac2735594c9e3da42d5546734d03381305` |
| `expected/background/hidden.pmm` | `0ae99ddff76bec5c71ac547669997c256568bde7ec1d284098e08f09c54e243f` |
| `expected/background/loaded.emm` | `096ea09ec3f32e8e55db3f589da7f2ac2735594c9e3da42d5546734d03381305` |
| `expected/background/loaded.pmm` | `02e516ae4a81344ce0d81d5e2ffca05cc51e78a9420b69a82ca2714fef35a0e4` |
| `expected/background/manifest.tsv` | `4d2793ebc24854576117620cfbb4698129fdd1487c76bde8092a708ea59d56ff` |
| `expected/background/none.emm` | `096ea09ec3f32e8e55db3f589da7f2ac2735594c9e3da42d5546734d03381305` |
| `expected/background/none.pmm` | `dd197a0b203a8b272dbb410c6ad9f7df01ff063b1df40c4cb1a9954e8b2f781f` |
| `expected/background/shown.emm` | `096ea09ec3f32e8e55db3f589da7f2ac2735594c9e3da42d5546734d03381305` |
| `expected/background/shown.pmm` | `47836956f736322b8f9ba7fa5db38ff94e06bebec0e813dd70cc76cddb175a61` |
| `expected/jointdrag/before.pmd` | `829a41d6f9901725e1bc1b087e739572eaf92597e1dc3c42b4b59e1a8e32f522` |
| `expected/jointdrag/body.pmd` | `ec10ad1ae4367f9b5df0f333316dc8cab713f81c34e4d1f89de7f2a4c63d9cbf` |
| `expected/jointdrag/joints.emm` | `c3b16cf05f381299a6ab61fa261d111715a200b5d0120f67cd3598a16c7e4427` |
| `expected/jointdrag/joints.pmd` | `2002f6813b44a93348934cb0a3231783e5cba4680fef78cbd84f18614143cc98` |
| `expected/jointdrag/joints.pmm` | `fd10dce41d46d943b7787196823426187d8c0f037a6eed092d9d27222f8aec23` |
| `expected/jointdrag/manifest.tsv` | `c614715829b5b604ceae07258c846a31daf219550566beda534cdd046b83ce1b` |
| `expected/jointdrag/messages.tsv` | `d5274073d084b973d40fd015a858fb51b1e08a43bd368d496e9f6ac22cfe2170` |
| `expected/jointdrag/nodrag.pmd` | `ea2d34569fc1c8357a8bf1d27f0d1b4167715c3b4fe3d2deb8f341a15a2b8705` |
| `expected/modelorder/before.emm` | `603c6fe3e237a4afc1a7eab321352501c47899d34096f429b070c4ca1d972f1a` |
| `expected/modelorder/before.pmm` | `71f9c12ae3e1738999b80bf4ac4f1ba02a726406897943b0743ae0262acfb712` |
| `expected/modelorder/calc-cancelled.emm` | `603c6fe3e237a4afc1a7eab321352501c47899d34096f429b070c4ca1d972f1a` |
| `expected/modelorder/calc-cancelled.pmm` | `dc3c4416709d9c96aca1765b30c927b1f782948df93f87b88a8db15236113c04` |
| `expected/modelorder/calc.emm` | `603c6fe3e237a4afc1a7eab321352501c47899d34096f429b070c4ca1d972f1a` |
| `expected/modelorder/calc.pmm` | `dc3c4416709d9c96aca1765b30c927b1f782948df93f87b88a8db15236113c04` |
| `expected/modelorder/draw.emm` | `603c6fe3e237a4afc1a7eab321352501c47899d34096f429b070c4ca1d972f1a` |
| `expected/modelorder/draw.pmm` | `78e25af320686649da9ca03879c513066b21f6efb3c360dec0273530bc3f3064` |
| `expected/modelorder/manifest.tsv` | `3f7aa1707b464da3fd47ad1a036a8c23c075c02a02f57b35442ec182a1a3a7e8` |
| `expected/outsideparent/attached.emm` | `291d9d235a226e23dcaa87884b3a89d6eb29b5044e655b064dfca64857093a6e` |
| `expected/outsideparent/attached.pmm` | `a6df3c292a69a77fec7b6886214948eb90e48c02b35d563141c27b2b3de8c0ad` |
| `expected/outsideparent/closed.emm` | `291d9d235a226e23dcaa87884b3a89d6eb29b5044e655b064dfca64857093a6e` |
| `expected/outsideparent/closed.pmm` | `60008f20468376ea02d4d934c3772e65495d0994ec4771d291c990232903d3bf` |
| `expected/outsideparent/ground.emm` | `291d9d235a226e23dcaa87884b3a89d6eb29b5044e655b064dfca64857093a6e` |
| `expected/outsideparent/ground.pmm` | `ef820e1f7812af54769aba647f1ac6dad310c7f212f32a4a49c6bfe561cc151c` |
| `expected/outsideparent/manifest.tsv` | `69ae79cb9580a82b6b635b30ef4328cc5c61cf757c3e6e842fb92d13d470767e` |
| `expected/physicsdrag/before.pmd` | `829a41d6f9901725e1bc1b087e739572eaf92597e1dc3c42b4b59e1a8e32f522` |
| `expected/physicsdrag/cancelled.pmd` | `77bd30e8cff97238d50504357524e0b472db6acb5542d0d413946c669068411d` |
| `expected/physicsdrag/dragged.emm` | `c832647c95b8029eb5dd23b0a31f469d6c4fa9ce5094ee5ae076f5818d770840` |
| `expected/physicsdrag/dragged.pmd` | `77bd30e8cff97238d50504357524e0b472db6acb5542d0d413946c669068411d` |
| `expected/physicsdrag/dragged.pmm` | `dbfb5c92c2136a8ec9e17ce693fecb84a17e565afea8e812750e6bb08574082c` |
| `expected/physicsdrag/manifest.tsv` | `ded2f39059c8443ab4529277d53eb6a66d634de5aee747e16e1d90f75c8d0248` |
| `expected/physicsdrag/messages.tsv` | `93f294643672e0624da39cdd099f38d72be0e13570f6a2f4ba13e9726c5c9163` |
| `expected/pmx263/after.emm` | `9ec2c56e12ca87ffb43e6f411af33f75dca106b707b552a90622ffe666754831` |
| `expected/pmx263/after.pmm` | `3a19272eda078bad5b6a18c87f85ca157b8d627aa64f0e57a4a62ca6d512de35` |
| `expected/pmx263/manifest.tsv` | `83a35e2d34e2b06371afdf85c4f28d9ca5a25b0253686ae853a94fac2c4ebbb1` |
| `expected/pmx263/messages.tsv` | `2e9223c9ae989b72c95b12f219e236f6ec808062acf3b25a584417f8aa458119` |
| `expected/pmx263/saved.pmd` | `829a41d6f9901725e1bc1b087e739572eaf92597e1dc3c42b4b59e1a8e32f522` |
| `expected/viewoffset/manifest.tsv` | `a9f3bfd2ed9c111320925e21e280391099d022f77bb6ff0f64c15f8336247326` |
| `expected/viewoffset/middle-modifiers.emm` | `e4698a9cfb8828688b5dd11e517c6e1004f65da6ed16298940fd2c2c63e7f531` |
| `expected/viewoffset/middle-modifiers.pmm` | `d9a3e3621e1d71fdf34e22510aa9e782e0c842586f44681234b228c8733d03f2` |
| `expected/viewoffset/middle.emm` | `e4698a9cfb8828688b5dd11e517c6e1004f65da6ed16298940fd2c2c63e7f531` |
| `expected/viewoffset/middle.pmm` | `610b1b62593ea825c47951022f7c6148810e1a2a0286dc1b1fe92d5c18d227fc` |
| `expected/viewoffset/orbit.emm` | `e4698a9cfb8828688b5dd11e517c6e1004f65da6ed16298940fd2c2c63e7f531` |
| `expected/viewoffset/orbit.pmm` | `db8d295ee0b15dbb59b6d67ebcb7214089c60893185c4247acb1525d59693feb` |
| `expected/viewoffset/shift-right.emm` | `e4698a9cfb8828688b5dd11e517c6e1004f65da6ed16298940fd2c2c63e7f531` |
| `expected/viewoffset/shift-right.pmm` | `429ded171a57d05155019fa87674cd9e5966457a8d27b8ef15ecc9ff819f9d0b` |
