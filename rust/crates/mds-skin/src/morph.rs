//! The material part of `ModelApplyMorphs` (`src/model/morph_apply.cpp`):
//! the additive and multiplicative pools, then the composed materials.

use crate::{Channels, MaterialOffset, Skin};

/// Every channel of `a` with the matching channel of `b`, in a fixed order.
fn zip(a: &mut Channels, b: &Channels, f: impl Fn(&mut f32, f32)) {
    let pairs = a
        .diffuse
        .iter_mut()
        .zip(b.diffuse)
        .chain(a.specular.iter_mut().zip(b.specular))
        .chain([(&mut a.specular_power, b.specular_power)])
        .chain(a.ambient.iter_mut().zip(b.ambient))
        .chain(a.edge_color.iter_mut().zip(b.edge_color))
        .chain([(&mut a.edge_size, b.edge_size)])
        .chain(a.texture_tint.iter_mut().zip(b.texture_tint))
        .chain(a.sphere_tint.iter_mut().zip(b.sphere_tint))
        .chain(a.toon_tint.iter_mut().zip(b.toon_tint));
    for (x, y) in pairs {
        f(x, y);
    }
}

fn apply_entry(add: &mut Channels, mul: &mut Channels, e: &MaterialOffset, w: f32) {
    if e.additive {
        zip(add, &e.channels, |a, d| *a += d * w);
    } else {
        zip(mul, &e.channels, |m, d| *m *= 1.0 - (1.0 - d) * w);
    }
}

impl Skin {
    /// `ModelApplyMorphs` without its bone morphs: resets the pools, adds
    /// every material morph with a nonzero weight (directly or through a
    /// group, as `weight * group weight`) and writes `mul * base + add` into
    /// the materials. Does nothing for a PMD model.
    pub fn apply_morphs(&mut self, weights: &[f32]) {
        assert_eq!(weights.len(), self.morphs.len(), "one weight per morph");
        if !self.is_pmx() {
            return;
        }
        let ones = Channels {
            diffuse: [1.0; 4],
            specular: [1.0; 3],
            specular_power: 1.0,
            ambient: [1.0; 3],
            edge_color: [1.0; 4],
            edge_size: 1.0,
            texture_tint: [1.0; 4],
            sphere_tint: [1.0; 4],
            toon_tint: [1.0; 4],
        };
        self.material_add.fill(Channels::default());
        self.material_mul.fill(ones);
        let (add, mul) = (&mut self.material_add, &mut self.material_mul);
        let mut accumulate = |entries: &[MaterialOffset], w: f32| {
            for e in entries {
                match e.material {
                    Some(i) => apply_entry(&mut add[i], &mut mul[i], e, w),
                    None => {
                        for (a, m) in add.iter_mut().zip(mul.iter_mut()) {
                            apply_entry(a, m, e, w);
                        }
                    }
                }
            }
        };
        for (morph, &w) in self.morphs.iter().zip(weights) {
            if w == 0.0 {
                continue;
            }
            match morph.kind {
                8 => accumulate(&morph.material, w),
                0 => {
                    for &(target, group_w) in &morph.group {
                        let target = &self.morphs[target];
                        if target.kind == 8 {
                            accumulate(&target.material, w * group_w);
                        }
                    }
                }
                _ => {}
            }
        }
        for (((mat, base), add), mul) in self
            .materials
            .iter_mut()
            .zip(&self.material_base)
            .zip(&self.material_add)
            .zip(&self.material_mul)
        {
            let f = |m: f32, b: f32, a: f32| m * b + a;
            for c in 0..3 {
                mat.diffuse_mirror[c] = f(mul.diffuse[c], base.diffuse[c], add.diffuse[c]);
                mat.specular[c] = f(mul.specular[c], base.specular[c], add.specular[c]);
                mat.ambient[c] = f(mul.ambient[c], base.ambient[c], add.ambient[c]);
                mat.edge_color[c] = f(mul.edge_color[c], base.edge_color[c], add.edge_color[c]);
            }
            mat.diffuse[3] = f(mul.diffuse[3], base.diffuse[3], add.diffuse[3]);
            mat.specular_power = f(mul.specular_power, base.specular_power, add.specular_power);
            mat.edge_color[3] = f(mul.edge_color[3], base.edge_color[3], add.edge_color[3]);
            mat.edge_size = f(mul.edge_size, base.edge_size, add.edge_size);
        }
    }
}
