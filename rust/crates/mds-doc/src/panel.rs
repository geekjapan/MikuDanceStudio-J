//! The model, bone, timeline, view and play panel commands that write a few
//! fields: `src/window/command_panel_toggles.cpp`, `command_frame_edit.cpp`,
//! `command_frame_register.cpp`, `command_dispatch.cpp`,
//! `bone_pose_edit.cpp`, `bone_pose_clipboard.cpp`, `ui_editor_click.cpp`,
//! `ui_scroll_mouse.cpp`, `command_file_menu.cpp` and
//! `command_view_menu.cpp`.

use crate::history::{snapshot, Entry, PoseSnapshot};
use crate::{not, refresh, Document, Error, Track};
use mds_formats::key_pool::KeyPool;
use mds_formats::pmm;
use mds_math::{Mat4, Quat};
use mds_pose::model::Model as PoseModel;

/// A model check box of the model panel.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ModelFlag {
    /// 439 (表示): `loadComplete`.
    Visible,
    /// 440 (影): `toonFlag`, `pmm::Model::toon`.
    Shadow,
    /// 441 (加算): `postLoadFlag2`, `pmm::Model::post_load`.
    AddBlend,
}

/// A view menu switch the PMM stores.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ViewOption {
    /// 211, `fpsOverlayEnabled`.
    Information,
    /// 215, `groundGridEnabled`.
    CoordinateAxis,
    /// 221, `groundShadowEnabled`.
    GroundShadow,
    /// 254, `projectedShadowBlendEnabled`.
    GroundShadowTransparency,
    /// 279, `selfShadowEnabled`, the byte `pmm.self_shadow_mode` (not the
    /// 0/1/2 radio of the self-shadow panel).
    SelfShadow,
}

/// The bone-pose clipboard of buttons 496..498 (`BoneCopyRecords`): name,
/// translation and rotation of each selected bone, in bone order.
pub type BonePoseClipboard = Vec<(Vec<u8>, [f32; 3], [f32; 4])>;

/// `kInterpCurveCombo` rows of the curve clipboard (`lightA..lightD`): the
/// four bytes of one curve channel per row.
pub type CurveClipboard = [[u8; 4]; 6];

fn cstr(s: &[u8]) -> &[u8] {
    &s[..s.iter().position(|&b| b == 0).unwrap_or(s.len())]
}

fn find(hay: &[u8], needle: &[u8]) -> Option<usize> {
    hay.windows(needle.len()).position(|w| w == needle)
}

/// The world position of a model's bone in the saved pose, as the frame loop
/// leaves `BoneRecord::matInit` without physics.
fn bone_world(file: &crate::ModelFile, m: &pmm::Model, bone: usize, mode: u8) -> Option<[f64; 3]> {
    let mut pose = match file {
        crate::ModelFile::Pmx(p) => PoseModel::from_pmx(m.slot, p).ok()?,
        crate::ModelFile::Pmd(p) => PoseModel::from_pmd(m.slot, p).ok()?,
        crate::ModelFile::Missing => return None,
    };
    pose.apply_pmm(m).ok()?;
    mds_pose::pose::apply_morphs(&mut pose);
    mds_pose::pose::set_physics_mode(&mut pose, 0, &mds_pose::pose::Others::NONE, i32::from(mode));
    let b = pose.bones.get(bone)?;
    let (p, t) = (b.position.map(f64::from), b.mat_init.0.map(f64::from));
    Some(std::array::from_fn(|c| {
        p[1] * t[4 + c] + p[0] * t[c] + p[2] * t[8 + c] + t[12 + c]
    }))
}

impl Document {
    /// The frame-strip click (`HandleLButtonDown_FrameStripHit`,
    /// `ui_editor_click.cpp` 791-923): every model with an edited bone
    /// pushes `SnapshotPoseBeforeFrameChange` at the frame it leaves and
    /// loses its edited marks (`bonePhysicsState`); the bone selection
    /// stays. Then the same seek, scroll and camera-mode refresh as
    /// [`crate::Command::SetFrame`].
    pub(crate) fn click_frame(&mut self, frame: u32) {
        let old = self.frame();
        for (m, e) in self.pmm.models.iter_mut().zip(&mut self.edit.models) {
            if m.bone_pose.iter().any(|p| p.flags[1] != 0) {
                crate::model::push_frame_change(m, &mut e.history, old);
                m.bone_pose.iter_mut().for_each(|p| p.flags[1] = 0);
            }
        }
        self.pmm.timeline.current_frame = frame as i32;
        self.seek_frame();
    }

    /// Button 494 (`command_panel_toggles.cpp` 658-690): selects every bone
    /// of type 0..6 or fixed axis, adding to the selection, and the bone
    /// edit mode.
    pub(crate) fn select_all_bones(&mut self) -> Result<(), Error> {
        let (i, f) = self.ops_model()?;
        for (p, b) in self.pmm.models[i].bone_pose.iter_mut().zip(&f.bones) {
            let fixed = (b.kind == 4 && b.flags & 0x400 != 0) || b.kind == 8;
            if fixed || b.kind <= 6 {
                p.flags[2] = 1;
            }
        }
        self.pmm.timeline.edit_mode = 0;
        Ok(())
    }

    /// Button 501 and key S (`command_frame_register.cpp` 399-420): the
    /// selection becomes the edited bones, `selectedBone` -1, edit mode bone.
    pub(crate) fn select_unregistered_bones(&mut self) -> Result<(), Error> {
        let m = self.model_mode_model()?;
        m.selection.selected_bone = -1;
        for p in &mut m.bone_pose {
            p.flags[2] = u8::from(p.flags[1] != 0);
        }
        self.pmm.timeline.edit_mode = 0;
        Ok(())
    }

    fn model_mode_model(&mut self) -> Result<&mut pmm::Model, Error> {
        if self.camera_mode() {
            return Err(not("the model panel is hidden in camera mode"));
        }
        let i = self.active_model()?;
        Ok(&mut self.pmm.models[i])
    }

    /// Button 495, `ResetSelectedBonePose` (`bone_pose_edit.cpp` 25-143),
    /// after `PushBoneEditUndo` of the selected bones. Bone 0 loses its Y
    /// and rotation; another root bone takes bone 0's rotation and the
    /// position that keeps its rest point where bone 0's translation puts
    /// it (single precision, the x64 path); any other bone becomes the
    /// identity. A bone that changes is marked edited.
    pub(crate) fn reset_bone_pose(&mut self) -> Result<(), Error> {
        if self.camera_mode() {
            return Err(not("the bone panel is hidden in camera mode"));
        }
        let i = self.active_model()?;
        let pose = match &self.models[i] {
            crate::ModelFile::Pmx(p) => PoseModel::from_pmx(self.pmm.models[i].slot, p),
            crate::ModelFile::Pmd(p) => PoseModel::from_pmd(self.pmm.models[i].slot, p),
            crate::ModelFile::Missing => return Err(not("the model file is missing")),
        }
        .map_err(Error::Format)?;
        let m = &mut self.pmm.models[i];
        if pose.bones.len() != m.bone_pose.len() {
            return Err(not("the model file does not match the PMM"));
        }
        crate::model::push_pose_edit(m, &mut self.edit.models[i].history);
        let b = &mut m.bone_pose;
        if b.first().is_some_and(|p| p.flags[2] != 0) {
            b[0].translation[1] = 0.0;
            b[0].rotation = [0.0, 0.0, 0.0, 1.0];
        }
        for n in 1..b.len() {
            if b[n].flags[2] == 0 {
                continue;
            }
            let (want_t, want_r) = if pose.bones[n].parent == -1 {
                let t = Mat4::rotation_quaternion(Quat(b[n].rotation)).0;
                let p = pose.bones[n].position;
                let r0 = b[0].translation;
                let at = |c: usize| {
                    p[0] * t[c] + p[1] * t[4 + c] + p[2] * t[8 + c] + t[12 + c] - p[c] + r0[c]
                };
                ([at(0), at(1), at(2)], b[0].rotation)
            } else {
                ([0.0; 3], [0.0, 0.0, 0.0, 1.0])
            };
            if b[n].translation != want_t || b[n].rotation != want_r {
                b[n].translation = want_t;
                b[n].rotation = want_r;
                b[n].flags[1] = 1;
            }
        }
        Ok(())
    }

    /// `BoneRotEdit` (`command_frame_register.cpp` 307-358), the model-mode
    /// path: `PushBoneEditUndo`, then the edited axis is zeroed and the
    /// other two boxes go from degrees to radians, X with float pi and Y, Z
    /// negated with double pi; the selected bone takes the quaternion of
    /// Rz * Rx * Ry and is marked edited. The typed value itself is dropped,
    /// as in the C++. Nothing without a selected bone.
    pub(crate) fn zero_bone_rotation_axis(
        &mut self,
        axis: u8,
        degrees: [f32; 3],
    ) -> Result<(), Error> {
        const PI: f64 = std::f64::consts::PI; // dbl_52B768
        const PI_F: f64 = 3.1415927410125732;
        let i = self.active_model()?;
        if self.camera_mode() {
            return Err(not(
                "the bone rotation boxes edit the camera in camera mode",
            ));
        }
        let m = &mut self.pmm.models[i];
        let Ok(sel) = usize::try_from(m.selection.selected_bone) else {
            return Ok(());
        };
        if sel >= m.bone_pose.len() {
            return Ok(());
        }
        crate::model::push_pose_edit(m, &mut self.edit.models[i].history);
        let [x, y, z] = degrees.map(f64::from);
        let x = if axis == 0 {
            0.0
        } else {
            (x * PI_F / 180.0) as f32
        };
        let y = if axis == 1 {
            0.0
        } else {
            (-y * PI / 180.0) as f32
        };
        let z = if axis >= 2 {
            0.0
        } else {
            (-z * PI / 180.0) as f32
        };
        let r = Mat4::multiply(&Mat4::rotation_z(z), &Mat4::rotation_x(x));
        let r = Mat4::multiply(&r, &Mat4::rotation_y(y));
        m.bone_pose[sel].rotation = Quat::from_matrix(&r).0;
        m.bone_pose[sel].flags[1] = 1;
        Ok(())
    }

    /// `DeleteSelectedAccessory` (`command_panel_toggles.cpp` 220-321): the
    /// record and its keys go, the orders above close up, and the accessory
    /// of order 0 (else slot 0) becomes the selected one.
    /// `accessory_render_order` and the edit mode stay.
    pub(crate) fn delete_accessory(&mut self, slot: u8) -> Result<(), Error> {
        let p = &mut self.pmm;
        let at = p
            .accessories
            .iter()
            .position(|a| a.slot == slot)
            .ok_or(not("no accessory in that slot"))?;
        let old = p.accessories.remove(at).order;
        for a in &mut p.accessories {
            if a.order > old {
                a.order -= 1;
            }
        }
        p.selected_accessory_slot = p
            .accessories
            .iter()
            .find(|a| a.order == 0)
            .map_or(0, |a| a.slot);
        Ok(())
    }

    /// Button 496, `CopySelectedBonePose` (`bone_pose_clipboard.cpp` 34-86):
    /// the saved pose of the selected bones. Nothing selected leaves the
    /// clipboard as it was.
    pub(crate) fn copy_bone_pose(&mut self) -> Result<(), Error> {
        let m = self.model_mode_model()?;
        let clip: BonePoseClipboard = m
            .bone_names
            .iter()
            .zip(&m.bone_pose)
            .filter(|(_, p)| p.flags[2] != 0)
            .map(|(n, p)| (cstr(&n.raw).to_vec(), p.translation, p.rotation))
            .collect();
        if !clip.is_empty() {
            self.edit.bone_pose_clipboard = clip;
        }
        Ok(())
    }

    /// Buttons 497 and 498 (`bone_pose_clipboard.cpp` 89-292): the selection
    /// is cleared, then each copied pose goes onto the first bone of its name
    /// (497) or onto its mirror bone, x of the translation and y, z of the
    /// rotation negated (498, the bone itself when its name has neither 左
    /// nor 右), which becomes selected, edited and `selectedBone`. One
    /// `BonePose` undo entry has a snapshot per copied record; a record whose
    /// name no bone has keeps a zero snapshot, which undo writes onto bone 0
    /// (the C++ behavior).
    pub(crate) fn paste_bone_pose(&mut self, mirror: bool) -> Result<(), Error> {
        if self.edit.bone_pose_clipboard.is_empty() {
            return Ok(());
        }
        if self.camera_mode() {
            return Err(not("the bone panel is hidden in camera mode"));
        }
        let i = self.active_model()?;
        let clip = self.edit.bone_pose_clipboard.clone();
        let m = &mut self.pmm.models[i];
        m.bone_pose.iter_mut().for_each(|p| p.flags[2] = 0);
        let named =
            |m: &pmm::Model, name: &[u8]| m.bone_names.iter().position(|n| cstr(&n.raw) == name);
        let mut snaps = Vec::with_capacity(clip.len());
        for (name, t, r) in &clip {
            let zero = PoseSnapshot {
                bone: 0,
                translation: [0.0; 3],
                rotation: [0.0; 4],
                edited: 0,
            };
            let Some(source) = named(m, name) else {
                snaps.push(zero);
                continue;
            };
            let target = if mirror {
                mirror_target(m, name).unwrap_or(source)
            } else {
                source
            };
            snaps.push(snapshot(m, [target].into_iter()).remove(0));
            let p = &mut m.bone_pose[target];
            p.flags[2] = 1;
            if mirror {
                p.translation = [-t[0], t[1], t[2]];
                p.rotation = [r[0], -r[1], -r[2], r[3]];
            } else {
                p.translation = *t;
                p.rotation = *r;
            }
            p.flags[1] = 1;
            m.selection.selected_bone = target as i32;
        }
        self.edit.models[i].history.push(Entry::BonePose(snaps));
        Ok(())
    }

    /// The camera parent model combo (449, `command_dispatch.cpp` 203-271).
    /// Attaching to a model clears the camera position and rotation when
    /// there was no parent before, and the parent bone becomes 0. Detaching
    /// moves the camera to the parent bone's world position, distance -20
    /// and no rotation.
    pub(crate) fn set_camera_parent_model(&mut self, slot: Option<u8>) {
        let a = &self.pmm.appearance;
        match slot.filter(|s| self.pmm.models.iter().any(|m| m.slot == *s)) {
            Some(s) => {
                if a.camera_parent_model < 0 {
                    self.pmm.camera_state[..3].fill(0.0);
                    self.pmm.camera_state[6..].fill(0.0);
                }
                let a = &mut self.pmm.appearance;
                a.camera_parent_model = i32::from(s);
                a.camera_parent_bone = 0;
            }
            None if slot.is_some() => {}
            None => {
                let parent = a.camera_parent_model;
                let bone = a.camera_parent_bone.max(0) as usize;
                let mode = self.pmm.physics.playback_mode;
                if let Some(i) = self
                    .pmm
                    .models
                    .iter()
                    .position(|m| i32::from(m.slot) == parent)
                {
                    if let Some(w) = bone_world(&self.models[i], &self.pmm.models[i], bone, mode) {
                        for (c, v) in w.into_iter().enumerate() {
                            self.pmm.camera_state[c] = v as f32;
                        }
                    }
                    self.pmm.camera_state[5] = -20.0;
                    self.pmm.camera_state[6..].fill(0.0);
                }
                self.pmm.appearance.camera_parent_model = -1;
            }
        }
    }

    /// The camera parent bone combo (450, `command_dispatch.cpp` 277-293):
    /// with a parent model, the bone.
    pub(crate) fn set_camera_parent_bone(&mut self, bone: u32) -> Result<(), Error> {
        let parent = self.pmm.appearance.camera_parent_model;
        if parent < 0 {
            return Ok(());
        }
        let m = self.pmm.models.iter().find(|m| i32::from(m.slot) == parent);
        if m.is_none_or(|m| bone as usize >= m.bone_names.len()) {
            return Err(not("no such bone"));
        }
        self.pmm.appearance.camera_parent_bone = bone as i32;
        Ok(())
    }

    /// Menu 247 (`command_file_menu.cpp` 1769-1819). Turning it on zeroes the
    /// view offset and refreshes the camera, light, self-shadow, gravity and
    /// accessory state; in model mode the attachment transform is no longer
    /// suppressed. Turning it off in model mode with the selected model as
    /// the camera parent does the same to the suppression.
    pub(crate) fn set_follow_camera(&mut self, on: bool) {
        let p = &mut self.pmm;
        p.appearance.follow_camera = u8::from(on);
        if on {
            p.camera_state[3] = 0.0;
            p.camera_state[4] = 0.0;
            refresh::camera(p);
            refresh::light(p);
            refresh::self_shadow(p, &mut self.edit.self_shadow_mode);
            refresh::gravity(p);
            let frame = p.timeline.current_frame as u32;
            for a in &mut p.accessories {
                refresh::accessory(a, frame);
            }
            if p.settings.options[0] == 0 {
                p.appearance.suppress_camera_transform = 0;
            }
        } else if p.settings.options[0] == 0 {
            let parent = p.appearance.camera_parent_model;
            if parent >= 0 && parent == i32::from(p.selected_model_slot) {
                p.appearance.suppress_camera_transform = 0;
            }
        }
    }

    /// Copy curve (`CopyInterpolationCurve`, `command_frame_edit.cpp`
    /// 987-1025) from the first marked camera key or bone key (lowest
    /// record index). `channel` is the curve combo: 0..5 camera (6 all), 0..3
    /// bone (4 all). One channel fills every row; "all" fills one row per
    /// channel. No marked key changes nothing.
    pub(crate) fn copy_curve(&mut self, channel: u8) -> Result<(), Error> {
        let sel = usize::from(channel);
        if self.pmm.settings.options[0] != 0 {
            let Some(k) = first_marked(&self.pmm.camera, |k| k.selected != 0) else {
                return Ok(());
            };
            for (row, c) in self.edit.curve_clipboard.iter_mut().enumerate() {
                let ch = if sel < 6 { sel } else { row };
                *c = std::array::from_fn(|r| k.interpolation[r][ch]);
            }
            return Ok(());
        }
        let i = self.active_model()?;
        let Some(k) = first_marked(&self.pmm.models[i].bone_keys, |k| k.allocated != 0) else {
            return Ok(());
        };
        let rows = if sel < 4 { 6 } else { 4 };
        let clip = &mut self.edit.curve_clipboard;
        for (row, c) in clip.iter_mut().enumerate().take(rows) {
            let ch = if sel < 4 { sel } else { row };
            *c = std::array::from_fn(|r| k.interpolation[4 * r + ch]);
        }
        Ok(())
    }

    /// Paste curve (`PasteInterpolationCurve`, 1033-1075) or reset curve
    /// (`ResetInterpolationCurves`, 1082-1124, the bytes 20, 20, 107, 107)
    /// on every marked camera key or bone key; one channel takes its own row.
    /// The bone variant pushes a `SnapshotSelectedKeysForUndo` entry first.
    pub(crate) fn write_curve(&mut self, channel: u8, reset: bool) -> Result<(), Error> {
        let sel = usize::from(channel);
        let clip = self.edit.curve_clipboard;
        let row = |ch: usize| if reset { [20, 20, 107, 107] } else { clip[ch] };
        if self.pmm.settings.options[0] != 0 {
            let channels = if sel < 6 { sel..sel + 1 } else { 0..6 };
            for_marked(
                &mut self.pmm.camera,
                |k| k.selected != 0,
                |k| {
                    for ch in channels.clone() {
                        for (r, v) in row(ch).into_iter().enumerate() {
                            k.interpolation[r][ch] = v;
                        }
                    }
                },
            );
            return Ok(());
        }
        let i = self.active_model()?;
        self.push_marked_undo(i);
        let channels = if sel < 4 { sel..sel + 1 } else { 0..4 };
        for_marked(
            &mut self.pmm.models[i].bone_keys,
            |k| k.allocated != 0,
            |k| {
                for ch in channels.clone() {
                    for (r, v) in row(ch).into_iter().enumerate() {
                        k.interpolation[4 * r + ch] = v;
                    }
                }
            },
        );
        Ok(())
    }

    /// The curve editor drag, `DragInterpolationControlPoint`
    /// (`ui_selection_reeval.cpp` 115-232): the start (`end == false`) or end
    /// control point of the combo's channel (all channels when it is past
    /// the last) on every marked bone key, or camera key in camera mode.
    /// The point is clamped to 0..127. No undo.
    pub(crate) fn set_curve_point(
        &mut self,
        channel: u8,
        end: bool,
        point: [i32; 2],
    ) -> Result<(), Error> {
        let sel = usize::from(channel);
        let [x, y] = point.map(|v| v.clamp(0, 127) as u8);
        if self.pmm.settings.options[0] != 0 {
            let channels = if sel < 6 { sel..sel + 1 } else { 0..6 };
            let r = if end { 2 } else { 0 };
            for_marked(
                &mut self.pmm.camera,
                |k| k.selected != 0,
                |k| {
                    for ch in channels.clone() {
                        k.interpolation[r][ch] = x;
                        k.interpolation[r + 1][ch] = y;
                    }
                },
            );
            return Ok(());
        }
        let i = self.active_model()?;
        let channels = if sel < 4 { sel..sel + 1 } else { 0..4 };
        let base = if end { 8 } else { 0 };
        for_marked(
            &mut self.pmm.models[i].bone_keys,
            |k| k.allocated != 0,
            |k| {
                for ch in channels.clone() {
                    k.interpolation[base + ch] = x;
                    k.interpolation[base + 4 + ch] = y;
                }
            },
        );
        Ok(())
    }

    /// The margin column click (`HandleLButtonDown_MarginColumnToggle`,
    /// `ui_editor_click.cpp` 439-453): the display group's fold flag.
    pub(crate) fn toggle_display_group(&mut self, group: u8) -> Result<(), Error> {
        let m = self.model_mode_model()?;
        let f = m
            .selection
            .group_flags
            .get_mut(usize::from(group))
            .filter(|_| group > 0)
            .ok_or(not("no such display group"))?;
        *f = u8::from(*f == 0);
        Ok(())
    }

    /// A plain click on an unmarked key (`ToggleModelKeyAllocated` and
    /// `ToggleTimelineCell`, `ui_editor_click.cpp` 347-414): the marks of the
    /// mode (the active model's three pools, or every camera-mode track) are
    /// cleared first.
    pub(crate) fn clear_mode_marks(&mut self, track: Track) -> Result<(), Error> {
        match track {
            Track::Global(_) => crate::global::clear_selection(&mut self.pmm),
            _ => {
                let i = self.active_model()?;
                let mut cursor = self.edit.models[i].search_cursor;
                crate::model::with_tracks(&mut self.pmm.models[i], &mut cursor, |t| {
                    t.clear_marks()
                });
            }
        }
        Ok(())
    }
}

/// The bone named as `name` with 左 and 右 swapped (`bone_pose_clipboard.cpp`
/// 235-264), `None` when the name has neither or no bone has the other name.
fn mirror_target(m: &pmm::Model, name: &[u8]) -> Option<usize> {
    const LEFT: &[u8] = b"\x8D\xB6";
    const RIGHT: &[u8] = b"\x89\x45";
    let opposite = |marker: &[u8], other: &[u8]| {
        let suffix = &name[find(name, marker)? + 2..];
        Some(m.bone_names.iter().position(|b| {
            let b = cstr(&b.raw);
            find(b, other).is_some_and(|at| &b[at + 2..] == suffix)
        }))
    };
    match opposite(LEFT, RIGHT) {
        Some(found) => found,
        None => opposite(RIGHT, LEFT).flatten(),
    }
}

fn first_marked<K: mds_formats::key_pool::Key + Clone>(
    pool: &KeyPool<K>,
    marked: impl Fn(&K) -> bool,
) -> Option<K> {
    let heads = pool.heads().iter().enumerate().map(|(i, k)| (i as u32, k));
    heads
        .chain(pool.records().iter().map(|(i, k)| (*i, k)))
        .filter(|(_, k)| marked(k))
        .min_by_key(|(i, _)| *i)
        .map(|(_, k)| k.clone())
}

fn for_marked<K: mds_formats::key_pool::Key>(
    pool: &mut KeyPool<K>,
    marked: impl Fn(&K) -> bool,
    mut f: impl FnMut(&mut K),
) {
    pool.heads_mut()
        .iter_mut()
        .filter(|k| marked(k))
        .for_each(&mut f);
    let at: Vec<u32> = pool
        .records()
        .iter()
        .filter(|(_, k)| marked(k))
        .map(|(i, _)| *i)
        .collect();
    for i in at {
        if let Some(k) = pool.get_mut(i) {
            f(k);
        }
    }
}
