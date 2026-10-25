//! Accessories: the `.x` meshes of `mds-accessory`, drawn with Direct3D 9's fixed-function
//! lighting as the golden2 images show it.

use crate::mesh::Textures;
use crate::texture::{Image, SphereMode};
use mds_accessory::{Accessory, AccessoryState, TextureKind};
use std::collections::HashMap;
use std::sync::Arc;

/// An accessory ready to draw: the mesh `mds_accessory::load_x` made, and the decoded images of
/// its materials.
pub struct AccessoryMesh {
    pub(crate) id: u64,
    pub(crate) accessory: Accessory,
    /// Per material: the texture and the sphere map (no toon).
    pub(crate) textures: Vec<Textures>,
}

/// One accessory of a frame: its mesh, its state at the frame (visible, opacity, the shadow and
/// additive flags) and its world matrix (`mds_accessory::transform::world_matrix`, row vectors,
/// row-major).
#[derive(Clone, Copy)]
pub struct AccessoryDraw<'a> {
    pub mesh: &'a AccessoryMesh,
    pub state: &'a AccessoryState,
    pub world: [f32; 16],
}

impl AccessoryMesh {
    pub fn new(accessory: Accessory) -> AccessoryMesh {
        AccessoryMesh {
            id: crate::mesh::next_id(),
            textures: vec![Textures::default(); accessory.materials.len()],
            accessory,
        }
    }

    /// Decodes the textures and sphere maps the materials name. `read` returns the bytes of a
    /// file by the name the `.x` stores (relative to the accessory's folder), or `None`. Returns
    /// the names that were found but did not decode.
    pub fn load_textures(
        &mut self,
        mut read: impl FnMut(&str) -> Option<Vec<u8>>,
    ) -> Vec<(String, String)> {
        let mut cache: HashMap<String, Option<Arc<Image>>> = HashMap::new();
        let mut errors = Vec::new();
        let mut load = |name: &str| -> Option<Arc<Image>> {
            if name.is_empty() {
                return None;
            }
            cache
                .entry(name.to_string())
                .or_insert_with(|| {
                    Image::decode(&read(name)?)
                        .map_err(|e| errors.push((name.to_string(), e)))
                        .ok()
                        .map(Arc::new)
                })
                .clone()
        };
        let slots: Vec<_> = self
            .accessory
            .materials
            .iter()
            .map(|m| {
                let t = &m.texture;
                let (primary, sphere) = (t.primary.text.as_str(), t.sphere.text.as_str());
                let (texture, sphere) = match t.kind {
                    TextureKind::Plain => (load(primary), None),
                    TextureKind::SphereMultiply => {
                        (None, load(primary).map(|i| (i, SphereMode::Multiply)))
                    }
                    TextureKind::SphereAdd => (None, load(primary).map(|i| (i, SphereMode::Add))),
                    TextureKind::SubMultiply => (
                        load(primary),
                        load(sphere).map(|i| (i, SphereMode::Multiply)),
                    ),
                    TextureKind::SubAdd => {
                        (load(primary), load(sphere).map(|i| (i, SphereMode::Add)))
                    }
                    TextureKind::Screen => (None, None),
                };
                Textures {
                    texture,
                    sphere,
                    toon: None,
                }
            })
            .collect();
        self.textures = slots;
        errors
    }
}
