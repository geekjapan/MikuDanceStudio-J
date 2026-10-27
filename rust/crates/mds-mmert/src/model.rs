//! Geometry an MME pass draws: a model's or an accessory's vertex and index buffers with its
//! material subsets, and the `Draw=Buffer` quad of `SasDefaultDrawBufferPass` (`pass_planner.cpp`).
//! [`Model::update`] writes a pose: the vertices and materials `mds-skin` computed.
//!
//! The vertex layout is the model FVF of `ModelVertexFormat` (`src/render/model_renderers.cpp`):
//! `XYZ | NORMAL | TEX1` plus up to four float4 additional UVs as `TEXCOORD1..4`. Every buffer
//! here holds all four (zero when the model has fewer), so one layout serves every shader.

use mds_accessory::accessory::TextureSlot;
use mds_accessory::{Accessory, TextureKind};
use mds_formats::pmd::Pmd;
use mds_formats::pmx::Pmx;
use mds_skin::Skin;
use wgpu::util::DeviceExt;

/// Floats per vertex: position 3, normal 3, uv 2, four additional uv4.
pub const VERTEX_FLOATS: usize = 3 + 3 + 2 + 16;
pub const STRIDE: u64 = (VERTEX_FLOATS * 4) as u64;

/// The byte offset and format a vertex-shader input of this D3D usage and index reads, or
/// `None` when the stream has no such element.
pub fn element(usage: &str, index: u32) -> Option<(u64, wgpu::VertexFormat)> {
    use wgpu::VertexFormat as F;
    match (usage, index) {
        ("position", 0) => Some((0, F::Float32x3)),
        ("normal", 0) => Some((12, F::Float32x3)),
        ("texcoord", 0) => Some((24, F::Float32x2)),
        ("texcoord", 1..=4) => Some((32 + 16 * u64::from(index - 1), F::Float32x4)),
        _ => None,
    }
}

/// Filterable D2 RGBA8 image uploaded once when its model loads.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MaterialTexture(wgpu::Texture);

impl MaterialTexture {
    fn upload(gpu: &crate::Gpu, image: &mds_render::Image) -> Option<Self> {
        let limit = gpu.device.limits().max_texture_dimension_2d;
        if image.width > limit || image.height > limit {
            return None;
        }
        let texture = gpu.device.create_texture(&wgpu::TextureDescriptor {
            label: Some("MME material texture"),
            size: wgpu::Extent3d {
                width: image.width,
                height: image.height,
                depth_or_array_layers: 1,
            },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: wgpu::TextureFormat::Rgba8Unorm,
            usage: wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST,
            view_formats: &[],
        });
        crate::resource::write_level(gpu, &texture, 0, image.width, image.height, &image.rgba);
        Some(Self(texture))
    }

    pub(crate) fn view(&self) -> wgpu::TextureView {
        self.0.create_view(&Default::default())
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct MaterialTextures {
    pub texture: Option<MaterialTexture>,
    pub sphere: Option<MaterialTexture>,
    pub toon: Option<MaterialTexture>,
}

/// One material subset: what the parameter binder reads and the index range it draws.
#[derive(Clone, Debug)]
pub struct Material {
    pub diffuse: [f32; 4],
    /// The record's mirror of the diffuse, its `D3DMATERIAL9` ambient (`mds_skin::Material`).
    pub mirror: [f32; 4],
    pub ambient: [f32; 3],
    pub specular: [f32; 3],
    pub power: f32,
    pub edge_color: [f32; 4],
    /// `UseTexture`: the material has a main texture that loaded (`GetTexture`, read from the
    /// texture stages: a file that did not load binds none).
    pub has_texture: bool,
    /// PMX sphere mode: 0 off, 1 multiply, 2 add, 3 sub-texture; 0 when the sphere did not load.
    pub sphere_mode: u8,
    /// `UseToon` (`IsToonUsed`): every model material, no accessory's.
    pub toon: bool,
    /// The main texture and sphere files the material names, relative to the object's folder;
    /// [`Model::load_textures`] drops the flags of those that do not load.
    pub texture: Option<String>,
    pub sphere: Option<String>,
    pub toon_texture: Option<String>,
    pub textures: MaterialTextures,
    /// The material draws its edge (the PMX flag 0x10, the PMD edge byte).
    pub edge: bool,
    /// Both sides of the faces draw, as `mds-render` culls: the PMX flag 0x01 or a diffuse alpha
    /// below 1.
    pub double_sided: bool,
    /// An accessory's `D3DMATERIAL9` (diffuse, ambient, specular, emissive), which
    /// `ExpGetAcsMaterial` returns in place of the fields above.
    pub accessory: Option<[[f32; 4]; 4]>,
    pub start: u32,
    pub count: u32,
}

pub struct Model {
    pub vertices: wgpu::Buffer,
    pub indices: wgpu::Buffer,
    pub materials: Vec<Material>,
}

fn floats(f: &[f32]) -> Vec<u8> {
    f.iter().flat_map(|x| x.to_le_bytes()).collect()
}

impl Model {
    /// A PMX model in its bind pose.
    pub fn from_pmx(device: &wgpu::Device, pmx: &Pmx) -> Result<Model, String> {
        let mut data = Vec::with_capacity(pmx.vertices.len() * VERTEX_FLOATS);
        for v in &pmx.vertices {
            data.extend(v.position);
            data.extend(v.normal);
            data.extend(v.uv);
            for k in 0..4 {
                data.extend(v.extra_uv.get(k).copied().unwrap_or([0.0; 4]));
            }
        }
        let n = pmx.vertices.len();
        let mut indices = Vec::with_capacity(pmx.indices.len());
        for &i in &pmx.indices {
            match usize::try_from(i) {
                Ok(i) if i < n => indices.push(i as u32),
                _ => return Err(format!("index {i} is outside the {n} vertices")),
            }
        }
        let tex = |i| pmx_texture(pmx, i);
        let mut start = 0u32;
        let mut materials = Vec::new();
        for m in &pmx.materials {
            let count = u32::try_from(m.face_vertex_count).map_err(|_| "negative face count")?;
            if (start + count) as usize > indices.len() {
                return Err("a material reaches past the index list".into());
            }
            // pmx_load.cpp:627-646: the sphere is used only with a mode.
            let texture = tex(m.texture);
            let sphere = if m.sphere_mode != 0 {
                tex(m.sphere)
            } else {
                None
            };
            materials.push(Material {
                diffuse: m.diffuse,
                mirror: m.diffuse,
                ambient: m.ambient,
                specular: m.specular,
                power: m.specular_power,
                edge_color: m.edge_color,
                has_texture: texture.is_some(),
                sphere_mode: if sphere.is_some() { m.sphere_mode } else { 0 },
                toon: true,
                texture,
                sphere,
                toon_texture: pmx_toon(pmx, m),
                textures: MaterialTextures::default(),
                edge: m.flags & 0x10 != 0,
                double_sided: m.flags & 0x01 != 0 || m.diffuse[3] < 1.0,
                accessory: None,
                start,
                count,
            });
            start += count;
        }
        Ok(Model::new(device, &data, &indices, materials))
    }

    /// A PMD model in its bind pose. Its texture field is `texture*sphere` (`pmd_load.cpp:296`):
    /// the sphere multiplies when its name has `.sph` or `.SPH`, else adds
    /// (`model_renderers.cpp:551`); a field without `*` is a sphere alone when it has `.sph` or
    /// `.spa` (`:521`, `:527`), else the texture. Every PMD material draws with a toon.
    pub fn from_pmd(device: &wgpu::Device, pmd: &Pmd) -> Result<Model, String> {
        let mut data = Vec::with_capacity(pmd.vertices.len() * VERTEX_FLOATS);
        for v in &pmd.vertices {
            data.extend(v.position);
            data.extend(v.normal);
            data.extend(v.uv);
            data.extend([0.0; 16]);
        }
        let n = pmd.vertices.len();
        let indices: Vec<u32> = pmd.indices.iter().map(|&i| u32::from(i)).collect();
        if indices.iter().any(|&i| i as usize >= n) {
            return Err(format!("an index is outside the {n} vertices"));
        }
        let mut start = 0u32;
        let mut materials = Vec::new();
        for m in &pmd.materials {
            let count = m.face_vertex_count;
            if (start + count) as usize > indices.len() {
                return Err("a material reaches past the index list".into());
            }
            let (texture, sphere, mode) = pmd_texture(&m.texture.text);
            materials.push(Material {
                diffuse: m.diffuse,
                mirror: m.diffuse,
                ambient: m.ambient,
                specular: m.specular,
                power: m.specular_power,
                edge_color: [0.0, 0.0, 0.0, 1.0],
                has_texture: texture.is_some(),
                sphere_mode: if sphere.is_some() { mode } else { 0 },
                toon: true,
                texture,
                sphere,
                toon_texture: pmd_toon(pmd, m.toon),
                textures: MaterialTextures::default(),
                edge: m.edge != 0,
                double_sided: m.diffuse[3] < 1.0,
                accessory: None,
                start,
                count,
            });
            start += count;
        }
        Ok(Model::new(device, &data, &indices, materials))
    }

    /// An accessory: one subset per material, its faces in the order `DrawSubset` draws them.
    pub fn from_accessory(device: &wgpu::Device, acc: &Accessory) -> Result<Model, String> {
        let mut data = Vec::with_capacity(acc.vertices.len() * VERTEX_FLOATS);
        for v in &acc.vertices {
            data.extend(v.position);
            data.extend(v.normal);
            data.extend(v.texcoord);
            data.extend([0.0; 16]);
        }
        let n = acc.vertices.len() as u32;
        let mut indices = Vec::with_capacity(acc.indices.len());
        let mut materials = Vec::new();
        for (k, m) in acc.materials.iter().enumerate() {
            let start = indices.len() as u32;
            for f in acc.subset_faces(k) {
                let face = acc
                    .indices
                    .get(3 * f..3 * f + 3)
                    .ok_or("a face past the indices")?;
                if face.iter().any(|&i| i >= n) {
                    return Err(format!("an index is outside the {n} vertices"));
                }
                indices.extend(face);
            }
            let (texture, sphere, sphere_mode) = texture_use(&m.texture);
            materials.push(Material {
                diffuse: m.diffuse,
                mirror: m.ambient,
                ambient: [m.emissive[0], m.emissive[1], m.emissive[2]],
                specular: [m.specular[0], m.specular[1], m.specular[2]],
                power: m.power,
                edge_color: [0.0; 4],
                has_texture: texture.is_some(),
                sphere_mode: if sphere.is_some() { sphere_mode } else { 0 },
                toon: false,
                texture,
                sphere,
                toon_texture: None,
                textures: MaterialTextures::default(),
                edge: false,
                double_sided: false,
                accessory: Some([m.diffuse, m.ambient, m.specular, m.emissive]),
                start,
                count: indices.len() as u32 - start,
            });
        }
        Ok(Model::new(device, &data, &indices, materials))
    }

    fn new(
        device: &wgpu::Device,
        data: &[f32],
        indices: &[u32],
        materials: Vec<Material>,
    ) -> Model {
        Model {
            vertices: buffer(device, wgpu::BufferUsages::VERTEX, &floats(data)),
            indices: buffer(
                device,
                wgpu::BufferUsages::INDEX,
                &indices
                    .iter()
                    .flat_map(|i| i.to_le_bytes())
                    .collect::<Vec<_>>(),
            ),
            materials,
        }
    }

    /// Load immutable sampled images through the host's cached object reader and shared toon reader.
    pub fn load_textures(
        &mut self,
        gpu: &crate::Gpu,
        mut read: impl FnMut(&str) -> Option<Vec<u8>>,
        mut shared: impl FnMut(&str) -> Option<Vec<u8>>,
    ) {
        let mut images = std::collections::HashMap::<String, Option<MaterialTexture>>::new();
        for m in &mut self.materials {
            let mut load = |name: &Option<String>, toon: bool| {
                let name = name.as_ref()?;
                let key = format!("{toon}:{name}");
                images
                    .entry(key)
                    .or_insert_with(|| {
                        let image = if toon {
                            toon_image(name, &mut read, &mut shared)
                        } else {
                            read(name).and_then(|b| mds_render::Image::decode(&b).ok())
                        }?;
                        MaterialTexture::upload(gpu, &image)
                    })
                    .clone()
            };
            m.textures = MaterialTextures {
                texture: load(&m.texture, false),
                sphere: load(&m.sphere, false),
                toon: load(&m.toon_texture, true),
            };
            m.has_texture = m.textures.texture.is_some();
            if m.textures.sphere.is_none() {
                m.sphere_mode = 0;
            }
        }
    }

    /// The pose `skin` holds after `Skin::apply_morphs` and `Skin::update`: its vertex buffer
    /// (position, normal, uv and the additional uvs, padded to four) and its material values.
    pub fn update(&mut self, queue: &wgpu::Queue, skin: &Skin) {
        let stride = skin.stride();
        let mut data = Vec::with_capacity(skin.vertex_count() * VERTEX_FLOATS);
        for v in skin.main.chunks_exact(stride) {
            data.extend(v);
            data.extend(std::iter::repeat_n(0.0, VERTEX_FLOATS - stride));
        }
        queue.write_buffer(&self.vertices, 0, &floats(&data));
        for (m, s) in self.materials.iter_mut().zip(&skin.materials) {
            m.diffuse = s.diffuse;
            m.mirror = s.diffuse_mirror;
            m.ambient = s.ambient;
            m.specular = s.specular;
            m.power = s.specular_power;
            m.edge_color = s.edge_color;
        }
    }
}

fn pmx_texture(pmx: &Pmx, index: i32) -> Option<String> {
    let t = usize::try_from(index)
        .ok()
        .and_then(|i| pmx.textures.get(i))?;
    nonempty(&t.text)
}

fn pmx_toon(pmx: &Pmx, material: &mds_formats::pmx::Material) -> Option<String> {
    if material.shared_toon != 0 {
        shared_toon(material.toon)
    } else {
        pmx_texture(pmx, material.toon)
    }
}

fn shared_toon(index: i32) -> Option<String> {
    (0..10)
        .contains(&index)
        .then(|| format!("toon{:02}.bmp", index + 1))
}

fn pmd_toon(pmd: &Pmd, index: u8) -> Option<String> {
    if index >= 10 {
        return None;
    }
    match &pmd.extension {
        Some(e) => e
            .toon_textures
            .get(index as usize)
            .and_then(|n| nonempty(&n.text)),
        None => None,
    }
}

fn toon_image(
    name: &str,
    mut read: impl FnMut(&str) -> Option<Vec<u8>>,
    mut shared: impl FnMut(&str) -> Option<Vec<u8>>,
) -> Option<mds_render::Image> {
    if name.is_empty() {
        return None;
    }
    const BUILTIN: [&[u8]; 10] = [
        include_bytes!("../../../../res/assets/toon01.png"),
        include_bytes!("../../../../res/assets/toon02.png"),
        include_bytes!("../../../../res/assets/toon03.png"),
        include_bytes!("../../../../res/assets/toon04.png"),
        include_bytes!("../../../../res/assets/toon05.png"),
        include_bytes!("../../../../res/assets/toon06.png"),
        include_bytes!("../../../../res/assets/toon07.png"),
        include_bytes!("../../../../res/assets/toon08.png"),
        include_bytes!("../../../../res/assets/toon09.png"),
        include_bytes!("../../../../res/assets/toon10.png"),
    ];
    if let Some(i) = (0..10).find(|&i| shared_toon(i).as_deref() == Some(name)) {
        shared(name)
            .and_then(|b| mds_render::Image::decode(&b).ok())
            .or_else(|| mds_render::Image::decode(BUILTIN[i as usize]).ok())
    } else {
        read(name).and_then(|b| mds_render::Image::decode(&b).ok())
    }
}

/// A PMD texture field as [`Model::from_pmd`] reads it: texture, sphere, sphere mode.
fn pmd_texture(field: &str) -> (Option<String>, Option<String>, u8) {
    let has = |n: &str, ext: &str| n.contains(ext) || n.contains(&ext.to_uppercase());
    match field.split_once('*') {
        Some((t, s)) => (nonempty(t), nonempty(s), if has(s, ".sph") { 1 } else { 2 }),
        None if has(field, ".sph") => (None, nonempty(field), 1),
        None if has(field, ".spa") => (None, nonempty(field), 2),
        None => (nonempty(field), None, 0),
    }
}

fn nonempty(s: &str) -> Option<String> {
    (!s.is_empty()).then(|| s.to_string())
}

/// An accessory's texture slot (`accessory.cpp:520-540`): its main texture, its sphere, and the
/// sphere mode as PMX numbers it. `screen.bmp` is the capture texture (`:533`, `:162`), which the
/// application creates only in screen capture mode, so it binds none here.
fn texture_use(t: &TextureSlot) -> (Option<String>, Option<String>, u8) {
    let (primary, sphere) = (nonempty(&t.primary.text), nonempty(&t.sphere.text));
    match t.kind {
        TextureKind::Plain => (primary, None, 0),
        TextureKind::SphereMultiply => (None, primary, 1),
        TextureKind::SphereAdd => (None, primary, 2),
        TextureKind::Screen => (None, None, 0),
        TextureKind::SubMultiply => (primary, sphere, 1),
        TextureKind::SubAdd => (primary, sphere, 2),
    }
}

pub fn buffer(device: &wgpu::Device, usage: wgpu::BufferUsages, data: &[u8]) -> wgpu::Buffer {
    let mut padded = data.to_vec();
    padded.resize(data.len().next_multiple_of(4).max(4), 0);
    device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
        label: None,
        contents: &padded,
        usage: usage | wgpu::BufferUsages::COPY_DST,
    })
}

/// The quad of `SasDefaultDrawBufferPass` for a `w` x `h` viewport, as a triangle list (the
/// original draws the same four vertices as a fan): one pixel of NDC expansion on the left and
/// top, one texel of under-scan on the matching u and v edges.
pub fn quad(w: u32, h: u32) -> Vec<u8> {
    let (w, h) = (w as f32, h as f32);
    let x_left = -1.0 - (1.0 / w) * 2.0;
    let y_top = (1.0 / h) * 2.0 + 1.0;
    let u_left = -(1.0 / w);
    let v_top = -(1.0 / h);
    let fan = [
        [1.0, -1.0, 1.0, 1.0],
        [x_left, -1.0, u_left, 1.0],
        [x_left, y_top, u_left, v_top],
        [1.0, y_top, 1.0, v_top],
    ];
    let mut out = Vec::new();
    for i in [0, 1, 2, 0, 2, 3] {
        let [x, y, u, v] = fan[i];
        let mut vtx = [0.0f32; VERTEX_FLOATS];
        vtx[0] = x;
        vtx[1] = y;
        vtx[6] = u;
        vtx[7] = v;
        out.extend(floats(&vtx));
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    /// `pmd_load.cpp:296-316` and `model_renderers.cpp:517-560`.
    #[test]
    fn pmd_texture_fields_split_as_the_cpp_does() {
        let s = |v: &str| Some(v.to_string());
        assert_eq!(pmd_texture("a.bmp"), (s("a.bmp"), None, 0));
        assert_eq!(pmd_texture("a.bmp*b.sph"), (s("a.bmp"), s("b.sph"), 1));
        assert_eq!(pmd_texture("a.bmp*b.SPH"), (s("a.bmp"), s("b.SPH"), 1));
        assert_eq!(pmd_texture("a.bmp*b.spa"), (s("a.bmp"), s("b.spa"), 2));
        assert_eq!(pmd_texture("a.bmp*b.png"), (s("a.bmp"), s("b.png"), 2));
        assert_eq!(pmd_texture("b.sph"), (None, s("b.sph"), 1));
        assert_eq!(pmd_texture("b.SPA"), (None, s("b.SPA"), 2));
        assert_eq!(pmd_texture("screen.bmp"), (s("screen.bmp"), None, 0));
        assert_eq!(pmd_texture(""), (None, None, 0));
    }

    /// `accessory.cpp:520-540`; `screen.bmp` binds the capture texture (`:162`), none outside
    /// screen capture (`frame_scene.cpp:271`).
    #[test]
    fn accessory_slots_use_their_texture_and_sphere() {
        let t = |name: &str| texture_use(&TextureSlot::parse(Some(name.as_bytes())));
        let s = |v: &str| Some(v.to_string());
        assert_eq!(t("a.bmp"), (s("a.bmp"), None, 0));
        assert_eq!(t("b.sph"), (None, s("b.sph"), 1));
        assert_eq!(t("b.spa"), (None, s("b.spa"), 2));
        assert_eq!(t("a.bmp*b.spa"), (s("a.bmp"), s("b.spa"), 2));
        assert_eq!(t("a.bmp*b.sph"), (s("a.bmp"), s("b.sph"), 1));
        assert_eq!(t("screen.bmp"), (None, None, 0));
    }
    #[test]
    fn toon_resolution_keeps_shared_names_out_of_the_model_directory() {
        let png = include_bytes!("../tests/data/blink.png");
        let image = mds_render::Image::decode(png).unwrap();
        let mut shared_names = Vec::new();
        let actual = toon_image(
            "toon02.bmp",
            |_| panic!("shared toon read model directory"),
            |n| {
                shared_names.push(n.to_string());
                Some(png.to_vec())
            },
        );
        assert_eq!(actual, Some(image.clone()));
        assert_eq!(shared_names, ["toon02.bmp"]);
        for n in [
            "Toon02.bmp",
            "toon02.BMP",
            "sub/toon02.bmp",
            "sub\\toon02.bmp",
            "custom.png",
        ] {
            assert_eq!(
                toon_image(
                    n,
                    |name| {
                        assert_eq!(name, n);
                        Some(png.to_vec())
                    },
                    |_| panic!("custom toon read app data")
                ),
                Some(image.clone())
            );
        }
        assert!(toon_image(
            "",
            |_| panic!("empty name read"),
            |_| panic!("empty shared read")
        )
        .is_none());
        assert!(toon_image(
            "missing.png",
            |_| None,
            |_| panic!("missing custom read app data")
        )
        .is_none());
        assert!(toon_image("broken.png", |_| Some(vec![0, 1]), |_| None).is_none());
        for i in 0..10 {
            let n = shared_toon(i).unwrap();
            assert!(toon_image(
                &n,
                |_| panic!("embedded fallback read model directory"),
                |_| None
            )
            .is_some());
            assert!(toon_image(&n, |_| None, |_| Some(vec![0])).is_some());
        }
        assert_eq!(shared_toon(-1), None);
        assert_eq!(shared_toon(10), None);
    }

    #[test]
    fn pmd_toon_255_is_null_and_other_indices_read_the_table() {
        let bytes = include_bytes!("../../../../tests/fixtures/rust/chain8.pmd");
        let mut pmd = Pmd::read(bytes).unwrap();
        assert_eq!(pmd_toon(&pmd, 255), None);
        assert_eq!(pmd_toon(&pmd, 10), None);
        assert_eq!(pmd_toon(&pmd, 0).as_deref(), Some("toon01.bmp"));
        pmd.extension.as_mut().unwrap().toon_textures[0].text = "custom.png".into();
        assert_eq!(pmd_toon(&pmd, 0).as_deref(), Some("custom.png"));
        pmd.extension.as_mut().unwrap().toon_textures[0]
            .text
            .clear();
        assert_eq!(pmd_toon(&pmd, 0), None);
        pmd.extension = None;
        assert_eq!(pmd_toon(&pmd, 9), None);
    }
    #[test]
    fn pmx_toon_indices_select_custom_or_shared_names() {
        let bytes = include_bytes!("../../../../tests/fixtures/rust/chain8.pmx");
        let mut pmx = Pmx::read(bytes).unwrap();
        let mut material = pmx.materials[0].clone();
        material.shared_toon = 1;
        material.toon = 0;
        assert_eq!(pmx_toon(&pmx, &material).as_deref(), Some("toon01.bmp"));
        material.toon = 9;
        assert_eq!(pmx_toon(&pmx, &material).as_deref(), Some("toon10.bmp"));
        material.toon = 10;
        assert_eq!(pmx_toon(&pmx, &material), None);
        material.shared_toon = 0;
        material.toon = 0;
        pmx.textures[0].text = "sub\\custom.png".into();
        assert_eq!(
            pmx_toon(&pmx, &material).as_deref(),
            Some("sub\\custom.png")
        );
        for i in [-1, 1, i32::MAX] {
            material.toon = i;
            assert_eq!(pmx_toon(&pmx, &material), None);
        }
        pmx.textures[0].text.clear();
        assert_eq!(pmx_texture(&pmx, 0), None);
    }
}
