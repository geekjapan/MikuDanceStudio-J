//! The pose lines of trace format 1, level L2 (`src/tools/trace_l2.hpp`):
//! per model in slot order, every `bone`, then every `bonew`, then every
//! `morph`. The `rigid` lines belong to `mds-physics`.

use crate::Scene;
use std::fmt::Write as _;

pub const HEADER: &str = "mds-trace 1 L2\n";

/// `FormatHexFloat`: `[-]0x1.hhhhhhp[+-]d`, or `[-]0x0.000000p+0` for zero.
/// `None` for nan and infinity.
pub fn hex_float(value: f32) -> Option<String> {
    let bits = value.to_bits();
    let biased = (bits >> 23) & 0xff;
    let mut mantissa = bits & 0x7f_ffff;
    if biased == 0xff {
        return None;
    }
    let mut exponent = 0i32;
    if biased != 0 {
        exponent = biased as i32 - 127;
    } else if mantissa != 0 {
        exponent = -126;
        while mantissa & 0x80_0000 == 0 {
            mantissa <<= 1;
            exponent -= 1;
        }
        mantissa &= 0x7f_ffff;
    }
    let lead = if biased == 0 && bits & 0x7f_ffff == 0 {
        '0'
    } else {
        '1'
    };
    let sign = if bits >> 31 != 0 { "-" } else { "" };
    let e = if exponent < 0 { '-' } else { '+' };
    Some(format!(
        "{sign}0x{lead}.{:06x}p{e}{}",
        mantissa << 1,
        exponent.unsigned_abs()
    ))
}

fn floats(line: &mut String, values: &[f32]) -> Result<(), String> {
    for &v in values {
        line.push(' ');
        line.push_str(&hex_float(v).ok_or("non-finite value")?);
    }
    Ok(())
}

impl Scene {
    /// Appends the pose lines of `frame` to `out`.
    pub fn write_frame(&self, out: &mut String, frame: u32) -> Result<(), String> {
        for model in &self.models {
            let slot = model.slot;
            for (i, bone) in model.bones.iter().enumerate() {
                write!(out, "{frame} bone {slot} {i}").unwrap();
                floats(out, &bone.trans)?;
                floats(out, &bone.rot_quat)?;
                out.push('\n');
            }
            for (i, bone) in model.bones.iter().enumerate() {
                write!(out, "{frame} bonew {slot} {i}").unwrap();
                floats(out, &bone.mat_init.0)?;
                out.push('\n');
            }
            for (i, morph) in model.morphs.iter().enumerate() {
                write!(out, "{frame} morph {slot} {i}").unwrap();
                floats(out, &[morph.value])?;
                out.push('\n');
            }
        }
        Ok(())
    }

    /// The header and frames `0..frames`, stepping the scene.
    pub fn trace(&mut self, frames: u32) -> Result<String, String> {
        let mut out = String::from(HEADER);
        for frame in 0..frames {
            if frame > 0 {
                self.step();
            }
            self.write_frame(&mut out, frame)
                .map_err(|e| format!("frame {frame}: {e}"))?;
        }
        Ok(out)
    }
}

#[cfg(test)]
mod tests {
    use super::hex_float;

    #[test]
    fn hex_float_matches_the_cpp_writer() {
        let cases: [(f32, &str); 8] = [
            (0.0, "0x0.000000p+0"),
            (-0.0, "-0x0.000000p+0"),
            (1.0, "0x1.000000p+0"),
            (f32::from_bits(0xc087_c394), "-0x1.0f8728p+2"),
            (f32::from_bits(0x3f35_04f3), "0x1.6a09e6p-1"),
            (f32::MIN_POSITIVE, "0x1.000000p-126"),
            (f32::from_bits(1), "0x1.000000p-149"),
            (f32::MAX, "0x1.fffffep+127"),
        ];
        for (value, text) in cases {
            assert_eq!(hex_float(value).as_deref(), Some(text), "{value:e}");
        }
        assert_eq!(hex_float(f32::NAN), None);
        assert_eq!(hex_float(f32::NEG_INFINITY), None);
    }
}
