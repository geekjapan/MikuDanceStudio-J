//! Model geometry for drawing: the index list and material ranges of a PMX or a PMD, and the
//! per-frame vertex buffers and material values that `mds-skin` computes for a pose.

use crate::texture::{self, Image, Names, SphereMode};
use mds_formats::{pmd::Pmd, pmx::Pmx};
use mds_skin::{Mat4, Skin};
use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;

pub(crate) const FLAG_DOUBLE_SIDED: u8 = 0x01;
pub(crate) const FLAG_GROUND_SHADOW: u8 = 0x02;
/// PMX: the material is drawn into the self-shadow map, and receives the self-shadow.
pub(crate) const FLAG_SHADOW_CAST: u8 = 0x04;
pub(crate) const FLAG_SHADOW_RECEIVE: u8 = 0x08;
pub(crate) const FLAG_EDGE: u8 = 0x10;

/// Where a material's faces sit in the index list, and how they are drawn. The colors come from
/// `Skin::materials` each frame, because material morphs change them.
pub(crate) struct Material {
    pub flags: u8,
    /// First index and index count of the material's faces.
    pub start: u32,
    pub count: u32,
    /// The files the material names, and those of them that [`Mesh::load_textures`] decoded.
    pub names: Names,
    pub textures: Textures,
}

/// The decoded images of one material; `None` draws the slot's default.
#[derive(Clone, Debug, Default)]
pub(crate) struct Textures {
    pub texture: Option<Arc<Image>>,
    pub sphere: Option<(Arc<Image>, SphereMode)>,
    pub toon: Option<Arc<Image>>,
}

/// What a pose changes: the skin matrix of every bone (row-major, row-vector convention, as the
/// D3DX matrices of `mds-pose`) and the morph values (indexed like the model's morph list).
#[derive(Clone, Debug, Default)]
pub struct Pose {
    pub skin: Vec<[f32; 16]>,
    pub morphs: Vec<f32>,
}

pub struct Mesh {
    /// Names the mesh to `Renderer`, which keeps the buffers of a model between frames.
    pub(crate) id: u64,
    /// Position and normal of every vertex in the file, for the bind-pose camera.
    bind: Vec<([f32; 3], [f32; 3])>,
    skin: Skin,
    pub(crate) indices: Vec<u32>,
    pub(crate) materials: Vec<Material>,
    edge_scale: f32,
}

/// The scene values the edge of `mds-skin` reads, except the model's edge scale.
pub(crate) struct EdgeView {
    pub world: [f32; 16],
    pub camera_position: [f32; 3],
    /// The `camera_fov` that `mds_skin::View` takes.
    pub fov: f32,
    pub self_shadow: bool,
}

/// A number no other [`Mesh`] or accessory has: `Renderer` keeps their buffers under it.
pub(crate) fn next_id() -> u64 {
    static NEXT_ID: AtomicU64 = AtomicU64::new(0);
    NEXT_ID.fetch_add(1, Ordering::Relaxed)
}

fn finish(
    bind: Vec<([f32; 3], [f32; 3])>,
    skin: Skin,
    indices: Vec<u32>,
    mut materials: Vec<Material>,
    names: Vec<Names>,
) -> Result<Mesh, String> {
    for (m, n) in materials.iter_mut().zip(names) {
        m.names = n;
    }
    if bind.is_empty() {
        return Err("model has no vertices".into());
    }
    if indices.iter().any(|&i| i as usize >= bind.len()) {
        return Err("an index is outside the vertex list".into());
    }
    if materials
        .iter()
        .any(|m| (m.start + m.count) as usize > indices.len())
    {
        return Err("a material reaches past the index list".into());
    }
    Ok(Mesh {
        id: next_id(),
        bind,
        skin,
        indices,
        materials,
        edge_scale: 1.0,
    })
}

impl Mesh {
    /// A PMX model. Materials with an alpha below 1 are drawn double sided, as for a PMD (golden2
    /// `skin-0.png`: material `mat2`, alpha 0.5, shows from behind).
    pub fn from_pmx(pmx: &Pmx) -> Result<Mesh, String> {
        let indices = pmx
            .indices
            .iter()
            .map(|&i| u32::try_from(i).map_err(|_| "negative index".to_string()))
            .collect::<Result<Vec<u32>, String>>()?;
        let mut start = 0u32;
        let mut materials = Vec::new();
        for m in &pmx.materials {
            let count = u32::try_from(m.face_vertex_count).map_err(|_| "negative face count")?;
            materials.push(Material {
                flags: m.flags
                    | if m.diffuse[3] < 1.0 {
                        FLAG_DOUBLE_SIDED
                    } else {
                        0
                    },
                start,
                count,
                names: Names::default(),
                textures: Textures::default(),
            });
            start = start.checked_add(count).ok_or("face count overflows")?;
        }
        let bind = pmx
            .vertices
            .iter()
            .map(|v| (v.position, v.normal))
            .collect();
        finish(
            bind,
            Skin::from_pmx(pmx)?,
            indices,
            materials,
            texture::pmx_names(pmx),
        )
    }

    /// A PMD model. Materials with an alpha below 1 are drawn double sided, and every material
    /// casts the ground shadow and casts and receives the self-shadow.
    pub fn from_pmd(pmd: &Pmd) -> Result<Mesh, String> {
        let indices = pmd.indices.iter().map(|&i| u32::from(i)).collect();
        let mut start = 0u32;
        let mut materials = Vec::new();
        for m in &pmd.materials {
            materials.push(Material {
                flags: (if m.diffuse[3] < 1.0 {
                    FLAG_DOUBLE_SIDED
                } else {
                    0
                }) | if m.edge != 0 { FLAG_EDGE } else { 0 }
                    | FLAG_GROUND_SHADOW
                    | FLAG_SHADOW_CAST
                    | FLAG_SHADOW_RECEIVE,
                start,
                count: m.face_vertex_count,
                names: Names::default(),
                textures: Textures::default(),
            });
            start = start
                .checked_add(m.face_vertex_count)
                .ok_or("face count overflows")?;
        }
        let bind = pmd
            .vertices
            .iter()
            .map(|v| (v.position, v.normal))
            .collect();
        finish(
            bind,
            Skin::from_pmd(pmd)?,
            indices,
            materials,
            texture::pmd_names(pmd),
        )
    }

    /// Decodes the texture, sphere and toon files the materials name. `read` returns the bytes of
    /// a file by the name the model stores (relative to the model's folder), or `None` when it
    /// does not exist; each name is read once. Returns the names that were found but did not
    /// decode. A mesh that never loads its textures draws every slot with its default.
    pub fn load_textures(
        &mut self,
        mut read: impl FnMut(&str) -> Option<Vec<u8>>,
    ) -> Vec<(String, String)> {
        let mut cache: HashMap<String, Option<Arc<Image>>> = HashMap::new();
        let mut errors = Vec::new();
        let mut load = |name: &Option<String>| {
            let name = name.as_ref()?;
            cache
                .entry(name.clone())
                .or_insert_with(|| {
                    let data = read(name)?;
                    Image::decode(&data)
                        .map_err(|e| errors.push((name.clone(), e)))
                        .ok()
                        .map(Arc::new)
                })
                .clone()
        };
        for m in &mut self.materials {
            m.textures = Textures {
                texture: load(&m.names.texture),
                sphere: m
                    .names
                    .sphere
                    .as_ref()
                    .and_then(|(n, mode)| Some((load(&Some(n.clone()))?, *mode))),
                toon: load(&m.names.toon),
            };
        }
        errors
    }

    /// The model's edge thickness, `edge_scale` of its PMM model record (1 when a mesh is made).
    pub fn set_edge_scale(&mut self, scale: f32) {
        self.edge_scale = scale;
    }

    pub(crate) fn vertex_count(&self) -> usize {
        self.bind.len()
    }

    /// Bounding box of the bind pose.
    pub(crate) fn bounds(&self) -> ([f32; 3], [f32; 3]) {
        let (mut min, mut max) = ([f32::MAX; 3], [f32::MIN; 3]);
        for (p, _) in &self.bind {
            for i in 0..3 {
                min[i] = min[i].min(p[i]);
                max[i] = max[i].max(p[i]);
            }
        }
        (min, max)
    }

    /// Side of the Z axis the mean vertex normal points to: +1 or -1.
    pub(crate) fn front(&self) -> f32 {
        let z: f32 = self.bind.iter().map(|(_, n)| n[2]).sum();
        if z > 0.0 {
            1.0
        } else {
            -1.0
        }
    }

    /// The skin after the material morphs and the vertex pass of `pose` (`None`: the bind pose).
    /// A pose that is shorter or longer than the model's bone and morph tables is padded with the
    /// identity and zero weights, or cut.
    pub(crate) fn skinned(&self, pose: Option<&Pose>, view: &EdgeView) -> Skin {
        let mut skin = self.skin.clone();
        let mut weights = vec![0.0; skin.morph_count()];
        let mut bones = vec![Mat4::IDENTITY; skin.bone_count()];
        if let Some(pose) = pose {
            for (w, &v) in weights.iter_mut().zip(&pose.morphs) {
                *w = v;
            }
            for (b, &m) in bones.iter_mut().zip(&pose.skin) {
                *b = Mat4(m);
            }
        }
        skin.apply_morphs(&weights);
        skin.update(
            &weights,
            &bones,
            &mds_skin::View {
                world: Mat4(view.world),
                camera_position: view.camera_position,
                camera_fov: view.fov,
                edge_scale: self.edge_scale,
                self_shadow: view.self_shadow,
            },
        );
        skin
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const VIEW: EdgeView = EdgeView {
        world: Mat4::IDENTITY.0,
        camera_position: [0.0; 3],
        fov: 30.0,
        self_shadow: false,
    };

    fn fixture(name: &str) -> Pmx {
        let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../../tests/fixtures/rust")
            .join(name);
        Pmx::read(&std::fs::read(path).unwrap()).unwrap()
    }

    #[test]
    fn bind_pose_is_the_file_and_a_vertex_morph_moves_it() {
        let pmx = fixture("morph4.pmx");
        let mesh = Mesh::from_pmx(&pmx).unwrap();
        let bind = mesh.skinned(None, &VIEW);
        let stride = bind.stride();
        for (i, v) in pmx.vertices.iter().enumerate() {
            assert_eq!(bind.main[stride * i..][..3], v.position, "vertex {i}");
        }
        let (k, m) = pmx
            .morphs
            .iter()
            .enumerate()
            .find(|(_, m)| m.kind == 1)
            .expect("a vertex morph");
        let mds_formats::pmx::Offsets::Vertex(offsets) = &m.offsets else {
            panic!("vertex morph without vertex offsets")
        };
        let mut morphs = vec![0.0; pmx.morphs.len()];
        morphs[k] = 1.0;
        let pose = Pose {
            morphs,
            ..Pose::default()
        };
        let moved = mesh.skinned(Some(&pose), &VIEW);
        let (v, d) = offsets[0];
        let v = v as usize;
        let (a, b) = (&bind.main[stride * v..], &moved.main[stride * v..]);
        assert_ne!(d, [0.0; 3]);
        for c in 0..3 {
            assert!((b[c] - a[c] - d[c]).abs() < 1e-5);
        }
    }

    /// CPU diagnostic only: the golden2 Rust pose is an input, not a native PMM pose oracle.
    #[test]
    #[ignore = "explicit CI diagnostic; requires MDS_SKIN_FRAME_OUT"]
    fn exact_frame_skin_cpu_probe() {
        use crate::scene;
        use mds_formats::pmm::Pmm;
        use mds_physics::PhysicsScene;
        use std::fmt::Write;
        use std::path::PathBuf;

        fn hex(out: &mut String, values: impl IntoIterator<Item = f32>) {
            for v in values {
                write!(out, " {:08x}", v.to_bits()).unwrap();
            }
            out.push('\n');
        }
        let out =
            PathBuf::from(std::env::var_os("MDS_SKIN_FRAME_OUT").expect("MDS_SKIN_FRAME_OUT"));
        std::fs::create_dir_all(&out).unwrap();
        let fixtures =
            PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/rust");
        let golden = fixtures.join("golden2");
        let reads = std::cell::RefCell::new(std::collections::BTreeSet::new());
        let missing = std::cell::RefCell::new(std::collections::BTreeSet::new());
        let read = |path: &str| -> Result<Vec<u8>, String> {
            let name = path.rsplit(['\\', '/']).next().unwrap_or(path);
            let file = [golden.clone(), fixtures.clone(), fixtures.join("accessory")]
                .into_iter()
                .map(|d| d.join(name))
                .find(|f| f.is_file())
                .unwrap_or_else(|| golden.join(name));
            let data = std::fs::read(&file).map_err(|e| format!("{}: {e}", file.display()));
            if data.is_ok() {
                reads.borrow_mut().insert(file);
            } else {
                missing.borrow_mut().insert(file);
            }
            data
        };
        let pmm = Pmm::read(&read("skin.pmm").unwrap()).unwrap();
        assert_eq!(
            pmm.models.len(),
            1,
            "diagnostic expects the skin scene model"
        );
        let mut cases = String::new();
        let mut dump = String::new();
        let mut details = String::new();
        let mut counts = String::new();
        for frame in [0, 30] {
            let mut physics = PhysicsScene::new(&pmm, &read).unwrap();
            for _ in 0..frame {
                physics.step().unwrap();
            }
            let view = scene::camera_at(&pmm, frame).unwrap().view(640, 360);
            let stage = scene::stage_at(&pmm, frame);
            let edge = EdgeView {
                world: view.edge_world.concat().try_into().unwrap(),
                camera_position: view.edge_origin,
                fov: view.edge_fov,
                self_shadow: stage.self_shadow.is_some_and(|s| s.shades()),
            };
            let m = &pmm.models[0];
            let name = m.path.text.rsplit(['\\', '/']).next().unwrap();
            assert_eq!(name, "skin_tex.pmx");
            let pmx = Pmx::read(&read(&m.path.text).unwrap()).unwrap();
            assert!(pmx.vertices[9].weight_kind <= 2);
            assert!(pmx.vertices[10].weight_kind <= 2);
            let mut mesh = Mesh::from_pmx(&pmx).unwrap();
            if m.path.text.contains('\\') {
                assert!(mesh.load_textures(|name| read(name).ok()).is_empty());
            }
            mesh.set_edge_scale(m.edge_scale);
            let model = physics
                .scene
                .models
                .iter()
                .find(|s| s.slot == m.slot)
                .unwrap();
            let pose = scene::pose_of(model);
            assert_eq!(pose.skin.len(), pmx.bones.len());
            assert_eq!(pose.morphs.len(), pmx.morphs.len());
            let skin = mesh.skinned(Some(&pose), &edge);
            let label = format!("skin-{frame}");
            writeln!(
                counts,
                "{label} {} {} {} {} {}",
                skin.vertex_count(),
                skin.stride(),
                skin.materials.len(),
                pose.skin.len(),
                pose.morphs.len()
            )
            .unwrap();
            writeln!(cases, "model {name}\ncase {label}").unwrap();
            cases.push_str("world");
            hex(&mut cases, edge.world);
            cases.push_str("camera");
            hex(
                &mut cases,
                edge.camera_position.into_iter().chain([edge.fov]),
            );
            cases.push_str("edge");
            hex(&mut cases, [m.edge_scale]);
            writeln!(cases, "shadow {}", u8::from(edge.self_shadow)).unwrap();
            for (i, &weight) in pose.morphs.iter().enumerate() {
                write!(cases, "morph {i}").unwrap();
                hex(&mut cases, [weight]);
            }
            for (i, &matrix) in pose.skin.iter().enumerate() {
                assert_eq!(matrix, model.bones[i].mat_init.0);
                write!(cases, "bone {i}").unwrap();
                hex(&mut cases, matrix);
            }
            cases.push_str("end\n");
            writeln!(
                details,
                "case {label}\nweight_kind 9 {}\nweight_kind 10 {}",
                pmx.vertices[9].weight_kind, pmx.vertices[10].weight_kind
            )
            .unwrap();
            for (field, values) in [
                ("view", view.view.concat()),
                ("view_proj", view.view_proj.concat()),
                ("eye", view.eye.to_vec()),
                ("distance", vec![view.distance]),
            ] {
                details.push_str(field);
                hex(&mut details, values);
            }
            writeln!(
                dump,
                "model {name} pmx vertices {} stride {}\ncase {label}",
                skin.vertex_count(),
                skin.stride() * 4
            )
            .unwrap();
            for (i, e) in skin.edge.iter().enumerate() {
                write!(dump, "v {i}").unwrap();
                for v in skin.main[i * skin.stride()..(i + 1) * skin.stride()]
                    .iter()
                    .chain(&e.position)
                {
                    write!(dump, " {:08x}", v.to_bits()).unwrap();
                }
                writeln!(dump, " {:08x}", e.diffuse).unwrap();
            }
            for (i, m) in skin.materials.iter().enumerate() {
                write!(dump, "m {i}").unwrap();
                hex(
                    &mut dump,
                    m.diffuse_mirror[..3]
                        .iter()
                        .copied()
                        .chain([m.diffuse[3]])
                        .chain(m.specular)
                        .chain(m.ambient)
                        .chain([m.specular_power])
                        .chain(m.edge_color)
                        .chain([m.edge_size]),
                );
                write!(details, "material {i}").unwrap();
                hex(
                    &mut details,
                    m.diffuse
                        .into_iter()
                        .chain(m.diffuse_mirror)
                        .chain(m.specular)
                        .chain(m.ambient)
                        .chain([m.specular_power])
                        .chain(m.edge_color)
                        .chain([m.edge_size]),
                );
            }
        }
        for (name, data) in [
            ("cases.txt", cases),
            ("rust.dump", dump),
            ("details.txt", details),
            ("counts.txt", counts),
        ] {
            std::fs::write(out.join(name), data).unwrap();
        }
        let files = reads
            .into_inner()
            .into_iter()
            .map(|p| format!("{}\n", p.canonicalize().unwrap().display()))
            .collect::<String>();
        std::fs::write(out.join("fixture-reads.txt"), files).unwrap();
        let missing = missing
            .into_inner()
            .into_iter()
            .map(|p| format!("{}\n", p.display()))
            .collect::<String>();
        std::fs::write(out.join("fixture-missing.txt"), missing).unwrap();
    }
}
