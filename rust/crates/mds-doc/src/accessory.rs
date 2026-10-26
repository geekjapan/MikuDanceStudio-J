//! Accessory loading: "load accessory" (button 472, `LoadAccessoryFile`,
//! `src/render/accessory.cpp`, VA 0x00460B30) and "load WAVE" (menu 206,
//! `LoadWaveFile`, `src/media/wave_audio.cpp`).

use crate::Error;
use mds_formats::key_pool::{KeyPool, GLOBAL_KEY_CAPACITY};
use mds_formats::pmm::{self, AccessoryKey, AccessoryState, Pmm};
use mds_formats::text::FixedSjis;

fn fixed<const N: usize>(text: &str) -> FixedSjis<N> {
    let mut raw = [0; N];
    let s = crate::add_model::sjis(text, N).raw;
    raw[..s.len()].copy_from_slice(&s);
    FixedSjis {
        raw,
        text: text.to_string(),
    }
}

/// The accessory record for `path`: `InitAccessoryRecord`
/// (`src/render/debug_geometry.cpp`), the name after the last backslash
/// (`LoadAccessoryObject`), the next combo index as its order, and the
/// head key seeded with the record (`LoadAccessoryFile`).
pub(crate) fn load(p: &mut Pmm, path: &str, data: &[u8]) -> Result<u8, Error> {
    let name = path
        .rsplit_once('\\')
        .map(|(_, n)| n)
        .ok_or(Error::NotApplicable(
            "an accessory path without a backslash",
        ))?;
    place(p, path, name, data, None)
}

/// The mesh file a `.vac` names: its second line without the newline
/// (`fgets`, then the `\n` cut), as Shift-JIS bytes.
pub fn vac_mesh_name(vac: &[u8]) -> Vec<u8> {
    let mut lines = vac.split_inclusive(|&b| b == b'\n');
    lines.next();
    let line = lines.next().unwrap_or(&[]);
    let line = &line[..line.len().min(255)];
    line.split(|&b| b == b'\n').next().unwrap_or(&[]).to_vec()
}

/// The `.vac` branch of `LoadAccessoryObject` (`src/render/accessory.cpp`
/// 461-488): the name is the mesh's file name (after the last backslash of
/// `mesh_path`, the whole path without one), the saved path is the `.vac`,
/// and the record and the head key take the scale, position, rotation and
/// shadow of the file (650-658).
pub(crate) fn load_vac(
    p: &mut Pmm,
    path: &str,
    vac: &[u8],
    mesh_path: &str,
    mesh: &[u8],
) -> Result<u8, Error> {
    if !path.contains('\\') {
        return Err(Error::NotApplicable(
            "an accessory path without a backslash",
        ));
    }
    let name = mesh_path.rsplit_once('\\').map_or(mesh_path, |(_, n)| n);
    place(p, path, name, mesh, Some(mds_accessory::vac::parse(vac)))
}

fn place(
    p: &mut Pmm,
    path: &str,
    name: &str,
    data: &[u8],
    vac: Option<mds_accessory::vac::Vac>,
) -> Result<u8, Error> {
    mds_accessory::load_x(data).map_err(|e| Error::Format(format!("{path}: {e:?}")))?;
    let slot = (0..255u8)
        .find(|s| p.accessories.iter().all(|a| a.slot != *s))
        .ok_or(Error::NotApplicable("every accessory slot is taken"))?;
    // `CB_ADDSTRING` on the unsorted combo 471.
    let order = p.accessories.len() as u8;
    let mut state = AccessoryState {
        opacity_visible: crate::save::opacity_visible(1.0, 1),
        parent_model: -1,
        parent_bone: 0,
        rotation: [0.0; 3],
        scale: 1.0,
        position: [0.0; 3],
        shadow: 0,
        additive: 0,
    };
    if let Some(v) = vac {
        state.scale = v.scale;
        state.position = v.position;
        state.rotation = v.rotation;
        state.shadow = u8::from(v.shadow_enabled);
    }
    // The slot's key array as `ResetAppState` leaves it (visible, no
    // parent), then the record's position, rotation, scale, opacity and
    // shadow.
    let head = AccessoryKey {
        opacity_visible: crate::save::opacity_visible(1.0, 1),
        parent_model: -1,
        scale: state.scale,
        position: state.position,
        rotation: state.rotation,
        shadow: state.shadow,
        ..AccessoryKey::default()
    };
    let a = pmm::Accessory {
        list_name: fixed(name),
        slot,
        name: fixed(name),
        path: fixed(path),
        order,
        keys: KeyPool::new(GLOBAL_KEY_CAPACITY, vec![head])
            .ok_or(Error::NotApplicable("accessory keys"))?,
        state,
    };
    let at = p.accessories.partition_point(|a| a.slot < slot);
    p.accessories.insert(at, a);
    let r = &mut p.physics.accessory_render_order;
    *r = (*r).max(i32::from(order) + 1);
    p.selected_accessory_slot = slot;
    Ok(slot)
}

/// `LoadWaveFile`: a RIFF WAVE file sets the path and enables the wave;
/// anything else clears both.
// ponytail: only the RIFF/WAVE header is checked; `WaveLoadFile` also needs
// a PCM `fmt ` and a `data` chunk. Port its parser when a script loads a
// broken WAV.
pub(crate) fn load_wave(p: &mut Pmm, path: &str, data: &[u8]) {
    let ok = data.len() >= 12 && &data[..4] == b"RIFF" && &data[8..12] == b"WAVE";
    p.wave.enabled = u8::from(ok);
    p.wave.path = fixed(if ok { path } else { "" });
}

impl crate::Document {
    /// The bones the accessory parent bone combo (475) lists for the model
    /// in `slot`, as bone indices (`RepopulateBoneCombo`,
    /// `src/window/command_dispatch.cpp` 72-85): types below 7 (`InertTip`)
    /// and 8 (`FixedAxis`). [`crate::Command::SetAccessoryParentBone`]
    /// takes the bone index, not the combo row.
    pub fn accessory_parent_bones(&self, slot: u8) -> Vec<u32> {
        let Some(i) = self.pmm.models.iter().position(|m| m.slot == slot) else {
            return Vec::new();
        };
        let pose = match &self.models[i] {
            crate::ModelFile::Pmx(p) => mds_pose::model::Model::from_pmx(slot, p),
            crate::ModelFile::Pmd(p) => mds_pose::model::Model::from_pmd(slot, p),
            crate::ModelFile::Missing => return Vec::new(),
        };
        let Ok(pose) = pose else { return Vec::new() };
        (0..pose.bones.len() as u32)
            .filter(|&b| matches!(pose.bones[b as usize].kind, 0..=6 | 8))
            .collect()
    }
}
