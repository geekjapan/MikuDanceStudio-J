#!/usr/bin/env python3
"""Generate tools/ui_inventory/inventory.tsv, the checklist of every user-visible
function of the C++ UI.

  python3 tools/ui_inventory/generate.py            # rewrite inventory.tsv + README counts
  python3 tools/ui_inventory/generate.py --check    # fail when either is stale
  python3 tools/ui_inventory/generate.py --progress # filled rust cells per area

Menus, controls, dialogs, viewport tools and file drops are parsed from the
sources and resources. Keyboard bindings and mouse interactions are code, so
they are hand-kept tables below; every row there names an anchor string that
is searched in its C++ file, so the file:line reference follows the code and
the run fails when an anchor disappears. The `rust` column is never generated:
a rewrite carries it over by id, and --check ignores it.
"""
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
TSV = HERE / "inventory.tsv"
README = HERE / "README.md"
COLUMNS = ["id", "kind", "label_ja", "label_en", "cpp_handler", "area", "rust"]
AREAS = ["file", "edit", "view", "background", "expression", "physics", "mocap", "help",
         "timeline", "play", "model-panel", "camera-panel", "light-panel", "accessory-panel",
         "bone-panel", "morph-panel", "shadow-panel", "viewport", "dialog"]
MENU_AREAS = AREAS[:8]  # top-level popup order of menus.rc
COUNTS_BEGIN, COUNTS_END = "<!-- counts:begin -->", "<!-- counts:end -->"


class Fail(Exception):
    pass


_cache = {}


def read(rel, encoding="utf-8"):
    key = (rel, encoding)
    if key not in _cache:
        text = (ROOT / rel).read_text(encoding=encoding, errors="replace").lstrip("﻿")
        _cache[key] = text
    return _cache[key]


def line_of(rel, *anchors):
    """1-based line of the last anchor, each searched after the previous one."""
    text = read(rel)
    pos = 0
    for a in anchors:
        i = text.find(a, pos)
        if i < 0:
            raise Fail(f"anchor {a!r} not found in {rel}" + (f" after offset {pos}" if pos else ""))
        pos = i
    return text.count("\n", 0, pos) + 1


def ref(rel, *anchors):
    return f"{rel}:{line_of(rel, *anchors)}"


def c_unescape(s, wide=True):
    """Value of a C string literal body; narrow literals are Shift-JIS bytes."""
    simple = {"n": "\n", "t": "\t", '"': '"', "\\": "\\", "'": "'"}
    out = []
    for m in re.finditer(r"\\x([0-9a-fA-F]+)|\\(.)|(.)", s, re.S):
        hexv, esc, plain = m.groups()
        out.append(int(hexv, 16) if hexv else ord(simple[esc]) if esc else ord(plain))
    if wide:
        return "".join(map(chr, out))
    return bytes(out).decode("cp932", errors="replace")


# ---------------------------------------------------------------- constants

def menu_commands():
    return {m[0]: int(m[1]) for m in
            re.findall(r"#define (MDS_CMD_\w+) (\d+)", read("include/mikudancestudio/menu_commands.h"))}


def panel_ids():
    return {m[0]: int(m[1]) for m in
            re.findall(r"constexpr int (k\w+) = (\d+);", read("include/mikudancestudio/panel_controls.hpp"))}


def case_lines(rels, names, lo, hi):
    """{id: 'file:line'} for the first `case <label>:` per id in lo..hi, files in priority order."""
    out = {}
    for rel in rels:
        for m in re.finditer(r"\bcase\s+((?:\w+::\s*)?\w+)\s*:", read(rel)):
            lab = re.sub(r"\s+", "", m.group(1))
            if lab.startswith("panel::"):
                v = names.get(lab[7:])
            elif lab in names:
                v = names[lab]
            elif re.fullmatch(r"0x[0-9a-fA-F]+|\d+", lab):
                v = int(lab, 0)
            else:
                v = None
            if v is not None and lo <= v <= hi and v not in out:
                out[v] = f"{rel}:{read(rel).count(chr(10), 0, m.start()) + 1}"
    return out


# --------------------------------------------------------------------- menus

def parse_menus():
    """{template: [(area, label, command_name)]} from res/templates/menu/menus.rc (UTF-16)."""
    text = read("res/templates/menu/menus.rc", "utf-16")
    menus, cur, top = {}, None, -1
    for line in text.splitlines():
        m = re.match(r"(\w+) MENU\s*$", line)
        if m:
            cur, top = m.group(1), -1
            menus[cur] = []
        elif cur and re.match(r"    POPUP ", line):
            top += 1
        else:
            m = re.match(r'\s+MENUITEM "(.*)", (\w+)\s*$', line)
            if m and cur and m.group(2) != "0":
                menus[cur].append((MENU_AREAS[top], m.group(1), m.group(2)))
    return menus


def menu_rows(cmds):
    menus = parse_menus()
    ja, en = menus["SAMPLE02"], menus["SAMPLE02E"]
    if [x[2] for x in ja] != [x[2] for x in en]:
        raise Fail("SAMPLE02 and SAMPLE02E list different commands")
    seen = Counter(x[2] for x in ja)
    dup = [k for k, v in seen.items() if v > 1]
    if dup:
        raise Fail(f"command listed twice in the menu: {dup}")
    missing = set(cmds) - set(seen)
    if missing:
        raise Fail(f"menu_commands.h ids absent from menus.rc: {sorted(missing)}")
    handlers = case_lines(["src/window/command_dispatch.cpp", "src/window/command_file_menu.cpp",
                           "src/window/command_view_menu.cpp"], cmds, 200, 302)
    rows = []
    for (area, label_ja, name), (_, label_en, _) in zip(ja, en):
        v = cmds[name]
        rows.append([f"menu:{v}", "menu", label_ja, label_en, handlers.get(v, ""), area, ""])
    no_handler = [r[0] for r in rows if not r[4]]
    if no_handler:
        raise Fail(f"menu ids with no handler case: {no_handler}")
    return rows


# ------------------------------------------------------------------- controls

def split_top(s, sep=","):
    parts, depth, i, start = [], 0, 0, 0
    while i < len(s):
        c = s[i]
        if c == '"':
            i += 1
            while s[i] != '"':
                i += 2 if s[i] == "\\" else 1
        elif c in "{(":
            depth += 1
        elif c in "})":
            depth -= 1
        elif c == sep and depth == 0:
            parts.append(s[start:i].strip())
            start = i + 1
        i += 1
    parts.append(s[start:].strip())
    return parts


def parse_control_table():
    text = read("src/window/ui_controls.inc")
    text = re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S)
    body = text[text.index("kControls[] = {") + len("kControls[] = {"):]
    body = body[:body.index("};")]
    entries = [e[1:-1] for e in split_top(body) if e.startswith("{")]
    out = []
    for e in entries:
        f = split_top(e)
        if len(f) != 12:
            raise Fail(f"ui_controls.inc entry with {len(f)} fields: {e[:60]}")

        def string(tok):
            m = re.fullmatch(r'(L?)"(.*)"', tok, flags=re.S)
            return c_unescape(m.group(2), bool(m.group(1))) if m else None
        cls = string(f[1]) or string(f[2])
        caption = string(f[3]) if f[3] != "nullptr" else string(f[4])
        out.append({"name": f[0].removeprefix("panel::"), "cls": cls.upper(),
                    "style": int(f[5], 16), "caption": caption or ""})
    return out


def control_kind(c):
    cls, bs = c["cls"], c["style"] & 0xF
    if cls == "BUTTON":
        if bs in (4, 9) or c["name"].endswith("Radio"):
            return "radio"
        if bs in (2, 3, 5, 6):
            return "toggle" if c["style"] & 0x1000 else "checkbox"  # BS_PUSHLIKE
        return "button"
    return {"EDIT": "edit", "COMBOBOX": "combo", "MSCTLS_TRACKBAR32": "slider",
            "SCROLLBAR": "scrollbar"}[cls]


# Panel control id ranges -> area; the first range containing the id wins.
CONTROL_AREAS = [
    (400, 401, "timeline"), (402, 407, "viewport"), (408, 411, "play"), (412, 412, "camera-panel"),
    (413, 414, "play"), (415, 434, "timeline"), (435, 445, "model-panel"), (446, 448, "camera-panel"),
    (449, 450, "bone-panel"), (451, 454, "camera-panel"), (455, 470, "light-panel"),
    (471, 489, "accessory-panel"), (490, 498, "bone-panel"), (499, 499, "physics"),
    (500, 503, "bone-panel"), (504, 529, "morph-panel"), (530, 530, "physics"),
    (531, 531, "camera-panel"), (532, 533, "timeline"), (534, 534, "view"),
    (535, 535, "camera-panel"), (536, 536, "model-panel"), (537, 550, "camera-panel"),
    (551, 552, "view"), (553, 555, "timeline"), (556, 556, "shadow-panel"), (557, 557, "view"),
    (558, 559, "timeline"), (560, 567, "shadow-panel"),
]

# Where a control with no WM_COMMAND case reaches its code: (files searched for a
# reference to the control, fallback function). Handlers found this way carry a "~".
CONTROL_FALLBACK = {
    "edit": (["src/window/ui_edit_commit.cpp"], "src/window/ui_edit_commit.cpp", "void CommitEditControl("),
    "slider": (["src/window/ui_hscroll.cpp", "src/window/ui_scroll_mouse.cpp"],
               "src/window/ui_hscroll.cpp", "void HandleHScroll("),
    "scrollbar": (["src/window/ui_hscroll.cpp", "src/window/ui_scroll_mouse.cpp"],
                  "src/window/ui_hscroll.cpp", "void HandleHScroll("),
    "combo": (["src/window/command_dispatch.cpp"], "src/window/command_dispatch.cpp",
              "bool DefaultSelChangeChain("),
}
# Buttons and checkboxes without a case: the first source that mentions the control,
# skipping the files that only lay out, create, label, paint or reset it.
NOT_LOGIC = {"command_dispatch", "ui_notify", "ui_windowsize", "localize_ui", "ui_init", "reset_app_state", "ui_palette", "ui_ctlcolor"}


def first_reference(name):
    for rel in sorted(p.relative_to(ROOT).as_posix() for d in ("src/window", "src/app", "src/model")
                      for p in (ROOT / d).glob("*.cpp") if p.stem not in NOT_LOGIC):
        if re.search(rf"\bpanel::{name}\b", read(rel)):
            return "~" + ref(rel, f"panel::{name}")
    return "~" + ref("src/window/command_dispatch.cpp", "void CommandDispatch(")


def control_rows(pan):
    cases = case_lines(["src/window/command_frame_edit.cpp", "src/window/command_panel_toggles.cpp",
                        "src/window/command_frame_register.cpp"], pan, 400, 567)
    en_text = dict(re.findall(r'\{panel::(k\w+), "([^"]*)"\}', read("src/window/localize_ui.cpp")))
    m = re.search(r'Dlg\(app, panel::kModelEditToggle\), cameraMode \? "([^"]*)" : "([^"]*)"',
                  read("src/window/localize_ui.cpp"))
    en_text["kModelEditToggle"] = f"{m.group(1)}|{m.group(2)}"
    rows = []
    for c in sorted(parse_control_table(), key=lambda c: pan[c["name"]]):
        v = pan[c["name"]]
        kind = control_kind(c)
        area = next(a for lo, hi, a in CONTROL_AREAS if lo <= v <= hi)
        ja = c["caption"] or f"<{c['name']}>"
        en = en_text.get(c["name"]) or ja
        handler = cases.get(v)
        if not handler:
            if kind in CONTROL_FALLBACK:
                files, fb_file, fb_def = CONTROL_FALLBACK[kind]
                handler = next(("~" + ref(rel, f"panel::{c['name']}") for rel in files
                                if re.search(rf"\bpanel::{c['name']}\b", read(rel))),
                               "~" + ref(fb_file, fb_def))
            else:
                handler = first_reference(c["name"])
        rows.append([f"ctl:{v}", kind, ja, en, handler, area, ""])
    return rows


# -------------------------------------------------------------------- dialogs

def dialog_rows():
    rc = read("res/templates/dialog/dialogs.rc", "utf-16")
    caps = {}
    blocks = re.split(r"^(MDS_DLG_\w+) DIALOGEX", rc, flags=re.M)
    for name, block in zip(blocks[1::2], blocks[2::2]):
        m = re.search(r'^\s*CAPTION "([^"]*)"', block, re.M)
        caps[name] = m.group(1) if m else ""
    ids = re.findall(r"#define (MDS_DLG_\w+_JP) (\d+)", read("include/mikudancestudio/dialog_resources.h"))
    rows = []
    for jp, _ in ids:
        base = jp[len("MDS_DLG_"):-3]
        en = f"MDS_DLG_{base}_EN"
        if jp not in caps or en not in caps:
            raise Fail(f"dialogs.rc has no DIALOGEX/CAPTION for {jp} / {en}")
        use = next((p for p in sorted((ROOT / "src").rglob("*.cpp"))
                    if re.search(rf"\b{jp}\b", p.read_text(encoding="utf-8", errors="replace"))), None)
        if use is None:
            raise Fail(f"{jp} is not used by any source")
        rel = use.relative_to(ROOT).as_posix()
        rows.append([f"dlg:IDD_{base}", "dialog", caps[jp], caps[en], ref(rel, jp), "dialog", ""])
    return rows


# ------------------------------------------------------------ keys and mouse
# Tables of hand-read bindings. Fields: id, target row (labels and area come
# from it) or None, area when no target, English description, file, anchors.
# Anchors are searched in order; the last one's line is the cpp_handler.

KL = "src/app/key_ladder.cpp"
PE = "src/app/pump_edit_keys.cpp"
PN = "src/app/pump_navigation.cpp"
KEYS = [
    ("B", "menu:282", None, "Toggle black/white background", KL, ["'B' (0x471EB5)"]),
    ("V", "menu:214", None, "Toggle transparent models", KL, ["'V' (0x471F37)", "command case 0xD6"]),
    ("Ctrl+V", "ctl:421", None, "Paste frames (not while playing)", KL, ["'V' (0x471F37)", "kPasteButton"]),
    ("Shift+V", "menu:283", None, "Toggle model non-display", KL, ["'V' (0x471F37)", "command case 283"]),
    ("C", "ctl:490", None, "Toggle bone-select mode (model mode)", KL, ["'C' (0x4720B7)", "else if (modelMode())"]),
    ("Ctrl+C", "ctl:420", None, "Copy frames", KL, ["'C' (0x4720B7)", "kCopyFramesButton"]),
    ("H", "menu:229", None, "Register all facial frames (model mode)", KL, ["'H' (0x472324)"]),
    ("I", "menu:255", None, "Insert bone/camera frame line", KL, ["'I' (0x472375)"]),
    ("K", "menu:256", None, "Delete bone/camera frame line", KL, ["'K' (0x4723AB)"]),
    ("U", "menu:257", None, "Insert facial/light frame line", KL, ["'U' (0x4723E1)"]),
    ("J", "menu:258", None, "Delete facial/light frame line", KL, ["'J' (0x472417)"]),
    ("G", "ctl:553", None, "Go to the frame typed in the go-to-frame edit", KL, ["'G' (0x4726B2)", "Same body as command case 553"]),
    ("Shift+G", None, "shadow-panel", "Toggle the self-shadow map display", KL, ["'G' (0x4726B2)", "Shift+G"]),
    ("Ctrl+G", None, "shadow-panel", "Notice that fine-shadow mode moved to the Fshadow button", KL, ["FineShadowModeNotice(app)"]),
    ("L", None, "viewport", "Cycle the transform-channel selector (camera/light/accessory target)", KL, ["'L' (0x472804)"]),
    ("Right", "ctl:419", None, "Next frame; hold repeats after 0.4 s", PN, ["RIGHT (x86 0x472868)"]),
    ("Ctrl+Right", "ctl:532", None, "Next keyframe", PN, ["RIGHT (x86 0x472868)", "JumpNextKeyframe(app)"]),
    ("Left", "ctl:418", None, "Previous frame; hold repeats after 0.4 s", PN, ["LEFT (x86 0x4728DC)"]),
    ("Ctrl+Left", "ctl:533", None, "Previous keyframe", PN, ["LEFT (x86 0x4728DC)", "JumpPrevKeyframe(app)"]),
    ("Up", None, "timeline", "Previous edit target (camera mode) or display bone (model mode); hold repeats", PN, ["UP (x86 0x47295B)"]),
    ("Down", None, "timeline", "Next edit target (camera mode) or display bone (model mode); hold repeats", PN, ["DOWN (x86 0x4729D3)"]),
    ("Ctrl+S", "menu:207", None, "Save project (plus bell)", KL, ["Ctrl+'S' (0x472A65)"]),
    ("P", "ctl:408", None, "Play / stop", KL, ["'P' (0x472A95)"]),
    ("F", "menu:250", None, "Paste frames at a different frame", KL, ["'F' (0x472B2A)"]),
    ("X", "ctl:493", None, "Rotate bone mode (model mode)", KL, ["'X' (0x472D5C)", "ViewportEditMode::Rotate"]),
    ("Ctrl+X", "ctl:401", None, "Redo (model mode)", KL, ["'X' (0x472D5C)", "RedoModelEdit(model"]),
    ("Z", "ctl:492", None, "Move bone mode (model mode)", KL, ["'Z' (0x472ED7)", "ViewportEditMode::Move"]),
    ("Ctrl+Z", "ctl:400", None, "Undo (model mode)", KL, ["'Z' (0x472ED7)", "UndoModelEdit(model"]),
    ("A", "ctl:494", None, "Select all bones (model mode)", KL, ["'A' (0x473092)"]),
    ("S", "ctl:501", None, "Select unregistered bones (model mode)", KL, ["plain 'S' (0x4730B1)"]),
    ("D", "menu:219", None, "Center position bias dialog (model mode)", KL, ["'D' (0x4730D9)"]),
    ("R", "menu:251", None, "Bone frame multiply dialog (model mode)", KL, ["'R' (0x473989)"]),
    ("Enter@model-mode", "ctl:500", None, "Register keyframe for the selected bones", PE, ["void PumpModelEnterRegister"]),
    ("Enter@camera-mode", None, "timeline", "Register camera, light, self-shadow, gravity and accessory keys at the current frame", PE, ["G2: camera/accessory mode register"]),
    ("Alt+Enter", "menu:290", None, "Toggle full screen", PE, ["Alt held", "FullscreenMode() = app->FullscreenMode() == 0"]),
    ("Esc@fullscreen", None, "view", "Leave full screen", PE, ["state.escKeyState == 1 &&", "FullscreenMode() = 0;"]),
    ("Esc@recording", None, "file", "Stop frame-step AVI recording", PE, ["void PumpEscStop"]),
    ("]", "ctl:530", None, "Toggle the physics on/off frame checkbox", PE, ["void PumpInterpolationToggle"]),
    ("Delete", None, "timeline", "Delete the marked keyframes (rebuild model edit)", PE, ["void PumpDeleteRebuild"]),
    ("Tab", "ctl:436", None, "Next model in the model selector", PE, ["void PumpTabCycle"]),
    ("Shift+Tab", "ctl:436", None, "Previous model in the model selector", PE, ["void PumpTabCycle", "shiftModifierState == 3"]),
    ("VK226", "ctl:436", None, "Same cycle as Tab (the extra key left of Z on 102-key layouts)", PE, ["keyState226 == 1"]),
    ("Tab@panel-edits", None, "timeline", "Move between panel edit boxes (Shift reverses) and commit the opacity edit", PE, ["bool PumpPanelFocusChain"]),
    ("Numpad0", None, "viewport", "Reset the view (camera mode) or reload models and reset transforms", PN, ["NUMPAD0 (x86 0x473799"]),
    ("Numpad1", None, "viewport", "Near-ground view", PN, ["NUMPAD1 (x86 0x473848"]),
    ("Numpad2", None, "viewport", "Front view", PN, ["NUMPAD2 (x86 0x47314B"]),
    ("Numpad4", None, "viewport", "Yaw +90 degrees", PN, ["NUMPAD4 (x86 0x473282"]),
    ("Numpad5", None, "viewport", "Top view", PN, ["NUMPAD5 (x86 0x473670"]),
    ("Numpad6", None, "viewport", "Yaw -90 degrees", PN, ["NUMPAD6 (x86 0x4733CC"]),
    ("Numpad8", None, "viewport", "Yaw 180 degrees", PN, ["NUMPAD8 (x86 0x473520"]),
]

FM = "src/app/frame_modes.cpp"
FMB = "src/app/frame_modes_bone.cpp"
UEC = "src/window/ui_editor_click.cpp"
UMM = "src/window/ui_mousemove.cpp"
MOUSE = [
    ("bone-pick", "viewport", "Click a bone marker to select it; Shift toggles; repeated clicks cycle overlapping markers", FM, ["void PickBoneAtCursor"]),
    ("bone-box-select", "viewport", "Drag a box to select bones (BOX select mode); Shift adds", FM, ["void UpdateBoneBoxSelection"]),
    ("bone-drag", "viewport", "Left drag on a gizmo handle edits the selected bones; Shift coarse (x5), Ctrl fine (x0.1); all selected root bones follow", FMB, ["void BoneEditModes"]),
    ("record-drag", "viewport", "While an accessory or light record is edited the same gizmo drags edit its fields instead of a bone", FMB, ["bool EditModeRecord"]),
    ("rmb-drag", "viewport", "Right drag: orbit the camera (yaw/pitch)", PN, ["void ConsumeRightButtonDrag", "CameraYaw() = app->CameraYaw() -"]),
    ("shift-rmb-drag", "viewport", "Shift + right drag: pan the view offsets (model mode)", PN, ["void ConsumeRightButtonDrag", "modelMode && app->ShiftModifierActive()"]),
    ("ctrl-rmb-drag", "viewport", "Ctrl + right drag: dolly the camera distance", PN, ["void ConsumeRightButtonDrag", "else if (app->CtrlModifierActive())"]),
    ("mmb-drag", "viewport", "Middle drag: pan the view offsets (model mode) or the camera target; Shift fast, Ctrl fine", PN, ["void ConsumeMiddleButtonPan"]),
    ("wheel", "viewport", "Wheel: dolly the camera distance or the camera target; over the timeline strip while playing it scrolls the strip", "src/window/ui_scroll_mouse.cpp", ["void HandleMouseWheel"]),
    ("timeline-margin-click", "timeline", "Click the margin column of a row to toggle its display flag", UEC, ["void HandleLButtonDown_MarginColumnToggle"]),
    ("timeline-name-click", "timeline", "Click a bone/morph row name to select the row and insert a key", UEC, ["void HandleLButtonDown_NameColumnHit"]),
    ("timeline-cell-click", "timeline", "Click timeline cells to select keys or ranges", UEC, ["void HandleLButtonDown_TimelineAreaHit"]),
    ("timeline-frame-strip-click", "timeline", "Click the frame strip to set the current frame", UEC, ["void HandleLButtonDown_FrameStripHit"]),
    ("timeline-name-rect-click", "timeline", "Click the bone/morph name rectangles to insert a key and mark the row", UEC, ["void HandleLButtonDown_NameRowRectHit"]),
    ("timeline-dblclick", "timeline", "Double click the frame strip to jump to that frame and reload the models", "src/window/ui_mouse_misc.cpp", ["void HandleLButtonDblClk"]),
    ("timeline-key-drag", "timeline", "Drag selected keys sideways to move them to other frames", UMM, ["void HandleMouseMove", "RemapList(app,"]),
    ("timeline-hover", "timeline", "Hover highlight of timeline rows and cells", UMM, ["void HandleMouseMove", "5. hover highlight"]),
    ("curve-point-drag", "timeline", "Drag the interpolation curve control points", UMM, ["void HandleMouseMove", "DragInterpolationControlPoint(app)"]),
    ("sidebar-resize", "view", "Drag the sidebar edge to resize it", UMM, ["void HandleMouseMove", "3. sidebar drag"]),
    ("rmb-dblclick", "viewport", "Right double click: switch the panel mode and park the cursor on the viewport tools", "src/window/ui_mouse_misc.cpp", ["void HandleMouseActivate"]),
]
# ViewportToolAction value -> (id slug, what the drag does, file, anchors). Zones are hit-tested by
# ViewportToolAtPoint and dispatched by the drag-mode switch in frame_driver.cpp.
TOOLS = {
    1: ("view-dolly", "Top-right view tool 1: left drag dollies the camera distance", FM, ["viewMode == ViewportToolAction::CameraOrbit"]),
    2: ("view-pan", "Top-right view tool 2: left drag pans the view offsets (model mode) or the camera target", FM, ["viewMode == ViewportToolAction::CameraPan"]),
    3: ("rotate-gizmo-x", "Rotate mode, horizontal gizmo handle: rotate the selected bones around the camera X axis", FM, ["void ModeRotate"]),
    4: ("rotate-gizmo-y", "Rotate mode, vertical gizmo handle: rotate the selected bones around the camera Y axis", FM, ["void ModeRotate"]),
    5: ("rotate-gizmo-ring", "Rotate mode, gizmo ring: rotate the selected bones in the view plane", FM, ["void ModeRotate"]),
    6: ("move-gizmo-horizontal", "Move mode, right gizmo handle: move the selected root bones horizontally", FM, ["void ModeScale"]),
    7: ("move-gizmo-vertical", "Move mode, upper gizmo handle: move the selected bones vertically", FM, ["void ModeBoneRotate"]),
    8: ("move-gizmo-plane", "Move mode, center gizmo handle: move the selected bones in the screen plane", FM, ["void ModeBoneRotate"]),
    9: ("model-local-rotate-x", "Model mode, upper tool row X: rotate the selected bones around their local X axis", FM, ["void ModeTranslate"]),
    10: ("model-local-rotate-y", "Model mode, upper tool row Y: rotate the selected bones around their local Y axis", FM, ["void ModeTranslate"]),
    11: ("model-local-rotate-z", "Model mode, upper tool row Z: rotate the selected bones around their local Z axis", FM, ["void ModeTranslate"]),
    12: ("model-local-translate-x", "Model mode, lower tool row X: translate along the local X axis or edit the physics-body record", FM, ["void ModePhysicsBody"]),
    13: ("model-local-translate-y", "Model mode, lower tool row Y: translate along the local Y axis or edit the physics-body record", FM, ["void ModePhysicsBody"]),
    14: ("model-local-translate-z", "Model mode, lower tool row Z: translate along the local Z axis or edit the physics-body record", FM, ["void ModePhysicsBody"]),
    15: ("camera-move-x", "Camera mode, lower tool row X: move the camera (or the selected accessory) along X", FM, ["void ModeCameraAdjust"]),
    16: ("camera-move-y", "Camera mode, lower tool row Y: move the camera (or the selected accessory) along Y", FM, ["void ModeCameraAdjust"]),
    17: ("camera-move-z", "Camera mode, lower tool row Z: move the camera (or the selected accessory) along Z", FM, ["void ModeCameraAdjust"]),
    18: ("camera-rotate-x", "Camera mode, upper tool row X: rotate the camera (or the selected accessory) around X", FM, ["void ModeAngleAdjust"]),
    19: ("camera-rotate-y", "Camera mode, upper tool row Y: rotate the camera (or the selected accessory) around Y", FM, ["void ModeAngleAdjust"]),
    20: ("camera-rotate-z", "Camera mode, upper tool row Z: rotate the camera (or the selected accessory) around Z", FM, ["void ModeAngleAdjust"]),
    21: ("coordinate-cycle", "Click the coordinate-system tool to cycle the transform target (camera, light, accessory)", FM, ["void BeginOrEndViewportToolDrag", "operation == 21"]),
}


def keymouse_rows(rows_by_id):
    rows = []
    for kid, target, area, desc, rel, anchors in KEYS:
        if target:
            t = rows_by_id[target]
            ja, area = t[2], t[5]
        else:
            ja = ""
        rows.append([f"key:{kid}", "key", ja, desc, ref(rel, *anchors), area, ""])
    # Letter keys the pump polls must all be listed (a new hotkey must not slip through).
    listed = {k[0] for k in KEYS}
    for letter in set(re.findall(r"pressed\(LetterKey::(\w)\)", read(KL))):
        if not any(k == letter or k.endswith("+" + letter) for k in listed):
            raise Fail(f"key_ladder.cpp tests LetterKey::{letter}, which KEYS does not list")
    for mid, area, desc, rel, anchors in MOUSE:
        rows.append([f"mouse:{mid}", "mouse", "", desc, ref(rel, *anchors), area, ""])
    enum = re.search(r"enum class ViewportToolAction[^{]*\{(.*?)\};", read("include/mikudancestudio/mmd_app.hpp"), re.S)
    values = {int(v): n for n, v in re.findall(r"(\w+) = (\d+),", enum.group(1)) if v != "0"}
    if set(values) != set(TOOLS):
        raise Fail(f"ViewportToolAction values {sorted(values)} differ from TOOLS {sorted(TOOLS)}")
    for val in values:
        slug, desc, rel, anchors = TOOLS[val]
        rows.append([f"mouse:tool-{slug}", "mouse", "", desc, ref(rel, *anchors), "viewport", ""])
    for ext in dict.fromkeys(re.findall(r'wcsstr\(szFile, L"\.([a-z]+)"\)', read("src/window/ui_dropfiles.cpp"))):
        rows.append([f"drop:{ext}", "drop", "", f"Drop a .{ext} file on the window to load it",
                     ref("src/window/ui_dropfiles.cpp", f'L".{ext}"'), "file", ""])
    return rows


# --------------------------------------------------------------------- output

def build_rows():
    cmds, pan = menu_commands(), panel_ids()
    rows = menu_rows(cmds) + control_rows(pan) + dialog_rows()
    rows += keymouse_rows({r[0]: r for r in rows})
    ids = [r[0] for r in rows]
    dup = [k for k, v in Counter(ids).items() if v > 1]
    if dup:
        raise Fail(f"duplicate inventory ids: {dup}")
    for r in rows:
        if r[5] not in AREAS:
            raise Fail(f"{r[0]}: unknown area {r[5]!r}")
        r[:] = [re.sub(r"[\t\r\n]+", " ", f) for f in r]
    return rows


def read_tsv():
    if not TSV.exists():
        return []
    lines = TSV.read_text(encoding="utf-8").split("\n")
    if lines[0].split("\t") != COLUMNS:
        raise Fail(f"{TSV.name}: header is not {COLUMNS}")
    return [l.split("\t") for l in lines[1:] if l]


def counts_block(rows):
    kinds, areas = Counter(r[1] for r in rows), Counter(r[5] for r in rows)
    out = [COUNTS_BEGIN, "", "| kind | rows |", "|---|---|"]
    out += [f"| {k} | {kinds[k]} |" for k in sorted(kinds)]
    out += [f"| **total** | **{len(rows)}** |", "", "| area | rows |", "|---|---|"]
    out += [f"| {a} | {areas[a]} |" for a in AREAS if areas[a]]
    out += ["", COUNTS_END]
    return "\n".join(out)


def readme_with(rows):
    text = README.read_text(encoding="utf-8")
    pat = re.compile(re.escape(COUNTS_BEGIN) + ".*?" + re.escape(COUNTS_END), re.S)
    if not pat.search(text):
        raise Fail("README.md has no counts markers")
    return pat.sub(lambda _: counts_block(rows), text)


def main(argv):
    mode = argv[1] if len(argv) > 1 else ""
    if mode not in ("", "--check", "--progress"):
        print(__doc__)
        return 2
    old = read_tsv()
    rust = {r[0]: r[6] for r in old}
    if mode == "--progress":
        for a in AREAS:
            rs = [r for r in old if r[5] == a]
            if rs:
                print(f"{a:16} {sum(1 for r in rs if r[6])}/{len(rs)}")
        return 0
    rows = build_rows()
    if mode == "--check":
        got = {r[0]: r[:6] for r in old}
        want = {r[0]: r[:6] for r in rows}
        bad = [i for i in want if got.get(i) != want[i]] + [i for i in got if i not in want]
        if bad or [r[0] for r in old] != [r[0] for r in rows]:
            first = bad[0] if bad else "(row order)"
            print(f"inventory.tsv is stale: {len(bad)} rows differ, first {first}\n"
                  f"  have {got.get(first)}\n  want {want.get(first)}\nrun generate.py", file=sys.stderr)
            return 1
        if readme_with(rows) != README.read_text(encoding="utf-8"):
            print("README.md counts are stale; run generate.py", file=sys.stderr)
            return 1
        print(f"ok: {len(rows)} rows")
        return 0
    lost = [i for i in rust if rust[i] and i not in {r[0] for r in rows}]
    if lost:
        print(f"warning: rust values of removed rows dropped: {lost}", file=sys.stderr)
    for r in rows:
        r[6] = rust.get(r[0], "")
    TSV.write_text("\n".join("\t".join(r) for r in [COLUMNS] + rows) + "\n", encoding="utf-8", newline="\n")
    README.write_text(readme_with(rows), encoding="utf-8", newline="\n")
    print(f"wrote {len(rows)} rows")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except Fail as e:
        print(f"generate.py: {e}", file=sys.stderr)
        sys.exit(1)
