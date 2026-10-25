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
    /// The `camera_fov` the edge thickness of `mds-skin` scales with.
    pub(crate) edge_fov: f32,
}

/// The ortho view is `ORTHO_WIDTH_PER_DISTANCE * |distance|` world units wide (measured on the
/// golden images: 8 and 12 units between model roots are 113.8 and 170.7 px of 640 at distance 45).
const ORTHO_WIDTH_PER_DISTANCE: f32 = 1.0;
/// The `camera_fov` that gives the C++ edge of the golden images under the orthographic camera.
/// `mds-skin` scales the edge by `distance * 4.5e-5 * (camera_fov * 0.6 + 1)`; the camera at
/// distance 45 with its view angle of 30 would make the edge 0.0385 thick, but the golden images fit
/// 0.019 to 0.0205 (0.0187 to 0.0195 at the models' own distances). The frames meet the golden rule
/// for `camera_fov` from 13.25 to 13.5 (and, with a bigger error, 13 to 14.5), and this is the
/// middle. What the app puts in `camera_fov` under an orthographic camera is not known, nor which
/// part of the formula differs; a perspective camera passes its view angle in degrees unverified.
const ORTHO_EDGE_FOV: f32 = 13.4;
const NEAR: f32 = 0.5;
const FAR: f32 = 5000.0;

/// The PMM camera at one frame.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Camera {
    /// The point looked at (the key's position).
    pub target: [f32; 3],
    /// Pitch, yaw, roll in radians. Only yaw is checked against a golden image.
    pub rotation: [f32; 3],
    /// Signed distance along the camera's z axis (MMD stores a negative number: the camera sits
    /// behind the target).
    pub distance: f32,
    /// Vertical view angle in degrees.
    pub fov_deg: f32,
    pub orthographic: bool,
}

/// D3DX `RotationYawPitchRoll` applied to a row vector: roll about z, then pitch about x, then
/// yaw about y.
fn rotate(v: [f32; 3], [pitch, yaw, roll]: [f32; 3]) -> [f32; 3] {
    let (s, c) = roll.sin_cos();
    let v = [v[0] * c - v[1] * s, v[0] * s + v[1] * c, v[2]];
    let (s, c) = pitch.sin_cos();
    let v = [v[0], v[1] * c - v[2] * s, v[1] * s + v[2] * c];
    let (s, c) = yaw.sin_cos();
    [v[0] * c + v[2] * s, v[1], -v[0] * s + v[2] * c]
}

impl Camera {
    pub fn view(&self, width: u32, height: u32) -> View {
        let aspect = width as f32 / height as f32;
        let offset = rotate([0.0, 0.0, self.distance], self.rotation);
        let eye = [0, 1, 2].map(|i| self.target[i] + offset[i]);
        let up = rotate([0.0, 1.0, 0.0], self.rotation);
        let view = look_at_lh(eye, self.target, up);
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
            edge_fov: if self.orthographic {
                ORTHO_EDGE_FOV
            } else {
                self.fov_deg
            },
        }
    }
}

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
        edge_fov: DEFAULT_FOV_DEG,
    }
}
