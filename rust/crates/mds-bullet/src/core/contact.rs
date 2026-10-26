//! Altered Rust translation of Bullet 2.75 narrowphase and persistent manifold.
//! Includes the vendored MMD local-coordinate patches. See mod.rs for zlib notice.

use super::math::{Basis, Quat, Transform, Vec3};
use super::shape::Shape;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PairKind {
    SphereSphere,
    /// Manifold body A is the convex input and body B is the plane input.
    ConvexPlane {
        swapped: bool,
    },
}

#[derive(Clone, Copy, Debug)]
pub struct ContactBody {
    pub world: Transform,
    pub friction: f32,
    pub restitution: f32,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct ContactPoint {
    pub local_a: Vec3,
    pub local_b: Vec3,
    pub world_a: Vec3,
    pub world_b: Vec3,
    pub normal_on_b: Vec3,
    pub distance: f32,
    pub combined_friction: f32,
    pub combined_restitution: f32,
    pub applied_impulse: f32,
    pub lateral_impulses: [f32; 2],
    pub lifetime: i32,
}

impl ContactPoint {
    const EMPTY: Self = Self {
        local_a: Vec3::ZERO,
        local_b: Vec3::ZERO,
        world_a: Vec3::ZERO,
        world_b: Vec3::ZERO,
        normal_on_b: Vec3::ZERO,
        distance: 0.0,
        combined_friction: 0.0,
        combined_restitution: 0.0,
        applied_impulse: 0.0,
        lateral_impulses: [0.0; 2],
        lifetime: 0,
    };
}

pub struct PairManifold {
    shapes: [Shape; 2],
    kind: PairKind,
    threshold: f32,
    points: [ContactPoint; 4],
    count: usize,
}

impl PairManifold {
    pub fn new(shape0: Shape, shape1: Shape) -> Option<Self> {
        use Shape::*;
        let kind = match (shape0, shape1) {
            (Sphere { .. }, Sphere { .. }) => PairKind::SphereSphere,
            (Sphere { .. } | Box { .. } | CapsuleY { .. }, StaticPlane { .. }) => {
                PairKind::ConvexPlane { swapped: false }
            }
            (StaticPlane { .. }, Sphere { .. } | Box { .. } | CapsuleY { .. }) => {
                PairKind::ConvexPlane { swapped: true }
            }
            _ => return None,
        };
        let a = shape0.angular_motion_disc() * 0.02;
        let b = shape1.angular_motion_disc() * 0.02;
        Some(Self {
            shapes: [shape0, shape1],
            kind,
            threshold: if a < b { a } else { b },
            points: [ContactPoint::EMPTY; 4],
            count: 0,
        })
    }

    pub fn kind(&self) -> PairKind {
        self.kind
    }
    pub fn shapes(&self) -> &[Shape; 2] {
        &self.shapes
    }
    pub fn contact_breaking_threshold(&self) -> f32 {
        self.threshold
    }
    pub fn contacts(&self) -> &[ContactPoint] {
        &self.points[..self.count]
    }

    pub fn process(&mut self, body0: ContactBody, body1: ContactBody) {
        let bodies = [body0, body1];
        match self.kind {
            PairKind::SphereSphere => {
                let Shape::Sphere { radius: a } = self.shapes[0] else {
                    unreachable!()
                };
                let Shape::Sphere { radius: b } = self.shapes[1] else {
                    unreachable!()
                };
                let diff = body0.world.origin.sub(body1.world.origin);
                let length = diff.length();
                if !(length > a + b) {
                    let normal = if length > f32::EPSILON {
                        diff.scale(1.0 / length)
                    } else {
                        Vec3([1.0, 0.0, 0.0])
                    };
                    self.add_contact(
                        normal,
                        body1.world.origin.add(normal.scale(b)),
                        length - (a + b),
                        bodies,
                    );
                }
                self.refresh(body0.world, body1.world);
            }
            PairKind::ConvexPlane { swapped } => {
                self.plane_contact(Quat::IDENTITY, bodies, swapped);
                let convex = usize::from(swapped);
                let plane = 1 - convex;
                if self.count < 1 {
                    let Shape::StaticPlane { normal, .. } = self.shapes[plane] else {
                        unreachable!()
                    };
                    let axis = plane_space(normal);
                    let mut angle = 0.02 / self.shapes[convex].angular_motion_disc();
                    let limit = 0.125 * std::f32::consts::PI;
                    if angle > limit {
                        angle = limit;
                    }
                    let perturb = Quat::from_axis_angle(axis, angle);
                    let rotation =
                        Quat::from_axis_angle(normal, 0.0 * (2.0 * std::f32::consts::PI));
                    self.plane_contact(
                        rotation.inverse().multiply(perturb).multiply(rotation),
                        bodies,
                        swapped,
                    );
                }
                if self.count != 0 {
                    self.refresh(bodies[convex].world, bodies[plane].world);
                }
            }
        }
    }

    fn plane_contact(&mut self, perturb: Quat, bodies: [ContactBody; 2], swapped: bool) {
        let convex = usize::from(swapped);
        let plane = 1 - convex;
        let Shape::StaticPlane { normal, constant } = self.shapes[plane] else {
            unreachable!()
        };
        let original = bodies[convex].world;
        let plane_world = bodies[plane].world;
        let convex_in_plane = plane_world.inverse().multiply(original);
        let perturbed = Transform {
            basis: original.basis.multiply(Basis::from_rotation(perturb)),
            ..original
        };
        let plane_in_convex = perturbed.inverse().multiply(plane_world);
        let support = self.shapes[convex]
            .supporting_vertex(plane_in_convex.basis.apply(normal.negate()))
            .unwrap();
        let vertex = convex_in_plane.apply(support);
        let distance = normal.dot(vertex) - constant;
        let projected = vertex.sub(normal.scale(distance));
        if distance < self.threshold {
            self.add_contact(
                plane_world.basis.apply(normal),
                plane_world.apply(projected),
                distance,
                bodies,
            );
        }
    }

    fn add_contact(
        &mut self,
        normal: Vec3,
        world_b: Vec3,
        distance: f32,
        bodies: [ContactBody; 2],
    ) {
        if distance > self.threshold {
            return;
        }
        let swapped = matches!(self.kind, PairKind::ConvexPlane { swapped: true });
        let world_a = world_b.add(normal.scale(distance));
        let (local_a, local_b) = if swapped {
            (
                local_point(bodies[1].world, world_a, [2, 1, 1]),
                local_point(bodies[0].world, world_b, [0, 0, 0]),
            )
        } else {
            (
                local_point(bodies[0].world, world_a, [0, 0, 0]),
                local_point(bodies[1].world, world_b, [1, 0, 0]),
            )
        };
        let mut friction = bodies[0].friction * bodies[1].friction;
        if friction < -10.0 {
            friction = -10.0;
        }
        if friction > 10.0 {
            friction = 10.0;
        }
        self.insert(ContactPoint {
            local_a,
            local_b,
            world_a,
            world_b,
            normal_on_b: normal,
            distance,
            combined_friction: friction,
            combined_restitution: bodies[0].restitution * bodies[1].restitution,
            ..ContactPoint::EMPTY
        });
    }

    fn nearest(&self, point: ContactPoint) -> Option<usize> {
        let mut shortest = self.threshold * self.threshold;
        let mut nearest = None;
        for (i, old) in self.contacts().iter().enumerate() {
            let distance = old.local_a.sub(point.local_a).length2();
            if distance < shortest {
                shortest = distance;
                nearest = Some(i);
            }
        }
        nearest
    }

    fn replacement(&self, point: ContactPoint) -> usize {
        let mut deepest = None;
        let mut distance = point.distance;
        for (i, old) in self.points.iter().enumerate() {
            if old.distance < distance {
                distance = old.distance;
                deepest = Some(i);
            }
        }
        let mut area = [0.0; 4];
        for (i, (a, b, c)) in [(1, 3, 2), (0, 3, 2), (0, 3, 1), (0, 2, 1)]
            .into_iter()
            .enumerate()
        {
            if deepest != Some(i) {
                area[i] = point
                    .local_a
                    .sub(self.points[a].local_a)
                    .cross(self.points[b].local_a.sub(self.points[c].local_a))
                    .length2();
            }
        }
        let mut index = 0;
        let mut maximum = -1e18;
        for (i, value) in area.into_iter().enumerate() {
            if value.abs() > maximum {
                maximum = value.abs();
                index = i;
            }
        }
        index
    }

    fn insert(&mut self, mut point: ContactPoint) {
        let index = if let Some(index) = self.nearest(point) {
            let old = self.points[index];
            point.lifetime = old.lifetime;
            point.applied_impulse = old.applied_impulse;
            point.lateral_impulses = old.lateral_impulses;
            index
        } else if self.count == 4 {
            self.replacement(point)
        } else {
            self.count += 1;
            self.count - 1
        };
        self.points[index] = point;
    }

    fn remove(&mut self, index: usize) {
        self.count -= 1;
        if index != self.count {
            self.points[index] = self.points[self.count];
        }
    }

    fn refresh(&mut self, a: Transform, b: Transform) {
        for point in self.points[..self.count].iter_mut().rev() {
            point.world_a = a.apply(point.local_a);
            point.world_b = b.apply(point.local_b);
            point.distance = point.world_a.sub(point.world_b).dot(point.normal_on_b);
            point.lifetime += 1;
        }
        for i in (0..self.count).rev() {
            let point = self.points[i];
            if !(point.distance <= self.threshold) {
                self.remove(i);
            } else {
                let projected = point.world_a.sub(point.normal_on_b.scale(point.distance));
                if point.world_b.sub(projected).length2() > self.threshold * self.threshold {
                    self.remove(i);
                }
            }
        }
    }
}

fn local_point(transform: Transform, point: Vec3, order: [u8; 3]) -> Vec3 {
    let value = point.sub(transform.origin).0;
    Vec3(std::array::from_fn(|i| {
        let [x, y, z] = std::array::from_fn(|j| transform.basis.0[j][i] * value[j]);
        match order[i] {
            1 => (x + z) + y,
            2 => (y + z) + x,
            _ => (z + y) + x,
        }
    }))
}

fn plane_space(n: Vec3) -> Vec3 {
    let [x, y, z] = n.0;
    if z.abs() > std::f32::consts::FRAC_1_SQRT_2 {
        let k = 1.0 / (y * y + z * z).sqrt();
        Vec3([0.0, -z * k, y * k])
    } else {
        let k = 1.0 / (x * x + y * y).sqrt();
        Vec3([-y * k, x * k, 0.0])
    }
}

#[cfg(test)]
#[path = "../../tests/pure_bullet/contacts.rs"]
mod tests;
