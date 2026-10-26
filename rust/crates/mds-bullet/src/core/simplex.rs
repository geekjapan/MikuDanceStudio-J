//! Altered Rust translation of Bullet 2.75 btVoronoiSimplexSolver.

/*
Bullet Continuous Collision Detection and Physics Library
Copyright (c) 2003-2006 Erwin Coumans  http://continuousphysics.com/Bullet/

This software is provided 'as-is', without any express or implied warranty.
In no event will the authors be held liable for any damages arising from the use of this software.
Permission is granted to anyone to use this software for any purpose,
including commercial applications, and to alter it and redistribute it freely,
subject to the following restrictions:

1. The origin of this software must not be misrepresented; you must not claim that you wrote the original software. If you use this software in a product, an acknowledgment in the product documentation would be appreciated but is not required.
2. Altered source versions must be plainly marked as such, and must not be misrepresented as being the original software.
3. This notice may not be removed or altered from any source distribution.

    Elsevier CDROM license agreements grants nonexclusive license to use the software
    for any purpose, commercial or non-commercial as long as the following credit is included
    identifying the original source of the software:

    Parts of the source are "from the book Real-Time Collision Detection by
    Christer Ericson, published by Morgan Kaufmann Publishers,
    (c) 2005 Elsevier Inc."

*/

use super::math::Vec3;

#[derive(Clone, Copy, Debug)]
pub struct Vertex {
    pub w: Vec3,
    pub p: Vec3,
    pub q: Vec3,
}

impl Vertex {
    const ZERO: Self = Self {
        w: Vec3::ZERO,
        p: Vec3::ZERO,
        q: Vec3::ZERO,
    };
}

#[derive(Clone, Copy, Debug)]
pub struct ClosestResult {
    pub point: Vec3,
    pub used: [bool; 4],
    pub barycentric: [f32; 4],
    pub degenerate: bool,
}

impl ClosestResult {
    fn reset(&mut self) {
        self.used = [false; 4];
        self.barycentric = [0.0; 4];
        self.degenerate = false;
    }

    fn valid(&self) -> bool {
        self.barycentric.iter().all(|&value| value >= 0.0)
    }
}

#[derive(Clone, Debug)]
pub struct VoronoiSimplexSolver {
    vertices: [Vertex; 4],
    count: usize,
    pub cached_p1: Vec3,
    pub cached_p2: Vec3,
    pub cached_v: Vec3,
    pub last_w: Vec3,
    pub cached_valid: bool,
    pub result: ClosestResult,
    pub needs_update: bool,
}

impl Default for VoronoiSimplexSolver {
    fn default() -> Self {
        let mut solver = Self {
            vertices: [Vertex::ZERO; 4],
            count: 0,
            cached_p1: Vec3::ZERO,
            cached_p2: Vec3::ZERO,
            cached_v: Vec3::ZERO,
            last_w: Vec3::ZERO,
            cached_valid: false,
            result: ClosestResult {
                point: Vec3::ZERO,
                used: [false; 4],
                barycentric: [0.0; 4],
                degenerate: false,
            },
            needs_update: true,
        };
        solver.reset();
        solver
    }
}

impl VoronoiSimplexSolver {
    pub fn reset(&mut self) {
        self.cached_valid = false;
        self.count = 0;
        self.needs_update = true;
        self.last_w = Vec3([1e18; 3]);
        self.result.reset();
    }

    pub fn add_vertex(&mut self, w: Vec3, p: Vec3, q: Vec3) {
        assert!(self.count < 4, "a simplex supports at most four vertices");
        self.last_w = w;
        self.needs_update = true;
        self.vertices[self.count] = Vertex { w, p, q };
        self.count += 1;
    }

    pub fn get_simplex(&self) -> &[Vertex] {
        &self.vertices[..self.count]
    }
    pub fn num_vertices(&self) -> usize {
        self.count
    }
    pub fn full_simplex(&self) -> bool {
        self.count == 4
    }
    pub fn empty_simplex(&self) -> bool {
        self.count == 0
    }
    pub fn in_simplex(&self, w: Vec3) -> bool {
        self.last_w == w || self.get_simplex().iter().any(|vertex| vertex.w == w)
    }
    pub fn max_vertex(&self) -> f32 {
        let mut maximum = 0.0;
        for vertex in self.get_simplex() {
            let length = vertex.w.length2();
            if maximum < length {
                maximum = length;
            }
        }
        maximum
    }
    pub fn backup_closest(&self) -> Vec3 {
        self.cached_v
    }
    pub fn closest(&mut self, v: &mut Vec3) -> bool {
        let valid = self.update();
        *v = self.cached_v;
        valid
    }
    pub fn compute_points(&mut self) -> (Vec3, Vec3) {
        self.update();
        (self.cached_p1, self.cached_p2)
    }

    fn reduce(&mut self) {
        for i in (0..4).rev() {
            if self.count > i && !self.result.used[i] {
                self.count -= 1;
                self.vertices[i] = self.vertices[self.count];
            }
        }
    }

    fn weighted(&self, p: bool) -> Vec3 {
        let vertex = |i: usize| {
            if p {
                self.vertices[i].p
            } else {
                self.vertices[i].q
            }
        };
        let mut value = vertex(0).scale(self.result.barycentric[0]);
        for i in 1..self.count {
            value = value.add(vertex(i).scale(self.result.barycentric[i]));
        }
        value
    }

    fn update(&mut self) -> bool {
        if !self.needs_update {
            return self.cached_valid;
        }
        self.result.reset();
        self.needs_update = false;
        match self.count {
            0 => self.cached_valid = false,
            1 => {
                self.cached_p1 = self.vertices[0].p;
                self.cached_p2 = self.vertices[0].q;
                self.cached_v = self.cached_p1.sub(self.cached_p2);
                self.result.barycentric = [1.0, 0.0, 0.0, 0.0];
                self.cached_valid = self.result.valid();
            }
            2 => {
                let from = self.vertices[0].w;
                let delta = self.vertices[1].w.sub(from);
                let [dx, dy, dz] = delta.0;
                let [x, y, z] = from.0;
                let mut t = (dx * -x + dz * -z) + dy * -y;
                if t > 0.0 {
                    let dot = (dx * dx + dz * dz) + dy * dy;
                    if dot > t {
                        t /= dot;
                        self.result.used[0] = true;
                        self.result.used[1] = true;
                    } else {
                        t = 1.0;
                        self.result.used[1] = true;
                    }
                } else {
                    t = 0.0;
                    self.result.used[0] = true;
                }
                self.result.barycentric = [1.0 - t, t, 0.0, 0.0];
                self.cached_p1 = self.vertices[1]
                    .p
                    .sub(self.vertices[0].p)
                    .scale(t)
                    .add(self.vertices[0].p);
                self.cached_p2 = self.vertices[1]
                    .q
                    .sub(self.vertices[0].q)
                    .scale(t)
                    .add(self.vertices[0].q);
                self.cached_v = self.cached_p1.sub(self.cached_p2);
                self.reduce();
                self.cached_valid = self.result.valid();
            }
            3 | 4 => {
                let w = self.vertices.map(|v| v.w);
                let separated = if self.count == 3 {
                    triangle(Vec3::ZERO, w[0], w[1], w[2], &mut self.result);
                    true
                } else {
                    tetrahedron(Vec3::ZERO, w, &mut self.result)
                };
                if separated {
                    self.cached_p1 = self.weighted(true);
                    self.cached_p2 = self.weighted(false);
                    self.cached_v = self.cached_p1.sub(self.cached_p2);
                    self.reduce();
                    self.cached_valid = self.result.valid();
                } else {
                    self.cached_valid = !self.result.degenerate;
                    if self.cached_valid {
                        self.cached_v = Vec3::ZERO;
                    }
                }
            }
            _ => unreachable!(),
        }
        self.cached_valid
    }
}

fn triangle(p: Vec3, a: Vec3, b: Vec3, c: Vec3, result: &mut ClosestResult) {
    result.used = [false; 4];
    let ab = b.sub(a);
    let ac = c.sub(a);
    let ap = p.sub(a);
    let d1 = ab.dot_sse(ap);
    let d2 = ac.dot_sse(ap);
    if d1 <= 0.0 && d2 <= 0.0 {
        result.point = a;
        result.used[0] = true;
        result.barycentric = [1.0, 0.0, 0.0, 0.0];
        return;
    }
    let bp = p.sub(b);
    let d3 = ab.dot_sse(bp);
    let d4 = ac.dot_sse(bp);
    if d3 >= 0.0 && d4 <= d3 {
        result.point = b;
        result.used[1] = true;
        result.barycentric = [0.0, 1.0, 0.0, 0.0];
        return;
    }
    let vc = d1 * d4 - d3 * d2;
    if vc <= 0.0 && d1 >= 0.0 && d3 <= 0.0 {
        let v = d1 / (d1 - d3);
        result.point = a.add(ab.scale(v));
        result.used = [true, true, false, false];
        result.barycentric = [1.0 - v, v, 0.0, 0.0];
        return;
    }
    let cp = p.sub(c);
    let d5 = ab.dot_sse(cp);
    let d6 = ac.dot_sse(cp);
    if d6 >= 0.0 && d5 <= d6 {
        result.point = c;
        result.used[2] = true;
        result.barycentric = [0.0, 0.0, 1.0, 0.0];
        return;
    }
    let vb = d5 * d2 - d1 * d6;
    if vb <= 0.0 && d2 >= 0.0 && d6 <= 0.0 {
        let w = d2 / (d2 - d6);
        result.point = a.add(ac.scale(w));
        result.used = [true, false, true, false];
        result.barycentric = [1.0 - w, 0.0, w, 0.0];
        return;
    }
    let va = d3 * d6 - d5 * d4;
    if va <= 0.0 && d4 - d3 >= 0.0 && d5 - d6 >= 0.0 {
        let w = (d4 - d3) / ((d4 - d3) + (d5 - d6));
        result.point = b.add(c.sub(b).scale(w));
        result.used = [false, true, true, false];
        result.barycentric = [0.0, 1.0 - w, w, 0.0];
        return;
    }
    let denom = 1.0 / ((va + vb) + vc);
    let v = vb * denom;
    let w = vc * denom;
    result.point = a.add(ab.scale(v)).add(ac.scale(w));
    result.used = [true, true, true, false];
    result.barycentric = [(1.0 - v) - w, v, w, 0.0];
}

fn outside_plane(p: Vec3, a: Vec3, b: Vec3, c: Vec3, d: Vec3) -> i32 {
    let normal = b.sub(a).cross(c.sub(a));
    let dot = |v: Vec3| (v.0[2] * normal.0[2] + v.0[0] * normal.0[0]) + v.0[1] * normal.0[1];
    let sign_p = dot(p.sub(a));
    let sign_d = dot(d.sub(a));
    if sign_d * sign_d < 1e-4_f32 * 1e-4_f32 {
        -1
    } else {
        i32::from(sign_p * sign_d < 0.0)
    }
}

fn tetrahedron(p: Vec3, vertices: [Vec3; 4], result: &mut ClosestResult) -> bool {
    result.point = p;
    result.used = [true; 4];
    let faces = [[0, 1, 2, 3], [0, 2, 3, 1], [0, 3, 1, 2], [1, 3, 2, 0]];
    let outside = faces
        .map(|[a, b, c, d]| outside_plane(p, vertices[a], vertices[b], vertices[c], vertices[d]));
    if outside.iter().any(|&value| value < 0) {
        result.degenerate = true;
        return false;
    }
    if outside == [0; 4] {
        return false;
    }
    let mut best = f32::MAX;
    for (face, outside) in faces.into_iter().zip(outside) {
        if outside == 0 {
            continue;
        }
        let [a, b, c, _] = face;
        let mut candidate = ClosestResult {
            point: Vec3::ZERO,
            used: [false; 4],
            barycentric: [0.0; 4],
            degenerate: false,
        };
        triangle(p, vertices[a], vertices[b], vertices[c], &mut candidate);
        let delta = candidate.point.sub(p);
        let distance = delta.dot_sse(delta);
        if distance < best {
            best = distance;
            result.point = candidate.point;
            result.used = [false; 4];
            result.barycentric = [0.0; 4];
            for (i, index) in [a, b, c].into_iter().enumerate() {
                result.used[index] = candidate.used[i];
                result.barycentric[index] = candidate.barycentric[i];
            }
        }
    }
    true
}
