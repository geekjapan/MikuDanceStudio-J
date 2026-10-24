//! Trace format 1, level L1: the writer of `src/tools/scene_trace.hpp`.
//!
//! ```text
//! mds-trace 1 L1
//! <frame> bone  <slot> <index> tx ty tz rx ry rz rw      (per model: bones, then morphs)
//! <frame> morph <slot> <index> weight
//! <frame> camera px py pz rx ry rz distance fov
//! <frame> light r g b dx dy dz
//! ```
//!
//! A float is the C99 `%a` of the `f32` widened to `f64`, for example
//! `0x1.8p+1`. The grammar and the reader are in `mds-trace`.

use crate::frame::{evaluate_scene_frame, ScenePose};
use crate::playback::{advance_playback, start_playback};
use mds_formats::pmm::Pmm;
use std::fmt::{self, Write as _};
use std::io::{self, Write};

#[derive(Debug)]
pub enum Error {
    /// A frame did not evaluate (broken key links).
    Evaluate {
        frame: u32,
    },
    /// A traced value is `nan` or infinite.
    NotFinite {
        frame: u32,
    },
    Io(io::Error),
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Error::Evaluate { frame } => write!(f, "frame {frame} does not evaluate"),
            Error::NotFinite { frame } => write!(f, "frame {frame} has a non-finite value"),
            Error::Io(e) => write!(f, "write error: {}", e.kind()),
        }
    }
}

impl std::error::Error for Error {}

impl From<io::Error> for Error {
    fn from(e: io::Error) -> Self {
        Error::Io(e)
    }
}

/// `printf("%a", double(value))` for a finite `f32`: `0x1.8p+1`, `-0x0p+0`.
/// `None` for `nan` and infinity.
pub fn hex_float(value: f32) -> Option<String> {
    if !value.is_finite() {
        return None;
    }
    let bits = f64::from(value).to_bits();
    let sign = if bits >> 63 != 0 { "-" } else { "" };
    let exponent = ((bits >> 52) & 0x7ff) as i32;
    let mantissa = bits & ((1u64 << 52) - 1);
    if exponent == 0 {
        // Zero: a widened f32 is never a double subnormal.
        debug_assert_eq!(mantissa, 0);
        return Some(format!("{sign}0x0p+0"));
    }
    let digits = format!("{mantissa:013x}");
    let digits = digits.trim_end_matches('0');
    let point = if digits.is_empty() { "" } else { "." };
    let e = exponent - 1023;
    Some(format!(
        "{sign}0x1{point}{digits}p{}{}",
        if e < 0 { '-' } else { '+' },
        e.abs()
    ))
}

fn floats(line: &mut String, values: &[f32]) -> Option<()> {
    for &v in values {
        line.push(' ');
        line.push_str(&hex_float(v)?);
    }
    Some(())
}

/// Writes the lines of one sample under the label `frame`.
fn write_pose(out: &mut impl Write, frame: u32, pose: &ScenePose) -> Result<(), Error> {
    let bad = || Error::NotFinite { frame };
    let mut line = String::new();
    for model in &pose.models {
        for (i, bone) in model.bones.iter().enumerate() {
            line.clear();
            write!(line, "{frame} bone {} {i}", model.slot).unwrap();
            floats(&mut line, &bone.translation).ok_or_else(bad)?;
            floats(&mut line, &bone.rotation).ok_or_else(bad)?;
            line.push('\n');
            out.write_all(line.as_bytes())?;
        }
        for (i, &weight) in model.morph_values.iter().enumerate() {
            line.clear();
            write!(line, "{frame} morph {} {i}", model.slot).unwrap();
            floats(&mut line, &[weight]).ok_or_else(bad)?;
            line.push('\n');
            out.write_all(line.as_bytes())?;
        }
    }
    line.clear();
    write!(line, "{frame} camera").unwrap();
    floats(&mut line, &pose.camera.position).ok_or_else(bad)?;
    floats(&mut line, &pose.camera.rotation).ok_or_else(bad)?;
    floats(&mut line, &[pose.camera.distance, pose.camera.fov]).ok_or_else(bad)?;
    write!(line, "\n{frame} light").unwrap();
    floats(&mut line, &pose.light_state).ok_or_else(bad)?;
    line.push('\n');
    out.write_all(line.as_bytes())?;
    Ok(())
}

const HEADER: &[u8] = b"mds-trace 1 L1\n";

/// `WriteSceneTrace`: frames `0..frames` of `EvaluatePmmSceneFrame`.
pub fn write_scene_trace(out: &mut impl Write, scene: &Pmm, frames: u32) -> Result<(), Error> {
    out.write_all(HEADER)?;
    for frame in 0..frames {
        let pose = evaluate_scene_frame(scene, frame).ok_or(Error::Evaluate { frame })?;
        write_pose(out, frame, &pose)?;
    }
    Ok(())
}

/// Samples of the playback evaluator, one block per entry of `seconds`,
/// labelled with the sample index. The state starts at frame 0 and advances
/// through the list, so `seconds` must not decrease.
pub fn write_playback_trace(
    out: &mut impl Write,
    scene: &Pmm,
    seconds: &[f32],
) -> Result<(), Error> {
    out.write_all(HEADER)?;
    let mut state = start_playback(scene).ok_or(Error::Evaluate { frame: 0 })?;
    for (sample, &s) in seconds.iter().enumerate() {
        let label = sample as u32;
        advance_playback(scene, s, &mut state).ok_or(Error::Evaluate { frame: label })?;
        write_pose(out, label, &state.pose)?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::hex_float;

    #[test]
    fn hex_float_matches_printf() {
        let cases: [(f32, &str); 9] = [
            (0.0, "0x0p+0"),
            (-0.0, "-0x0p+0"),
            (1.0, "0x1p+0"),
            (3.0, "0x1.8p+1"),
            (-0.5, "-0x1p-1"),
            (0.8, "0x1.99999ap-1"),
            (30.0, "0x1.ep+4"),
            (f32::MIN_POSITIVE, "0x1p-126"),
            // A subnormal f32 is a normal f64.
            (f32::from_bits(1), "0x1p-149"),
        ];
        for (value, text) in cases {
            assert_eq!(hex_float(value).as_deref(), Some(text), "{value:e}");
        }
        assert_eq!(hex_float(f32::NAN), None);
        assert_eq!(hex_float(f32::INFINITY), None);
    }
}
