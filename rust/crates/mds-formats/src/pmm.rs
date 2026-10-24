//! PMM v2 scene files ("Polygon Movie maker 0002"), in the section order of
//! `src/io/pmm_save.cpp` and `pmm_scene_document.cpp` on `next`.
//!
//! Byte fields that the C++ code treats as flags stay `u8` with the value as
//! read, so a file written by any tool keeps its bytes.

use crate::io::{Reader, Result, Writer};
use crate::key_pool::{
    Key, KeyPool, BONE_KEY_CAPACITY, DISPLAY_KEY_CAPACITY, GLOBAL_KEY_CAPACITY, MORPH_KEY_CAPACITY,
};
use crate::text::{FixedSjis, Sjis};

/// Cap on name tables and track heads, as in `pmm_scene_document.cpp`.
const MAX_RECORDS: usize = 100_000;

#[derive(Clone, Debug)]
pub struct Pmm {
    /// The 30-byte header: magic, version, and the bytes after the NUL.
    pub header: [u8; 30],
    pub settings: SceneSettings,
    pub selected_model_slot: u8,
    pub models: Vec<Model>,
    pub camera: KeyPool<CameraKey>,
    /// Camera position, view offset, distance, pitch, yaw, roll.
    pub camera_state: [f32; 9],
    pub camera_perspective: u8,
    pub light: KeyPool<LightKey>,
    /// Light color, then direction.
    pub light_state: [f32; 6],
    pub selected_accessory_slot: u8,
    pub display_list_scroll: i32,
    pub accessories: Vec<Accessory>,
    pub timeline: Timeline,
    pub wave: Wave,
    pub avi: Background,
    pub picture: Background,
    pub view: View,
    pub physics: Physics,
    pub gravity: KeyPool<GravityKey>,
    pub self_shadow_mode: u8,
    pub physics_interval: f32,
    pub self_shadow: KeyPool<SelfShadowKey>,
    pub appearance: Appearance,
    pub tail: Tail,
}

#[derive(Clone, Debug, Default)]
pub struct SceneSettings {
    pub render_width: i32,
    pub render_height: i32,
    pub panel_width: i32,
    pub camera_fov: f32,
    pub options: [u8; 7],
}

/// One model slot. The name, key-head and pose tables run in parallel:
/// `bone_names`, `bone_keys.heads()` and `bone_pose` have one entry per
/// bone, and likewise for morphs, IK chains and outside-parent selectors.
#[derive(Clone, Debug)]
pub struct Model {
    pub slot: u8,
    pub name: Sjis,
    pub name_en: Sjis,
    pub path: FixedSjis<256>,
    pub group_count: u8,
    pub bone_names: Vec<Sjis>,
    pub morph_names: Vec<Sjis>,
    /// Bone index of each IK chain.
    pub ik_bones: Vec<i32>,
    /// Bone index of each outside-parent selector.
    pub selector_bones: Vec<i32>,
    pub selection: Selection,
    pub bone_keys: KeyPool<BoneKey>,
    pub morph_keys: KeyPool<MorphKey>,
    pub display_keys: KeyPool<DisplayKey>,
    pub bone_pose: Vec<BonePose>,
    pub morph_pose: Vec<f32>,
    pub ik_pose: Vec<u8>,
    /// Window start, window end, linked model, linked bone.
    pub selector_pose: Vec<[i32; 4]>,
    pub post_load: u8,
    pub edge_scale: f32,
    pub toon: u8,
    pub display_order: u8,
}

#[derive(Clone, Debug, Default)]
pub struct Selection {
    pub combo_index: u8,
    pub load_complete: u8,
    pub selected_bone: i32,
    pub selected_morphs: [i32; 4],
    /// The group count is written a second time here; kept as read.
    pub group_count_repeat: u8,
    /// One flag per display group (`Model::group_count`).
    pub group_flags: Vec<u8>,
    pub bone_list_pos: i32,
    pub max_frame: u32,
}

#[derive(Clone, Debug, Default)]
pub struct BonePose {
    pub translation: [f32; 3],
    pub rotation: [f32; 4],
    /// Physics disabled, physics state, selected.
    pub flags: [u8; 3],
}

#[derive(Clone, Debug)]
pub struct Accessory {
    /// The accessory's entry in the shadow list that precedes the blocks.
    pub list_name: FixedSjis<100>,
    pub slot: u8,
    pub name: FixedSjis<100>,
    pub path: FixedSjis<256>,
    pub order: u8,
    pub keys: KeyPool<AccessoryKey>,
    pub state: AccessoryState,
}

#[derive(Clone, Debug, Default)]
pub struct AccessoryState {
    /// `(100 - opacity * 100) * 2`, plus 1 when visible.
    pub opacity_visible: u8,
    pub parent_model: i32,
    pub parent_bone: i32,
    pub rotation: [f32; 3],
    pub scale: f32,
    pub position: [f32; 3],
    pub shadow: u8,
    pub additive: u8,
}

#[derive(Clone, Debug, Default)]
pub struct Timeline {
    pub current_frame: i32,
    pub start_frame: i32,
    pub last_registered_frame: i32,
    pub edit_mode: i32,
    pub camera_reference_mode: u8,
    pub playback_loop: u8,
    pub return_to_start: u8,
    pub start_at_current: u8,
    pub play_start_frame: i32,
    pub play_stop_frame: i32,
}

#[derive(Clone, Debug)]
pub struct Wave {
    pub enabled: u8,
    pub path: FixedSjis<256>,
}

/// The AVI or picture background. The AVI `enabled` field is 4 bytes in
/// the file, the picture one is 1 byte.
#[derive(Clone, Debug)]
pub struct Background {
    pub offset: [i32; 2],
    pub scale: f32,
    pub path: FixedSjis<256>,
    pub enabled: u32,
}

#[derive(Clone, Debug, Default)]
pub struct View {
    pub fps_overlay: u8,
    pub ground_grid: u8,
    pub ground_shadow: u8,
    pub fps_limit: f32,
    pub capture_mode: i32,
}

#[derive(Clone, Debug, Default)]
pub struct Physics {
    pub accessory_render_order: i32,
    pub projected_shadow_ambient: f32,
    pub projected_shadow_blend: u8,
    pub playback_mode: u8,
    pub gravity_magnitude: f32,
    pub gravity_noise: i32,
    pub gravity_direction: [f32; 3],
    pub gravity_noise_enabled: u8,
}

#[derive(Clone, Debug, Default)]
pub struct Appearance {
    pub outline_color: [i32; 3],
    pub black_background: u8,
    pub camera_parent_model: i32,
    pub camera_parent_bone: i32,
    pub camera_attachment_basis: [f32; 16],
    pub follow_camera: u8,
    pub suppress_camera_transform: u8,
    pub floor_visible: u8,
    pub max_frame: i32,
}

/// The optional end of the file: nothing, a flag byte other than 1, or
/// flag 1 and one frame-registration selection per model.
#[derive(Clone, Debug)]
pub enum Tail {
    Absent,
    Flag(u8),
    Registrations(Vec<Registration>),
}

#[derive(Clone, Debug, Default)]
pub struct Registration {
    pub slot: u8,
    pub selection: i32,
}

// ---- key records ----------------------------------------------------------

#[derive(Clone, Debug, Default)]
pub struct BoneKey {
    pub frame: u32,
    pub previous: u32,
    pub next: u32,
    /// Curve control bytes in C++ memory order: index `lane + 4 * group`.
    pub interpolation: [u8; 16],
    pub position: [f32; 3],
    pub rotation: [f32; 4],
    pub allocated: u8,
    pub physics_disabled: u8,
}

#[derive(Clone, Debug, Default)]
pub struct MorphKey {
    pub frame: u32,
    pub previous: u32,
    pub next: u32,
    pub value: f32,
    pub allocated: u8,
}

/// The IK and outside-parent track of a model.
#[derive(Clone, Debug, Default)]
pub struct DisplayKey {
    pub frame: u32,
    pub previous: u32,
    pub next: u32,
    pub visible: u8,
    /// One flag per IK chain.
    pub ik_enabled: Vec<u8>,
    /// `(model, bone)` per outside-parent selector.
    pub selectors: Vec<[i32; 2]>,
    pub allocated: u8,
}

#[derive(Clone, Debug, Default)]
pub struct CameraKey {
    pub frame: u32,
    pub previous: u32,
    pub next: u32,
    pub distance: f32,
    pub eye: [f32; 3],
    pub target: [f32; 3],
    pub parent_model: i32,
    pub parent_bone: i32,
    /// `[row][channel]`, as `PmmCameraKey::interpolation`.
    pub interpolation: [[u8; 6]; 4],
    pub perspective: u8,
    pub fov: i32,
    pub selected: u8,
}

#[derive(Clone, Debug, Default)]
pub struct LightKey {
    pub frame: u32,
    pub previous: u32,
    pub next: u32,
    pub color: [f32; 3],
    pub direction: [f32; 3],
    pub selected: u8,
}

#[derive(Clone, Debug, Default)]
pub struct GravityKey {
    pub frame: u32,
    pub previous: u32,
    pub next: u32,
    pub noise_enabled: u8,
    pub noise: i32,
    pub acceleration: f32,
    pub direction: [f32; 3],
    pub selected: u8,
}

#[derive(Clone, Debug, Default)]
pub struct SelfShadowKey {
    pub frame: u32,
    pub previous: u32,
    pub next: u32,
    pub mode: u8,
    pub distance: f32,
    pub selected: u8,
}

#[derive(Clone, Debug, Default)]
pub struct AccessoryKey {
    pub frame: u32,
    pub previous: u32,
    pub next: u32,
    pub opacity_visible: u8,
    pub parent_model: i32,
    pub parent_bone: i32,
    pub position: [f32; 3],
    pub rotation: [f32; 3],
    pub scale: f32,
    pub shadow: u8,
    pub selected: u8,
}

macro_rules! impl_key {
    ($($t:ty),*) => {$(
        impl Key for $t {
            fn frame(&self) -> u32 { self.frame }
            fn previous(&self) -> u32 { self.previous }
            fn next(&self) -> u32 { self.next }
        }
    )*};
}
impl_key!(
    BoneKey,
    MorphKey,
    DisplayKey,
    CameraKey,
    LightKey,
    GravityKey,
    SelfShadowKey,
    AccessoryKey
);

fn links(r: &mut Reader) -> Result<[u32; 3]> {
    Ok([r.u32()?, r.u32()?, r.u32()?])
}
fn write_links(w: &mut Writer, frame: u32, previous: u32, next: u32) {
    w.u32(frame);
    w.u32(previous);
    w.u32(next);
}

impl BoneKey {
    const SIZE: usize = 58;
    fn read(r: &mut Reader) -> Result<Self> {
        let [frame, previous, next] = links(r)?;
        let file = r.array::<16>()?;
        let mut interpolation = [0; 16];
        for lane in 0..4 {
            for group in 0..4 {
                interpolation[lane + 4 * group] = file[lane * 4 + group];
            }
        }
        Ok(BoneKey {
            frame,
            previous,
            next,
            interpolation,
            position: r.f32s()?,
            rotation: r.f32s()?,
            allocated: r.u8()?,
            physics_disabled: r.u8()?,
        })
    }
    fn write(&self, w: &mut Writer) {
        write_links(w, self.frame, self.previous, self.next);
        for lane in 0..4 {
            for group in 0..4 {
                w.u8(self.interpolation[lane + 4 * group]);
            }
        }
        w.f32s(&self.position);
        w.f32s(&self.rotation);
        w.u8(self.allocated);
        w.u8(self.physics_disabled);
    }
}

impl MorphKey {
    const SIZE: usize = 17;
    fn read(r: &mut Reader) -> Result<Self> {
        let [frame, previous, next] = links(r)?;
        Ok(MorphKey {
            frame,
            previous,
            next,
            value: r.f32()?,
            allocated: r.u8()?,
        })
    }
    fn write(&self, w: &mut Writer) {
        write_links(w, self.frame, self.previous, self.next);
        w.f32(self.value);
        w.u8(self.allocated);
    }
}

impl DisplayKey {
    fn size(ik: usize, selectors: usize) -> usize {
        14 + ik + 8 * selectors
    }
    fn read(r: &mut Reader, ik: usize, selectors: usize) -> Result<Self> {
        let [frame, previous, next] = links(r)?;
        Ok(DisplayKey {
            frame,
            previous,
            next,
            visible: r.u8()?,
            ik_enabled: r.bytes(ik)?.to_vec(),
            selectors: r.vec(selectors, 8, |r| Ok([r.i32()?, r.i32()?]))?,
            allocated: r.u8()?,
        })
    }
    fn write(&self, w: &mut Writer, ik: usize, selectors: usize) -> Result<()> {
        if self.ik_enabled.len() != ik || self.selectors.len() != selectors {
            return Err(w.invalid("display key tables differ from the model"));
        }
        write_links(w, self.frame, self.previous, self.next);
        w.u8(self.visible);
        w.bytes(&self.ik_enabled);
        for [model, bone] in &self.selectors {
            w.i32(*model);
            w.i32(*bone);
        }
        w.u8(self.allocated);
        Ok(())
    }
}

impl CameraKey {
    const SIZE: usize = 78;
    fn read(r: &mut Reader) -> Result<Self> {
        let [frame, previous, next] = links(r)?;
        let distance = r.f32()?;
        let eye = r.f32s()?;
        let target = r.f32s()?;
        let parent_model = r.i32()?;
        let parent_bone = r.i32()?;
        let file = r.array::<24>()?;
        let mut interpolation = [[0; 6]; 4];
        for channel in 0..6 {
            for (row, line) in interpolation.iter_mut().enumerate() {
                line[channel] = file[channel * 4 + row];
            }
        }
        Ok(CameraKey {
            frame,
            previous,
            next,
            distance,
            eye,
            target,
            parent_model,
            parent_bone,
            interpolation,
            perspective: r.u8()?,
            fov: r.i32()?,
            selected: r.u8()?,
        })
    }
    fn write(&self, w: &mut Writer) {
        write_links(w, self.frame, self.previous, self.next);
        w.f32(self.distance);
        w.f32s(&self.eye);
        w.f32s(&self.target);
        w.i32(self.parent_model);
        w.i32(self.parent_bone);
        for channel in 0..6 {
            for line in &self.interpolation {
                w.u8(line[channel]);
            }
        }
        w.u8(self.perspective);
        w.i32(self.fov);
        w.u8(self.selected);
    }
}

impl LightKey {
    const SIZE: usize = 37;
    fn read(r: &mut Reader) -> Result<Self> {
        let [frame, previous, next] = links(r)?;
        Ok(LightKey {
            frame,
            previous,
            next,
            color: r.f32s()?,
            direction: r.f32s()?,
            selected: r.u8()?,
        })
    }
    fn write(&self, w: &mut Writer) {
        write_links(w, self.frame, self.previous, self.next);
        w.f32s(&self.color);
        w.f32s(&self.direction);
        w.u8(self.selected);
    }
}

impl GravityKey {
    const SIZE: usize = 34;
    fn read(r: &mut Reader) -> Result<Self> {
        let [frame, previous, next] = links(r)?;
        Ok(GravityKey {
            frame,
            previous,
            next,
            noise_enabled: r.u8()?,
            noise: r.i32()?,
            acceleration: r.f32()?,
            direction: r.f32s()?,
            selected: r.u8()?,
        })
    }
    fn write(&self, w: &mut Writer) {
        write_links(w, self.frame, self.previous, self.next);
        w.u8(self.noise_enabled);
        w.i32(self.noise);
        w.f32(self.acceleration);
        w.f32s(&self.direction);
        w.u8(self.selected);
    }
}

impl SelfShadowKey {
    const SIZE: usize = 18;
    fn read(r: &mut Reader) -> Result<Self> {
        let [frame, previous, next] = links(r)?;
        Ok(SelfShadowKey {
            frame,
            previous,
            next,
            mode: r.u8()?,
            distance: r.f32()?,
            selected: r.u8()?,
        })
    }
    fn write(&self, w: &mut Writer) {
        write_links(w, self.frame, self.previous, self.next);
        w.u8(self.mode);
        w.f32(self.distance);
        w.u8(self.selected);
    }
}

impl AccessoryKey {
    const SIZE: usize = 51;
    fn read(r: &mut Reader) -> Result<Self> {
        let [frame, previous, next] = links(r)?;
        Ok(AccessoryKey {
            frame,
            previous,
            next,
            opacity_visible: r.u8()?,
            parent_model: r.i32()?,
            parent_bone: r.i32()?,
            position: r.f32s()?,
            rotation: r.f32s()?,
            scale: r.f32()?,
            shadow: r.u8()?,
            selected: r.u8()?,
        })
    }
    fn write(&self, w: &mut Writer) {
        write_links(w, self.frame, self.previous, self.next);
        w.u8(self.opacity_visible);
        w.i32(self.parent_model);
        w.i32(self.parent_bone);
        w.f32s(&self.position);
        w.f32s(&self.rotation);
        w.f32(self.scale);
        w.u8(self.shadow);
        w.u8(self.selected);
    }
}

// ---- sections -------------------------------------------------------------

/// A table count: i32, not negative, at most `MAX_RECORDS`.
fn count(r: &mut Reader) -> Result<usize> {
    let n = usize::try_from(r.i32()?).map_err(|_| r.invalid("negative count"))?;
    r.limit(n, MAX_RECORDS, "count over 100000")
}

/// The header check of `ParsePmmHeader`: the signature may start anywhere
/// in the first 30 bytes, with "0002" and a NUL 0x14 bytes after it.
fn check_header(r: &Reader, h: &[u8; 30]) -> Result<()> {
    const SIG: &[u8] = b"Polygon Movie maker";
    for offset in 0..=h.len() - SIG.len() {
        if h[offset] == 0 {
            break;
        }
        if &h[offset..offset + SIG.len()] != SIG {
            continue;
        }
        return match h.get(offset + 0x14..offset + 0x19) {
            Some(b"0002\0") => Ok(()),
            Some(b"0001\0") => Err(r.invalid("PMM version 1 is not supported")),
            _ => Err(r.invalid("unsupported PMM version")),
        };
    }
    Err(r.invalid("not a PMM file"))
}

impl Model {
    fn read(r: &mut Reader) -> Result<Self> {
        let slot = r.u8()?;
        if slot == 255 {
            return Err(r.invalid("model slot 255"));
        }
        let name = Sjis::read_u8_prefixed(r)?;
        let name_en = Sjis::read_u8_prefixed(r)?;
        let path = FixedSjis::read(r)?;
        let group_count = r.u8()?;
        let n = count(r)?;
        let bone_names = r.vec(n, 1, Sjis::read_u8_prefixed)?;
        let n = count(r)?;
        let morph_names = r.vec(n, 1, Sjis::read_u8_prefixed)?;
        let n = count(r)?;
        let ik_bones = r.vec(n, 4, |r| r.i32())?;
        let n = count(r)?;
        let selector_bones = r.vec(n, 4, |r| r.i32())?;
        let selection = Selection {
            combo_index: r.u8()?,
            load_complete: r.u8()?,
            selected_bone: r.i32()?,
            selected_morphs: [r.i32()?, r.i32()?, r.i32()?, r.i32()?],
            group_count_repeat: r.u8()?,
            group_flags: r.bytes(group_count.into())?.to_vec(),
            bone_list_pos: r.i32()?,
            max_frame: r.u32()?,
        };
        let (bones, morphs) = (bone_names.len(), morph_names.len());
        let (ik, selectors) = (ik_bones.len(), selector_bones.len());
        let bone_keys = KeyPool::read(r, bones, BONE_KEY_CAPACITY, BoneKey::SIZE, BoneKey::read)?;
        let morph_keys = KeyPool::read(
            r,
            morphs,
            MORPH_KEY_CAPACITY,
            MorphKey::SIZE,
            MorphKey::read,
        )?;
        let display_keys = KeyPool::read(
            r,
            1,
            DISPLAY_KEY_CAPACITY,
            DisplayKey::size(ik, selectors),
            |r| DisplayKey::read(r, ik, selectors),
        )?;
        Ok(Model {
            slot,
            name,
            name_en,
            path,
            group_count,
            bone_names,
            morph_names,
            ik_bones,
            selector_bones,
            selection,
            bone_keys,
            morph_keys,
            display_keys,
            bone_pose: r.vec(bones, 31, |r| {
                Ok(BonePose {
                    translation: r.f32s()?,
                    rotation: r.f32s()?,
                    flags: r.array()?,
                })
            })?,
            morph_pose: r.vec(morphs, 4, |r| r.f32())?,
            ik_pose: r.bytes(ik)?.to_vec(),
            selector_pose: r.vec(selectors, 16, |r| {
                Ok([r.i32()?, r.i32()?, r.i32()?, r.i32()?])
            })?,
            post_load: r.u8()?,
            edge_scale: r.f32()?,
            toon: r.u8()?,
            display_order: r.u8()?,
        })
    }

    fn write(&self, w: &mut Writer) -> Result<()> {
        let (bones, morphs) = (self.bone_names.len(), self.morph_names.len());
        let (ik, selectors) = (self.ik_bones.len(), self.selector_bones.len());
        if self.bone_pose.len() != bones
            || self.morph_pose.len() != morphs
            || self.ik_pose.len() != ik
            || self.selector_pose.len() != selectors
            || self.selection.group_flags.len() != self.group_count as usize
        {
            return Err(w.invalid("model tables differ in length"));
        }
        w.u8(self.slot);
        self.name.write_u8_prefixed(w)?;
        self.name_en.write_u8_prefixed(w)?;
        self.path.write(w);
        w.u8(self.group_count);
        w.count32(bones)?;
        for n in &self.bone_names {
            n.write_u8_prefixed(w)?;
        }
        w.count32(morphs)?;
        for n in &self.morph_names {
            n.write_u8_prefixed(w)?;
        }
        w.count32(ik)?;
        for &b in &self.ik_bones {
            w.i32(b);
        }
        w.count32(selectors)?;
        for &b in &self.selector_bones {
            w.i32(b);
        }
        let s = &self.selection;
        w.u8(s.combo_index);
        w.u8(s.load_complete);
        w.i32(s.selected_bone);
        for &m in &s.selected_morphs {
            w.i32(m);
        }
        w.u8(s.group_count_repeat);
        w.bytes(&s.group_flags);
        w.i32(s.bone_list_pos);
        w.u32(s.max_frame);
        self.bone_keys.write(w, bones, |w, k| {
            k.write(w);
            Ok(())
        })?;
        self.morph_keys.write(w, morphs, |w, k| {
            k.write(w);
            Ok(())
        })?;
        self.display_keys
            .write(w, 1, |w, k| k.write(w, ik, selectors))?;
        for p in &self.bone_pose {
            w.f32s(&p.translation);
            w.f32s(&p.rotation);
            w.bytes(&p.flags);
        }
        w.f32s(&self.morph_pose);
        w.bytes(&self.ik_pose);
        for p in &self.selector_pose {
            for &v in p {
                w.i32(v);
            }
        }
        w.u8(self.post_load);
        w.f32(self.edge_scale);
        w.u8(self.toon);
        w.u8(self.display_order);
        Ok(())
    }
}

impl Background {
    fn read(r: &mut Reader, wide_flag: bool) -> Result<Self> {
        Ok(Background {
            offset: [r.i32()?, r.i32()?],
            scale: r.f32()?,
            path: FixedSjis::read(r)?,
            enabled: if wide_flag { r.u32()? } else { r.u8()?.into() },
        })
    }
    fn write(&self, w: &mut Writer, wide_flag: bool) -> Result<()> {
        w.i32(self.offset[0]);
        w.i32(self.offset[1]);
        w.f32(self.scale);
        self.path.write(w);
        if wide_flag {
            w.u32(self.enabled);
        } else {
            let b = u8::try_from(self.enabled).map_err(|_| w.invalid("picture flag over 255"))?;
            w.u8(b);
        }
        Ok(())
    }
}

fn global<K: Key>(
    r: &mut Reader,
    size: usize,
    item: impl FnMut(&mut Reader) -> Result<K>,
) -> Result<KeyPool<K>> {
    KeyPool::read(r, 1, GLOBAL_KEY_CAPACITY, size, item)
}

fn write_global<K: Key>(
    w: &mut Writer,
    pool: &KeyPool<K>,
    item: impl Fn(&K, &mut Writer),
) -> Result<()> {
    pool.write(w, 1, |w, k| {
        item(k, w);
        Ok(())
    })
}

impl Pmm {
    pub fn read(data: &[u8]) -> Result<Self> {
        let r = &mut Reader::new(data);
        let header = r.array::<30>()?;
        check_header(r, &header)?;
        let settings = SceneSettings {
            render_width: r.i32()?,
            render_height: r.i32()?,
            panel_width: r.i32()?,
            camera_fov: r.f32()?,
            options: r.array()?,
        };
        let selected_model_slot = r.u8()?;
        let model_count = r.u8()?;
        if model_count > 254 || selected_model_slot == 255 {
            return Err(r.invalid("bad model count or selected slot"));
        }
        let mut used = [false; 256];
        let models = r.vec(model_count.into(), 1, |r| {
            let m = Model::read(r)?;
            if std::mem::replace(&mut used[m.slot as usize], true) {
                return Err(r.invalid("two models in one slot"));
            }
            Ok(m)
        })?;
        let camera = global(r, CameraKey::SIZE, CameraKey::read)?;
        let camera_state = r.f32s()?;
        let camera_perspective = r.u8()?;
        let light = global(r, LightKey::SIZE, LightKey::read)?;
        let light_state = r.f32s()?;
        let selected_accessory_slot = r.u8()?;
        if selected_accessory_slot == 255 {
            return Err(r.invalid("selected accessory slot 255"));
        }
        let display_list_scroll = r.i32()?;
        let n = r.u8()?.into();
        let names = r.vec(n, 100, FixedSjis::<100>::read)?;
        let mut used = [false; 256];
        let mut accessories = Vec::with_capacity(n);
        for list_name in names {
            let slot = r.u8()?;
            if slot == 255 || std::mem::replace(&mut used[slot as usize], true) {
                return Err(r.invalid("bad accessory slot"));
            }
            accessories.push(Accessory {
                list_name,
                slot,
                name: FixedSjis::read(r)?,
                path: FixedSjis::read(r)?,
                order: r.u8()?,
                keys: global(r, AccessoryKey::SIZE, AccessoryKey::read)?,
                state: AccessoryState {
                    opacity_visible: r.u8()?,
                    parent_model: r.i32()?,
                    parent_bone: r.i32()?,
                    rotation: r.f32s()?,
                    scale: r.f32()?,
                    position: r.f32s()?,
                    shadow: r.u8()?,
                    additive: r.u8()?,
                },
            });
        }
        let timeline = Timeline {
            current_frame: r.i32()?,
            start_frame: r.i32()?,
            last_registered_frame: r.i32()?,
            edit_mode: r.i32()?,
            camera_reference_mode: r.u8()?,
            playback_loop: r.u8()?,
            return_to_start: r.u8()?,
            start_at_current: r.u8()?,
            play_start_frame: r.i32()?,
            play_stop_frame: r.i32()?,
        };
        let wave = Wave {
            enabled: r.u8()?,
            path: FixedSjis::read(r)?,
        };
        let avi = Background::read(r, true)?;
        let picture = Background::read(r, false)?;
        let view = View {
            fps_overlay: r.u8()?,
            ground_grid: r.u8()?,
            ground_shadow: r.u8()?,
            fps_limit: r.f32()?,
            capture_mode: r.i32()?,
        };
        let physics = Physics {
            accessory_render_order: r.i32()?,
            projected_shadow_ambient: r.f32()?,
            projected_shadow_blend: r.u8()?,
            playback_mode: r.u8()?,
            gravity_magnitude: r.f32()?,
            gravity_noise: r.i32()?,
            gravity_direction: r.f32s()?,
            gravity_noise_enabled: r.u8()?,
        };
        let gravity = global(r, GravityKey::SIZE, GravityKey::read)?;
        let self_shadow_mode = r.u8()?;
        let physics_interval = r.f32()?;
        let self_shadow = global(r, SelfShadowKey::SIZE, SelfShadowKey::read)?;
        let appearance = Appearance {
            outline_color: [r.i32()?, r.i32()?, r.i32()?],
            black_background: r.u8()?,
            camera_parent_model: r.i32()?,
            camera_parent_bone: r.i32()?,
            camera_attachment_basis: r.f32s()?,
            follow_camera: r.u8()?,
            suppress_camera_transform: r.u8()?,
            floor_visible: r.u8()?,
            max_frame: r.i32()?,
        };
        let tail = match r.remaining() {
            0 => Tail::Absent,
            _ => match r.u8()? {
                1 => Tail::Registrations(r.vec(models.len(), 5, |r| {
                    Ok(Registration {
                        slot: r.u8()?,
                        selection: r.i32()?,
                    })
                })?),
                flag => Tail::Flag(flag),
            },
        };
        if r.remaining() != 0 {
            return Err(r.invalid("bytes after the end of the scene"));
        }
        Ok(Pmm {
            header,
            settings,
            selected_model_slot,
            models,
            camera,
            camera_state,
            camera_perspective,
            light,
            light_state,
            selected_accessory_slot,
            display_list_scroll,
            accessories,
            timeline,
            wave,
            avi,
            picture,
            view,
            physics,
            gravity,
            self_shadow_mode,
            physics_interval,
            self_shadow,
            appearance,
            tail,
        })
    }

    pub fn write(&self) -> Result<Vec<u8>> {
        let w = &mut Writer::default();
        w.bytes(&self.header);
        let s = &self.settings;
        w.i32(s.render_width);
        w.i32(s.render_height);
        w.i32(s.panel_width);
        w.f32(s.camera_fov);
        w.bytes(&s.options);
        w.u8(self.selected_model_slot);
        let n = u8::try_from(self.models.len())
            .ok()
            .filter(|&n| n <= 254)
            .ok_or_else(|| w.invalid("more than 254 models"))?;
        w.u8(n);
        for m in &self.models {
            m.write(w)?;
        }
        write_global(w, &self.camera, CameraKey::write)?;
        w.f32s(&self.camera_state);
        w.u8(self.camera_perspective);
        write_global(w, &self.light, LightKey::write)?;
        w.f32s(&self.light_state);
        w.u8(self.selected_accessory_slot);
        w.i32(self.display_list_scroll);
        let n =
            u8::try_from(self.accessories.len()).map_err(|_| w.invalid("over 255 accessories"))?;
        w.u8(n);
        for a in &self.accessories {
            a.list_name.write(w);
        }
        for a in &self.accessories {
            w.u8(a.slot);
            a.name.write(w);
            a.path.write(w);
            w.u8(a.order);
            write_global(w, &a.keys, AccessoryKey::write)?;
            let s = &a.state;
            w.u8(s.opacity_visible);
            w.i32(s.parent_model);
            w.i32(s.parent_bone);
            w.f32s(&s.rotation);
            w.f32(s.scale);
            w.f32s(&s.position);
            w.u8(s.shadow);
            w.u8(s.additive);
        }
        let t = &self.timeline;
        for v in [
            t.current_frame,
            t.start_frame,
            t.last_registered_frame,
            t.edit_mode,
        ] {
            w.i32(v);
        }
        w.bytes(&[
            t.camera_reference_mode,
            t.playback_loop,
            t.return_to_start,
            t.start_at_current,
        ]);
        w.i32(t.play_start_frame);
        w.i32(t.play_stop_frame);
        w.u8(self.wave.enabled);
        self.wave.path.write(w);
        self.avi.write(w, true)?;
        self.picture.write(w, false)?;
        let v = &self.view;
        w.bytes(&[v.fps_overlay, v.ground_grid, v.ground_shadow]);
        w.f32(v.fps_limit);
        w.i32(v.capture_mode);
        let p = &self.physics;
        w.i32(p.accessory_render_order);
        w.f32(p.projected_shadow_ambient);
        w.u8(p.projected_shadow_blend);
        w.u8(p.playback_mode);
        w.f32(p.gravity_magnitude);
        w.i32(p.gravity_noise);
        w.f32s(&p.gravity_direction);
        w.u8(p.gravity_noise_enabled);
        write_global(w, &self.gravity, GravityKey::write)?;
        w.u8(self.self_shadow_mode);
        w.f32(self.physics_interval);
        write_global(w, &self.self_shadow, SelfShadowKey::write)?;
        let a = &self.appearance;
        for &c in &a.outline_color {
            w.i32(c);
        }
        w.u8(a.black_background);
        w.i32(a.camera_parent_model);
        w.i32(a.camera_parent_bone);
        w.f32s(&a.camera_attachment_basis);
        w.bytes(&[
            a.follow_camera,
            a.suppress_camera_transform,
            a.floor_visible,
        ]);
        w.i32(a.max_frame);
        match &self.tail {
            Tail::Absent => {}
            Tail::Flag(1) => return Err(w.invalid("tail flag 1 needs registrations")),
            Tail::Flag(f) => w.u8(*f),
            Tail::Registrations(regs) => {
                if regs.len() != self.models.len() {
                    return Err(w.invalid("one registration per model"));
                }
                w.u8(1);
                for g in regs {
                    w.u8(g.slot);
                    w.i32(g.selection);
                }
            }
        }
        Ok(std::mem::take(&mut w.out))
    }
}
