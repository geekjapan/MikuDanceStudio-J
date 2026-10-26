//! Camera, projection and light: from the PMM camera key (target, rotation, distance, view angle,
//! projection flag) to the view and projection matrices, in the Direct3D conventions (left-handed,
//! depth 0 to 1, row vectors).

/// A column-major `[column][row]` array of the matrix whose D3D row-major layout is the same
/// array flattened; `mul(a, b)` is the D3D product `b * a`. WGSL reads it as `M^T * v`, which is
/// the D3D `v * M`.
pub(crate) type Mat = [[f32; 4]; 4];

pub(crate) fn mul(a: &Mat, b: &Mat) -> Mat {
    let mut r = [[0.0; 4]; 4];
    for (c, col) in r.iter_mut().enumerate() {
        for (row, cell) in col.iter_mut().enumerate() {
            *cell = (0..4).map(|k| a[k][row] * b[c][k]).sum();
        }
    }
    r
}

fn sub(a: [f32; 3], b: [f32; 3]) -> [f32; 3] {
    [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
}
fn dot(a: [f32; 3], b: [f32; 3]) -> f32 {
    a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
}
fn cross(a: [f32; 3], b: [f32; 3]) -> [f32; 3] {
    [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]
}
pub(crate) fn normalize(a: [f32; 3]) -> [f32; 3] {
    let l = dot(a, a).sqrt();
    [a[0] / l, a[1] / l, a[2] / l]
}
pub(crate) fn len(a: [f32; 3]) -> f32 {
    dot(a, a).sqrt()
}

fn look_at_lh(eye: [f32; 3], target: [f32; 3], up: [f32; 3]) -> Mat {
    let z = normalize(sub(target, eye));
    let x = normalize(cross(up, z));
    let y = cross(z, x);
    [
        [x[0], y[0], z[0], 0.0],
        [x[1], y[1], z[1], 0.0],
        [x[2], y[2], z[2], 0.0],
        [-dot(x, eye), -dot(y, eye), -dot(z, eye), 1.0],
    ]
}

fn perspective_lh(fov_y: f32, aspect: f32, near: f32, far: f32) -> Mat {
    let f = 1.0 / (fov_y / 2.0).tan();
    let q = far / (far - near);
    [
        [f / aspect, 0.0, 0.0, 0.0],
        [0.0, f, 0.0, 0.0],
        [0.0, 0.0, q, 1.0],
        [0.0, 0.0, -near * q, 0.0],
    ]
}

fn ortho_lh(width: f32, height: f32, near: f32, far: f32) -> Mat {
    let q = 1.0 / (far - near);
    [
        [2.0 / width, 0.0, 0.0, 0.0],
        [0.0, 2.0 / height, 0.0, 0.0],
        [0.0, 0.0, q, 0.0],
        [0.0, 0.0, -near * q, 1.0],
    ]
}

/// The matrices and eye position one frame is drawn with.
#[derive(Clone, Copy, Debug)]
pub struct View {
    pub(crate) view: Mat,
    pub(crate) view_proj: Mat,
    pub(crate) eye: [f32; 3],
    /// What the edge thickness of `mds-skin` reads: the frame world matrix (`mds_skin::View::world`),
    /// the point the distance is measured to (`camera_position`) and `camera_fov`.
    pub(crate) edge_world: Mat,
    pub(crate) edge_origin: [f32; 3],
    pub(crate) edge_fov: f32,
    /// The camera's signed distance: the camera sits at `(0, 0, distance)` of the space the frame
    /// world matrix maps to. 0 for a view not made from a [`Camera`].
    pub(crate) distance: f32,
}

impl View {
    /// The clip-space position `(x, y, z, w)` of a scene point: x and y over w run from -1 to 1
    /// across the picture (y up), z over w from 0 to 1 in depth.
    pub fn clip(&self, p: [f32; 3]) -> [f32; 4] {
        let m = &self.view_proj;
        std::array::from_fn(|c| p[0] * m[0][c] + p[1] * m[1][c] + p[2] * m[2][c] + m[3][c])
    }
}

/// The ortho view is `ORTHO_WIDTH_PER_DISTANCE * |distance|` world units wide (measured on the
/// golden images: 8 and 12 units between model roots are 113.8 and 170.7 px of 640 at distance 45).
const ORTHO_WIDTH_PER_DISTANCE: f32 = 1.0;
const NEAR: f32 = 0.5;
const FAR: f32 = 5000.0;

/// The PMM camera at one frame.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Camera {
    /// The point looked at (the key's position).
    pub target: [f32; 3],
    /// Pitch, yaw, roll in radians. Roll is not checked against a golden image.
    pub rotation: [f32; 3],
    /// Signed distance along the camera's z axis (MMD stores a negative number: the camera sits
    /// behind the target).
    pub distance: f32,
    /// Vertical view angle in degrees.
    pub fov_deg: f32,
    pub orthographic: bool,
}

/// The rows of `Ry(yaw) * Rx(pitch) * Rz(roll)` (D3DX row-vector matrices): the rotation part of
/// the frame world matrix. The edge probe (`tests/fixtures/rust/golden2/*.edge.txt`) shows the
/// yaw-pitch product; where roll goes is a guess, no fixture has one.
fn rotation_rows([pitch, yaw, roll]: [f32; 3]) -> [[f32; 3]; 3] {
    let (sp, cp) = pitch.sin_cos();
    let (sy, cy) = yaw.sin_cos();
    let (sr, cr) = roll.sin_cos();
    let ry = [[cy, 0.0, -sy], [0.0, 1.0, 0.0], [sy, 0.0, cy]];
    let rx = [[1.0, 0.0, 0.0], [0.0, cp, sp], [0.0, -sp, cp]];
    let rz = [[cr, sr, 0.0], [-sr, cr, 0.0], [0.0, 0.0, 1.0]];
    let m3 = |a: [[f32; 3]; 3], b: [[f32; 3]; 3]| -> [[f32; 3]; 3] {
        std::array::from_fn(|r| std::array::from_fn(|c| (0..3).map(|k| a[r][k] * b[k][c]).sum()))
    };
    m3(m3(ry, rx), rz)
}

impl Camera {
    /// The frame world matrix of the C++ app: the target moved to the origin, then the camera
    /// rotation. A point of the scene ends up in a space where the camera sits at
    /// `(0, 0, distance)` and looks along +z.
    pub(crate) fn world(&self) -> Mat {
        let r = rotation_rows(self.rotation);
        let t = self.target;
        let mut m = IDENTITY;
        for i in 0..3 {
            m[i][..3].copy_from_slice(&r[i]);
            m[3][i] = -(0..3).map(|k| t[k] * r[k][i]).sum::<f32>();
        }
        m
    }

    pub fn view(&self, width: u32, height: u32) -> View {
        let aspect = width as f32 / height as f32;
        let world = self.world();
        let r = rotation_rows(self.rotation);
        // The eye is (0, 0, distance) of the camera space taken back to the scene: through R^T.
        let eye = std::array::from_fn(|i| self.target[i] + self.distance * r[i][2]);
        let mut back = IDENTITY;
        back[3][2] = -self.distance;
        let view = mul(&back, &world);
        let proj = if self.orthographic {
            let w = ORTHO_WIDTH_PER_DISTANCE * self.distance.abs();
            // The depth range is wide: every model is near the target plane.
            ortho_lh(w, w / aspect, -FAR, FAR)
        } else {
            perspective_lh(self.fov_deg.to_radians(), aspect, NEAR, FAR)
        };
        View {
            view,
            view_proj: mul(&proj, &view),
            eye,
            edge_world: world,
            edge_origin: self.target,
            edge_fov: self.fov_deg,
            distance: self.distance,
        }
    }
}

/// The self-shadow light view and light view projection of a frame, from the frame world matrix
/// `world`, the camera distance, the light direction `light` (PMM light direction times the
/// rotation of `world`, not normalized: `SceneLight().Direction`), the mode and the distance value.
/// The projection maps a scene point (not a frame world point) to the shadow map's clip space.
///
/// Read off the `shadow` lines of `tests/fixtures/rust/golden2/selfshadow.edge.txt` and
/// `swing600-golden.edge.txt` (both orthographic cameras; `light_view_matches_the_probes` checks
/// all six): the light looks from `50 * light` before the camera position `(0, 0, distance)` with
/// up +z (so the map's y follows the camera's view direction), and in that view's coordinates
/// `(x, y, z)` the projection is
/// `(s x, s y - 1, z_scale z + a s y / 2, a s y + 1)` with `s` the x/y scale (2 or 3 times the
/// distance in mode 1 or 2), `z_scale` 0.15 times the distance, and `a` 0.5 or 1 in mode 1 or 2.
pub(crate) fn self_shadow_matrices(
    world: &Mat,
    distance: f32,
    light: [f32; 3],
    mode: u8,
    range: f32,
) -> (Mat, Mat) {
    let target = [0.0, 0.0, distance];
    let eye = std::array::from_fn(|i| target[i] - 50.0 * light[i]);
    let light_view = look_at_lh(eye, target, [0.0, 0.0, 1.0]);
    let (s, a) = if mode == 2 {
        (3.0 * range, 1.0)
    } else {
        (2.0 * range, 0.5)
    };
    let proj = [
        [s, 0.0, 0.0, 0.0],
        [0.0, s, a * s / 2.0, a * s],
        [0.0, 0.0, 0.15 * range, 0.0],
        [0.0, -1.0, 0.0, 1.0],
    ];
    (light_view, mul(&proj, &mul(&light_view, world)))
}

impl View {
    /// [`self_shadow_matrices`] for this view's camera and `light`.
    pub(crate) fn self_shadow_view_proj(&self, light: &Light, mode: u8, range: f32) -> Mat {
        let w = &self.edge_world;
        let [x, y, z] = light.direction;
        let rotated = std::array::from_fn(|c| x * w[0][c] + y * w[1][c] + z * w[2][c]);
        self_shadow_matrices(w, self.distance, rotated, mode, range).1
    }
}

pub(crate) const IDENTITY: Mat = [
    [1.0, 0.0, 0.0, 0.0],
    [0.0, 1.0, 0.0, 0.0],
    [0.0, 0.0, 1.0, 0.0],
    [0.0, 0.0, 0.0, 1.0],
];

/// The light at one frame.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Light {
    pub color: [f32; 3],
    /// The direction the light travels.
    pub direction: [f32; 3],
}

/// MMD's default view angle, light color and direction.
pub(crate) const DEFAULT_FOV_DEG: f32 = 30.0;
pub(crate) const DEFAULT_LIGHT: Light = Light {
    color: [154.0 / 255.0; 3],
    direction: [-0.5, -1.0, 0.5],
};

/// A camera for a model alone: MMD's view angle, looking at the center of the bounding box from the
/// side the model faces (`front`, -Z for an MMD model), a little to the right and above, far enough
/// that the box's bounding sphere fits.
pub(crate) fn bounding_box_view(min: [f32; 3], max: [f32; 3], front: f32, aspect: f32) -> View {
    let center = [0, 1, 2].map(|i| (min[i] + max[i]) / 2.0);
    let radius = (len(sub(max, min)) / 2.0).max(1e-3);
    let fov = DEFAULT_FOV_DEG.to_radians();
    let dist = radius / (fov / 2.0).sin() * 1.1;
    let dir = normalize([0.25, 0.2, front]);
    let eye = [0, 1, 2].map(|i| center[i] + dir[i] * dist);
    let view = look_at_lh(eye, center, [0.0, 1.0, 0.0]);
    let proj = perspective_lh(
        fov,
        aspect,
        (dist - radius * 2.0).max(dist * 0.05),
        dist + radius * 2.0,
    );
    View {
        view,
        view_proj: mul(&proj, &view),
        eye,
        edge_world: IDENTITY,
        edge_origin: eye,
        edge_fov: DEFAULT_FOV_DEG,
        distance: 0.0,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Every `*.edge.txt` probe of `tests/fixtures/rust/golden2`: the camera line gives the
    /// frame world matrix of the `world` line, and each `edge` line's result follows from its
    /// model point with the inputs `Camera::view` hands to `mds-skin` (whose formula, checked
    /// against the C++ in `mds-skin`, is restated here because it is private there).
    #[test]
    fn edge_probes_match_the_view() {
        let dir = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../../tests/fixtures/rust/golden2");
        let mut probes = 0;
        let mut edges = 0;
        for entry in std::fs::read_dir(&dir).unwrap() {
            let path = entry.unwrap().path();
            if !path.to_string_lossy().ends_with(".edge.txt") {
                continue;
            }
            probes += 1;
            let text = std::fs::read_to_string(&path).unwrap();
            let mut view = None;
            for line in text.lines().skip(1) {
                let mut words = line.split(' ');
                let _frame = words.next();
                let kind = words.next().unwrap();
                let v: Vec<f32> = words.map(|w| w.parse().unwrap()).collect();
                let at = |what: &str| format!("{}: {line} ({what})", path.display());
                match kind {
                    "camera" => {
                        let camera = Camera {
                            orthographic: v[0] == 1.0,
                            fov_deg: v[1],
                            target: [v[2], v[3], v[4]],
                            distance: v[5],
                            rotation: [v[6], v[7], v[8]],
                        };
                        view = Some(camera.view(640, 360));
                    }
                    "world" => {
                        let world = view.unwrap().edge_world;
                        for (k, (&got, &want)) in world.iter().flatten().zip(&v).enumerate() {
                            assert!((got - want).abs() <= 1e-6, "{} [{k}] {got}", at("world"));
                        }
                    }
                    "edge" => {
                        edges += 1;
                        let view = view.unwrap();
                        let w = &view.edge_world;
                        let p: [f32; 3] = std::array::from_fn(|c| {
                            v[2] * w[0][c] + v[3] * w[1][c] + v[4] * w[2][c] + w[3][c]
                        });
                        for c in 0..3 {
                            assert!((p[c] - v[5 + c]).abs() <= 1e-5, "{}", at("world point"));
                        }
                        let d = len(sub(p, view.edge_origin));
                        assert!((d - v[8]).abs() <= 1e-5 * v[8], "{} {d}", at("distance"));
                        let edge = d * 4.5e-5 * (view.edge_fov * 0.6 + 1.0) * v[9];
                        assert!(
                            (edge - v[10]).abs() <= 1e-6 * v[10],
                            "{} {edge}",
                            at("edge")
                        );
                    }
                    "picture" | "shadow" | "ground" => {}
                    other => panic!("{}: unknown line {other}", path.display()),
                }
            }
        }
        assert_eq!((probes, edges), (7, 35));
    }

    /// Every `shadow` line of the golden2 probes: the light view and light view projection that
    /// `self_shadow_matrices` makes from the line's light direction, mode and distance, and the
    /// camera line's world matrix and distance, equal the recorded ones to float precision.
    #[test]
    fn light_view_matches_the_probes() {
        let dir = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../../tests/fixtures/rust/golden2");
        let mut lines = 0;
        for name in ["selfshadow.edge.txt", "swing600-golden.edge.txt"] {
            let text = std::fs::read_to_string(dir.join(name)).unwrap();
            let mut camera = None;
            for line in text.lines().skip(1) {
                let words: Vec<&str> = line.split(' ').collect();
                let v: Vec<f32> = words[2..].iter().map(|w| w.parse().unwrap()).collect();
                match words[1] {
                    "camera" => {
                        camera = Some(Camera {
                            orthographic: v[0] == 1.0,
                            fov_deg: v[1],
                            target: [v[2], v[3], v[4]],
                            distance: v[5],
                            rotation: [v[6], v[7], v[8]],
                        })
                    }
                    "shadow" => {
                        lines += 1;
                        let c = camera.unwrap();
                        let (lv, lvp) = self_shadow_matrices(
                            &c.world(),
                            c.distance,
                            [v[4], v[5], v[6]],
                            v[2] as u8,
                            v[3],
                        );
                        let close = |got: &Mat, want: &[f32]| {
                            let scale = want.iter().fold(0f32, |m, x| m.max(x.abs()));
                            got.iter()
                                .flatten()
                                .zip(want)
                                .all(|(g, w)| (g - w).abs() <= 1e-6 * scale.max(1.0))
                        };
                        assert!(close(&lv, &v[19..35]), "{name}: {line}: view {lv:?}");
                        assert!(close(&lvp, &v[35..51]), "{name}: {line}: proj {lvp:?}");
                    }
                    _ => {}
                }
            }
        }
        assert_eq!(lines, 6);
    }
}
