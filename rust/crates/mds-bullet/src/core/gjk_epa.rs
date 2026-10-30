//! Altered Rust translation of Bullet's btGjkEpa2.cpp by Nathanael Presson.
//! Float association follows the native source.
/*
Bullet Continuous Collision Detection and Physics Library
Copyright (c) 2003-2008 Erwin Coumans  http://continuousphysics.com/Bullet/

This software is provided 'as-is', without any express or implied warranty.
In no event will the authors be held liable for any damages arising from the
use of this software.
Permission is granted to anyone to use this software for any purpose,
including commercial applications, and to alter it and redistribute it
freely,
subject to the following restrictions:

1. The origin of this software must not be misrepresented; you must not
claim that you wrote the original software. If you use this software in a
product, an acknowledgment in the product documentation would be appreciated
but is not required.
2. Altered source versions must be plainly marked as such, and must not be
misrepresented as being the original software.
3. This notice may not be removed or altered from any source distribution.
*/

use super::math::{Basis, Transform, Vec3};
use super::shape::Shape;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Status {
    Separated,
    Penetrating,
    GjkFailed,
    EpaFailed,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Solution {
    pub witnesses: [Vec3; 2],
    /// Native normal is in shape 0's local frame; witnesses are in world space.
    pub normal: Vec3,
    pub distance: f32,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum QueryResult {
    Success(Solution),
    Failure(Status),
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum PenDepth {
    Penetrating(Solution),
    Separated(Solution),
    Failed,
}

#[derive(Clone, Copy)]
struct Minkowski {
    shapes: [Shape; 2],
    to1: Basis,
    to0: Transform,
    margins: bool,
}
fn apply_yzx(b: Basis, v: Vec3) -> Vec3 {
    Vec3(b.0.map(|r| (r[1] * v.0[1] + r[2] * v.0[2]) + r[0] * v.0[0]))
}
impl Minkowski {
    fn new(shapes: [Shape; 2], t: [Transform; 2], margins: bool) -> Self {
        let inverse = t[0].basis.transpose();
        Self {
            shapes,
            to1: t[1].basis.transpose().multiply(t[0].basis),
            to0: Transform {
                basis: inverse.multiply(t[1].basis),
                origin: apply_yzx(inverse, t[1].origin.sub(t[0].origin)),
            },
            margins,
        }
    }
    fn local(self, index: usize, d: Vec3) -> Vec3 {
        if self.margins {
            self.shapes[index].supporting_vertex_nonvirtual(d)
        } else {
            self.shapes[index].supporting_vertex_without_margin_nonvirtual(d)
        }
        .expect("GJK/EPA requires convex shapes")
    }
    fn support0(self, d: Vec3) -> Vec3 {
        self.local(0, d)
    }
    fn support1(self, d: Vec3) -> Vec3 {
        apply_yzx(self.to0.basis, self.local(1, apply_yzx(self.to1, d))).add(self.to0.origin)
    }
    fn vertex(self, d: Vec3) -> Vertex {
        let d = d.scale(1.0 / d.length());
        Vertex {
            d,
            w: self.support0(d).sub(self.support1(d.negate())),
        }
    }
}
#[derive(Clone, Copy)]
struct Vertex {
    d: Vec3,
    w: Vec3,
}
impl Vertex {
    const ZERO: Self = Self {
        d: Vec3::ZERO,
        w: Vec3::ZERO,
    };
}
#[derive(Clone, Copy)]
struct Simplex {
    c: [usize; 4],
    p: [f32; 4],
    rank: usize,
}
impl Simplex {
    const ZERO: Self = Self {
        c: [0; 4],
        p: [0.0; 4],
        rank: 0,
    };
}
#[derive(Clone, Copy, PartialEq)]
enum GjkStatus {
    Valid,
    Inside,
    Failed,
}
struct Gjk {
    shape: Minkowski,
    store: [Vertex; 4],
    free: [usize; 4],
    nfree: usize,
    simplices: [Simplex; 2],
    current: usize,
    ray: Vec3,
}
fn dot_zyx(a: Vec3, b: Vec3) -> f32 {
    (a.0[2] * b.0[2] + a.0[1] * b.0[1]) + a.0[0] * b.0[0]
}
fn det(a: Vec3, b: Vec3, c: Vec3) -> f32 {
    (((a.0[1] * b.0[2] * c.0[0] + a.0[2] * b.0[0] * c.0[1]) - a.0[0] * b.0[2] * c.0[1])
        - a.0[1] * b.0[0] * c.0[2])
        + a.0[0] * b.0[1] * c.0[2]
        - a.0[2] * b.0[1] * c.0[0]
}
fn project2(a: Vec3, b: Vec3, w: &mut [f32; 4], mask: &mut usize) -> f32 {
    let [dx, dy, dz] = b.sub(a).0;
    let l = (dx * dx + dz * dz) + dy * dy;
    if l > 0.0 {
        let t = -((a.0[2] * dz + a.0[0] * dx) + a.0[1] * dy) / l;
        if t >= 1.0 {
            w[0] = 0.0;
            w[1] = 1.0;
            *mask = 2;
            return dot_zyx(b, b);
        }
        if t <= 0.0 {
            w[0] = 1.0;
            w[1] = 0.0;
            *mask = 1;
            return dot_zyx(a, a);
        }
        let pz = a.0[2] + dz * t;
        let px = a.0[0] + dx * t;
        let py = dy * t + a.0[1];
        w[1] = t;
        w[0] = 1.0 - t;
        *mask = 3;
        return (pz * pz + px * px) + py * py;
    }
    -1.0
}
fn project3(a: Vec3, b: Vec3, c: Vec3, w: &mut [f32; 4], mask: &mut usize) -> f32 {
    let vt = [a, b, c];
    let dl = [a.sub(b), b.sub(c), c.sub(a)];
    let n = dl[0].cross(dl[1]);
    let l = dot_zyx(n, n);
    if l > 0.0 {
        let mut mindist = -1.0;
        let mut subw = [0.0; 4];
        let mut subm = 0;
        for i in 0..3 {
            if dot_zyx(vt[i], dl[i].cross(n)) > 0.0 {
                let j = (i + 1) % 3;
                let subd = project2(vt[i], vt[j], &mut subw, &mut subm);
                if mindist < 0.0 || subd < mindist {
                    mindist = subd;
                    *mask = if subm & 1 != 0 { 1 << i } else { 0 }
                        | if subm & 2 != 0 { 1 << j } else { 0 };
                    w[i] = subw[0];
                    w[j] = subw[1];
                    w[(j + 1) % 3] = 0.0;
                }
            }
        }
        if mindist < 0.0 {
            let d = (a.0[0] * n.0[0] + a.0[1] * n.0[1]) + n.0[2] * a.0[2];
            let p = n.scale(d / l);
            mindist = dot_zyx(p, p);
            *mask = 7;
            let s = l.sqrt();
            w[0] = dl[1].cross(b.sub(p)).length() / s;
            w[1] = dl[2].cross(c.sub(p)).length() / s;
            w[2] = 1.0 - (w[0] + w[1]);
        }
        return mindist;
    }
    -1.0
}
fn project4(a: Vec3, b: Vec3, c: Vec3, d: Vec3, w: &mut [f32; 4], mask: &mut usize) -> f32 {
    let vt = [a, b, c, d];
    let dl = [a.sub(d), b.sub(d), c.sub(d)];
    let vl = det(dl[0], dl[1], dl[2]);
    let ngc = b.sub(c).cross(a.sub(b));
    if vl * dot_zyx(a, ngc) <= 0.0 && vl.abs() > 0.0 {
        let mut mindist = -1.0;
        let mut subw = [0.0; 4];
        let mut subm = 0;
        for i in 0..3 {
            let j = (i + 1) % 3;
            let ej = dl[i].cross(dl[j]);
            if vl * d.dot(ej) > 0.0 {
                let subd = project3(vt[i], vt[j], d, &mut subw, &mut subm);
                if mindist < 0.0 || subd < mindist {
                    mindist = subd;
                    *mask = (if subm & 1 != 0 { 1 << i } else { 0 })
                        + (if subm & 2 != 0 { 1 << j } else { 0 })
                        + (if subm & 4 != 0 { 8 } else { 0 });
                    w[i] = subw[0];
                    w[j] = subw[1];
                    w[(j + 1) % 3] = 0.0;
                    w[3] = subw[2];
                }
            }
        }
        if mindist < 0.0 {
            mindist = 0.0;
            *mask = 15;
            let inv = 1.0 / vl;
            w[0] = det(c, b, d) * inv;
            w[1] = det(a, c, d) * inv;
            w[2] = det(b, a, d) * inv;
            w[3] = 1.0 - ((w[2] + w[1]) + w[0]);
        }
        return mindist;
    }
    -1.0
}
impl Gjk {
    fn new(shape: Minkowski) -> Self {
        Self {
            shape,
            store: [Vertex::ZERO; 4],
            free: [0, 1, 2, 3],
            nfree: 4,
            simplices: [Simplex::ZERO; 2],
            current: 0,
            ray: Vec3::ZERO,
        }
    }
    fn simplex(&self) -> Simplex {
        self.simplices[self.current]
    }
    fn append(&mut self, d: Vec3) {
        let s = &mut self.simplices[self.current];
        self.nfree -= 1;
        let index = self.free[self.nfree];
        s.c[s.rank] = index;
        s.p[s.rank] = 0.0;
        s.rank += 1;
        self.store[index] = self.shape.vertex(d);
    }
    fn remove(&mut self) {
        let s = &mut self.simplices[self.current];
        s.rank -= 1;
        self.free[self.nfree] = s.c[s.rank];
        self.nfree += 1;
    }
    fn evaluate(&mut self, guess: Vec3) -> GjkStatus {
        self.ray = guess;
        self.append(if guess.length2() > 0.0 {
            guess.negate()
        } else {
            Vec3([1.0, 0.0, 0.0])
        });
        self.simplices[0].p[0] = 1.0;
        self.ray = self.store[self.simplices[0].c[0]].w;
        let mut lastw = [self.ray; 4];
        let mut clastw = 0;
        let mut alpha = 0.0;
        let mut status = GjkStatus::Valid;
        let mut iterations = 0;
        loop {
            let rl = self.ray.length();
            if rl < 0.0001 {
                status = GjkStatus::Inside;
                break;
            }
            self.append(self.ray.negate());
            let cs = self.simplex();
            let w = self.store[cs.c[cs.rank - 1]].w;
            if lastw.iter().any(|&old| {
                let v = w.sub(old);
                dot_zyx(v, v) < 0.0001
            }) {
                self.remove();
                break;
            }
            clastw = (clastw + 1) & 3;
            lastw[clastw] = w;
            let omega = dot_zyx(self.ray, w) / rl;
            alpha = if omega > alpha { omega } else { alpha };
            if (rl - alpha) - (0.0001 * rl) <= 0.0 {
                self.remove();
                break;
            }
            let mut weights = [0.0; 4];
            let mut mask = 0;
            let v = cs.c.map(|i| self.store[i].w);
            let sqdist = match cs.rank {
                2 => project2(v[0], v[1], &mut weights, &mut mask),
                3 => project3(v[0], v[1], v[2], &mut weights, &mut mask),
                4 => project4(v[0], v[1], v[2], v[3], &mut weights, &mut mask),
                _ => unreachable!(),
            };
            if sqdist >= 0.0 {
                let next = 1 - self.current;
                let mut ns = Simplex::ZERO;
                self.ray = Vec3::ZERO;
                self.current = next;
                for (i, &weight) in weights.iter().enumerate().take(cs.rank) {
                    if mask & (1 << i) != 0 {
                        ns.c[ns.rank] = cs.c[i];
                        ns.p[ns.rank] = weight;
                        ns.rank += 1;
                        self.ray = self.ray.add(self.store[cs.c[i]].w.scale(weight));
                    } else {
                        self.free[self.nfree] = cs.c[i];
                        self.nfree += 1;
                    }
                }
                self.simplices[next] = ns;
                if mask == 15 {
                    status = GjkStatus::Inside;
                }
            } else {
                self.remove();
                break;
            }
            iterations += 1;
            if iterations >= 128 {
                status = GjkStatus::Failed;
            }
            if status != GjkStatus::Valid {
                break;
            }
        }
        status
    }
    fn enclose(&mut self) -> bool {
        let s = self.simplex();
        let v = s.c.map(|i| self.store[i].w);
        match s.rank {
            1 | 2 => {
                for i in 0..3 {
                    let mut axis = Vec3::ZERO;
                    axis.0[i] = 1.0;
                    let p = if s.rank == 1 {
                        axis
                    } else {
                        v[1].sub(v[0]).cross(axis)
                    };
                    if s.rank == 1 || p.length2() > 0.0 {
                        self.append(p);
                        if self.enclose() {
                            return true;
                        }
                        self.remove();
                        self.append(p.negate());
                        if self.enclose() {
                            return true;
                        }
                        self.remove();
                    }
                }
            }
            3 => {
                let n = v[1].sub(v[0]).cross(v[2].sub(v[0]));
                if n.length2() > 0.0 {
                    self.append(n);
                    if self.enclose() {
                        return true;
                    }
                    self.remove();
                    self.append(n.negate());
                    if self.enclose() {
                        return true;
                    }
                    self.remove();
                }
            }
            4 => return det(v[0].sub(v[3]), v[1].sub(v[3]), v[2].sub(v[3])).abs() > 0.0,
            _ => unreachable!(),
        }
        false
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum EpaStatus {
    Valid,
    Degenerated,
    NonConvex,
    InvalidHull,
    OutOfFaces,
    OutOfVertices,
    AccuracyReached,
    FallBack,
    Failed,
}
#[derive(Clone, Copy)]
struct Face {
    n: Vec3,
    d: f32,
    p: f32,
    c: [usize; 3],
    f: [usize; 3],
    e: [usize; 3],
    links: [Option<usize>; 2],
    pass: u8,
}
impl Face {
    const ZERO: Self = Self {
        n: Vec3::ZERO,
        d: 0.0,
        p: 0.0,
        c: [0; 3],
        f: [0; 3],
        e: [0; 3],
        links: [None; 2],
        pass: 0,
    };
}
#[derive(Clone, Copy, Default)]
struct List {
    root: Option<usize>,
    count: usize,
}
#[derive(Default)]
struct Horizon {
    cf: Option<usize>,
    ff: Option<usize>,
    nf: usize,
}
struct Epa {
    status: EpaStatus,
    vertices: [Vertex; 68],
    faces: [Face; 128],
    next: usize,
    hull: List,
    stock: List,
    result: Simplex,
    normal: Vec3,
    depth: f32,
}
fn native_min(a: f32, b: f32) -> f32 {
    if a < b {
        a
    } else {
        b
    }
}
impl Epa {
    fn new(gjk: &Gjk) -> Self {
        let mut e = Self {
            status: EpaStatus::Failed,
            vertices: [Vertex::ZERO; 68],
            faces: [Face::ZERO; 128],
            next: 0,
            hull: List::default(),
            stock: List::default(),
            result: Simplex::ZERO,
            normal: Vec3::ZERO,
            depth: 0.0,
        };
        e.vertices[..4].copy_from_slice(&gjk.store);
        for i in (0..128).rev() {
            Self::append(&mut e.faces, &mut e.stock, i);
        }
        e
    }
    fn append(faces: &mut [Face; 128], list: &mut List, f: usize) {
        faces[f].links = [None, list.root];
        if let Some(root) = list.root {
            faces[root].links[0] = Some(f);
        }
        list.root = Some(f);
        list.count += 1;
    }
    fn remove(faces: &mut [Face; 128], list: &mut List, f: usize) {
        let [prev, next] = faces[f].links;
        if let Some(next) = next {
            faces[next].links[0] = prev;
        }
        if let Some(prev) = prev {
            faces[prev].links[1] = next;
        }
        if list.root == Some(f) {
            list.root = next;
        }
        list.count -= 1;
    }
    fn bind(&mut self, a: usize, ea: usize, b: usize, eb: usize) {
        self.faces[a].e[ea] = eb;
        self.faces[a].f[ea] = b;
        self.faces[b].e[eb] = ea;
        self.faces[b].f[eb] = a;
    }
    fn newface(&mut self, a: usize, b: usize, c: usize, forced: bool) -> Option<usize> {
        if let Some(index) = self.stock.root {
            Self::remove(&mut self.faces, &mut self.stock, index);
            Self::append(&mut self.faces, &mut self.hull, index);
            let av = self.vertices[a].w;
            let bv = self.vertices[b].w;
            let cv = self.vertices[c].w;
            let face = &mut self.faces[index];
            face.pass = 0;
            face.c = [a, b, c];
            face.n = bv.sub(av).cross(cv.sub(av));
            let l = face.n.length();
            let valid = l > 0.0001;
            face.p = native_min(
                native_min(
                    av.dot(face.n.cross(av.sub(bv))),
                    bv.dot(face.n.cross(bv.sub(cv))),
                ),
                cv.dot(face.n.cross(cv.sub(av))),
            ) / if valid { l } else { 1.0 };
            if face.p >= -0.01 {
                face.p = 0.0;
            }
            if valid {
                let inv = (1.0_f64 / f64::from(l)) as f32;
                face.d =
                    ((av.0[1] * face.n.0[1] + av.0[2] * face.n.0[2]) + face.n.0[0] * av.0[0]) * inv;
                face.n = face.n.scale(inv);
                if forced || face.d >= -0.00001 {
                    return Some(index);
                }
                self.status = EpaStatus::NonConvex;
            } else {
                self.status = EpaStatus::Degenerated;
            }
            Self::remove(&mut self.faces, &mut self.hull, index);
            Self::append(&mut self.faces, &mut self.stock, index);
            None
        } else {
            self.status = EpaStatus::OutOfFaces;
            None
        }
    }
    fn best(&self) -> usize {
        let mut minf = self.hull.root.unwrap();
        let mut mind = self.faces[minf].d * self.faces[minf].d;
        let mut maxp = self.faces[minf].p;
        let mut next = self.faces[minf].links[1];
        while let Some(f) = next {
            let face = self.faces[f];
            let sqd = face.d * face.d;
            if face.p >= maxp && sqd < mind {
                minf = f;
                mind = sqd;
                maxp = face.p;
            }
            next = face.links[1];
        }
        minf
    }
    fn expand(&mut self, pass: usize, w: usize, f: usize, e: usize, horizon: &mut Horizon) -> bool {
        if usize::from(self.faces[f].pass) != pass {
            let e1 = (e + 1) % 3;
            if self.faces[f].n.dot(self.vertices[w].w) - self.faces[f].d < -0.00001 {
                if let Some(nf) = self.newface(self.faces[f].c[e1], self.faces[f].c[e], w, false) {
                    self.bind(nf, 0, f, e);
                    if let Some(cf) = horizon.cf {
                        self.bind(cf, 1, nf, 2);
                    } else {
                        horizon.ff = Some(nf);
                    }
                    horizon.cf = Some(nf);
                    horizon.nf += 1;
                    return true;
                }
            } else {
                let e2 = (e + 2) % 3;
                self.faces[f].pass = pass as u8;
                if self.expand(pass, w, self.faces[f].f[e1], self.faces[f].e[e1], horizon)
                    && self.expand(pass, w, self.faces[f].f[e2], self.faces[f].e[e2], horizon)
                {
                    Self::remove(&mut self.faces, &mut self.hull, f);
                    Self::append(&mut self.faces, &mut self.stock, f);
                    return true;
                }
            }
        }
        false
    }
    fn evaluate(&mut self, gjk: &mut Gjk, guess: Vec3) -> EpaStatus {
        if gjk.simplex().rank > 1 && gjk.enclose() {
            self.vertices[..4].copy_from_slice(&gjk.store);
            self.status = EpaStatus::Valid;
            self.next = 0;
            let mut s = gjk.simplex();
            let v = s.c.map(|i| self.vertices[i].w);
            if det(v[0].sub(v[3]), v[1].sub(v[3]), v[2].sub(v[3])) < 0.0 {
                s.c.swap(0, 1);
                s.p.swap(0, 1);
                gjk.simplices[gjk.current] = s;
            }
            let tetra = [
                self.newface(s.c[0], s.c[1], s.c[2], true),
                self.newface(s.c[1], s.c[0], s.c[3], true),
                self.newface(s.c[2], s.c[1], s.c[3], true),
                self.newface(s.c[0], s.c[2], s.c[3], true),
            ];
            if self.hull.count == 4 {
                let t = tetra.map(Option::unwrap);
                let mut best = self.best();
                let mut outer = self.faces[best];
                self.bind(t[0], 0, t[1], 0);
                self.bind(t[0], 1, t[2], 0);
                self.bind(t[0], 2, t[3], 0);
                self.bind(t[1], 1, t[3], 2);
                self.bind(t[1], 2, t[2], 1);
                self.bind(t[2], 2, t[3], 1);
                self.status = EpaStatus::Valid;
                for pass in 1..=255 {
                    if self.next < 64 {
                        let mut horizon = Horizon::default();
                        let w = 4 + self.next;
                        self.next += 1;
                        self.faces[best].pass = pass as u8;
                        self.vertices[w] = gjk.shape.vertex(self.faces[best].n);
                        let wdist =
                            dot_zyx(self.vertices[w].w, self.faces[best].n) - self.faces[best].d;
                        if wdist > 0.0001 {
                            let mut valid = true;
                            for j in 0..3 {
                                if !valid {
                                    break;
                                }
                                valid &= self.expand(
                                    pass,
                                    w,
                                    self.faces[best].f[j],
                                    self.faces[best].e[j],
                                    &mut horizon,
                                );
                            }
                            if valid && horizon.nf >= 3 {
                                self.bind(horizon.cf.unwrap(), 1, horizon.ff.unwrap(), 2);
                                Self::remove(&mut self.faces, &mut self.hull, best);
                                Self::append(&mut self.faces, &mut self.stock, best);
                                best = self.best();
                                if self.faces[best].p >= outer.p {
                                    outer = self.faces[best];
                                }
                            } else {
                                self.status = EpaStatus::InvalidHull;
                                break;
                            }
                        } else {
                            self.status = EpaStatus::AccuracyReached;
                            break;
                        }
                    } else {
                        self.status = EpaStatus::OutOfVertices;
                        break;
                    }
                }
                let projection = outer.n.scale(outer.d);
                self.normal = outer.n;
                self.depth = outer.d;
                self.result.rank = 3;
                self.result.c[..3].copy_from_slice(&outer.c);
                for i in 0..3 {
                    self.result.p[i] = self.vertices[outer.c[(i + 1) % 3]]
                        .w
                        .sub(projection)
                        .cross(self.vertices[outer.c[(i + 2) % 3]].w.sub(projection))
                        .length();
                }
                let sum = (self.result.p[2] + self.result.p[1]) + self.result.p[0];
                let inv = (1.0_f64 / f64::from(sum)) as f32;
                #[allow(clippy::assign_op_pattern)]
                // Preserve the native operand order, including raw NaNs.
                for i in 0..3 {
                    self.result.p[i] = inv * self.result.p[i];
                }
                return self.status;
            }
        }
        self.vertices[..4].copy_from_slice(&gjk.store);
        self.status = EpaStatus::FallBack;
        self.normal = guess.negate();
        let nl = self.normal.length();
        self.normal = if nl > 0.0 {
            self.normal.scale(1.0 / nl)
        } else {
            Vec3([1.0, 0.0, 0.0])
        };
        self.depth = 0.0;
        self.result.rank = 1;
        self.result.c[0] = gjk.simplex().c[0];
        self.result.p[0] = 1.0;
        self.status
    }
}

/// Distance excludes margins, matching btGjkEpaSolver2::Distance.
/// Both shapes must be convex. Dimensions are passed through like the native API.
pub fn distance(shapes: [Shape; 2], transforms: [Transform; 2], guess: Vec3) -> QueryResult {
    let shape = Minkowski::new(shapes, transforms, false);
    let mut gjk = Gjk::new(shape);
    match gjk.evaluate(guess) {
        GjkStatus::Valid => {
            let s = gjk.simplex();
            let mut w0 = Vec3::ZERO;
            let mut w1 = Vec3::ZERO;
            for i in 0..s.rank {
                let d = gjk.store[s.c[i]].d;
                w0 = w0.add(shape.support0(d).scale(s.p[i]));
                w1 = w1.add(shape.support1(d.negate()).scale(s.p[i]));
            }
            let normal = w0.sub(w1);
            let distance = normal.length();
            QueryResult::Success(Solution {
                witnesses: [transforms[0].apply(w0), transforms[0].apply(w1)],
                normal: normal.scale(1.0 / if distance > 0.0001 { distance } else { 1.0 }),
                distance,
            })
        }
        GjkStatus::Inside => QueryResult::Failure(Status::Penetrating),
        GjkStatus::Failed => QueryResult::Failure(Status::GjkFailed),
    }
}

pub fn penetration(
    shapes: [Shape; 2],
    transforms: [Transform; 2],
    guess: Vec3,
    use_margins: bool,
) -> QueryResult {
    let shape = Minkowski::new(shapes, transforms, use_margins);
    let mut gjk = Gjk::new(shape);
    match gjk.evaluate(guess.negate()) {
        GjkStatus::Inside => {
            let mut epa = Epa::new(&gjk);
            if epa.evaluate(&mut gjk, guess.negate()) == EpaStatus::Failed {
                return QueryResult::Failure(Status::EpaFailed);
            }
            let mut w0 = Vec3::ZERO;
            for i in 0..epa.result.rank {
                w0 = w0.add(
                    shape
                        .support0(epa.vertices[epa.result.c[i]].d)
                        .scale(epa.result.p[i]),
                );
            }
            let w1 = w0.sub(epa.normal.scale(epa.depth));
            let b = transforms[0].basis.0;
            let o = transforms[0].origin;
            let a = Vec3(std::array::from_fn(|i| {
                if i == 0 {
                    ((b[i][2] * w0.0[2] + b[i][0] * w0.0[0]) + b[i][1] * w0.0[1]) + o.0[i]
                } else {
                    ((b[i][1] * w0.0[1] + b[i][2] * w0.0[2]) + b[i][0] * w0.0[0]) + o.0[i]
                }
            }));
            let c = Vec3(std::array::from_fn(|i| {
                ((b[i][2] * w1.0[2] + b[i][1] * w1.0[1]) + b[i][0] * w1.0[0]) + o.0[i]
            }));
            QueryResult::Success(Solution {
                witnesses: [a, c],
                normal: epa.normal.negate(),
                distance: -epa.depth,
            })
        }
        GjkStatus::Valid => QueryResult::Failure(Status::Separated),
        GjkStatus::Failed => QueryResult::Failure(Status::GjkFailed),
    }
}

/// The native adapter writes outputs for penetration and distance fallback only.
pub fn calc_pen_depth(shapes: [Shape; 2], transforms: [Transform; 2]) -> PenDepth {
    let guess = transforms[0].origin.sub(transforms[1].origin);
    if let QueryResult::Success(solution) = penetration(shapes, transforms, guess, true) {
        PenDepth::Penetrating(solution)
    } else if let QueryResult::Success(solution) = distance(shapes, transforms, guess) {
        PenDepth::Separated(solution)
    } else {
        PenDepth::Failed
    }
}
