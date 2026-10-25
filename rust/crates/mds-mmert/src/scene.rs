//! Offscreen turns: which effect draws each object into an `OFFSCREENRENDERTARGET`, from the
//! target's `DefaultEffect` rows. Ported from `third_party/mmeffect/src/mmeffect/`
//! `material_bind.cpp` (`MmeWildcardMatch`, `MmeFindDefaultEffectRow`, `MmeOffscreenObjectShown`,
//! `MmeResolveTurnEffectBinding`) and `callbacks.cpp` (the offscreen draw gate: a model with no
//! row is not drawn, a `none` row is the host's own draw, scene carriers never draw as objects).
//!
//! The per-object overrides of the MME dialog (`effectOverrides`, `shownOverrides`) are not
//! modelled: every turn resolves from the annotation rows.

use std::path::PathBuf;

use mds_mme::sas::Resource;

use crate::emm::Assignment;

/// What one object, or one material subset of it, draws in an offscreen turn.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum TurnDraw {
    /// Not drawn.
    Hide,
    /// Drawn by the host with its standard shading (`none`, or `main_default` of an object with
    /// no effect): the renderer's draw, not an effect's.
    Host,
    /// Drawn with this effect file.
    Effect(PathBuf),
}

/// An object of the scene as an offscreen turn sees it.
pub struct TurnObject<'a> {
    /// The file name with its extension (`ModelData::name`), which the rows glob against.
    pub name: &'a str,
    /// The object the effect declaring the target is assigned to (`self`).
    pub owner: bool,
    /// `ModelData::renderClass`: 0 an ordinary object, otherwise a scene effect carrier.
    pub render_class: i32,
    /// The object's main assignment, for `main_default` rows.
    pub main: &'a Assignment,
}

/// `MmeWildcardMatch` with `ignoreCase` set, over bytes: `?` one byte, `*` any run, `\` escapes.
pub fn wildcard(name: &[u8], pat: &[u8]) -> bool {
    if pat.is_empty() {
        return name.is_empty();
    }
    let (mut n, mut p) = (0, 0);
    loop {
        let pc = pat[p];
        if n == name.len() {
            return pc == b'*' && star(&name[n..], &pat[p..]);
        }
        if pc == b'*' {
            return star(&name[n..], &pat[p..]);
        }
        if pc == b'?' {
            p += 1;
        } else {
            if pc == b'\\' {
                p += 1;
                if p == pat.len() {
                    return false;
                }
            }
            if !name[n].eq_ignore_ascii_case(&pat[p]) {
                return false;
            }
            p += 1;
        }
        n += 1;
        if p == pat.len() {
            return n == name.len();
        }
    }
}

/// The `star:` tail of `MmeWildcardMatch`; `pat` starts at a `*`.
fn star(name: &[u8], pat: &[u8]) -> bool {
    let p = pat.iter().position(|&c| c != b'*').unwrap_or(pat.len());
    if p == pat.len() {
        return true;
    }
    let first = pat[p].to_ascii_lowercase();
    let mut n = 0;
    loop {
        if first != b'?' && first != b'\\' {
            while n < name.len() && first != name[n] && first != name[n].to_ascii_lowercase() {
                n += 1;
            }
        }
        if wildcard(&name[n..], &pat[p..]) {
            return true;
        }
        if n == name.len() {
            return false;
        }
        n += 1;
    }
}

/// `MmeFindDefaultEffectRow`: the first row whose key matches. `self` is the exact keyword and
/// matches only the owner; every other key globs against the file name.
pub fn find_row(resource: &Resource, obj: &TurnObject) -> Option<usize> {
    resource.default_effect.iter().position(|(key, _)| {
        if key == "self" {
            obj.owner
        } else {
            !key.is_empty() && wildcard(obj.name.as_bytes(), key.as_bytes())
        }
    })
}

/// What `obj` draws into `resource` in its turn; `subset` is the material being drawn.
pub fn turn_draw(resource: &Resource, obj: &TurnObject, subset: Option<i32>) -> TurnDraw {
    if obj.render_class != 0 {
        return TurnDraw::Hide;
    }
    let Some(row) = find_row(resource, obj) else {
        return TurnDraw::Hide;
    };
    match resource.default_effect[row].1.as_str() {
        "hide" => TurnDraw::Hide,
        "none" => TurnDraw::Host,
        "main_default" => {
            let main = obj.main;
            if !subset.map_or(main.shown, |s| main.subset_shown(s)) {
                return TurnDraw::Hide;
            }
            let path = subset
                .and_then(|s| main.subsets.get(&s))
                .unwrap_or(&main.effect);
            if path.is_empty() {
                TurnDraw::Host
            } else {
                TurnDraw::Effect(PathBuf::from(path))
            }
        }
        _ => resource.default_effect_files[row]
            .clone()
            .map_or(TurnDraw::Host, TurnDraw::Effect),
    }
}

#[cfg(test)]
mod tests {
    use super::wildcard;

    #[test]
    fn globs_follow_the_cpp_matcher() {
        let m = |n: &str, p: &str| wildcard(n.as_bytes(), p.as_bytes());
        assert!(m("SkyBox_Night.PMX", "sky*box*.*"));
        assert!(m("a.pmx", "*.PMX") && m("a.pmx", "?.pmx") && m("", "*"));
        assert!(!m("ab.pmx", "?.pmx") && !m("a.pmx", "") && !m("a.pmx", "a.pm"));
        assert!(m("a*b.x", "a\\*b.x") && !m("aZb.x", "a\\*b.x") && !m("a", "a\\"));
        assert!(m("GroundFog01.x", "GroundFog*.*") && !m("Ground.x", "GroundFog*"));
    }
}
