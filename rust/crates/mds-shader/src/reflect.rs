//! Parameter reflection: the constant register of each effect parameter.

use crate::ctab::{self, Constant};
use crate::vkd3d::{Target, Vkd3d};

/// Where a reflection came from.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Source {
    /// The `CTAB` block of a d3dbc compile of the same source and profile.
    Ctab,
}

impl Source {
    pub fn as_str(self) -> &'static str {
        match self {
            Source::Ctab => "ctab",
        }
    }
}

pub struct Reflection {
    pub source: Source,
    pub constants: Vec<Constant>,
}

/// Reflects the parameters of `entry_point` in `source`.
pub fn reflect(
    vk: &Vkd3d,
    source: &str,
    name: &str,
    profile: &str,
    entry_point: &str,
) -> Result<Reflection, String> {
    let d3dbc = vk
        .compile_hlsl(source, name, profile, entry_point, Target::D3dBytecode)
        .map_err(|e| e.summary())?;
    Ok(Reflection {
        source: Source::Ctab,
        constants: ctab::parse(&d3dbc)?,
    })
}
