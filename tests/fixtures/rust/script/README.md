# Script oracle (`--mds-script`)

The C++ application runs a text script of editing commands through its own
window handlers and writes every file the script saves:

```
MikuDanceStudio.exe --mds-script <script.txt> <out-dir>
```

The scripts in this directory and their outputs under `expected/` are the oracle
for the Rust document (`mds-doc`, slices `doc` and `docgold`) and the Rust UI.
A Rust replay of a script must save the same bytes.

The runner is `src/tools/script_mode.cpp`; the parser is
`src/tools/script_parse.hpp` (test: `src/tools/script_parse_test.cpp`, which
also builds on macOS with `c++ -std=c++17 -I src/tools
src/tools/script_parse_test.cpp`).

## Outputs

`expected/<script>/` holds the files that `<script>.txt` saved and `manifest.tsv`:

```
step	file	sha256
<line>	<file name>	<lowercase hex sha256>
```

`step` is the line number of the save command in the script. After each save
the runner lists `<out-dir>` and adds every file that is new or changed since
the last save: the target first, then the files the save wrote beside it, by
name. A PMM save also writes `<name>.emm` (the MME effect map), so each PMM
line is followed by its `.emm` line.

The `.emm` files hold the absolute paths that MME resolved on the host
(`C:\mds\w2-script\repo\out\ci\build\Release\chain8.pmx`). Nothing else in the
outputs depends on the checkout's location.

Every saved PMM, VMD, VPD, and PMD also reads and writes back byte for byte
through `mds-formats roundtrip` (checked by hand when the outputs were made;
`docgold` owns the automated comparison).

## Regenerating

On the Windows host, from a checkout at `C:\mds\w2-script\repo`:

1. `tools\windows\build.ps1 -Root <checkout> -Testing OFF -Targets MikuDanceStudio`
2. `tools\windows\runtask.ps1 -Script <checkout>\tools\oracle\script_run.ps1
   -Log <x.log> -ScriptArgs '-Root <checkout> -Out <empty dir>'`

`script_run.ps1` stages the inputs next to the exe (`tests/fixtures/rust/*`
and `tests/fixtures/rust/script/inputs/*`), runs every `*.txt` here twice into
`<Out>\run1` and `<Out>\run2`, compares the two runs file by file, and prints
each manifest. It exits 1 when a script fails or a file differs. Copy
`<Out>\run1\<script>\` to `expected/<script>/`.

The run needs the console session (`runtask.ps1`), because it creates the
D3D9 device. No `Data\mmconfig.ini` is next to the exe, so the application
starts with its defaults, among them the Japanese UI: message boxes, combo
items, and model and bone names are Japanese.

Current outputs: build of commit `1806993` (180699366cd73c3d979f806855dd3fe56b9c9e5c) on `nanoha-lan` (Windows,
x64 Release, VS 2022), run 2026-10-25. Two runs gave identical bytes for every
file.

## Script language

UTF-8, one command per line. Words are separated by spaces or tabs; quote a
word that holds spaces (`"my model.pmx"`). Empty lines and lines whose first
word starts with `#` are skipped. The whole script is checked before any
window exists; a bad line exits 1 with `line N: <reason>` on stderr.

Paths:

- A load path is passed to the handler as written. The handlers set the
  current directory to the exe directory first, so a relative path names a
  file next to the exe. The accessory loader needs a backslash in the path,
  so accessories are written `.\tri.x`. A real file dialog returns absolute
  paths; relative ones keep the saved PMM free of the checkout's location.
- `out/<name>` loads a file that an earlier step saved into `<out-dir>`.
- A save target is a plain file name, written into `<out-dir>`. Each target
  is saved once per script.

Numbers are decimal (`-12.5`, `+3`). A frame is an integer below 100000. A
lane is a morph-panel lane: 0 eyebrow, 1 eye, 2 lip, 3 other.

## How a step runs

- Menu commands send `WM_COMMAND` with the menu id. Buttons send
  `WM_COMMAND` with the id, `BN_CLICKED`, and the button's HWND. A grayed-out
  menu item or a disabled control fails the step, because a user could not
  click it.
- Numeric edits are set with `SetWindowTextA` (the whole text at once) and
  committed with `WM_KEYDOWN VK_RETURN` to the edit, which the edit subclass
  (`src/window/ui_edit_commit.cpp` `EditSubclassProc`) commits.
- Combos are set with `CB_SETCURSEL` and `WM_COMMAND CBN_SELCHANGE` with the
  combo's HWND. A name picks the first item with that text
  (`CB_FINDSTRINGEXACT`, case-insensitive), converted to Shift-JIS.
- File dialogs never open: `GetOpenFileNameW` and `GetSaveFileNameW` are
  replaced in the executable's import table and return the step's path. A
  dialog that the step did not expect, or an expected dialog that the handler
  never opened (a gate returned first), fails the step.
- Message boxes never open: `MessageBoxA` and `MessageBoxW` are replaced. An
  OK/Cancel question is answered OK in the steps whose GUI action asks one:
  `new`, `load pmm` (the unsaved-changes question), `load model` (the model
  comment box), and `paste different`. Any other box fails the step and
  prints its caption and text. Any other dialog window fails the step, except
  the gravity dialog that `gravity open` creates.
- After every step the runner drains the message queue and runs `FrameDriver`
  twice with a fixed frame delta of 1/30 s, as the application's loop does
  between two user actions. The main window stays hidden.
- An edit command commits its value only. In the GUI, a physical Enter can
  also register a key through the frame loop's Enter poll
  (`src/app/pump_edit_keys.cpp`); the runner's Enter is a message, so
  `GetKeyState` never sees it and keys are registered by `register` alone.

A failed step exits 1 with `mds-script: line N (<command>): <reason>` on
stderr. Every step also writes `mds-script: line N (<command>): start` there
first, so a crash names its step.

## Commands

| Command | What the runner sends | Notes |
|---|---|---|
| `new` | menu 204 | Answers the OK/Cancel question. `ResetAppState`. |
| `load pmm <path>` | menu 205 | `LoadSceneFile`. |
| `load model <path>` | button 435 | PMX or PMD, `LoadModelFile`. Selects the new model and leaves camera mode. |
| `load vmd <path>` | menu 209 | Onto the selected model, or onto the camera after `select camera`. |
| `load vpd <path>` | menu 202 | Onto the selected model. Menu 202 stays disabled until a model is loaded. |
| `load accessory <path>` | button 472 | `.x`; `LoadAccessoryFile`. |
| `load wav <path>` | menu 206 | `LoadWaveFile`. |
| `save pmm <name>` | menu 208 (save as) | `SaveSceneFile`. Also writes `<name>.emm`. |
| `save vmd <name>` | menu 210 | Saves the selected keys of the selected model, or of camera, light, and self-shadow in camera mode. Without selected keys the handler shows a box, which fails the step. |
| `save vpd <name>` | menu 203 | The selected bones' pose. Needs a selected bone. |
| `save pmd <name>` | menu 263 | `SaveEnhancedModel`, the PMD writer. Only for a PMD model: on a PMX model it ends the process (0xC0000409). The saved path (`.\<name>`) becomes the model's path, so later PMM saves record that relative path. |
| `select camera` | combo 436, item 0 | Camera, light, and accessory mode (`ApplyModelComboSelection`). |
| `select model <name>` | combo 436 | The model's name as the combo shows it. |
| `select bone <name>` | `SelectDisplayBone` | Japanese or English bone name of the selected model. A user picks a bone by clicking its timeline row, which needs layout-dependent mouse coordinates; `SelectDisplayBone` is where the Up and Down keys and display-list picks end. It selects that bone only. |
| `select morph <lane> <name>` | combo 504/509/514/519 | The lane's combo; `MorphRowSelect`. |
| `select accessory <name>` | combo 471 | The accessory's file name (`tri.x`). |
| `frame <n>` | edit 417 | The current frame. |
| `bone position <x> <y> <z>` | edits 544, 545, 546 | The selected bone's translation, one commit per axis, in model mode. |
| `bone rotation <x> <y> <z>` | edits 547, 548, 549 | Degrees, one commit per axis. |
| `morph <lane> <weight>` | edit 506/511/516/521 | The weight of the lane's selected morph. |
| `camera position <x> <y> <z>` | edits 544, 545, 546 | In camera mode. Z is negated when the camera follows a model. |
| `camera rotation <x> <y> <z>` | edits 547, 548, 549 | Degrees. The stored pitch is the negated X. |
| `camera distance <d>` | edit 550 | Stored negated (`25` is saved as -25). |
| `camera fov <deg>` | edit 448 | Integer degrees (`atol`). |
| `light color <r> <g> <b>` | edits 461, 462, 463 | 0..255, stored as value / 256. |
| `light direction <x> <y> <z>` | edits 464, 465, 466 | |
| `shadow mode <0/1/2>` | button 562/563/564 | Self-shadow off, mode 1, mode 2. |
| `shadow range <v>` | edit 561 | Stored as (10000 - v) / 100000. |
| `gravity open` | menu 266 | Opens the modeless gravity dialog. |
| `gravity magnitude <m>` | dialog edit 709 | One `EN_UPDATE` with the whole text. |
| `gravity direction <x> <y> <z>` | dialog edits 710, 711, 712 | One `EN_UPDATE` per axis, in X, Y, Z order. Each one normalizes the stored direction (`SetGravityChannel`), so the order matters. |
| `gravity close` | dialog `IDCANCEL` | |
| `accessory position <x> <y> <z>` | edits 478, 479, 480 | The selected accessory. |
| `accessory rotation <x> <y> <z>` | edits 481, 482, 483 | Degrees, stored in radians. |
| `accessory scale <s>` | edit 484 | |
| `accessory opacity <a>` | edit 485 | Clamped to 0..1. |
| `accessory parent <model> <bone>` | combos 474 and 475 | `ground` is item 0 of combo 474. `-` as the bone leaves combo 475 alone. |
| `register bone` | button 500 | The selected bones at the current frame. |
| `register morph <lane>` | button 525/524/527/526 | Lanes 0..3, in that order. |
| `register display` | button 438 | Display and IK key. |
| `register camera` | button 452 | |
| `register light` | button 468 | |
| `register shadow` | button 565 | |
| `register gravity` | gravity dialog `IDOK` | Needs `gravity open`. |
| `register accessory` | button 487 | |
| `copy` | button 420 | The selected keys. |
| `paste` | button 421 | At the current frame. |
| `paste reverse` | button 422 | Mirrored bone keys. |
| `paste different` | menu 250 | Pastes the copied bone keys onto the selected bone (in camera mode, the copied accessory keys onto the selected accessory). Answers the OK/Cancel question. |
| `delete` | button 423 | The selected keys. |
| `line insert bone` / `line delete bone` | menus 255 / 256 | Bone frame line, or the camera line in camera mode. |
| `line insert morph` / `line delete morph` | menus 257 / 258 | Morph frame line, or the light line in camera mode. |
| `select all bone` / `display` / `morph` | menus 217 / 218 / 220 | Keys of the selected model. |
| `select all camera` / `light` / `shadow` / `gravity` / `accessory` | menus 237 / 238 / 239 / 240 / 241 | |
| `undo` / `redo` | buttons 400 / 401 | Model mode; bone poses and bone keys only. |

Key selection is part of the saved bytes: the PMM saver writes each key's
selection byte, and registering or pasting changes which keys are selected.
A script that saves a VMD selects the keys it wants saved first.

## Scripts

| Script | Inputs | Covers |
|---|---|---|
| `empty.txt` | none | The start-up scene: `save pmm`. |
| `bones.txt` | `chain8.pmx`, `chain8.pmd` | `load model` (PMX and PMD), `select bone`, `frame`, `bone position`, `bone rotation`, `register bone`, `register display`, `select all bone`, `copy`, `paste`, `paste reverse`, `paste different`, `line insert bone`, `line delete bone`, `undo`, `redo`, `delete`, `save vmd`, `save vpd`, `save pmd`, `save pmm`. |
| `morphs.txt` | `morph4.pmx` | `select morph`, `morph`, `register morph` (all four lanes), `select all morph`, `select all display`, `copy`, `paste`, `line insert morph`, `line delete morph`, `delete`. |
| `motion.txt` | `chain8.pmx`, `morph4.pmx`, `swing600.vmd`, `pose.vpd` | `load vmd` onto a model, `load vpd`, `select model`. |
| `camera.txt` | `camera3.pmm` | `load pmm`, `select camera`, `camera position`, `camera rotation`, `camera distance`, `camera fov`, `register camera`, `light color`, `light direction`, `register light`, `shadow mode`, `shadow range`, `register shadow`, `gravity open`, `gravity magnitude`, `gravity direction`, `register gravity`, `gravity close`, `select all camera`, `select all light`, `select all shadow`, `select all gravity`, camera-mode `copy`, `paste`, `delete`, and the camera and light lines, `save vmd` of the camera, `new`, and `load vmd` onto the camera (`out/camera.vmd`). |
| `accessory.txt` | `chain8.pmx`, `inputs/tri.x`, `inputs/tone.wav` | `load accessory`, `load wav`, `select accessory`, `accessory position`, `accessory rotation`, `accessory scale`, `accessory opacity`, `accessory parent`, `register accessory`, `select all accessory`, accessory `copy`, `paste`, `delete`. |

`inputs/tri.x` is a hand-written one-triangle DirectX text mesh with one
material. `inputs/tone.wav` is 0.5 s of a 441 Hz sine, 16-bit mono 22050 Hz,
written with Python's `wave` module:
`int(8000 * sin(2 * pi * 441 * i / 22050))` for i in 0..11024.

## Not reached, and limits

- `register morph 0` and `register morph 3` run their handlers, but
  `morph4.pmx` has no eyebrow or other morph, so they only clear the key
  selection. No fixture model has morphs in those lanes.
- `paste different` runs its bone path only; the accessory path (camera mode)
  is not in a script.
- `save pmd` is not run on a PMX model, because the PMD writer ends the
  process there (`SaveEnhancedModel` in `src/window/enhance_model_io.cpp`
  reads PMD-only model data).
- Typing into an edit character by character is not modelled: each value is
  one `SetWindowTextA`. That matters for the gravity dialog, whose edits act on
  every `EN_UPDATE`.
- Bone selection by mouse is not modelled (see `select bone`).
