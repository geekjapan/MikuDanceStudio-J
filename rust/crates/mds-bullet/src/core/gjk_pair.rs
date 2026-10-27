//! Altered Rust translation of btGjkPairDetector.cpp. See mod.rs for license.
use super::gjk_epa::{calc_pen_depth, PenDepth};
use super::math::{Basis, Transform, Vec3};
use super::shape::Shape;
use super::simplex::VoronoiSimplexSolver;

#[derive(Clone, Copy, Debug)]
pub struct Contact {
    pub normal_on_b: Vec3,
    pub point_on_b: Vec3,
    pub distance: f32,
}

#[derive(Clone, Copy, Debug)]
pub struct Query {
    pub contact: Option<Contact>,
    pub cached_axis: Vec3,
    pub cached_distance: f32,
    pub iterations: i32,
    pub degeneracy: i32,
    pub method: i32,
}

fn support_world(b: Basis, p: Vec3, origin: Vec3) -> Vec3 {
    Vec3(std::array::from_fn(|i| {
        ((b.0[i][1] * p.0[1] + b.0[i][2] * p.0[2]) + b.0[i][0] * p.0[0]) + origin.0[i]
    }))
}
fn length_zyx(v: Vec3) -> f32 {
    (v.0[2] * v.0[2] + v.0[1] * v.0[1]) + v.0[0] * v.0[0]
}

/// Uses the configuration-owned simplex, including witnesses retained by reset.
pub fn closest_points(
    shapes: [Shape; 2],
    mut transforms: [Transform; 2],
    maximum_distance_squared: f32,
    simplex: &mut VoronoiSimplexSolver,
) -> Query {
    let offset = transforms[0].origin.add(transforms[1].origin).scale(0.5);
    for transform in &mut transforms {
        transform.origin = transform.origin.sub(offset);
    }
    let [margin_a, margin_b] = shapes.map(Shape::margin);
    let margin = margin_a + margin_b;
    let mut query = Query {
        contact: None,
        cached_axis: Vec3([0.0, 1.0, 0.0]),
        cached_distance: 0.0,
        iterations: 0,
        degeneracy: 0,
        method: -1,
    };
    let mut squared_distance = 1e18;
    let mut check_simplex = false;
    simplex.reset();
    loop {
        let [x, y, z] = query.cached_axis.0;
        let a = transforms[0].basis.0;
        let b = transforms[1].basis.0;
        let da = Vec3([
            (a[0][0] * -x + a[2][0] * -z) + a[1][0] * -y,
            (a[0][1] * -x + a[1][1] * -y) + a[2][1] * -z,
            (a[2][2] * -z + a[0][2] * -x) + a[1][2] * -y,
        ]);
        let db = Vec3([
            (b[2][0] * z + b[0][0] * x) + b[1][0] * y,
            (b[1][1] * y + b[2][1] * z) + b[0][1] * x,
            (b[1][2] * y + b[2][2] * z) + b[0][2] * x,
        ]);
        let p = support_world(
            transforms[0].basis,
            shapes[0]
                .supporting_vertex_without_margin_nonvirtual(da)
                .expect("convex shape"),
            transforms[0].origin,
        );
        let q = support_world(
            transforms[1].basis,
            shapes[1]
                .supporting_vertex_without_margin_nonvirtual(db)
                .expect("convex shape"),
            transforms[1].origin,
        );
        let w = p.sub(q);
        let delta = (z * w.0[2] + y * w.0[1]) + x * w.0[0];
        if delta > 0.0 && delta * delta > squared_distance * maximum_distance_squared {
            check_simplex = true;
            break;
        }
        if simplex.in_simplex(w) {
            query.degeneracy = 1;
            check_simplex = true;
            break;
        }
        let f0 = squared_distance - delta;
        if f0 <= squared_distance * 1e-6 {
            query.degeneracy = if f0 <= 0.0 { 2 } else { 11 };
            check_simplex = true;
            break;
        }
        simplex.add_vertex(w, p, q);
        let mut axis = Vec3::ZERO;
        if !simplex.closest(&mut axis) {
            query.degeneracy = 3;
            check_simplex = true;
            break;
        }
        let new_distance = axis.length2();
        if new_distance < 1e-6 {
            query.cached_axis = axis;
            query.degeneracy = 6;
            check_simplex = true;
            break;
        }
        let previous = squared_distance;
        squared_distance = new_distance;
        if squared_distance > previous {
            query.degeneracy = 7;
            break;
        }
        query.cached_axis = axis;
        if previous - squared_distance <= f32::EPSILON * previous {
            query.cached_axis = simplex.backup_closest();
            query.degeneracy = 12;
            check_simplex = true;
            break;
        }
        let iteration = query.iterations;
        query.iterations += 1;
        if iteration > 1000 {
            break;
        }
        if simplex.full_simplex() {
            query.cached_axis = simplex.backup_closest();
            break;
        }
    }
    let mut contact = None;
    let mut distance = 0.0;
    if check_simplex {
        let (p, mut q) = simplex.compute_points();
        let len2 = query.cached_axis.length2();
        if (len2 as f64) < 0.0001 {
            query.degeneracy = 5;
        }
        if len2 > f32::EPSILON * f32::EPSILON {
            let rlen = 1.0 / len2.sqrt();
            let normal = p.sub(q).scale(rlen);
            q = q.add(
                query
                    .cached_axis
                    .scale((1.0 / squared_distance.sqrt()) * margin_b),
            );
            distance = (1.0 / rlen) - margin;
            contact = Some(Contact {
                normal_on_b: normal,
                point_on_b: q,
                distance,
            });
            query.method = 1;
        } else {
            query.method = 2;
        }
    }
    if contact.is_none() || (query.degeneracy != 0 && f64::from(distance + margin) < 0.01) {
        query.cached_axis = Vec3::ZERO;
        match calc_pen_depth(shapes, transforms) {
            PenDepth::Penetrating(solution) => {
                query.cached_axis = solution.normal;
                let [p, q] = solution.witnesses;
                let mut normal = q.sub(p);
                let mut len2 = length_zyx(normal);
                if len2 <= f32::EPSILON * f32::EPSILON {
                    normal = query.cached_axis;
                    len2 = normal.length2();
                }
                if len2 > f32::EPSILON * f32::EPSILON {
                    normal = normal.scale(1.0 / len2.sqrt());
                    let depth = -length_zyx(p.sub(q)).sqrt();
                    if contact.is_none() || depth < distance {
                        contact = Some(Contact {
                            normal_on_b: normal,
                            point_on_b: q,
                            distance: depth,
                        });
                        query.method = 3;
                    } else {
                        query.method = 8;
                    }
                } else {
                    query.method = 9;
                }
            }
            PenDepth::Separated(solution) => {
                query.cached_axis = solution.normal;
                if query.cached_axis.length2() > 0.0 {
                    let [p, q] = solution.witnesses;
                    let depth = length_zyx(p.sub(q)).sqrt() - margin;
                    if contact.is_none() || depth < distance {
                        contact = Some(Contact {
                            normal_on_b: query.cached_axis,
                            point_on_b: q.add(query.cached_axis.scale(margin_b)),
                            distance: depth,
                        });
                        query.method = 6;
                    } else {
                        query.method = 5;
                    }
                }
            }
            PenDepth::Failed => {}
        }
    }
    if let Some(mut point) = contact {
        query.cached_axis = point.normal_on_b;
        query.cached_distance = point.distance;
        point.point_on_b = point.point_on_b.add(offset);
        query.contact = Some(point);
    }
    query
}
