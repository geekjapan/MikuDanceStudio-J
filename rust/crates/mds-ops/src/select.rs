//! Select-all frames. Selection is the mark byte of every key record
//! (`allocated` on model keys, `selected` on global keys); the commands
//! clear every mark of the family and set it on the records that hold a key
//! and on the track heads.

use crate::model::active_model;
use crate::pool::set_marks;
use crate::Result;
use mds_formats::pmm::Pmm;

/// Menu 217, `SelectFrameGroup(Bone)` (`src/window/frame_line_edit.cpp`,
/// 540-553): the mark of a bone key is set when the record is a bone's head
/// (`i < boneCount`) or holds a key (`frame != 0`). Only the mark byte
/// changes; the physics byte next to it is left alone.
pub fn select_all_bone_frames(pmm: &mut Pmm) -> Result<()> {
    let m = active_model(pmm)?;
    let pool = &mut pmm.models[m].bone_keys;
    let heads = pool.heads().len() as u32;
    set_marks(pool, |i, k| i < heads || k.frame != 0);
    Ok(())
}

/// Menu 218, `SelectFrameGroup(Display)` (`frame_line_edit.cpp`, 554-565):
/// the mark is set where `frame != 0`, and record 0 is forced to 1 after the
/// loop.
pub fn select_all_display_frames(pmm: &mut Pmm) -> Result<()> {
    let m = active_model(pmm)?;
    let pool = &mut pmm.models[m].display_keys;
    set_marks(pool, |_, k| k.frame != 0);
    pool.heads_mut()[0].allocated = 1;
    Ok(())
}

/// Menu 220, `SelectFrameGroup(Morph)` (`frame_line_edit.cpp`, 566-577):
/// like the bone variant, with the morph count.
pub fn select_all_morph_frames(pmm: &mut Pmm) -> Result<()> {
    let m = active_model(pmm)?;
    let pool = &mut pmm.models[m].morph_keys;
    let heads = pool.heads().len() as u32;
    set_marks(pool, |i, k| i < heads || k.frame != 0);
    Ok(())
}

/// Menus 237 to 241 mark a global record when it holds a key or is record 0
/// (`esi == 0`, "frame 0 always selected"), in
/// `src/window/command_file_menu.cpp` 1964-2029.
fn global(i: u32, frame: u32) -> bool {
    frame != 0 || i == 0
}

/// Menu 237 (`command_file_menu.cpp`, 1964-1979): the camera track.
pub fn select_all_camera_frames(pmm: &mut Pmm) {
    set_marks(&mut pmm.camera, |i, k| global(i, k.frame));
}

/// Menu 238 (`command_file_menu.cpp`, 1981-1995): the light track.
pub fn select_all_light_frames(pmm: &mut Pmm) {
    set_marks(&mut pmm.light, |i, k| global(i, k.frame));
}

/// Menu 239 (`command_file_menu.cpp`, 1997-2011): the self-shadow track.
pub fn select_all_self_shadow_frames(pmm: &mut Pmm) {
    set_marks(&mut pmm.self_shadow, |i, k| global(i, k.frame));
}

/// Menu 240 (`command_file_menu.cpp`, 2013-2027): the gravity track.
pub fn select_all_gravity_frames(pmm: &mut Pmm) {
    set_marks(&mut pmm.gravity, |i, k| global(i, k.frame));
}

/// Menu 241 (`command_file_menu.cpp`, 2029 onward): every accessory's
/// track, the test restarting at record 0 for each table.
pub fn select_all_accessory_frames(pmm: &mut Pmm) {
    for acc in &mut pmm.accessories {
        set_marks(&mut acc.keys, |i, k| global(i, k.frame));
    }
}
