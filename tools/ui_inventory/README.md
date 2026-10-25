# UI inventory

`inventory.tsv` lists every user-visible function of the C++ UI, one row each. The Rust UI slices
use it as their acceptance checklist: the UI may change as long as every function stays available.

## Rule

A UI slice is done when every row of its area has a `rust` value that names the Rust action
(a function, command or widget id of the Rust UI), and `python3 tools/ui_inventory/generate.py --check`
passes. A row for a function the operator dropped (for example 3D Vision, 2026-10-25) takes
`dropped: <reason>` instead.

## Commands

```sh
python3 tools/ui_inventory/generate.py            # rewrite inventory.tsv and the counts below
python3 tools/ui_inventory/generate.py --check    # fail when either differs from the C++ sources
python3 tools/ui_inventory/generate.py --progress # rust cells filled per area
python3 tools/ui_inventory/test_generate.py       # self-check of --check
```

`--check` ignores the `rust` column, so slices fill it by hand and regeneration keeps it (matched by
`id`). A C++ change that moves a handler, renames a label or adds a menu item makes `--check` fail
until the TSV is regenerated; the diff then shows what changed for the UI slices. The script uses
only the standard library and reads `res/`, `include/` and `src/`; it never writes outside this
directory.

## Columns

`id`, `kind`, `label_ja`, `label_en`, `cpp_handler`, `area`, `rust`.

- `id` is stable: `menu:<command id>`, `ctl:<control id>`, `dlg:IDD_<name>`, `key:<chord>`,
  `mouse:<name>`, `drop:<extension>`. A chord carries a mode after `@` when the same key does two
  jobs (`key:Enter@model-mode`, `key:Enter@camera-mode`).
- `kind`: `menu`, `button`, `toggle` (push-like check box), `checkbox`, `radio`, `edit`, `combo`,
  `slider`, `scrollbar`, `dialog`, `key`, `mouse`, `drop`.
- Labels are the text the C++ application shows, mnemonics included (`&F`). A control with no
  caption shows `<kName>`, the constant in `panel_controls.hpp`. A key row takes its Japanese label
  from the command it triggers; its English label describes the action. Mouse and drop rows have no
  Japanese label.
- `cpp_handler` is `file:line` of the handler case or function. A leading `~` marks a control that
  has no `WM_COMMAND` case: the line is the first place its notification is handled (the edit
  commit, the scroll handler, the combo selection chain) or, for a button, the first code that
  mentions it. Treat `~` rows as a starting point, not as proof of the whole behavior.
- `area` is one of `file edit view background expression physics mocap help timeline play
  model-panel camera-panel light-panel accessory-panel bone-panel morph-panel shadow-panel viewport
  dialog`.

## Where the rows come from

| rows | source |
|---|---|
| menu | `res/templates/menu/menus.rc` (`SAMPLE02` Japanese, `SAMPLE02E` English), ids from `menu_commands.h`, handler = `case` in `command_dispatch.cpp`, `command_file_menu.cpp`, `command_view_menu.cpp`. Area = the top-level popup. |
| ctl | the 168 `CreateWindowEx` entries of `src/window/ui_controls.inc`; English captions from `kEnTexts` in `localize_ui.cpp`; handler = `case` in `command_frame_edit.cpp`, `command_panel_toggles.cpp`, `command_frame_register.cpp`. Area = the id range table `CONTROL_AREAS` in `generate.py`. |
| dlg | the 24 JP/EN `DIALOGEX` pairs of `dialogs.rc`, named by `dialog_resources.h`; handler = first use of the template id in `src/`. Fields inside a dialog are not separate rows: a dialog row is done when the Rust dialog offers every control of both templates. |
| key | `KEYS` in `generate.py`, hand-read from `key_ladder.cpp`, `pump_edit_keys.cpp`, `pump_navigation.cpp`. Each row names anchor strings that are searched in the C++ file to get the line; the run fails when an anchor disappears or when `key_ladder.cpp` tests a letter that `KEYS` does not list. |
| mouse | `MOUSE` in `generate.py` (same anchor rule) plus `TOOLS`, one row for each of the 21 `ViewportToolAction` hot zones of `mmd_app.hpp` (the view tools, the rotate and move gizmo handles, the bottom-right tool rows). The run fails when the enum gains a value that `TOOLS` lacks. A tool row's handler is the `Mode*` function that `frame_driver.cpp` dispatches the drag to; the bone ones continue in `BoneEditModes` (`frame_modes_bone.cpp`). The enum's own names ("CameraGizmo", "LightGizmo") do not match what the zones do, so the ids use the slugs in `TOOLS`. |
| drop | the extensions that `HandleDropFiles` dispatches in `ui_dropfiles.cpp`. |

## Counts

The block is rewritten by `generate.py` and verified by `--check`.

<!-- counts:begin -->

| kind | rows |
|---|---|
| button | 78 |
| checkbox | 9 |
| combo | 13 |
| dialog | 24 |
| drop | 13 |
| edit | 33 |
| key | 50 |
| menu | 103 |
| mouse | 41 |
| radio | 6 |
| scrollbar | 2 |
| slider | 13 |
| toggle | 14 |
| **total** | **399** |

| area | rows |
|---|---|
| file | 30 |
| edit | 27 |
| view | 31 |
| background | 13 |
| expression | 9 |
| physics | 16 |
| mocap | 6 |
| help | 7 |
| timeline | 52 |
| play | 7 |
| model-panel | 15 |
| camera-panel | 24 |
| light-panel | 16 |
| accessory-panel | 19 |
| bone-panel | 21 |
| morph-panel | 26 |
| shadow-panel | 11 |
| viewport | 45 |
| dialog | 24 |

<!-- counts:end -->

## Differences from the 9367de3 survey

- 103 menu items in 8 menus, 24 dialogs (48 `DIALOGEX`): same.
- 168 panel controls in the table, not 130: 130 is the number of distinct `case panel::k...`
  labels in `src/`, and 12 of those sit in `ui_init.cpp` and `ui_font.cpp` where they set slider
  ranges and fonts, not handle events. 118 controls have a `WM_COMMAND` case; the other 50 (edits,
  sliders, scrollbars, combos, the physics check box) are handled through the notification paths
  and carry a `~` handler.
- 77 captioned controls is the number of controls that `LocalizeUI` retitles (76 `kEnTexts`
  entries and the model/camera toggle). 94 controls carry a caption at creation; the rest keep the
  same ASCII caption in English.
- 50 key rows, not about 45: the survey did not split Ctrl and Shift variants and the Enter modes.
