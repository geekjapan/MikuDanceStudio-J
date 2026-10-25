//! The camera, light, self-shadow, gravity and accessory tracks: register,
//! paste, select and delete.
//!
//! Every track is a 10000-record pool with the head at record 0. The C++
//! duplicates one walk-and-splice sequence per payload
//! (`InsertGlobalFrame` in `src/model/global_key_registration.cpp`); the
//! copies differ only in whether an appended record gets `next = 0` and in
//! whether an exact hit bumps `lastRegisteredFrame` (none does).

use crate::Error;
use mds_formats::key_pool::{Key, KeyPool};
use mds_formats::pmm::{AccessoryKey, CameraKey, GravityKey, LightKey, Pmm, SelfShadowKey};

/// A record of a global pool: links and the `selected` mark.
pub(crate) trait GlobalKey: Key + Clone + Default {
    fn links_mut(&mut self) -> [&mut u32; 3];
    fn selected_mut(&mut self) -> &mut u8;
    fn is_selected(&self) -> bool;
}

macro_rules! global_key {
    ($($t:ty),*) => {$(
        impl GlobalKey for $t {
            fn links_mut(&mut self) -> [&mut u32; 3] {
                [&mut self.frame, &mut self.previous, &mut self.next]
            }
            fn selected_mut(&mut self) -> &mut u8 {
                &mut self.selected
            }
            fn is_selected(&self) -> bool {
                self.selected != 0
            }
        }
    )*};
}
global_key!(CameraKey, LightKey, SelfShadowKey, GravityKey, AccessoryKey);

/// The record at `i`; a never-used record is zeroed memory in the C++.
fn slot<K: GlobalKey>(pool: &mut KeyPool<K>, i: u32) -> Result<&mut K, Error> {
    if pool.get(i).is_none() {
        pool.insert(i, K::default()).ok_or(corrupt())?;
    }
    pool.get_mut(i).ok_or(corrupt())
}

fn corrupt() -> Error {
    Error::Edit(mds_edit::Error::Corrupt)
}

fn links<K: Key>(pool: &KeyPool<K>, i: u32) -> (u32, u32, u32) {
    pool.get(i)
        .map_or((0, 0, 0), |k| (k.frame(), k.previous(), k.next()))
}

/// From `head` along `next` to the first record at or after `frame`, or
/// the last record.
pub(crate) fn walk<K: Key>(pool: &KeyPool<K>, head: u32, frame: u32) -> Result<u32, Error> {
    let mut i = head;
    for _ in 0..pool.capacity() {
        let (f, _, next) = links(pool, i);
        if f >= frame || next == 0 {
            return Ok(i);
        }
        i = next;
    }
    Err(corrupt())
}

/// How [`insert`] placed the key.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum Placed {
    /// A key at that frame existed and was overwritten.
    Exact,
    /// A free record was linked in.
    New,
}

/// The walk, the free-record scan from record 1, and the splice. `clear_next`
/// is the `added.next = 0` of `InsertGlobalFrame` on append; the other
/// copies leave the free record's `next` as it is.
pub(crate) fn insert<K: GlobalKey>(
    pool: &mut KeyPool<K>,
    frame: u32,
    clear_next: bool,
    fill: impl FnOnce(&mut K),
) -> Result<Placed, Error> {
    let cur = walk(pool, 0, frame)?;
    let (cur_frame, cur_prev, _) = links(pool, cur);
    if cur_frame == frame {
        fill(slot(pool, cur)?);
        return Ok(Placed::Exact);
    }
    let fresh = pool
        .allocate_from_cursor(&mut 0)
        .ok_or(Error::Edit(mds_edit::Error::Full {
            pool: "global",
            limit: pool.capacity(),
        }))?;
    if cur_frame < frame {
        *slot(pool, cur)?.links_mut()[2] = fresh;
        let k = slot(pool, fresh)?;
        *k.links_mut()[1] = cur;
        if clear_next {
            *k.links_mut()[2] = 0;
        }
    } else {
        *slot(pool, cur_prev)?.links_mut()[2] = fresh;
        *slot(pool, fresh)?.links_mut()[1] = cur_prev;
        *slot(pool, cur)?.links_mut()[1] = fresh;
        *slot(pool, fresh)?.links_mut()[2] = cur;
    }
    let k = slot(pool, fresh)?;
    *k.links_mut()[0] = frame;
    fill(k);
    Ok(Placed::New)
}

/// `if (frame > lastRegisteredFrame) lastRegisteredFrame = frame`, unsigned.
pub(crate) fn bump(pmm: &mut Pmm, placed: Placed, frame: u32) {
    let last = &mut pmm.timeline.last_registered_frame;
    if placed == Placed::New && frame > *last as u32 {
        *last = frame as i32;
    }
}

/// A global track, or an accessory's track by accessory slot.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum GlobalTrack {
    Camera,
    Light,
    SelfShadow,
    Gravity,
    Accessory(u8),
}

fn clear<K: GlobalKey>(pool: &mut KeyPool<K>) {
    for k in pool.heads_mut() {
        *k.selected_mut() = 0;
    }
    let indices: Vec<u32> = pool.records().iter().map(|r| r.0).collect();
    for i in indices {
        if let Some(k) = pool.get_mut(i) {
            *k.selected_mut() = 0;
        }
    }
}

/// `ClearFrameSelection` (`command_panel_toggles.cpp`): no camera-mode key is
/// selected.
pub(crate) fn clear_selection(pmm: &mut Pmm) {
    clear(&mut pmm.camera);
    clear(&mut pmm.light);
    clear(&mut pmm.self_shadow);
    clear(&mut pmm.gravity);
    for a in &mut pmm.accessories {
        clear(&mut a.keys);
    }
}

fn mark<K: GlobalKey>(pool: &mut KeyPool<K>, from: u32, to: u32) -> Result<(), Error> {
    let mut i = 0;
    for _ in 0..pool.capacity() {
        let k = slot(pool, i)?;
        if (from..=to).contains(&k.frame()) {
            *k.selected_mut() = 1;
        }
        i = k.next();
        if i == 0 {
            return Ok(());
        }
    }
    Err(corrupt())
}

pub(crate) fn accessory(
    pmm: &mut Pmm,
    slot: u8,
) -> Result<&mut mds_formats::pmm::Accessory, Error> {
    pmm.accessories
        .iter_mut()
        .find(|a| a.slot == slot)
        .ok_or(Error::NotApplicable("no accessory in that slot"))
}

/// Selects the keys of `track` whose frame is in `from..=to`, as the
/// timeline click and range selection do.
pub(crate) fn select(pmm: &mut Pmm, track: GlobalTrack, from: u32, to: u32) -> Result<(), Error> {
    match track {
        GlobalTrack::Camera => mark(&mut pmm.camera, from, to),
        GlobalTrack::Light => mark(&mut pmm.light, from, to),
        GlobalTrack::SelfShadow => mark(&mut pmm.self_shadow, from, to),
        GlobalTrack::Gravity => mark(&mut pmm.gravity, from, to),
        GlobalTrack::Accessory(s) => mark(&mut accessory(pmm, s)?.keys, from, to),
    }
}

/// The camera key the register button stores (`RegisterCameraState`, VA
/// 0x00410560) before the curve choice.
fn camera_state(pmm: &Pmm) -> CameraClip {
    let s = &pmm.camera_state;
    CameraClip {
        frame: 0,
        distance: s[5],
        eye: [s[0], s[1], s[2]],
        target: [s[6], s[7], s[8]],
        parent_model: pmm.appearance.camera_parent_model,
        parent_bone: pmm.appearance.camera_parent_bone,
        interpolation: DEFAULT_CAMERA_CURVE,
        perspective: pmm.camera_perspective,
        fov: pmm.settings.camera_fov as i32,
    }
}

/// Rows 0 and 1 of 20, rows 2 and 3 of 107 (`memset` 12 bytes each).
pub(crate) const DEFAULT_CAMERA_CURVE: [[u8; 6]; 4] = [[20; 6], [20; 6], [107; 6], [107; 6]];

/// The register of one track at `frame`: `RegisterCameraState`,
/// `RegisterLightState` (0x00411630), `RegisterSelfShadowState`
/// (0x00411DF0), `RegisterGravityKeyCurrent` (0x00412B20) and
/// `RegisterAccessoryKey` (0x00413CB0).
pub(crate) fn register(
    pmm: &mut Pmm,
    track: GlobalTrack,
    frame: u32,
    self_shadow_mode: u8,
    reset_curve: bool,
) -> Result<(), Error> {
    match track {
        GlobalTrack::Camera => {
            let mut clip = camera_state(pmm);
            let existing = find(&pmm.camera, frame)?;
            if let (Some(i), false) = (existing, reset_curve) {
                clip.interpolation = pmm.camera.get(i).ok_or(corrupt())?.interpolation;
            }
            paste_camera(pmm, &clip, frame)
        }
        GlobalTrack::Light => {
            let s = pmm.light_state;
            let clip = LightClip {
                frame: 0,
                color: [s[0], s[1], s[2]],
                direction: [s[3], s[4], s[5]],
            };
            paste_light(pmm, &clip, frame)
        }
        GlobalTrack::SelfShadow => {
            if (frame as i32) < 0 {
                return Ok(());
            }
            let distance = pmm.physics_interval;
            let placed = insert(&mut pmm.self_shadow, frame, false, |k| {
                k.mode = self_shadow_mode;
                k.distance = distance;
                k.selected = 1;
            })?;
            bump(pmm, placed, frame);
            Ok(())
        }
        GlobalTrack::Gravity => {
            let p = pmm.physics.clone();
            let placed = insert(&mut pmm.gravity, frame, false, |k| {
                k.acceleration = p.gravity_magnitude;
                k.direction = p.gravity_direction;
                k.noise = p.gravity_noise;
                k.noise_enabled = p.gravity_noise_enabled;
                k.selected = 1;
            })?;
            bump(pmm, placed, frame);
            Ok(())
        }
        GlobalTrack::Accessory(s) => {
            let a = accessory(pmm, s)?;
            let st = a.state.clone();
            let placed = insert(&mut a.keys, frame, false, |k| {
                k.opacity_visible = st.opacity_visible;
                k.shadow = st.shadow;
                k.parent_model = st.parent_model;
                k.parent_bone = st.parent_bone;
                k.position = st.position;
                k.rotation = st.rotation;
                k.scale = st.scale;
                k.selected = 1;
            })?;
            bump(pmm, placed, frame);
            Ok(())
        }
    }
}

/// `FindGlobalFrame`: the key at exactly `frame`.
fn find<K: Key>(pool: &KeyPool<K>, frame: u32) -> Result<Option<u32>, Error> {
    let i = walk(pool, 0, frame)?;
    Ok((links(pool, i).0 == frame).then_some(i))
}

#[derive(Clone, Debug, PartialEq)]
pub struct CameraClip {
    /// Relative to the first copied key.
    pub frame: u32,
    pub distance: f32,
    pub eye: [f32; 3],
    pub target: [f32; 3],
    pub parent_model: i32,
    pub parent_bone: i32,
    pub interpolation: [[u8; 6]; 4],
    pub perspective: u8,
    pub fov: i32,
}

#[derive(Clone, Debug, PartialEq)]
pub struct LightClip {
    pub frame: u32,
    pub color: [f32; 3],
    pub direction: [f32; 3],
}

#[derive(Clone, Debug, PartialEq)]
pub struct ShadowClip {
    pub frame: u32,
    pub mode: u8,
    pub distance: f32,
}

#[derive(Clone, Debug, PartialEq)]
pub struct GravityClip {
    pub frame: u32,
    pub acceleration: f32,
    pub direction: [f32; 3],
    pub noise: i32,
    pub noise_enabled: u8,
}

/// `AccessoryClipboardKey`, with the file's transparency byte.
#[derive(Clone, Debug, PartialEq)]
pub struct AccessoryClip {
    pub frame: u32,
    pub slot: u8,
    pub opacity_visible: u8,
    pub shadow: u8,
    pub parent_model: i32,
    pub parent_bone: i32,
    pub position: [f32; 3],
    pub rotation: [f32; 3],
    pub scale: f32,
}

/// `RegisterCameraKey` (VA 0x00410AA0) at absolute `frame`.
fn paste_camera(pmm: &mut Pmm, c: &CameraClip, frame: u32) -> Result<(), Error> {
    let placed = insert(&mut pmm.camera, frame, true, |k| {
        k.distance = c.distance;
        k.eye = c.eye;
        k.target = c.target;
        k.interpolation = c.interpolation;
        k.perspective = c.perspective;
        k.fov = c.fov;
        k.selected = 1;
        k.parent_model = c.parent_model;
        k.parent_bone = c.parent_bone;
    })?;
    bump(pmm, placed, frame);
    Ok(())
}

/// `RegisterLightKey` (VA 0x00411900).
fn paste_light(pmm: &mut Pmm, c: &LightClip, frame: u32) -> Result<(), Error> {
    let placed = insert(&mut pmm.light, frame, true, |k| {
        k.direction = c.direction;
        k.color = c.color;
        k.selected = 1;
    })?;
    bump(pmm, placed, frame);
    Ok(())
}

/// The camera-mode clipboard (`CopySelectedKeyframes`, camera branch).
#[derive(Clone, Debug, Default, PartialEq)]
pub struct GlobalClipboard {
    pub cameras: Vec<CameraClip>,
    pub lights: Vec<LightClip>,
    pub shadows: Vec<ShadowClip>,
    pub gravity: Vec<GravityClip>,
    pub accessories: Vec<AccessoryClip>,
}

impl GlobalClipboard {
    fn is_empty(&self) -> bool {
        self.cameras.is_empty()
            && self.lights.is_empty()
            && self.shadows.is_empty()
            && self.gravity.is_empty()
            && self.accessories.is_empty()
    }
}

fn selected<K: GlobalKey>(pool: &KeyPool<K>) -> impl Iterator<Item = &K> {
    pool.heads()
        .iter()
        .chain(pool.records().iter().map(|r| &r.1))
        .filter(|k| k.is_selected())
}

/// `CopySelectedKeyframes` in camera mode (`frame_clipboard.cpp`). With
/// nothing selected the clipboard comes back empty, as the counts are reset
/// first.
pub(crate) fn copy(pmm: &Pmm) -> GlobalClipboard {
    let mut min = u32::MAX;
    let mut see = |f: u32| min = min.min(f);
    selected(&pmm.camera).for_each(|k| see(k.frame));
    selected(&pmm.light).for_each(|k| see(k.frame));
    selected(&pmm.self_shadow).for_each(|k| see(k.frame));
    selected(&pmm.gravity).for_each(|k| see(k.frame));
    // Key index outer, accessory slot inner.
    let mut acc: Vec<(u32, u8, &AccessoryKey)> = Vec::new();
    for a in &pmm.accessories {
        let heads = a.keys.heads().iter().map(|k| (0, k));
        for (i, k) in heads.chain(a.keys.records().iter().map(|(i, k)| (*i, k))) {
            if k.selected != 0 {
                see(k.frame);
                acc.push((i, a.slot, k));
            }
        }
    }
    acc.sort_by_key(|&(i, s, _)| (i, s));
    let rel = |f: u32| f.wrapping_sub(min);
    GlobalClipboard {
        cameras: selected(&pmm.camera)
            .map(|k| CameraClip {
                frame: rel(k.frame),
                distance: k.distance,
                eye: k.eye,
                target: k.target,
                parent_model: k.parent_model,
                parent_bone: k.parent_bone,
                interpolation: k.interpolation,
                perspective: k.perspective,
                fov: k.fov,
            })
            .collect(),
        lights: selected(&pmm.light)
            .map(|k| LightClip {
                frame: rel(k.frame),
                color: k.color,
                direction: k.direction,
            })
            .collect(),
        shadows: selected(&pmm.self_shadow)
            .map(|k| ShadowClip {
                frame: rel(k.frame),
                mode: k.mode,
                distance: k.distance,
            })
            .collect(),
        gravity: selected(&pmm.gravity)
            .map(|k| GravityClip {
                frame: rel(k.frame),
                acceleration: k.acceleration,
                direction: k.direction,
                noise: k.noise,
                noise_enabled: k.noise_enabled,
            })
            .collect(),
        accessories: acc
            .into_iter()
            .map(|(_, slot, k)| AccessoryClip {
                frame: rel(k.frame),
                slot,
                opacity_visible: k.opacity_visible,
                shadow: k.shadow,
                parent_model: k.parent_model,
                parent_bone: k.parent_bone,
                position: k.position,
                rotation: k.rotation,
                scale: k.scale,
            })
            .collect(),
    }
}

/// `PasteSelectedKeyframes` in camera mode: clears the selection, then each
/// list in turn at `current + frame`. A full pool stops its own list; the
/// first error is returned at the end.
pub(crate) fn paste(pmm: &mut Pmm, clip: &GlobalClipboard) -> Result<(), Error> {
    if clip.is_empty() {
        return Ok(());
    }
    clear_selection(pmm);
    let at = |pmm: &Pmm, f: u32| f.wrapping_add(pmm.timeline.current_frame as u32);
    let mut first = Ok(());
    let mut note = |r: Result<(), Error>| {
        let failed = r.is_err();
        if failed && first.is_ok() {
            first = r;
        }
        failed
    };
    for c in &clip.cameras {
        if note(paste_camera(pmm, c, at(pmm, c.frame))) {
            break;
        }
    }
    for c in &clip.lights {
        if note(paste_light(pmm, c, at(pmm, c.frame))) {
            break;
        }
    }
    for c in &clip.shadows {
        let frame = at(pmm, c.frame);
        // `RegisterSelfShadowKey` (VA 0x004120B0).
        let r = insert(&mut pmm.self_shadow, frame, true, |k| {
            k.mode = c.mode;
            k.distance = c.distance;
            k.selected = 1;
        })
        .map(|p| bump(pmm, p, frame));
        if note(r) {
            break;
        }
    }
    for c in &clip.gravity {
        let frame = at(pmm, c.frame);
        // `RegisterGravityKey` (VA 0x00412DF0).
        let r = insert(&mut pmm.gravity, frame, true, |k| {
            k.acceleration = c.acceleration;
            k.direction = c.direction;
            k.noise = c.noise;
            k.noise_enabled = c.noise_enabled;
            k.selected = 1;
        })
        .map(|p| bump(pmm, p, frame));
        if note(r) {
            break;
        }
    }
    for c in &clip.accessories {
        // `PasteAccessoryKeyRecord` (accessory_paste.cpp): a slot with no
        // accessory is skipped.
        let frame = at(pmm, c.frame);
        let Ok(a) = accessory(pmm, c.slot) else {
            continue;
        };
        let r = insert(&mut a.keys, frame, false, |k| {
            k.opacity_visible = c.opacity_visible;
            k.shadow = c.shadow;
            k.parent_model = c.parent_model;
            k.parent_bone = c.parent_bone;
            k.position = c.position;
            k.rotation = c.rotation;
            k.scale = c.scale;
            k.selected = 1;
        })
        .map(|p| bump(pmm, p, frame));
        if note(r) {
            break;
        }
    }
    first
}

/// `UnlinkGlobalKey` / `UnlinkAccessoryKey`: writes through both links, so
/// the last key of a track writes `previous` of record 0.
fn unlink<K: GlobalKey>(pool: &mut KeyPool<K>, i: u32) -> Result<(), Error> {
    let (_, prev, next) = links(pool, i);
    *slot(pool, prev)?.links_mut()[2] = next;
    *slot(pool, next)?.links_mut()[1] = prev;
    let k = slot(pool, i)?;
    let [f, p, n] = k.links_mut();
    (*f, *p, *n) = (0, 0, 0);
    Ok(())
}

/// Frees every selected record of a pool. `reset(head, key)` is the
/// payload reset; `cut_head` is the `head.next = 0` of the light,
/// self-shadow and gravity heads, which leaves any unselected key of the
/// track on no track, as in the original.
fn free_selected<K: GlobalKey>(
    pool: &mut KeyPool<K>,
    cut_head: bool,
    reset: impl Fn(bool, &mut K),
) -> Result<(), Error> {
    if slot(pool, 0)?.is_selected() {
        let head = slot(pool, 0)?;
        reset(true, head);
        if cut_head {
            *head.links_mut()[2] = 0;
        }
    }
    let marked: Vec<u32> = pool
        .records()
        .iter()
        .filter(|r| r.1.is_selected())
        .map(|r| r.0)
        .collect();
    for i in marked {
        unlink(pool, i)?;
        reset(false, slot(pool, i)?);
    }
    Ok(())
}

/// The camera-mode branch of `DeleteMarkedKeyframes` (VA 0x004316B0).
pub(crate) fn delete_selected(pmm: &mut Pmm) -> Result<(), Error> {
    free_selected(&mut pmm.camera, false, |head, k| {
        k.selected = 0;
        k.distance = -45.0;
        k.eye = [0.0, if head { 10.0 } else { 0.0 }, 0.0];
        k.target = [0.0; 3];
        k.parent_model = -1;
        k.parent_bone = 0;
        k.interpolation = DEFAULT_CAMERA_CURVE;
    })?;
    free_selected(&mut pmm.light, true, |head, k| {
        k.selected = 0;
        if head {
            k.direction = [-0.5, -1.0, 0.5];
            k.color = [0.602; 3];
        } else {
            k.direction = [0.0; 3];
            k.color = [0.0; 3];
        }
    })?;
    free_selected(&mut pmm.self_shadow, true, |_, k| {
        k.selected = 0;
        k.mode = crate::POST_PROCESS_SHADOW_MODE;
        k.distance = 0.01125;
    })?;
    free_selected(&mut pmm.gravity, true, |_, k| {
        k.selected = 0;
        k.noise_enabled = 0;
        k.noise = 10;
        k.acceleration = 9.8;
        k.direction = [0.0, -1.0, 0.0];
    })?;
    for a in &mut pmm.accessories {
        free_selected(&mut a.keys, false, |_, k| {
            k.selected = 0;
            k.parent_bone = 0;
            k.shadow = 0;
            k.parent_model = -1;
            k.position = [0.0; 3];
            k.rotation = [0.0; 3];
            k.opacity_visible = crate::save::opacity_visible(1.0, 1);
            k.scale = 1.0;
        })?;
    }
    Ok(())
}

/// The camera branch of `LoadVmdMotion` (`src/model/vmd_load.cpp`, VA
/// 0x00434B60): the camera keys (`RegisterCameraKey`, parent -1), the light
/// keys and the self-shadow keys, each list stopping at its first full
/// pool. A version 1 file's shared curve byte fills its row, with fov 45.
pub(crate) fn load_vmd(pmm: &mut Pmm, vmd: &mds_formats::vmd::Vmd) -> Result<(), Error> {
    let v1 = vmd.header.starts_with(b"Vocaloid Motion Data file\0");
    let mut first = Ok(());
    for k in vmd.cameras.iter().flatten() {
        let mut interpolation = [[0; 6]; 4];
        for (n, row) in [0, 2, 1, 3].into_iter().enumerate() {
            for (c, v) in interpolation[row].iter_mut().enumerate() {
                *v = k.interpolation[if v1 { 0 } else { 4 * c } + n];
            }
        }
        let clip = CameraClip {
            frame: 0,
            distance: k.distance,
            eye: k.eye,
            target: k.target,
            parent_model: -1,
            parent_bone: 0,
            interpolation,
            perspective: if v1 { 0 } else { u8::from(k.perspective != 0) },
            fov: if v1 { 45 } else { k.fov as i32 },
        };
        if let Err(e) = paste_camera(pmm, &clip, k.frame) {
            first = first.and(Err(e));
            break;
        }
    }
    for k in vmd.lights.iter().flatten() {
        let clip = LightClip {
            frame: 0,
            color: k.color,
            direction: k.direction,
        };
        if let Err(e) = paste_light(pmm, &clip, k.frame) {
            first = first.and(Err(e));
            break;
        }
    }
    for k in vmd.shadows.iter().flatten() {
        let r = insert(&mut pmm.self_shadow, k.frame, true, |s| {
            s.mode = k.mode;
            s.distance = k.distance;
            s.selected = 1;
        });
        match r {
            Ok(p) => bump(pmm, p, k.frame),
            Err(e) => {
                first = first.and(Err(e));
                break;
            }
        }
    }
    first
}
