//! MMD accessories: the `.x` meshes MMD loads, their materials and texture
//! names, and the world transform of an accessory.
//!
//! A port of `src/render/accessory.cpp` without the Direct3D 9 calls:
//!
//! * [`xfile`]: the `.x` container, text and binary. The C++ hands this to
//!   `D3DXLoadMeshFromXW`, which has no Rust equivalent.
//! * [`mesh`]: what `D3DXLoadMeshFromXW` makes of the objects (`LoadAccessoryObject`,
//!   `accessory.cpp:490`): merged frame meshes, split vertices, fan triangles, faces
//!   grouped by material.
//! * [`accessory`]: the rest of `LoadAccessoryObject`: material colors, sphere map
//!   texture names, the FVF 274 conversion with `D3DXComputeNormals`, and the
//!   record defaults of `InitAccessoryRecord` and `LoadAccessoryFile`.
//! * [`vac`]: the `.vac` wrapper file.
//! * [`transform`]: `AccessoryPlacement` and the shadow decisions of
//!   `RenderAccessoriesShadow` and `RenderAccessoriesProjectedGroundShadowGeometry`.
//!
//! Not ported: the dialogs and combo boxes of `LoadAccessoryFile`, the slot table,
//! texture loading (`LoadTextureShared`) and its `ExtractXTexture` retry (the
//! retry re-reads the texture name from the `.x` text, which this loader already
//! has), the effect renderer, and every draw call.

pub mod accessory;
pub mod mesh;
pub mod transform;
pub mod vac;
pub mod xfile;

pub use accessory::{load_x, Accessory, AccessoryMaterial, AccessoryState, TextureKind};

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Error {
    /// Not an `xof` file of version 0302 or 0303.
    BadHeader,
    /// A valid `.x` format this crate does not read.
    Unsupported(&'static str),
    /// The text or binary container is malformed.
    Syntax(&'static str),
    /// An object whose data D3DX rejects.
    Invalid(&'static str),
    /// The file holds no mesh (D3DX fails with `E_FAIL`).
    NoMesh,
    /// More than 65535 vertices: the mesh uses 16-bit indices.
    TooLarge,
    /// The `.vac` file or its mesh could not be read.
    Io(String),
}

impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Error::BadHeader => write!(f, "not a DirectX .x file"),
            Error::Unsupported(what) => write!(f, "unsupported: {what}"),
            Error::Syntax(what) | Error::Invalid(what) => write!(f, "{what}"),
            Error::NoMesh => write!(f, "the file has no mesh"),
            Error::TooLarge => write!(f, "more than 65535 vertices"),
            Error::Io(what) => write!(f, "{what}"),
        }
    }
}

impl std::error::Error for Error {}
