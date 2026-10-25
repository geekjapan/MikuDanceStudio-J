//! PMM version 1 scenes ("Polygon Movie maker 0001"), read into the `Pmm`
//! that the version 2 reader produces. Ports `LoadSceneV1`
//! (`src/io/pmm_load_v1.cpp`), the v1 dialect of the record readers in
//! `src/io/pmm_io_common.hpp`, and the version dispatch of
//! `src/io/pmm_load_dispatch.cpp`.
//!
//! # What the result is
//!
//! The C++ loader reads a 0001 file into the application state, and
//! `SaveSceneFile` writes that state as 0002. [`read`] returns the `Pmm`
//! whose `write` is that 0002 (after the save-time normalization of
//! `mds-doc`), so a 0001 file opens in the document like any other scene.
//! Where the stream carries a byte flag, the result holds what the loader
//! stores (`b == 1`, as the loader tests it). Fields the stream does not
//! carry hold what the loader leaves.
//!
//! # What 0001 leaves to the model files
//!
//! A 0001 model block holds a 20-byte name and a path, not the bone, morph
//! and IK tables: the key tracks have as many heads as the PMD has bones and
//! morphs, and the stream cannot be read without it. `Pmm::read_with` takes
//! a closure that returns the PMD of each model block. The names, the IK
//! bones, the outside-parent selectors and the display group count of the
//! 0002 model block come from that PMD, as `src/model/pmd_load.cpp` leaves
//! them in the model record. 0001 predates PMX, and the portable reader on
//! `next` takes PMD only too.
//!
//! # State the stream does not carry
//!
//! Values of a fresh application, because the loader does not reset them:
//! option flag 6 (the self-shadow panel is open), the playback physics mode
//! 2, a visible floor, and the goto-frame edit "0" (`max_frame`). Values the
//! loader resets itself: accessory render order 0, shadow blend 0, gravity
//! 9.8 / 10 / (0, -1, 0), the self-shadow head key (mode 1, distance
//! 0.01125), and an identity camera attachment basis. A model starts with
//! `post_load` 0, edge scale 1, toon 1 and `display_order` equal to its
//! combo index; the tail sections of the stream override them. The saved
//! frame-registration selection is 3 for every model.
//!
//! The scene file names media (wave, AVI, picture, accessories) that this
//! reader does not open. Paths stay as the stream holds them, where the C++
//! stores the resolved path. A non-empty AVI or picture path counts as
//! loaded: the offsets and the enabled flag come from the stream, otherwise
//! they are the unloaded defaults (offset 0, scale 1, disabled).
//!
//! # Where the reader differs from the C++
//!
//! * A model whose PMD `model_file` cannot supply stops the load with an
//!   error. The C++ asks for the file in a dialog and aborts on cancel.
//! * The C++ ignores a failed read inside the tail; this reader accepts the
//!   end of the stream only at a section gate and fails closed on a partial
//!   section or on bytes after the end, as the portable reader does.
//! * A stream that ends right after the shadow-blend byte (the gate of the
//!   per-model edge scales is missing) is accepted here, as a zero-byte
//!   `_read` leaves it in the C++. The portable reader on `next` fails
//!   there; at every later gate it accepts the end of the stream too.
//! * The camera-parent section reads its key list only when the first key's
//!   parent is in range (`pmm_load_v1.cpp`, read-gate 9). The portable
//!   reader on `next` reads it always; this reader follows the C++ here.
//! * A parent or index that names a camera key that does not exist is an
//!   error here; the C++ writes into a free record that no save emits.
//! * A key stored with frame 0 is a free record: it is dropped, as a save
//!   and a reread of the 0002 would drop it.
//! * The two chain-integrity message boxes of the load tail are not shown.
//!   The state they leave is: the root of every bone and IK chain has
//!   `previous` 0, and a chain whose links disagree ends at the last
//!   consistent key.

use crate::io::{Reader, Result};
use crate::key_pool::{
    Key, KeyPool, BONE_KEY_CAPACITY, DISPLAY_KEY_CAPACITY, GLOBAL_KEY_CAPACITY, MORPH_KEY_CAPACITY,
};
use crate::pmd::Pmd;
use crate::pmm::{
    count, links, Accessory, AccessoryKey, AccessoryState, Appearance, Background, BoneKey,
    BonePose, CameraKey, DisplayKey, GravityKey, LightKey, Model, MorphKey, Physics, Pmm,
    Registration, SceneSettings, Selection, SelfShadowKey, Tail, Timeline, View, Wave,
};
use crate::text::{FixedSjis, Sjis};

/// `kSelfShadowDistanceDefault`, `flt_52A1D8`.
const SHADOW_DISTANCE: f32 = 0.01125;
/// The goto-frame edit and `frameRegistrationSelection` of a fresh model.
const REGISTRATION: i32 = 3;

/// The stream loader tests flags as `b == 1`.
fn flag(b: u8) -> u8 {
    u8::from(b == 1)
}

fn cstr(raw: &[u8]) -> &[u8] {
    &raw[..raw.iter().position(|&b| b == 0).unwrap_or(raw.len())]
}

fn name(raw: &[u8]) -> Sjis {
    Sjis::from_raw(cstr(raw).to_vec())
}

/// What the model record holds of a PMD (`pmd_load.cpp`) and the 0002 model
/// block needs.
struct Layout {
    name: Sjis,
    name_en: Sjis,
    bone_names: Vec<Sjis>,
    morph_names: Vec<Sjis>,
    ik_bones: Vec<i32>,
    selector_bones: Vec<i32>,
    group_count: u8,
}

fn layout(r: &Reader, pmd: &Pmd) -> Result<Layout> {
    // The English name is read as 20 bytes and cut to 19; a model without
    // the English section repeats the Japanese name.
    let english = pmd.extension.as_ref().and_then(|e| e.english.as_ref());
    let name_en = match english {
        Some(e) => name(&e.name.raw[..19]),
        None => name(&pmd.name.raw),
    };
    // Two fixed groups, then the file's; one more when facial frames exist.
    let groups = pmd.bone_groups.len() + 2 + usize::from(!pmd.morph_display.is_empty());
    let group_count = u8::try_from(groups).map_err(|_| r.invalid("over 255 display groups"))?;
    // `InitBoneSortOrder`: slot 0 is the root dummy, then every move or IK
    // bone.
    let mut selector_bones = vec![-1];
    for (i, b) in pmd.bones.iter().enumerate() {
        if b.kind == 1 || b.kind == 2 {
            selector_bones.push(i as i32);
        }
    }
    Ok(Layout {
        name: name(&pmd.name.raw),
        name_en,
        bone_names: pmd.bones.iter().map(|b| name(&b.name.raw)).collect(),
        morph_names: pmd.morphs.iter().map(|m| name(&m.name.raw)).collect(),
        ik_bones: pmd.ik_chains.iter().map(|k| i32::from(k.bone)).collect(),
        selector_bones,
        group_count,
    })
}

/// Reads a track as `LoadSceneV1` does: `heads` dense records, a count, then
/// `(index, record)` pairs written to `keys[index]` in stream order. A
/// record with frame 0 is a free record.
fn track<K: Key>(
    r: &mut Reader,
    heads: usize,
    capacity: u32,
    min_size: usize,
    mut item: impl FnMut(&mut Reader) -> Result<K>,
) -> Result<KeyPool<K>> {
    let heads = r.vec(heads, min_size, &mut item)?;
    let mut pool = KeyPool::new(capacity, heads).ok_or_else(|| r.invalid("too many heads"))?;
    let n = count(r)?;
    let sparse = r.vec(n, 4 + min_size, |r| {
        let index = r.i32()?;
        let index = u32::try_from(index)
            .ok()
            .filter(|&i| i < capacity)
            .ok_or_else(|| r.invalid("key index outside the pool"))?;
        Ok((index, item(r)?))
    })?;
    for (index, key) in sparse {
        if let Some(head) = pool.heads_mut().get_mut(index as usize) {
            *head = key;
        } else if key.frame() == 0 {
            pool.remove(index);
        } else {
            pool.insert(index, key);
        }
    }
    Ok(pool)
}

fn display_key(r: &mut Reader, ik: usize, selectors: usize) -> Result<DisplayKey> {
    let [frame, previous, next] = links(r)?;
    Ok(DisplayKey {
        frame,
        previous,
        next,
        visible: flag(r.u8()?),
        ik_enabled: r.bytes(ik)?.iter().map(|&b| flag(b)).collect(),
        // The stream has no selector pairs; a fresh record holds (-1, 0).
        selectors: vec![[-1, 0]; selectors],
        allocated: flag(r.u8()?),
    })
}

fn read_model(
    r: &mut Reader,
    used: &mut [bool; 256],
    model_file: &mut impl FnMut(u8, &[u8; 20], &FixedSjis<256>) -> Option<Pmd>,
) -> Result<Model> {
    let slot = r.u8()?;
    if slot == 255 || std::mem::replace(&mut used[slot as usize], true) {
        return Err(r.invalid("bad model slot"));
    }
    let v1_name = r.array::<20>()?;
    let path = FixedSjis::<256>::read(r)?;
    let pmd = model_file(slot, &v1_name, &path).ok_or_else(|| r.invalid("model file not found"))?;
    let l = layout(r, &pmd)?;
    let (bones, morphs, ik) = (l.bone_names.len(), l.morph_names.len(), l.ik_bones.len());
    let selectors = l.selector_bones.len();

    let combo_index = r.u8()?;
    let load_complete = flag(r.u8()?);
    let selected_bone = r.i32()?;
    let selected_morphs = [r.i32()?, r.i32()?, r.i32()?, r.i32()?];
    // Every stored group byte is consumed; the model keeps the groups it has.
    let stored = r.u8()?;
    let stored = r.bytes(stored.into())?;
    let mut group_flags = vec![0; l.group_count.into()];
    for (g, b) in group_flags.iter_mut().zip(stored) {
        *g = flag(*b);
    }
    let selection = Selection {
        combo_index,
        load_complete,
        selected_bone,
        selected_morphs,
        group_count_repeat: l.group_count,
        group_flags,
        bone_list_pos: r.i32()?,
        max_frame: r.u32()?,
    };
    let bone_keys = track(r, bones, BONE_KEY_CAPACITY, 57, |r| {
        BoneKey::read_dialect(r, false)
    })?;
    let morph_keys = track(
        r,
        morphs,
        MORPH_KEY_CAPACITY,
        MorphKey::SIZE,
        MorphKey::read,
    )?;
    let display_keys = track(r, 1, DISPLAY_KEY_CAPACITY, 14 + ik, |r| {
        display_key(r, ik, selectors)
    })?;
    // The first quaternion component is read twice and the second wins.
    let bone_pose = r.vec(bones, 34, |r| {
        let translation = r.f32s()?;
        let [_, y, z, w] = r.f32s()?;
        let x = r.f32()?;
        Ok(BonePose {
            translation,
            rotation: [x, y, z, w],
            flags: [0, flag(r.u8()?), flag(r.u8()?)],
        })
    })?;
    let morph_pose = r.vec(morphs, 4, |r| r.f32())?;
    let ik_pose = r.bytes(ik)?.iter().map(|&b| flag(b)).collect();
    Ok(Model {
        slot,
        name: l.name,
        name_en: l.name_en,
        path,
        group_count: l.group_count,
        bone_names: l.bone_names,
        morph_names: l.morph_names,
        ik_bones: l.ik_bones,
        selector_bones: l.selector_bones,
        selection,
        bone_keys,
        morph_keys,
        display_keys,
        bone_pose,
        morph_pose,
        ik_pose,
        selector_pose: vec![[0, 0, -1, 0]; selectors],
        post_load: 0,
        edge_scale: 1.0,
        toon: 1,
        display_order: combo_index,
    })
}

trait Chain {
    fn links_mut(&mut self) -> (&mut u32, &mut u32);
}

impl Chain for BoneKey {
    fn links_mut(&mut self) -> (&mut u32, &mut u32) {
        (&mut self.previous, &mut self.next)
    }
}

impl Chain for DisplayKey {
    fn links_mut(&mut self) -> (&mut u32, &mut u32) {
        (&mut self.previous, &mut self.next)
    }
}

/// The chain check of the load tail for the track of `head`: the head's
/// `previous` is 0, and the walk from its `next` ends at the first record
/// whose `previous` is not the record before it. An absent record reads as
/// zeros, as a free record of the C++ pool does.
fn relink<K: Key + Chain>(r: &Reader, pool: &mut KeyPool<K>, head: u32) -> Result<()> {
    if let Some(k) = pool.get_mut(head) {
        *k.links_mut().0 = 0;
    }
    let (mut prev, mut cur) = (head, pool.get(head).map_or(0, |k| k.next()));
    for _ in 0..=pool.capacity() {
        if cur == 0 {
            return Ok(());
        }
        if pool.get(cur).map_or(0, |k| k.previous()) != prev {
            if let Some(k) = pool.get_mut(prev) {
                *k.links_mut().1 = 0;
            }
            return Ok(());
        }
        (prev, cur) = (cur, pool.get(cur).map_or(0, |k| k.next()));
    }
    Err(r.invalid("key chain does not end"))
}

/// `RefreshSelfShadowPanel`: the distance of the self-shadow key at or
/// before `frame`.
fn shadow_distance(pool: &KeyPool<SelfShadowKey>, frame: u32) -> f32 {
    let at = |i: u32| pool.get(i).cloned().unwrap_or_default();
    let mut index = 0;
    if at(0).frame < frame {
        loop {
            let next = at(index).next;
            if next == 0 {
                break;
            }
            index = next;
            if at(index).frame >= frame {
                break;
            }
        }
    }
    let key = at(index);
    if key.frame != frame {
        at(key.previous).distance
    } else {
        key.distance
    }
}

/// A section gate of the tail: false at the end of the stream and for a byte
/// other than 1.
fn gate(r: &mut Reader) -> Result<bool> {
    Ok(r.remaining() != 0 && r.u8()? == 1)
}

/// The sections after the configuration block. Each starts behind a gate, and
/// the stream may end at any gate (`pmm_load_v1.cpp`, `ReadGatedTail`).
fn tail(r: &mut Reader, p: &mut Pmm) -> Result<()> {
    if r.remaining() == 0 {
        return Ok(());
    }
    // Models and accessories are visited in slot order, 0..255.
    let mut accessories: Vec<usize> = (0..p.accessories.len()).collect();
    accessories.sort_by_key(|&i| p.accessories[i].slot);

    p.physics.accessory_render_order = r.i32()?;
    p.physics.projected_shadow_ambient = r.f32()?;
    for m in &mut p.models {
        m.post_load = flag(r.u8()?);
    }
    for &i in &accessories {
        p.accessories[i].state.additive = flag(r.u8()?);
    }
    if r.remaining() == 0 {
        return Ok(());
    }
    let edge_scale = r.f32()?;
    p.models.iter_mut().for_each(|m| m.edge_scale = edge_scale);
    p.physics.projected_shadow_blend = flag(r.u8()?);
    if !gate(r)? {
        return Ok(());
    }
    for m in &mut p.models {
        m.edge_scale = r.f32()?;
    }
    if !gate(r)? {
        return Ok(());
    }
    let ph = &mut p.physics;
    ph.playback_mode = r.u8()?;
    ph.gravity_magnitude = r.f32()?;
    ph.gravity_noise = r.i32()?;
    ph.gravity_direction = r.f32s()?;
    ph.gravity_noise_enabled = flag(r.u8()?);
    if !gate(r)? {
        return Ok(());
    }
    let mode = r.u8()?;
    p.self_shadow_mode = u8::from(mode != 0);
    let head = &mut p.self_shadow.heads_mut()[0];
    head.mode = mode;
    head.distance = r.f32()?;
    for m in &mut p.models {
        m.toon = flag(r.u8()?);
    }
    if !gate(r)? {
        return Ok(());
    }
    p.self_shadow = track(
        r,
        1,
        GLOBAL_KEY_CAPACITY,
        SelfShadowKey::SIZE,
        self_shadow_key,
    )?;
    if !gate(r)? {
        return Ok(());
    }
    p.appearance.outline_color = [r.i32()?, r.i32()?, r.i32()?];
    if !gate(r)? {
        return Ok(());
    }
    p.appearance.black_background = u8::from(r.u8()? != 0);
    if !gate(r)? {
        return Ok(());
    }
    let (model, bone) = (r.i32()?, r.i32()?);
    let head = &mut p.camera.heads_mut()[0];
    (head.parent_model, head.parent_bone) = (model, bone);
    if (0..1_000).contains(&model) && (0..10_000).contains(&bone) {
        let n = count(r)?;
        let parents = r.vec(n, 12, |r| Ok((r.i32()?, r.i32()?, r.i32()?)))?;
        for (index, model, bone) in parents {
            let key = u32::try_from(index)
                .ok()
                .and_then(|i| p.camera.get_mut(i))
                .ok_or_else(|| r.invalid("camera parent of a free key"))?;
            (key.parent_model, key.parent_bone) = (model, bone);
        }
        p.appearance.camera_parent_model = r.i32()?;
        p.appearance.camera_parent_bone = r.i32()?;
    }
    if !gate(r)? {
        return Ok(());
    }
    p.appearance.camera_attachment_basis = r.f32s()?;
    p.appearance.follow_camera = flag(r.u8()?);
    p.appearance.suppress_camera_transform = flag(r.u8()?);
    if !gate(r)? {
        return Ok(());
    }
    p.appearance.floor_visible = u8::from(r.u8()? != 0);
    if !gate(r)? {
        return Ok(());
    }
    for m in &mut p.models {
        m.display_order = r.u8()?;
    }
    Ok(())
}

fn light_key(r: &mut Reader) -> Result<LightKey> {
    let mut k = LightKey::read(r)?;
    k.selected = flag(k.selected);
    Ok(k)
}

fn self_shadow_key(r: &mut Reader) -> Result<SelfShadowKey> {
    let mut k = SelfShadowKey::read(r)?;
    k.selected = flag(k.selected);
    Ok(k)
}

fn accessory_key(r: &mut Reader) -> Result<AccessoryKey> {
    let mut k = AccessoryKey::read(r)?;
    k.shadow = flag(k.shadow);
    k.selected = flag(k.selected);
    Ok(k)
}

fn camera_key(r: &mut Reader) -> Result<CameraKey> {
    let mut k = CameraKey::read_dialect(r, false)?;
    k.perspective = flag(k.perspective);
    k.selected = flag(k.selected);
    Ok(k)
}

/// Reads a version 1 scene from the byte after its 30-byte header.
pub(crate) fn read(
    r: &mut Reader,
    mut model_file: impl FnMut(u8, &[u8; 20], &FixedSjis<256>) -> Option<Pmd>,
) -> Result<Pmm> {
    let mut header = [0; 30];
    header[..24].copy_from_slice(b"Polygon Movie maker 0002");
    let mut settings = SceneSettings {
        render_width: r.i32()?,
        render_height: r.i32()?,
        panel_width: r.i32()?,
        camera_fov: r.f32()?,
        options: [0, 0, 0, 0, 0, 0, 1],
    };
    for o in &mut settings.options[..6] {
        *o = flag(r.u8()?);
    }
    let selected_model_slot = r.u8()?;
    let model_count = r.u8()?;
    if model_count > 254 || selected_model_slot == 255 {
        return Err(r.invalid("bad model count or selected slot"));
    }
    // The 20-byte names only fill the model combo box.
    r.bytes(20 * usize::from(model_count))?;
    let mut used = [false; 256];
    let mut models = r.vec(model_count.into(), 1, |r| {
        read_model(r, &mut used, &mut model_file)
    })?;
    models.sort_by_key(|m| m.slot);

    // `ReallocateTracks` seeds every camera key with parent model -1, which
    // the 0001 record keeps (`CameraKey::read_dialect`).
    let camera = track(r, 1, GLOBAL_KEY_CAPACITY, 70, camera_key)?;
    let camera_state = r.f32s()?;
    let camera_perspective = flag(r.u8()?);
    let light = track(r, 1, GLOBAL_KEY_CAPACITY, LightKey::SIZE, light_key)?;
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
            keys: track(r, 1, GLOBAL_KEY_CAPACITY, AccessoryKey::SIZE, accessory_key)?,
            state: AccessoryState {
                opacity_visible: r.u8()?,
                parent_model: r.i32()?,
                parent_bone: r.i32()?,
                rotation: r.f32s()?,
                scale: r.f32()?,
                position: r.f32s()?,
                shadow: flag(r.u8()?),
                additive: 0,
            },
        });
    }

    let mut timeline = Timeline {
        current_frame: r.i32()?,
        start_frame: r.i32()?,
        last_registered_frame: r.i32()?,
        edit_mode: r.i32()?,
        ..Timeline::default()
    };
    timeline.camera_reference_mode = r.u8()?;
    timeline.playback_loop = u8::from(r.u8()? != 0);
    timeline.return_to_start = u8::from(r.u8()? != 0);
    timeline.start_at_current = u8::from(r.u8()? != 0);
    timeline.play_start_frame = r.i32()?;
    timeline.play_stop_frame = r.i32()?;
    let wave = Wave {
        enabled: u8::from(r.u8()? != 0),
        path: FixedSjis::read(r)?,
    };
    let avi = {
        let b = Background::read(r, true)?;
        if b.path.raw[0] != 0 {
            b
        } else {
            Background {
                offset: [0, 0],
                scale: 1.0,
                enabled: 0,
                ..b
            }
        }
    };
    let picture = {
        let b = Background::read(r, false)?;
        if b.path.raw[0] != 0 {
            Background {
                enabled: u32::from(b.enabled != 0),
                ..b
            }
        } else {
            Background {
                offset: [0, 0],
                scale: 1.0,
                enabled: 0,
                ..b
            }
        }
    };
    let view = View {
        fps_overlay: u8::from(r.u8()? != 0),
        ground_grid: u8::from(r.u8()? != 0),
        ground_shadow: u8::from(r.u8()? != 0),
        fps_limit: r.f32()?,
        capture_mode: r.i32()?,
    };

    let mut p = Pmm {
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
        physics: Physics {
            accessory_render_order: 0,
            projected_shadow_ambient: 0.0,
            projected_shadow_blend: 0,
            playback_mode: 2,
            gravity_magnitude: 9.8,
            gravity_noise: 10,
            gravity_direction: [0.0, -1.0, 0.0],
            gravity_noise_enabled: 0,
        },
        gravity: KeyPool::new(
            GLOBAL_KEY_CAPACITY,
            vec![GravityKey {
                noise: 10,
                acceleration: 9.8,
                direction: [0.0, -1.0, 0.0],
                ..GravityKey::default()
            }],
        )
        .expect("one head fits"),
        self_shadow_mode: 0,
        physics_interval: SHADOW_DISTANCE,
        self_shadow: KeyPool::new(
            GLOBAL_KEY_CAPACITY,
            vec![SelfShadowKey {
                mode: 1,
                distance: SHADOW_DISTANCE,
                ..SelfShadowKey::default()
            }],
        )
        .expect("one head fits"),
        appearance: Appearance {
            outline_color: [0; 3],
            black_background: 0,
            camera_parent_model: -1,
            camera_parent_bone: 0,
            camera_attachment_basis: [
                1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0,
            ],
            follow_camera: 0,
            suppress_camera_transform: 0,
            floor_visible: 1,
            max_frame: 0,
        },
        tail: Tail::Absent,
    };
    tail(r, &mut p)?;
    if r.remaining() != 0 {
        return Err(r.invalid("bytes after the end of the scene"));
    }

    p.physics_interval = shadow_distance(&p.self_shadow, p.timeline.current_frame as u32);
    for m in &mut p.models {
        relink(r, &mut m.display_keys, 0)?;
        for head in 0..m.bone_names.len() as u32 {
            relink(r, &mut m.bone_keys, head)?;
        }
    }
    p.tail = Tail::Registrations(
        p.models
            .iter()
            .map(|m| Registration {
                slot: m.slot,
                selection: REGISTRATION,
            })
            .collect(),
    );
    Ok(p)
}
