# Document commands (`--mds-script`, slice script3)

These scripts run the document commands that `rust/crates/mds-doc` added in
slice `doccmds2` (the timeline key drag, model delete, the camera reference,
VSQ lip sync, the PMD edits, `.vac` accessories, and menu 250 in camera mode)
through the C++ application's own handlers, and save the scene after each
command. They are the oracle for those commands. The runner, the script
language, and the regenerating steps are those of `../script/README.md`, with
`-Dir script3`; this file adds the commands. `script_run.ps1` also stages
`../vsq/*.vsq` next to the exe for this directory.

## Commands

| Command | What the runner sends | C++ handler | Notes |
|---|---|---|---|
| `drag <frame> <frames>` | `WM_MOUSEMOVE`, `WM_LBUTTONDOWN` on a marked key at `<frame>`, `WM_MOUSEMOVE` by `<frames>` columns, `WM_LBUTTONUP` | `HandleLButtonDown` (`src/window/ui_editor_click.cpp`), `HandleMouseMove` with `RemapList` and `RemapAccList` (`src/window/ui_mousemove.cpp`), `HandleLButtonUp` | Model mode moves the marked bone, morph, and display keys; camera mode the marked camera, light, self-shadow, gravity, and accessory keys. `<frames>` is a whole number, negative to the left. Below. |
| `delete model` | button 437 | `DeleteSelectedModel` (`src/window/command_frame_edit.cpp` 1186-1335) | Deletes the model the model combo shows. Answers its OK/Cancel question; fails when the handler asked none (camera mode, or a dialog open). |
| `camera reference <0/1/2>` | check boxes 412 (1, model) and 531 (2, bone); 0 unchecks the checked one | `command_frame_edit.cpp` 1448-1466, `command_frame_register.cpp` 559-578, `ApplyCameraReferenceModeChange` (`src/app/frame_modes.cpp` 741-789) | Does nothing when the boxes already say so. |
| `load lip sync <path>` | menu 224 | `LoadVsqFile` (`src/io/vsq_load.cpp`) | The VSQ text the handler writes beside the VSQ (`<stem>.txt`) goes into `<out-dir>`. Below. |
| `drop <path>` | `WM_DROPFILES` with an HDROP of the absolute path | `HandleDropFiles` (`src/window/ui_dropfiles.cpp`) | Any file a user can drop. A `.vsq` is refused in camera mode with an info box, which is answered OK and written to `messages.tsv`. |
| `toon <slot> <name>` | menu 261; the modal dialog's edit `708 + <slot>` set to `<name>`, then OK | `EnhanceModelDlgProc`, `CollectToonFileNames` (`src/window/enhance_model_io.cpp`) | Slot 1..10. The reminder box after OK is answered and recorded; the "cannot find" box (owned by the dialog) fails the step. |
| `english open` | menu 259 | `EnglishNameDlgProc` (`src/window/english_name_dialog.cpp`), modeless | `english.txt`. |
| `physics model open` | menu 262 | `PhysicsModelDlgProc` (`src/window/physics_model_dialog.cpp`), modeless | |
| `dialog text <id> <text>` | `SetWindowTextA` on control `<id>` of the open modeless dialog | | Sets the text only; the dialog reads it on OK or when its combo changes. |
| `dialog click <id>` | `WM_COMMAND` `BN_CLICKED` of control `<id>` to the dialog | | An auto check box toggles and an auto radio button checks itself first, as a click does. |
| `dialog select <id> <item>` | `CB_SETCURSEL` and `WM_COMMAND` `CBN_SELCHANGE` to the dialog | | The physics dialog's list combos (704 bodies, 736 joints) first collect the edits of the record they leave; so do the English dialog's combos (669, 673, 677). |
| `dialog ok` / `dialog cancel` | `WM_COMMAND` `IDOK` / `IDCANCEL` to the dialog | | Fails when the dialog stays open. The reminder box after OK is answered and recorded. |

The `.vac` accessory and menu 250 in camera mode need no new command:
`load accessory .\tri2.vac` (button 472, `LoadAccessoryObject` in
`src/render/accessory.cpp`) and `paste different` after `select camera`.

### The drag

A user drags marked keys by pressing one of them and moving the mouse. The
runner calls `PanelPaint` (`src/window/ui_panel_paint.cpp`), which draws the
timeline and fills its hit maps, finds in the column of `<frame>` the first
row whose cell holds a marked key, and presses the centre of that cell
(x = 100 + 13 * column + 6, y = 160 + 14 * row + 7). In model mode a bone in
a folded display group is drawn on the group's row, whose cell holds -1 when
one of its keys is marked; a press there starts the drag too, so the drags of
`drag.txt` land on the row of the group that holds センター. The hidden main
window shows 12 frame columns from `timelineStartFrame`, so a script sets
`frame` near the key first (the timeline starts six frames before the
current frame). The step fails when the press starts no drag.

### Saved PMDs

`save pmd <name>` (menu 263, every script directory) now answers the save
dialog with `.\<name>`, which the handler writes next to the exe, and the
runner moves the file into `<out-dir>`. The saved path becomes the model's
path, which later PMM saves record (`pmdedit/edited.pmm` holds
`.\edited.pmd`); a relative path keeps that PMM free of `<out-dir>`, as the
relative load paths keep it free of the checkout. A file of that name next to
the exe fails the step. The PMD bytes do not depend on the path.

### Lip sync text

`LoadVsqFile` writes the text dump of the VSQ in place of the VSQ, with the
extension `.txt` (`basic.vsq` gives `basic.txt` next to the exe). The runner
deletes that file before the step, and copies it into `<out-dir>` after the
step and adds it to `manifest.tsv` at the step's line. A script lip-syncs
each VSQ file once, so the names do not collide. The handler opens the text
with `L"wt"`, so its lines end in CRLF.

## Scripts

| Script | Inputs | Covers |
|---|---|---|
| `english.txt` | `inputs/lips.pmd` | `english open`, the English model name and comment, a bone (combo 669 item 1), a morph (673 item 1), and a group (677 item 0), `dialog ok`; `save pmd` and the PMM; the dialog again with a changed model name and `dialog cancel`; `save pmd`. |
| `drag.txt` | `chain8.pmx` | `drag` in model mode: the bone keys of センター at 10, 20, 30 dragged by -15 stop at 1, 5, 15 (the head key at 0 holds the first one), then the bone and display keys dragged by +40 (41, 45, 55 and the display key 15 to 55). |
| `dragcamera.txt` | `../script/inputs/tri.x` | `drag` in camera mode: camera keys 10 and 20, the light key 12, and the accessory key 25 dragged by +7, then by -30 (each stops one frame after its previous key). |
| `deletemodel.txt` | `chain8.pmx`, `inputs/lips.pmd`, `morph4.pmx`, `tri.x` | `delete model` of the middle model, whose bone 首 parents the accessory and its key at 10, then of the first model. |
| `camref.txt` | `chain8.pmx` | `camera reference` 1, 2, 0 in model mode (首 moved up 0.5, so the bone reference moves the view), then 2 in camera mode. |
| `lipsync.txt` | `inputs/lips.pmd`, `../vsq/basic.vsq`, `vowels.vsq`, `rests.vsq` | `load lip sync`; `drop` of a VSQ in model mode and in camera mode (refused). |
| `pmdedit.txt` | `inputs/lips.pmd`, `inputs/toonx.bmp` | `toon` (slot 3), `physics model open` with the mass of body 0, the position and box shape of body 3, and OK; `save pmd` and the PMM with the new model path; the physics dialog again with a change and `dialog cancel`. |
| `vac.txt` | `inputs/tri2.vac`, `inputs/tri2.x` | `load accessory` of a `.vac`. |
| `pastecamera.txt` | `tri.x`, `inputs/tri2.x` | `paste different` in camera mode: the keys of `tri.x` at 0, 10, 20 onto `tri2.x` at 40. |

`inputs/gen_inputs.py` (`--write`, `--check`) writes the inputs:
`lips.pmd` is `chain8.pmd` with a base morph and the lip morphs あ, い, う, お
(lip panel, English names, all in the facial display list), which the lip
sync and the English morph names need; `tri2.x` is `tri.x` under another
name, so the accessory combo tells two accessories apart; `tri2.vac` names
`tri2.x` with scale 1.5, position (1, 2, -3), rotation (0.5, 0.25, 0), and the
shadow off, in CRLF lines as MMD writes them; `toonx.bmp` is a 2x2 BMP.
Every saved PMM, VMD, and PMD reads and writes back byte for byte through
`mds-formats roundtrip`.

## C++ behavior the outputs record

- **The lip sync of `vowels.vsq` registers keys at frame -2.** A note that
  starts at 0 s gives its first key the frame `-2 - (int)(0 * -30) = -2`
  (`vsq_load.cpp`), stored as the unsigned 4294967294, so the model's max
  frame and then `lastRegisteredFrame` become -2 as well (`lipsync/drop.pmm`).
- **A dropped `.vsq` is refused in camera mode** with an info box
  (`lipsync/messages.tsv`), and `refused.pmm` keeps the keys of the drop
  before it. Menu 224 has no such gate in its handler, but the switch to
  camera mode grays it out (`ApplyModelComboSelection`,
  `src/window/ui_model_reload.cpp` 453), so a user cannot reach it there
  (`load lip sync` after `select camera` fails with "menu item 224 is
  disabled").
- **`.vac` lines are read in text mode**, so a CRLF file names the mesh
  `tri2.x` without the CR (`vac/vac.pmm`). `mds_doc::vac_mesh_name` splits the
  raw bytes at `\n` only and keeps the CR.
- **A model loaded by a bare file name gets a one-letter model directory.**
  `pmd_load.cpp` cuts the path after its last backslash, or after its first
  character when it has none, so `lips.pmd` gives the directory `l` and the
  toon dialog looks for `ltoonx.bmp`. `pmdedit.txt` loads `.\lips.pmd`.
  A real file dialog returns an absolute path.
- **`delete model` cuts the accessory parent to model -1 and keeps the bone
  index** (3) in the accessory state and in its key at 10
  (`deletemodel/deleted-lips.pmm`).
- **The English name dialog opens on x64.** `EnglishNameDlgProc` and
  `EdgeThicknessDlgProc` cut the address of their edit subclass procedure to 32
  bits (`(LONG)(LONG_PTR)`) before `SetWindowLongPtrA(.., GWLP_WNDPROC, ..)`, so
  opening menu 259 ended the process with 0xC000041D (`english.txt` found it);
  slice `cppfix` casts to `LONG_PTR`, as the other install sites do.
- **Cancel applies the English name edits too.** `IDCANCEL` and `IDOK` both run
  `ApplyEnglishNameDialog`; `english/cancelled.pmd` carries "Cancelled Name",
  and differs from `english/english.pmd` in the model name only. Only OK shows
  the reminder box (`english/messages.tsv`). The dialog reads an edit
  when OK or Cancel applies it, or when its own combo changes, not when the
  text is set.
- **Cancel drops the physics edit typed before it**: the mass 9 of body 0 is
  not applied, and `pmdedit/cancelled.pmd` equals `edited.pmd`.
- **The bones of chain8 are on folded group rows**; `drag` presses those
  rows (above).

## Not reached

- **Links that `delete model` cuts beyond the accessory parent**: the camera
  parent and the outside parents of the display keys are set in the
  outside-parent dialog (button 442), which no command opens.
- **The drop of other file kinds** (`.pmm`, `.pmx`, `.vmd`, ...) runs through
  the same command but is not in a script; their handlers are those of the
  load commands.

## Outputs

`expected/<script>/` holds `manifest.tsv` (format: `../script/README.md`),
`messages.tsv` where a box was answered, the saved files, and the lip sync
texts. A PMM saved from a loaded model or accessory also writes `<name>.emm`,
which holds absolute paths on the host
(`C:\mds\w2-winoracle3\repo\out\ci\build\Release\...`); nothing else depends
on the checkout.

`english/` comes from branch `w2-cppfix` on `nanoha-lan`, built at `1502f1e` plus
the two casts (x64 Release, as below), run 2026-10-26: two runs gave identical
bytes for every file. Its `english.emm` holds `C:\mds\w2-cppfix\repo\...`. The
same build reran the other scripts of this directory: every PMM, PMD, VMD, and
text matches the files below, and the `.emm` files differ by the checkout path.

Build: commit `93301af` of branch `w2-winoracle3` on `nanoha-lan` (Windows,
x64 Release, VS 2022, `tools/windows/build.ps1 -Testing OFF -Targets
MikuDanceStudio`; the later commits change only this directory), run
2026-10-26 with

    tools\windows\runtask.ps1 -Script <checkout>\tools\oracle\script_run.ps1
        -Log <x.log> -ScriptArgs '-Root <checkout> -Out <empty dir> -Dir script3'

Two runs gave identical bytes for every file. The same build reran the
scripts of `../script/`, `../script2/`, `../script2/pmm1/`, and
`../physscen/` and saved the files of their committed manifests byte for
byte (the `.emm` files differ by the checkout path).

## Files

| File | sha256 |
|---|---|
| `camref.txt` | `74a6865fff9e200b4b2860f2e2728cd06f68252d6e87ed50e20fc145bc62486e` |
| `deletemodel.txt` | `68f5155f92316f2f6043bdc60225bddaaaa284384235d76f432d478f4c63a3fa` |
| `drag.txt` | `4aade940c539178edb85a6ac42c1d91f723b73c9a7a6c3eb89a9534866433a81` |
| `dragcamera.txt` | `5ed2fbaff7aaf7b6f19c9bdb0e3a732d730165aa4e85ede980acfd24349479f5` |
| `english.txt` | `e856473bedb786dc99fdaba52acc390ce9cb27e2c597b2b54067ae3656c31a49` |
| `expected/camref/camera-mode.emm` | `a925c0061c2e50c477b9ae92005e677d2d5f6174a5666969f7096adf64bc231d` |
| `expected/camref/camera-mode.pmm` | `ce4e43589c06151b1afdb8ef554ee4f4fba8f01a5c4f0dc1be9c7ac105d1f507` |
| `expected/camref/manifest.tsv` | `737e136e4a7e6d8b618d8ed630a76e08c260a9d9e82feb937d3c48b47026b0a3` |
| `expected/camref/model-root.emm` | `a925c0061c2e50c477b9ae92005e677d2d5f6174a5666969f7096adf64bc231d` |
| `expected/camref/model-root.pmm` | `b4b1be922ae36b9fb66986243668fce6528d45dbeb97f2cdc142e8d343de1ba9` |
| `expected/camref/none.emm` | `a925c0061c2e50c477b9ae92005e677d2d5f6174a5666969f7096adf64bc231d` |
| `expected/camref/none.pmm` | `5381a4ceb13f8683f9207b6167b19d565295e44a3b2295f2b18bb144d3fa5b70` |
| `expected/camref/selected-bone.emm` | `a925c0061c2e50c477b9ae92005e677d2d5f6174a5666969f7096adf64bc231d` |
| `expected/camref/selected-bone.pmm` | `4076a4dd30081e2636f31dfc1c1c6b6dcb939e6206662731847cfd36cedf7298` |
| `expected/deletemodel/deleted-chain8.emm` | `bffb9f2bbf8246bacd1d4ad46baff1a090431a7e441448c0667ffe1ad59d8011` |
| `expected/deletemodel/deleted-chain8.pmm` | `5e689bab93cf46cbe5a4399a13b50006eac5d7745322596219586417bc3d1e0b` |
| `expected/deletemodel/deleted-lips.emm` | `6210a1b8f179fafca9c116c81040700090aa59060dccaa6853d6035129bcb809` |
| `expected/deletemodel/deleted-lips.pmm` | `8b11793822807428fe65a9cc4a74346c87c6b447f2e9854929695f385523b129` |
| `expected/deletemodel/manifest.tsv` | `941f99b781441aa0a0f34a61f8244754a8b334464051445d84d69c91643ad98c` |
| `expected/deletemodel/three.emm` | `33f05ad1914f85b12159af430bd1bb5b35ef365b950ef6783762033a3e6a9033` |
| `expected/deletemodel/three.pmm` | `c1eede74e5a1a2925b3d7ef2159dbae990537fd0f29f6fc5debd96dedc507f43` |
| `expected/drag/back.emm` | `a925c0061c2e50c477b9ae92005e677d2d5f6174a5666969f7096adf64bc231d` |
| `expected/drag/back.pmm` | `cab2657416c1376ac378f50c4df4d2a7fd1aadc4c30f2d8f1bdab1bcc97f8fa5` |
| `expected/drag/forward.emm` | `a925c0061c2e50c477b9ae92005e677d2d5f6174a5666969f7096adf64bc231d` |
| `expected/drag/forward.pmm` | `9e1c733fe7a6274893b384fe5b1b9de82cebb526e77cbe2268efac4439520455` |
| `expected/drag/forward.vmd` | `3a1409e0f2c72fafd886b46af4d2f276c48ae4da0ae29c35a7cb0b27de6e556b` |
| `expected/drag/manifest.tsv` | `cc1656ef6c4394ca8368302e75138172e9f6c7b10f10af21cb5122f5dfc00af4` |
| `expected/drag/registered.emm` | `a925c0061c2e50c477b9ae92005e677d2d5f6174a5666969f7096adf64bc231d` |
| `expected/drag/registered.pmm` | `645979c87ea75d8d7fc07200b00d4a22a571c8f018e53ad39b24ea9703c5f8f5` |
| `expected/dragcamera/back.emm` | `bcf3c7e0a814711b475f222541a1ab857787edf8b1d72c7a760ede8f89e62a88` |
| `expected/dragcamera/back.pmm` | `b29e65b8d0532e5747b02889c71ea5661804b3d668d2facf9922ae95a4996521` |
| `expected/dragcamera/back.vmd` | `bb07483249fd4642137e78736341c26c1b81ccd891b4618d2cc25b555ea39eee` |
| `expected/dragcamera/forward.emm` | `bcf3c7e0a814711b475f222541a1ab857787edf8b1d72c7a760ede8f89e62a88` |
| `expected/dragcamera/forward.pmm` | `0c1ec8e40b1d2af56b7f5a5d59c23850f71414e398248a4832d3256ab5802c56` |
| `expected/dragcamera/manifest.tsv` | `6c8a2249cda4ef08fdc23b500c2909639c04f1ae3cc5fae54da93d97d3254941` |
| `expected/dragcamera/registered.emm` | `bcf3c7e0a814711b475f222541a1ab857787edf8b1d72c7a760ede8f89e62a88` |
| `expected/dragcamera/registered.pmm` | `a9d811909a97bc6f2ce25a24b73c1eda01b97b32835570723d1577bb95c99c94` |
| `expected/english/cancelled.pmd` | `95106c5ea394422e217cacdf883b3ce0e89e8861bedc2514acc83e031c52fe2a` |
| `expected/english/english.emm` | `9d3897f98d746a28d5728bef4713211c04b8852cc5e98b01be529cb22efe995d` |
| `expected/english/english.pmd` | `368d70f19e1129f7b17ec959cf0c8af9ecb81033627aba3a1191c3f5df40e380` |
| `expected/english/english.pmm` | `7a2843cadc98913715dcac1d842dad8e95eb5dd687134ec8232abb0b6976d3b8` |
| `expected/english/manifest.tsv` | `58eb7075d88437fbaa8687753d303822074e50f13c5d7e825d5d77895fe32e3b` |
| `expected/english/messages.tsv` | `49fdf0a81f5a4acbeb47f25245a337148105172a88620d51e54f4f51696e9669` |
| `expected/lipsync/basic.txt` | `b90611f4fcb6c72d4417907647fe2705debbf2737c134bb32baf55686f11e817` |
| `expected/lipsync/drop.emm` | `b15d0c0e7ab50e60b7ba9fced9b46928227b5b82ef81aff7be17e5c75552e146` |
| `expected/lipsync/drop.pmm` | `68c2c9794df82a1fa10f8d9f40a77405c087c295eadeeabb72690650beff7cba` |
| `expected/lipsync/manifest.tsv` | `10f861a672b1f847a3ccaff6bf7e6f4357c1879c8efeab51d690d6541ad49881` |
| `expected/lipsync/menu.emm` | `b15d0c0e7ab50e60b7ba9fced9b46928227b5b82ef81aff7be17e5c75552e146` |
| `expected/lipsync/menu.pmm` | `b3fc7f846c280fe0d598591bcaa8f775aa7e35135010c08d917aba803f84f72a` |
| `expected/lipsync/menu.vmd` | `9d13e754945e611a550a2cc90f1a9ad44391fbac5c9868f914b2ba109882059a` |
| `expected/lipsync/messages.tsv` | `f403e4475b15917e6465ef63e7def25d84a2d5a86abb5bec5169d7ce093488e4` |
| `expected/lipsync/refused.emm` | `b15d0c0e7ab50e60b7ba9fced9b46928227b5b82ef81aff7be17e5c75552e146` |
| `expected/lipsync/refused.pmm` | `920ec6ef3f7ec7abb7f69543c6338b3502283c8187af77bb9ce8d653dcc9d11c` |
| `expected/lipsync/vowels.txt` | `4e9e4edd9800d83f354a4f5e6e69b2533c017ba4945cbfaa9526f9b46fdbabd2` |
| `expected/pastecamera/manifest.tsv` | `412988308a74e91a0ebff61480d23026d2109015a333760168b11fe86bca1f6e` |
| `expected/pastecamera/pasted.emm` | `4b4ad6ba809aa1b1e73717510d317df236672df3221f3952c8a43810620e527b` |
| `expected/pastecamera/pasted.pmm` | `0ab9aeefd9c945b6828cfca83b8df21904ee057ef470bbacee3bc0375947f74f` |
| `expected/pmdedit/cancelled.pmd` | `a705bbefcdd889d6ba41ac46bd2ff68de47d0b7addf16c211c16f5978dfa3dc1` |
| `expected/pmdedit/edited.emm` | `d1a7246f851e70f0acf68cfd9f49559f7cb8e3046925499b64d108c891896d7d` |
| `expected/pmdedit/edited.pmd` | `a705bbefcdd889d6ba41ac46bd2ff68de47d0b7addf16c211c16f5978dfa3dc1` |
| `expected/pmdedit/edited.pmm` | `847f9c508f7113a45afb82d86b9e3b7881eae30c1c9721992bd65c8081b2404d` |
| `expected/pmdedit/manifest.tsv` | `03ecebd57097153ae9f9114300fa094985c6a1cc6f9a41fec5eee7f0a7d9f74c` |
| `expected/pmdedit/messages.tsv` | `0128573e0b9101a6d4368f9e94b7e202486ee69840460f93d1f0d85ae7ad0cda` |
| `expected/vac/manifest.tsv` | `c76f0630df8b939a85da5bb1e5453c8ee137c1db622e57ac43166fd416b5bcd0` |
| `expected/vac/vac.emm` | `9b90116c9b596de28146023ad1b1a060016c67cf11ba9f19894fabafae30b76b` |
| `expected/vac/vac.pmm` | `e08118c5b835bd07ba8ac1fba697d39462f5566d5407b20c5140ab825056ffea` |
| `inputs/gen_inputs.py` | `0ab13f6164ab4c3f4229786b628846ef2421585e8bf9e634d4525b2cc4f3ecf9` |
| `inputs/lips.pmd` | `bff9fc1f271f4ed2ea4b7aba1a247a68fb9732633a7af71083b56dea90837231` |
| `inputs/toonx.bmp` | `f049a1b8f5dd6a9c9077d065848c3b7812b7ad2b3ad91fa5dea84a827c1a73d2` |
| `inputs/tri2.vac` | `ffed69c54f5667ffc6cbe697c9b9ccb5ed997583ff2eb27d8ed39544ded9b985` |
| `inputs/tri2.x` | `3d444ec4a9e9dbeea26c27b36b59cc091149802e9e8fe154e4458cfabe46840c` |
| `lipsync.txt` | `6ab8aca5331034db2d654f055ef377c77366bac1f6fdb61716278c746375ad48` |
| `pastecamera.txt` | `a39ff744ce9e5edb52a1350eba1315492e4ec66de2c2fc0400bb3dc650a99506` |
| `pmdedit.txt` | `7a383f84785b4531d7295f96b5a9c962406dd9dbe1d4c040211c5dbcce3f2068` |
| `vac.txt` | `bfb1a7890958a96fd1b3697e05bc9957a0d879435c3a199cfd6b1d8efd758e0d` |
