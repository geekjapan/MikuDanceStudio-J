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
    mds_accessory::load_x(data).map_err(|e| Error::Format(format!("{path}: {e:?}")))?;
    let name = path
        .rsplit_once('\\')
        .map(|(_, n)| n)
        .ok_or(Error::NotApplicable(
            "an accessory path without a backslash",
        ))?;
    let slot = (0..255u8)
        .find(|s| p.accessories.iter().all(|a| a.slot != *s))
        .ok_or(Error::NotApplicable("every accessory slot is taken"))?;
    // `CB_ADDSTRING` on the unsorted combo 471.
    let order = p.accessories.len() as u8;
    let state = AccessoryState {
        opacity_visible: crate::save::opacity_visible(1.0, 1),
        parent_model: -1,
        parent_bone: 0,
        rotation: [0.0; 3],
        scale: 1.0,
        position: [0.0; 3],
        shadow: 0,
        additive: 0,
    };
    // The slot's key array as `ResetAppState` leaves it (visible, no
    // parent), then the record's position, rotation, scale, opacity and
    // shadow.
    let head = AccessoryKey {
        opacity_visible: crate::save::opacity_visible(1.0, 1),
        parent_model: -1,
        scale: 1.0,
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
