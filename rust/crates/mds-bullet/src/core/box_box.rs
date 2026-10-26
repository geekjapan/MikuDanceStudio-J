//! Altered Rust translation of the vendored Bullet 2.75 ODE box detector.
/*
 * Box-Box collision detection re-distributed under the ZLib license with permission from Russell L. Smith
 * Original version is from Open Dynamics Engine, Copyright (C) 2001,2002 Russell L. Smith.
 * All rights reserved.  Email: russ@q12.org   Web: www.q12.org
 Bullet Continuous Collision Detection and Physics Library
 Bullet is Copyright (c) 2003-2006 Erwin Coumans  http://continuousphysics.com/Bullet/

This software is provided 'as-is', without any express or implied warranty.
In no event will the authors be held liable for any damages arising from the use of this software.
Permission is granted to anyone to use this software for any purpose,
including commercial applications, and to alter it and redistribute it freely,
subject to the following restrictions:

1. The origin of this software must not be misrepresented; you must not claim that you wrote the original software. If you use this software in a product, an acknowledgment in the product documentation would be appreciated but is not required.
2. Altered source versions must be plainly marked as such, and must not be misrepresented as being the original software.
3. This notice may not be removed or altered from any source distribution.
*/

use super::math::{Transform, Vec3};
use super::shape::Shape;

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct BoxContact {
    pub normal_on_b: Vec3,
    pub point_on_b: Vec3,
    pub distance: f32,
}

fn clip(h: [f32; 2], mut q: Vec<[f32; 2]>) -> Vec<[f32; 2]> {
    for dir in 0..2 {
        for sign in [-1.0, 1.0] {
            let mut r = Vec::with_capacity(8);
            for i in 0..q.len() {
                let p = q[i];
                let next = q[(i + 1) % q.len()];
                if sign * p[dir] < h[dir] {
                    r.push(p);
                    if r.len() == 8 {
                        return r;
                    }
                }
                if (sign * p[dir] < h[dir]) != (sign * next[dir] < h[dir]) {
                    let mut v = [0.0; 2];
                    v[1 - dir] = p[1 - dir]
                        + (next[1 - dir] - p[1 - dir]) / (next[dir] - p[dir])
                            * (sign * h[dir] - p[dir]);
                    v[dir] = sign * h[dir];
                    r.push(v);
                    if r.len() == 8 {
                        return r;
                    }
                }
            }
            q = r;
        }
    }
    q
}

fn cull(p: &[[f32; 2]], first: usize) -> [usize; 4] {
    let n = p.len();
    let (mut area, mut cx, mut cy) = (0.0_f32, 0.0_f32, 0.0_f32);
    for i in 0..n - 1 {
        let q = p[i][0] * p[i + 1][1] - p[i + 1][0] * p[i][1];
        area += q;
        cx += q * (p[i][0] + p[i + 1][0]);
        cy += q * (p[i][1] + p[i + 1][1]);
    }
    let q = p[n - 1][0] * p[0][1] - p[0][0] * p[n - 1][1];
    area = if (area + q).abs() > f32::EPSILON {
        1.0 / (3.0 * (area + q))
    } else {
        1e18
    };
    cx = area * (cx + q * (p[n - 1][0] + p[0][0]));
    cy = area * (cy + q * (p[n - 1][1] + p[0][1]));
    let angles: Vec<f32> = p
        .iter()
        .map(|v| mds_crtmath::atan2f(v[1] - cy, v[0] - cx))
        .collect();
    let mut available = [true; 8];
    available[first] = false;
    let mut selected = [first; 4];
    for j in 1..4 {
        let mut a = j as f32 * (2.0 * std::f32::consts::PI / 4.0) + angles[first];
        if a > std::f32::consts::PI {
            a -= 2.0 * std::f32::consts::PI;
        }
        let mut maxdiff = 1e9;
        for i in 0..n {
            if available[i] {
                let mut diff = (angles[i] - a).abs();
                if diff > std::f32::consts::PI {
                    diff = 2.0 * std::f32::consts::PI - diff;
                }
                if diff < maxdiff {
                    maxdiff = diff;
                    selected[j] = i;
                }
            }
        }
        available[selected[j]] = false;
    }
    selected
}

/// Identity-scaled box shapes only, matching btBoxBoxDetector::getClosestPoints.
pub fn box_box_contacts(
    shape_a: Shape,
    world_a: Transform,
    shape_b: Shape,
    world_b: Transform,
) -> Option<Vec<BoxContact>> {
    let (
        Shape::Box {
            half_extents_without_margin: ha,
        },
        Shape::Box {
            half_extents_without_margin: hb,
        },
    ) = (shape_a, shape_b)
    else {
        return None;
    };
    let a = ha.0.map(|v| (2.0 * (v + 0.04)) * 0.5);
    let b = hb.0.map(|v| (2.0 * (v + 0.04)) * 0.5);
    let r1 = world_a.basis.0;
    let r2 = world_b.basis.0;
    let p1 = world_a.origin;
    let p2 = world_b.origin;
    let p = p2.sub(p1).0;
    let pp: [f32; 3] =
        std::array::from_fn(|i| (r1[2][i] * p[2] + r1[1][i] * p[1]) + r1[0][i] * p[0]);
    let r = [
        [
            (r1[0][0] * r2[0][0] + r1[2][0] * r2[2][0]) + r1[1][0] * r2[1][0],
            ((f64::from(r1[2][0]) * f64::from(r2[2][1])
                + f64::from(r1[1][0]) * f64::from(r2[1][1]))
                + f64::from(r1[0][0]) * f64::from(r2[0][1])) as f32,
            (r1[1][0] * r2[1][2] + r1[2][0] * r2[2][2]) + r1[0][0] * r2[0][2],
        ],
        [
            (r1[1][1] * r2[1][0] + r1[2][1] * r2[2][0]) + r1[0][1] * r2[0][0],
            (r1[2][1] * r2[2][1] + r1[1][1] * r2[1][1]) + r1[0][1] * r2[0][1],
            (r1[2][1] * r2[2][2] + r1[1][1] * r2[1][2]) + r1[0][1] * r2[0][2],
        ],
        [
            (r1[1][2] * r2[1][0] + r1[2][2] * r2[2][0]) + r1[0][2] * r2[0][0],
            (r1[2][2] * r2[2][1] + r1[1][2] * r2[1][1]) + r1[0][2] * r2[0][1],
            (r1[2][2] * r2[2][2] + r1[1][2] * r2[1][2]) + r1[0][2] * r2[0][2],
        ],
    ];
    let q = r.map(|row| row.map(f32::abs));
    let mut s = -f32::MAX;
    let mut code = 0;
    let mut invert = false;
    let mut normal = Vec3::ZERO;
    let mut normal_c = Vec3::ZERO;
    for i in 0..3 {
        let e = f64::from(pp[i]);
        let radius = ((f64::from(a[i]) + f64::from(b[0]) * f64::from(q[i][0]))
            + f64::from(b[1]) * f64::from(q[i][1]))
            + f64::from(b[2]) * f64::from(q[i][2]);
        let s2 = (e.abs() - radius) as f32;
        if s2 > 0.0 {
            return Some(Vec::new());
        }
        if s2 > s {
            s = s2;
            normal = Vec3(std::array::from_fn(|j| r1[j][i]));
            invert = e < 0.0;
            code = i + 1;
        }
    }
    for i in 0..3 {
        let e = (f64::from(r2[0][i]) * f64::from(p[0]) + f64::from(r2[1][i]) * f64::from(p[1]))
            + f64::from(r2[2][i]) * f64::from(p[2]);
        let radius = ((f64::from(a[0]) * f64::from(q[0][i])
            + f64::from(a[1]) * f64::from(q[1][i]))
            + f64::from(a[2]) * f64::from(q[2][i]))
            + f64::from(b[i]);
        let s2 = (e.abs() - radius) as f32;
        if s2 > 0.0 {
            return Some(Vec::new());
        }
        if s2 > s {
            s = s2;
            normal = Vec3(std::array::from_fn(|j| r2[j][i]));
            invert = e < 0.0;
            code = i + 4;
        }
    }
    macro_rules! cross_axis {
        ($expr:expr, $radius:expr, $n1:expr, $n2:expr, $n3:expr, $code:expr) => {{
            let expr: f64 = $expr;
            let radius: f64 = $radius;
            let n = [$n1, $n2, $n3];
            let mut s2 = (expr.abs() - radius) as f32;
            if s2 > 0.0 {
                return Some(Vec::new());
            }
            let l = ((f64::from(n[0]) * f64::from(n[0]) + f64::from(n[1]) * f64::from(n[1]))
                + f64::from(n[2]) * f64::from(n[2]))
            .sqrt() as f32;
            if l > 0.0 {
                let inv_l = 1.0 / l;
                s2 *= inv_l;
                if s2 * 1.05 > s {
                    s = s2;
                    normal_c = Vec3(n).scale(inv_l);
                    invert = expr < 0.0;
                    code = $code;
                }
            }
        }};
    }
    cross_axis!(
        f64::from(pp[2]) * f64::from(r[1][0]) - f64::from(pp[1]) * f64::from(r[2][0]),
        f64::from(a[1]) * f64::from(q[2][0])
            + f64::from(a[2]) * f64::from(q[1][0])
            + f64::from(b[1]) * f64::from(q[0][2])
            + f64::from(b[2]) * f64::from(q[0][1]),
        0.0_f32,
        -r[2][0],
        r[1][0],
        7
    );
    cross_axis!(
        f64::from(pp[2]) * f64::from(r[1][1]) - f64::from(pp[1]) * f64::from(r[2][1]),
        f64::from(a[1]) * f64::from(q[2][1])
            + f64::from(a[2]) * f64::from(q[1][1])
            + f64::from(b[0]) * f64::from(q[0][2])
            + f64::from(b[2]) * f64::from(q[0][0]),
        0.0_f32,
        -r[2][1],
        r[1][1],
        8
    );
    cross_axis!(
        f64::from(pp[2]) * f64::from(r[1][2]) - f64::from(pp[1]) * f64::from(r[2][2]),
        f64::from(a[1]) * f64::from(q[2][2])
            + f64::from(a[2]) * f64::from(q[1][2])
            + f64::from(b[0]) * f64::from(q[0][1])
            + f64::from(b[1]) * f64::from(q[0][0]),
        0.0_f32,
        -r[2][2],
        r[1][2],
        9
    );
    cross_axis!(
        f64::from(pp[0]) * f64::from(r[2][0]) - f64::from(pp[2]) * f64::from(r[0][0]),
        f64::from(a[0]) * f64::from(q[2][0])
            + f64::from(a[2]) * f64::from(q[0][0])
            + f64::from(b[1]) * f64::from(q[1][2])
            + f64::from(b[2]) * f64::from(q[1][1]),
        r[2][0],
        0.0_f32,
        -r[0][0],
        10
    );
    cross_axis!(
        f64::from(pp[0]) * f64::from(r[2][1]) - f64::from(pp[2]) * f64::from(r[0][1]),
        f64::from(a[0]) * f64::from(q[2][1])
            + f64::from(a[2]) * f64::from(q[0][1])
            + f64::from(b[0]) * f64::from(q[1][2])
            + f64::from(b[2]) * f64::from(q[1][0]),
        r[2][1],
        0.0_f32,
        -r[0][1],
        11
    );
    cross_axis!(
        f64::from(pp[0]) * f64::from(r[2][2]) - f64::from(pp[2]) * f64::from(r[0][2]),
        f64::from(a[0]) * f64::from(q[2][2])
            + f64::from(a[2]) * f64::from(q[0][2])
            + f64::from(b[0]) * f64::from(q[1][1])
            + f64::from(b[1]) * f64::from(q[1][0]),
        r[2][2],
        0.0_f32,
        -r[0][2],
        12
    );
    cross_axis!(
        f64::from(pp[1]) * f64::from(r[0][0]) - f64::from(pp[0]) * f64::from(r[1][0]),
        f64::from(a[0]) * f64::from(q[1][0])
            + f64::from(a[1]) * f64::from(q[0][0])
            + f64::from(b[1]) * f64::from(q[2][2])
            + f64::from(b[2]) * f64::from(q[2][1]),
        -r[1][0],
        r[0][0],
        0.0_f32,
        13
    );
    cross_axis!(
        f64::from(pp[1]) * f64::from(r[0][1]) - f64::from(pp[0]) * f64::from(r[1][1]),
        f64::from(a[0]) * f64::from(q[1][1])
            + f64::from(a[1]) * f64::from(q[0][1])
            + f64::from(b[0]) * f64::from(q[2][2])
            + f64::from(b[2]) * f64::from(q[2][0]),
        -r[1][1],
        r[0][1],
        0.0_f32,
        14
    );
    cross_axis!(
        f64::from(pp[1]) * f64::from(r[0][2]) - f64::from(pp[0]) * f64::from(r[1][2]),
        f64::from(a[0]) * f64::from(q[1][2])
            + f64::from(a[1]) * f64::from(q[0][2])
            + f64::from(b[0]) * f64::from(q[2][1])
            + f64::from(b[1]) * f64::from(q[2][0]),
        -r[1][2],
        r[0][2],
        0.0_f32,
        15
    );
    if code == 0 {
        return Some(Vec::new());
    }
    if code > 6 {
        normal = world_a.basis.apply(normal_c);
    }
    if invert {
        normal = normal.negate();
    }
    if code > 6 {
        let mut pa = p1.0;
        let mut pb = p2.0;
        for j in 0..3 {
            let da = (normal.0[0] * r1[0][j] + normal.0[2] * r1[2][j]) + normal.0[1] * r1[1][j];
            let db = (normal.0[0] * r2[0][j] + normal.0[2] * r2[2][j]) + normal.0[1] * r2[1][j];
            let sa = if da > 0.0 { 1.0 } else { -1.0 };
            let sb = if db > 0.0 { -1.0 } else { 1.0 };
            for k in 0..3 {
                pa[k] += sa * a[j] * r1[k][j];
                pb[k] += sb * b[j] * r2[k][j];
            }
        }
        let ua = Vec3(std::array::from_fn(|i| r1[i][(code - 7) / 3]));
        let ub = Vec3(std::array::from_fn(|i| r2[i][(code - 7) % 3]));
        let delta = Vec3(pb).sub(Vec3(pa));
        let uaub = ua.dot(ub);
        let q1 = ua.dot(delta);
        let q2 = -ub.dot(delta);
        let d = 1.0 - uaub * uaub;
        let beta = if d <= 0.0001 {
            0.0
        } else {
            (uaub * q1 + q2) * (1.0 / d)
        };
        return Some(vec![BoxContact {
            normal_on_b: normal.negate(),
            point_on_b: Vec3(pb).add(ub.scale(beta)),
            distance: s,
        }]);
    }
    let (ra, rb, pa, pb, sa, sb) = if code <= 3 {
        (r1, r2, p1, p2, a, b)
    } else {
        (r2, r1, p2, p1, b, a)
    };
    let normal2 = if code <= 3 { normal } else { normal.negate() };
    let nr: [f32; 3] = std::array::from_fn(|i| {
        (rb[0][i] * normal2.0[0] + rb[1][i] * normal2.0[1]) + rb[2][i] * normal2.0[2]
    });
    let anr = nr.map(f32::abs);
    let lanr = if anr[1] > anr[0] {
        if anr[1] > anr[2] {
            1
        } else {
            2
        }
    } else if anr[0] > anr[2] {
        0
    } else {
        2
    };
    let [a1, a2] = match lanr {
        0 => [1, 2],
        1 => [0, 2],
        _ => [0, 1],
    };
    let center: [f32; 3] = std::array::from_fn(|i| {
        if nr[lanr] < 0.0 {
            (pb.0[i] - pa.0[i]) + sb[lanr] * rb[i][lanr]
        } else {
            (pb.0[i] - pa.0[i]) - sb[lanr] * rb[i][lanr]
        }
    });
    let cn = if code <= 3 { code - 1 } else { code - 4 };
    let [c1i, c2i] = match cn {
        0 => [1, 2],
        1 => [0, 2],
        _ => [0, 1],
    };
    let coordinate = |i| (center[1] * ra[1][i] + center[2] * ra[2][i]) + center[0] * ra[0][i];
    let c1 = coordinate(c1i);
    let c2 = coordinate(c2i);
    let entry = |i, j| (ra[2][i] * rb[2][j] + ra[1][i] * rb[1][j]) + ra[0][i] * rb[0][j];
    let mut m11 = entry(c1i, a1);
    let mut m12 = entry(c1i, a2);
    let mut m21 = entry(c2i, a1);
    let mut m22 = entry(c2i, a2);
    let k1 = m11 * sb[a1];
    let k2 = m21 * sb[a1];
    let k3 = m12 * sb[a2];
    let k4 = m22 * sb[a2];
    let quad = vec![
        [(c1 - k1) - k3, (c2 - k2) - k4],
        [(c1 - k1) + k3, (c2 - k2) + k4],
        [(k3 + k1) + c1, (k4 + k2) + c2],
        [(k1 + c1) - k3, (k2 + c2) - k4],
    ];
    let clipped = clip([sa[c1i], sa[c2i]], quad);
    let det = 1.0 / (m11 * m22 - m12 * m21);
    m11 *= det;
    m12 *= det;
    m21 *= det;
    m22 *= det;
    let mut points = Vec::with_capacity(8);
    let mut positions = Vec::with_capacity(8);
    for v in clipped {
        let k1 = m22 * (v[0] - c1) - m12 * (v[1] - c2);
        let k2 = -m21 * (v[0] - c1) + m11 * (v[1] - c2);
        let point: [f32; 3] =
            std::array::from_fn(|i| (k1 * rb[i][a1] + k2 * rb[i][a2]) + center[i]);
        let dot = (normal2.0[2] * point[2] + normal2.0[0] * point[0]) + normal2.0[1] * point[1];
        let depth = sa[cn] - dot;
        if depth >= 0.0 {
            positions.push(v);
            points.push(BoxContact {
                normal_on_b: normal.negate(),
                point_on_b: Vec3(point).add(pa),
                distance: -depth,
            });
        }
    }
    if points.len() <= 4 {
        return Some(points);
    }
    let mut first = 0;
    for i in 1..points.len() {
        if -points[i].distance > -points[first].distance {
            first = i;
        }
    }
    Some(cull(&positions, first).map(|i| points[i]).to_vec())
}
