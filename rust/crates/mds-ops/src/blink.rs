//! Random blinks (menu 227).

use crate::model::{active_model, commit, open, soft};
use crate::{Error, ModelFacts, Result};
use mds_formats::pmm::Pmm;

/// The MSVC CRT `rand()`: a linear congruential generator over a 32-bit
/// state, `state = state * 214013 + 2531011`, returning bits 16 to 30. The C
/// application never calls `srand`, so the state starts at 1, and the one
/// generator is shared by every caller of `rand()` (menu 227 and the gravity
/// noise of the physics loop); keep one value per application and pass it
/// to every user.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct MsvcRand(pub u32);

impl Default for MsvcRand {
    fn default() -> Self {
        MsvcRand(1)
    }
}

impl MsvcRand {
    pub fn rand(&mut self) -> i32 {
        self.0 = self.0.wrapping_mul(214_013).wrapping_add(2_531_011);
        ((self.0 >> 16) & 0x7fff) as i32
    }
}

/// "まばたき" in Shift-JIS: the name `memcmp(name, ..., 9)` looks for, whose
/// ninth byte is the NUL.
const MABATAKI: [u8; 8] = [0x82, 0xDC, 0x82, 0xCE, 0x82, 0xBD, 0x82, 0xAB];

fn is_blink(name: &[u8]) -> bool {
    name.get(..MABATAKI.len()) == Some(&MABATAKI)
        && name.get(MABATAKI.len()).is_none_or(|&b| b == 0)
}

/// Menu 227, register random blinking (`src/window/command_file_menu.cpp`
/// 1352-1438). The blink morph is the first one named まばたき, else
/// [`Error::NoBlinkMorph`] (the C++ shows a message box). From `start` while
/// `frame < end`, each step draws `q = rand() * 230 / 32768`:
///
/// * `q < 90` and `blink_phase <= 0` (as a signed byte): `frame += 7`,
///   `blink_phase = 3`, register a blink;
/// * else `q > 50`: `frame += q`, `blink_phase -= 1`, register a blink;
/// * otherwise nothing happens and the loop draws again.
///
/// A blink registers the morph's weight 0 at `frame`, 1 at `frame + 2`, 1 at
/// `frame + 3` and 0 at `frame + 6` with `RegisterMorphKeyCurrent`, so the
/// morph's live weight is 0 afterwards (in the PMM, `morph_pose`). The
/// `blink_phase` byte lives in the application and persists between calls.
/// Afterwards `last_registered_frame` rises to the model's `max_frame`.
/// Returns the number of blinks, which the message box reports.
///
/// A full pool does not stop the loop; the first error is returned after
/// the loop and the pools keep the keys registered.
pub fn random_blinks(
    pmm: &mut Pmm,
    facts: &ModelFacts,
    start: i32,
    end: i32,
    rng: &mut MsvcRand,
    blink_phase: &mut u8,
) -> Result<u32> {
    if pmm.settings.options[0] != 0 {
        return Err(Error::WrongMode);
    }
    let m = active_model(pmm)?;
    let (mut tracks, mut rig) = open(&pmm.models[m], facts)?;
    let blink = rig
        .morphs
        .iter()
        .position(|morph| is_blink(&morph.name))
        .ok_or(Error::NoBlinkMorph)? as i32;
    let mut first = Ok(());
    let (mut frame, mut count) = (start, 0);
    while frame < end {
        let q = rng.rand() * 230 / 32768;
        let phase = *blink_phase as i8;
        if q < 90 && phase <= 0 {
            frame = frame.wrapping_add(7);
            *blink_phase = 3;
        } else if q > 50 {
            frame = frame.wrapping_add(q);
            *blink_phase = phase.wrapping_sub(1) as u8;
        } else {
            continue;
        }
        for (value, at) in [(0.0, 0), (1.0, 2), (1.0, 3), (0.0, 6)] {
            rig.morphs[blink as usize].value = value;
            if let Err(e) =
                tracks.register_morph_current(&rig, blink, frame.wrapping_add(at) as u32)
            {
                soft(&mut first, e)?;
            }
        }
        count += 1;
    }
    let last = pmm
        .timeline
        .last_registered_frame
        .max(tracks.max_frame as i32);
    commit(&mut pmm.models[m], tracks, &rig);
    pmm.timeline.last_registered_frame = last;
    first.map(|()| count)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rand_is_the_msvc_sequence() {
        let mut r = MsvcRand::default();
        let first: Vec<i32> = (0..10).map(|_| r.rand()).collect();
        assert_eq!(
            first,
            [41, 18467, 6334, 26500, 19169, 15724, 11478, 29358, 26962, 24464]
        );
    }

    #[test]
    fn blink_name_matches_nine_bytes() {
        let mut name = MABATAKI.to_vec();
        assert!(is_blink(&name));
        name.push(0);
        name.extend([0x41; 3]);
        assert!(is_blink(&name), "residue after the NUL is not compared");
        assert!(!is_blink(&[MABATAKI.as_slice(), b"x"].concat()));
        assert!(!is_blink(&MABATAKI[..6]));
    }
}
