//! Accessory loading: "load accessory" (button 472, `LoadAccessoryFile`,
//! `src/render/accessory.cpp`, VA 0x00460B30) and "load WAVE" (menu 206,
//! `LoadWaveFile`, `src/media/wave_audio.cpp`).

use crate::Error;
use mds_formats::key_pool::{KeyPool, GLOBAL_KEY_CAPACITY};
use mds_formats::pmm::{self, AccessoryKey, AccessoryState, Pmm};
use mds_formats::text::FixedSjis;

pub(crate) fn fixed<const N: usize>(text: &str) -> FixedSjis<N> {
    let mut raw = [0; N];
    let s = crate::add_model::sjis(text, N).raw;
    raw[..s.len()].copy_from_slice(&s);
    FixedSjis {
        raw,
        text: text.to_string(),
    }
}

/// `strcpy_s` (and `WideToAnsi`) into a 100-byte name: the bytes and a NUL;
/// what follows stays.
pub(crate) fn strcpy_name(name: &mut FixedSjis<100>, s: &[u8]) {
    let s = &s[..s.len().min(99)];
    name.raw[..s.len()].copy_from_slice(s);
    name.raw[s.len()] = 0;
    name.text = mds_formats::text::decode_sjis(&name.raw);
}

fn cstr(s: &[u8]) -> &[u8] {
    &s[..s.iter().position(|&b| b == 0).unwrap_or(s.len())]
}

/// The name an accessory record holds after a PMM load (`pmm_load_v2.cpp`
/// 1799-1865): a zeroed record, `LoadAccessoryObject`'s file name of the
/// path (`accessory.cpp` 445), then `strcpy_s` of the saved name.
// ponytail: a `.vac` writes the name of its mesh between the two; the
// document does not read the `.vac` here, so its file name stands in.
pub(crate) fn record_name(a: &mut pmm::Accessory) {
    let path = cstr(&a.path.raw);
    let Some(at) = path.iter().rposition(|&b| b == b'\\') else {
        return;
    };
    let saved = cstr(&a.name.raw).to_vec();
    let mut name = fixed::<100>("");
    strcpy_name(&mut name, &path[at + 1..]);
    strcpy_name(&mut name, &saved);
    a.name = name;
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
/// (`fgets`, then the `\n` cut), as Shift-JIS bytes. The file is read in
/// text mode (`_wfopen_s(.., L"r")`, `accessory.cpp` 464), so CRLF reads as
/// LF.
pub fn vac_mesh_name(vac: &[u8]) -> Vec<u8> {
    let mut text = Vec::with_capacity(vac.len());
    for (i, &b) in vac.iter().enumerate() {
        if !(b == b'\r' && vac.get(i + 1) == Some(&b'\n')) {
            text.push(b);
        }
    }
    let mut lines = text.split_inclusive(|&b| b == b'\n');
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
    // `LoadAccessoryObject`: the file name of the path, then a `.vac`'s
    // mesh name over it (`accessory.cpp` 445, 477).
    let mut record = fixed::<100>("");
    let tail = path.rsplit_once('\\').map_or(path, |(_, t)| t);
    strcpy_name(&mut record, &crate::add_model::sjis(tail, 100).raw);
    strcpy_name(&mut record, &crate::add_model::sjis(name, 100).raw);
    let a = pmm::Accessory {
        list_name: fixed(name),
        slot,
        name: record,
        path: fixed(path),
        order,
        keys: KeyPool::new(GLOBAL_KEY_CAPACITY, vec![head])
            .ok_or(Error::NotApplicable("accessory keys"))?,
        state,
    };
    p.accessories.push(a);
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
