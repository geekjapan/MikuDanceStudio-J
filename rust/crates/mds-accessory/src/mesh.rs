//! `D3DXLoadMeshFromXW` with the options the C++ passes (544, `D3DXMESH_MANAGED`:
//! 16-bit indices): the `.x` objects become one triangle mesh, its attribute
//! per face and its `D3DXMATERIAL` list.
//!
//! The rules follow the D3DX9 behavior that Wine's `d3dx9_36/mesh.c`
//! reimplements (`D3DXLoadMeshFromXInMemory`, `D3DXLoadSkinMeshFromXof`,
//! `parse_mesh` and the `parse_*` helpers). None of it is checked against the
//! native `d3dx9_43.dll` yet; `README.md` lists the places where the slice
//! `accgold` has to decide.

use crate::xfile::{self, Child, Node, Value};
use crate::Error;
use mds_math::{Mat4, Vec3};
use std::collections::HashMap;

/// 16-bit indices: `D3DXMESH_32BIT` (0x1) is not in option word 544.
const MAX_VERTICES: usize = 0xFFFF;

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct Vertex {
    pub position: [f32; 3],
    pub normal: [f32; 3],
    pub texcoord: [f32; 2],
}

/// A `D3DXMATERIAL` as D3DX fills it from a `Material` object.
#[derive(Clone, Debug, PartialEq)]
pub struct XMaterial {
    pub diffuse: [f32; 4],
    pub ambient: [f32; 4],
    pub specular: [f32; 4],
    pub emissive: [f32; 4],
    pub power: f32,
    /// `TextureFilename` bytes as in the file.
    pub texture: Option<Vec<u8>>,
}

/// The mesh D3DX returns, before `LoadAccessoryObject` converts it to FVF 274.
#[derive(Clone, Debug, PartialEq)]
pub struct XMesh {
    pub vertices: Vec<Vertex>,
    /// Three indices per face.
    pub indices: Vec<u32>,
    /// The attribute (material index) of each face.
    pub face_material: Vec<u32>,
    pub materials: Vec<XMaterial>,
    /// What the loaded vertex format has; `D3DFVF_XYZ` is always there.
    pub has_normals: bool,
    pub has_texcoords: bool,
    pub has_colors: bool,
}

struct Values<'a> {
    v: &'a [Value],
    pos: usize,
}

impl<'a> Values<'a> {
    fn new(node: &'a Node) -> Self {
        Values {
            v: &node.values,
            pos: 0,
        }
    }
    fn left(&self) -> usize {
        self.v.len() - self.pos
    }
    fn next(&mut self) -> Result<&'a Value, Error> {
        let v = self
            .v
            .get(self.pos)
            .ok_or(Error::Invalid("object data is truncated"))?;
        self.pos += 1;
        Ok(v)
    }
    fn u32(&mut self) -> Result<u32, Error> {
        match self.next()? {
            Value::Int(i) => u32::try_from(*i).map_err(|_| Error::Invalid("integer out of range")),
            _ => Err(Error::Invalid("expected an integer")),
        }
    }
    fn f32(&mut self) -> Result<f32, Error> {
        match self.next()? {
            Value::Int(i) => Ok(*i as f32),
            Value::Float(f) => Ok(*f),
            Value::Str(_) => Err(Error::Invalid("expected a number")),
        }
    }
    fn f3(&mut self) -> Result<[f32; 3], Error> {
        Ok([self.f32()?, self.f32()?, self.f32()?])
    }
    /// A count followed by `per` values each; the count is checked against the data left.
    fn count(&mut self, per: usize) -> Result<usize, Error> {
        let n = self.u32()? as usize;
        if n.checked_mul(per).is_none_or(|need| need > self.left()) {
            return Err(Error::Invalid("object data is truncated"));
        }
        Ok(n)
    }
}

struct Container {
    vertices: Vec<Vertex>,
    indices: Vec<u32>,
    face_material: Vec<u32>,
    materials: Vec<XMaterial>,
    has_normals: bool,
    has_texcoords: bool,
    has_colors: bool,
    transform: Mat4,
}

type Names<'a> = HashMap<&'a str, &'a Node>;

/// `MeshNormals`: the unit normals and, per face, the normal of each corner.
type FaceNormals = (Vec<[f32; 3]>, Vec<Vec<u32>>);

fn collect_names<'a>(nodes: &'a [Node], names: &mut Names<'a>) {
    for n in nodes {
        if let Some(name) = &n.name {
            names.entry(name.as_str()).or_insert(n);
        }
        for c in &n.children {
            if let Child::Node(c) = c {
                collect_names(std::slice::from_ref(c), names);
            }
        }
    }
}

/// Resolves a child the way `ID3DXFileData::GetChild` does: a reference gives
/// the object it names.
fn resolve<'a>(c: &'a Child, names: &Names<'a>) -> Result<&'a Node, Error> {
    match c {
        Child::Node(n) => Ok(n),
        Child::Ref(r) => names
            .get(r.as_str())
            .copied()
            .ok_or(Error::Invalid("reference to an undefined object")),
    }
}

/// Loads the first `.x` file content: every `Mesh`, at top level or in a
/// `Frame`, merged into one mesh with the frame transforms applied.
pub fn load(data: &[u8]) -> Result<XMesh, Error> {
    let nodes = xfile::parse(data)?;
    let mut names = Names::new();
    collect_names(&nodes, &mut names);

    let mut containers = Vec::new();
    for n in &nodes {
        match n.kind.as_str() {
            "Mesh" => containers.extend(container(n, Mat4::IDENTITY, &names)?),
            "Frame" => frame(n, Mat4::IDENTITY, &names, &mut containers, 0)?,
            _ => {}
        }
    }
    if containers.is_empty() {
        return Err(Error::NoMesh);
    }
    merge(containers)
}

fn frame<'a>(
    node: &'a Node,
    parent: Mat4,
    names: &Names<'a>,
    out: &mut Vec<Container>,
    depth: usize,
) -> Result<(), Error> {
    if depth > 64 {
        return Err(Error::Syntax("frames nested too deep"));
    }
    let mut transform = parent;
    for c in &node.children {
        let n = resolve(c, names)?;
        match n.kind.as_str() {
            "Mesh" => out.extend(container(n, transform, names)?),
            "FrameTransformMatrix" => {
                let mut v = Values::new(n);
                if v.left() != 16 {
                    return Err(Error::Invalid("FrameTransformMatrix needs 16 floats"));
                }
                let mut m = [0.0f32; 16];
                for x in &mut m {
                    *x = v.f32()?;
                }
                // `parse_frame`: transform = transform * new; the parent applies first.
                transform = Mat4::multiply(&transform, &Mat4(m));
            }
            "Frame" => {
                if !matches!(c, Child::Node(_)) {
                    return Err(Error::Invalid("frame reference"));
                }
                frame(n, transform, names, out, depth + 1)?
            }
            _ => {}
        }
    }
    Ok(())
}

fn material(node: &Node) -> Result<XMaterial, Error> {
    let mut v = Values::new(node);
    if v.left() != 11 {
        return Err(Error::Invalid("Material needs 11 numbers"));
    }
    let d = [v.f32()?, v.f32()?, v.f32()?, v.f32()?];
    let power = v.f32()?;
    let s = v.f3()?;
    let e = v.f3()?;
    let mut texture = None;
    for c in &node.children {
        if let Child::Node(t) = c {
            if t.kind == "TextureFilename" {
                texture = match t.values.as_slice() {
                    [Value::Str(s)] => Some(s.clone()),
                    _ => return Err(Error::Invalid("TextureFilename needs one string")),
                };
            }
        }
    }
    Ok(XMaterial {
        diffuse: d,
        // `parse_material` zeroes the color and sets alpha 1; LoadAccessoryObject replaces it.
        ambient: [0.0, 0.0, 0.0, 1.0],
        specular: [s[0], s[1], s[2], 1.0],
        emissive: [e[0], e[1], e[2], 1.0],
        power,
        texture,
    })
}

/// `D3DXLoadSkinMeshFromXof` for one `Mesh`. `None` for a mesh with no vertices.
fn container(node: &Node, transform: Mat4, names: &Names) -> Result<Option<Container>, Error> {
    let mut v = Values::new(node);
    let nv = v.count(3)?;
    let mut positions = Vec::with_capacity(nv);
    for _ in 0..nv {
        positions.push(v.f3()?);
    }
    let nf = v.u32()? as usize;
    // Each face has at least its count.
    if nf > v.left() {
        return Err(Error::Invalid("object data is truncated"));
    }
    let mut faces: Vec<Vec<u32>> = Vec::with_capacity(nf);
    for _ in 0..nf {
        let n = v.u32()? as usize;
        if n < 3 {
            return Err(Error::Invalid("face with fewer than 3 vertices"));
        }
        if n > v.left() {
            return Err(Error::Invalid("object data is truncated"));
        }
        let mut f = Vec::with_capacity(n);
        for _ in 0..n {
            let i = v.u32()?;
            if i as usize >= nv {
                return Err(Error::Invalid("face index out of range"));
            }
            f.push(i);
        }
        faces.push(f);
    }

    let mut normals: Option<FaceNormals> = None;
    let mut texcoords: Option<Vec<[f32; 2]>> = None;
    let mut has_colors = false;
    let mut face_material: Option<Vec<u32>> = None;
    let mut materials: Vec<XMaterial> = Vec::new();

    for c in &node.children {
        let n = resolve(c, names)?;
        let mut v = Values::new(n);
        match n.kind.as_str() {
            "MeshNormals" => {
                let nn = v.count(3)?;
                let mut list = Vec::with_capacity(nn);
                for _ in 0..nn {
                    list.push(Vec3(v.f3()?).normalize().0);
                }
                if v.u32()? as usize != nf {
                    return Err(Error::Invalid("face normal count differs from face count"));
                }
                let mut idx = Vec::with_capacity(nf);
                for f in &faces {
                    if v.u32()? as usize != f.len() {
                        return Err(Error::Invalid("face normal has a different vertex count"));
                    }
                    let mut fi = Vec::with_capacity(f.len());
                    for _ in f {
                        let i = v.u32()?;
                        if i as usize >= nn {
                            return Err(Error::Invalid("normal index out of range"));
                        }
                        fi.push(i);
                    }
                    idx.push(fi);
                }
                normals = Some((list, idx));
            }
            "MeshTextureCoords" => {
                if v.u32()? as usize != nv {
                    return Err(Error::Invalid(
                        "texture coordinate count differs from vertex count",
                    ));
                }
                if v.left() < nv * 2 {
                    return Err(Error::Invalid("object data is truncated"));
                }
                let mut list = Vec::with_capacity(nv);
                for _ in 0..nv {
                    list.push([v.f32()?, v.f32()?]);
                }
                texcoords = Some(list);
            }
            "MeshVertexColors" => {
                let n = v.u32()? as usize;
                if n.checked_mul(5).is_none_or(|need| need > v.left()) {
                    return Err(Error::Invalid("object data is truncated"));
                }
                for _ in 0..n {
                    if v.u32()? as usize >= nv {
                        return Err(Error::Invalid("vertex color index out of range"));
                    }
                    for _ in 0..4 {
                        v.f32()?;
                    }
                }
                has_colors = true;
            }
            "MeshMaterialList" => {
                let count = v.u32()? as usize;
                // A list that declares no material leaves the mesh without any.
                (face_material, materials) = (None, Vec::new());
                if count == 0 {
                    continue;
                }
                if v.u32()? as usize != nf {
                    return Err(Error::Invalid(
                        "material index count differs from face count",
                    ));
                }
                if v.left() < nf {
                    return Err(Error::Invalid("object data is truncated"));
                }
                let mut idx = Vec::with_capacity(nf);
                for _ in 0..nf {
                    let i = v.u32()?;
                    if i as usize >= count {
                        return Err(Error::Invalid("material index out of range"));
                    }
                    idx.push(i);
                }
                for mc in &n.children {
                    let m = resolve(mc, names)?;
                    if m.kind == "Material" {
                        if materials.len() >= count {
                            return Err(Error::Invalid("more materials than declared"));
                        }
                        materials.push(material(m)?);
                    }
                }
                if materials.len() != count {
                    return Err(Error::Invalid("fewer materials than declared"));
                }
                face_material = Some(idx);
            }
            _ => {}
        }
    }

    if nv == 0 {
        return Ok(None);
    }
    if nf == 0 {
        return Err(Error::Invalid("mesh has no faces"));
    }

    // Duplicate a vertex for each distinct normal used with it: the first normal
    // stays on the vertex, a different one appends a copy at the end.
    let mut vertices: Vec<Vertex> = (0..nv)
        .map(|i| Vertex {
            position: positions[i],
            normal: [0.0; 3],
            texcoord: texcoords.as_ref().map_or([0.0; 2], |t| t[i]),
        })
        .collect();
    let mut normal_of: Vec<Option<u32>> = vec![None; nv];
    let mut chain: Vec<Vec<usize>> = vec![Vec::new(); nv];
    let mut tri = Vec::new();
    let mut attr = Vec::new();
    for (fi, f) in faces.iter().enumerate() {
        let mut f = f.clone();
        if let Some((list, nidx)) = &normals {
            for (k, vi) in f.iter_mut().enumerate() {
                let ni = nidx[fi][k];
                let new = list[ni as usize];
                let head = *vi as usize;
                if normal_of[head].is_none() {
                    normal_of[head] = Some(ni);
                    vertices[head].normal = new;
                    continue;
                }
                let same = |n: [f32; 3]| n.iter().zip(new).all(|(a, b)| *a == b);
                let hit = std::iter::once(head)
                    .chain(chain[head].iter().copied())
                    .find(|&c| same(vertices[c].normal));
                *vi = match hit {
                    Some(c) => c as u32,
                    None => {
                        let mut copy = vertices[head];
                        copy.normal = new;
                        vertices.push(copy);
                        chain[head].push(vertices.len() - 1);
                        (vertices.len() - 1) as u32
                    }
                };
            }
        }
        let m = face_material.as_ref().map_or(0, |m| m[fi]);
        for k in 1..f.len() - 1 {
            tri.extend([f[0], f[k], f[k + 1]]);
            attr.push(m);
        }
    }

    // `OptimizeInplace(ATTRSORT | IGNOREVERTS | DONOTSPLIT)` groups faces by attribute.
    // Stable order inside a group is an assumption.
    if face_material.is_some() {
        let mut order: Vec<usize> = (0..attr.len()).collect();
        order.sort_by_key(|&i| attr[i]);
        tri = order
            .iter()
            .flat_map(|&i| tri[i * 3..i * 3 + 3].iter().copied())
            .collect();
        attr = order.iter().map(|&i| attr[i]).collect();
    }

    Ok(Some(Container {
        vertices,
        indices: tri,
        face_material: attr,
        materials,
        has_normals: normals.is_some(),
        has_texcoords: texcoords.is_some(),
        has_colors,
        transform,
    }))
}

/// `D3DXVec3TransformCoord`.
fn transform_coord(p: [f32; 3], m: &Mat4) -> [f32; 3] {
    let [x, y, z] = p;
    let m = &m.0;
    let w = ((x * m[3] + y * m[7]) + z * m[11]) + m[15];
    if w == 0.0 {
        return [0.0; 3];
    }
    [
        (((x * m[0] + y * m[4]) + z * m[8]) + m[12]) / w,
        (((x * m[1] + y * m[5]) + z * m[9]) + m[13]) / w,
        (((x * m[2] + y * m[6]) + z * m[10]) + m[14]) / w,
    ]
}

fn merge(containers: Vec<Container>) -> Result<XMesh, Error> {
    let mut mesh = XMesh {
        vertices: Vec::new(),
        indices: Vec::new(),
        face_material: Vec::new(),
        materials: Vec::new(),
        has_normals: false,
        has_texcoords: false,
        has_colors: false,
    };
    for c in &containers {
        mesh.has_normals |= c.has_normals;
        mesh.has_texcoords |= c.has_texcoords;
        mesh.has_colors |= c.has_colors;
    }
    for c in containers {
        let base = mesh.vertices.len() as u32;
        let offset = mesh.materials.len() as u32;
        for v in &c.vertices {
            // D3DX transforms the normal as a coordinate too, translation included,
            // and does not normalize it again.
            mesh.vertices.push(Vertex {
                position: transform_coord(v.position, &c.transform),
                normal: if c.has_normals {
                    transform_coord(v.normal, &c.transform)
                } else {
                    [0.0; 3]
                },
                texcoord: v.texcoord,
            });
        }
        mesh.indices.extend(c.indices.iter().map(|i| base + i));
        mesh.face_material
            .extend(c.face_material.iter().map(|m| offset + m));
        mesh.materials.extend(c.materials);
    }
    if mesh.vertices.len() > MAX_VERTICES {
        return Err(Error::TooLarge);
    }
    if mesh.materials.is_empty() {
        // D3DXLoadMeshFromXInMemory: one default material for a file without any.
        mesh.materials.push(XMaterial {
            diffuse: [0.5, 0.5, 0.5, 0.0],
            ambient: [0.0; 4],
            specular: [0.5, 0.5, 0.5, 0.0],
            emissive: [0.0; 4],
            power: 0.0,
            texture: None,
        });
    }
    Ok(mesh)
}
