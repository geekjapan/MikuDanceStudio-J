//! Offscreen turns: which effect draws each object into an `OFFSCREENRENDERTARGET`, from the
//! target's `DefaultEffect` rows and the mapping dialog's overrides. Ported from
//! `third_party/mmeffect/src/mmeffect/` `material_bind.cpp` (`MmeWildcardMatch`,
//! `MmeFindDefaultEffectRow`, `MmeOffscreenEffectValue`, `MmeOffscreenObjectShown`,
//! `MmeResolveTurnEffectBinding`) and `callbacks.cpp` (the offscreen draw gate: a hidden object
//! and one with no row are not drawn, a `none` row is the host's own draw, scene carriers never
//! draw as objects).

use std::collections::BTreeMap;
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

/// The mapping dialog's edits of one object in one offscreen target, by subset (`-1` the whole
/// object): `SasResource::effectOverrides` (a path, `none`, `hide` or `main_default`) and
/// `shownOverrides` (`mme_dlg.cpp:357`, `:741`).
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Overrides {
    pub effects: BTreeMap<i32, String>,
    pub shown: BTreeMap<i32, bool>,
}

/// The dialog's overrides of every offscreen target: by the file of the effect that declares the
/// target and the target's name, then by object (an index into the scene's objects).
pub type Offscreen = BTreeMap<(PathBuf, String), BTreeMap<usize, Overrides>>;

/// No overrides.
pub static NO_OVERRIDES: Overrides = Overrides {
    effects: BTreeMap::new(),
    shown: BTreeMap::new(),
};

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
    /// The dialog's overrides of the object in this target.
    pub overrides: &'a Overrides,
    /// The file of an effect path as an assignment or an override stores it.
    pub resolve: &'a dyn Fn(&str) -> PathBuf,
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
pub fn find_row(rows: &[(String, String)], obj: &TurnObject) -> Option<usize> {
    rows.iter().position(|(key, _)| {
        if key == "self" {
            obj.owner
        } else {
            !key.is_empty() && wildcard(obj.name.as_bytes(), key.as_bytes())
        }
    })
}

/// Where a value comes from: an override, or the row at this index.
enum Value<'a> {
    Override(&'a str),
    Row(usize),
}

impl Value<'_> {
    fn text<'a>(&'a self, rows: &'a [(String, String)]) -> &'a str {
        match self {
            Value::Override(v) => v,
            Value::Row(i) => &rows[*i].1,
        }
    }
}

/// `MmeOffscreenEffectValue`: the override of the subset, else of the whole object, else the
/// first matching row.
fn value<'a>(rows: &[(String, String)], obj: &'a TurnObject, subset: i32) -> Option<Value<'a>> {
    let e = &obj.overrides.effects;
    match e
        .get(&subset)
        .or_else(|| (subset >= 0).then(|| e.get(&-1)).flatten())
    {
        Some(v) => Some(Value::Override(v)),
        None => find_row(rows, obj).map(Value::Row),
    }
}

/// `MmeOffscreenObjectShown` over a target's `DefaultEffect` rows: the shown override of the
/// subset, else of the whole object; a carrier is hidden, `main_default` follows the main
/// assignment, `hide` hides.
pub fn shown(rows: &[(String, String)], obj: &TurnObject, subset: i32) -> bool {
    let s = &obj.overrides.shown;
    if let Some(&v) = s
        .get(&subset)
        .or_else(|| (subset >= 0).then(|| s.get(&-1)).flatten())
    {
        return v;
    }
    if obj.render_class != 0 {
        return false;
    }
    match value(rows, obj, subset).as_ref().map(|v| v.text(rows)) {
        Some("main_default") => obj.main.subset_shown(subset),
        v => v != Some("hide"),
    }
}

/// What a row of an offscreen tab of the mapping dialog shows for an object or a subset.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum RowText<'a> {
    /// `(hide)`.
    Hide,
    /// `(none)`: no value, `none` or `hide`.
    None,
    /// `main_default`: the row text of the main tab.
    MainDefault,
    Effect(&'a str),
}

/// `DlgOffscreenRowText` (`mme_dlg.cpp:383`) over a target's `DefaultEffect` rows.
pub fn row_text<'a>(rows: &'a [(String, String)], obj: &'a TurnObject, subset: i32) -> RowText<'a> {
    if !shown(rows, obj, subset) {
        return RowText::Hide;
    }
    let text = value(rows, obj, subset).map(|v| match v {
        Value::Override(t) => t,
        Value::Row(i) => &rows[i].1,
    });
    match text {
        None | Some("none" | "hide") => RowText::None,
        Some("main_default") => RowText::MainDefault,
        Some(t) => RowText::Effect(t),
    }
}

/// What `obj` draws into `resource` in its turn; `subset` is the material being drawn (`None`
/// the whole object). The gate of `callbacks.cpp:174` and `:223`, then
/// `MmeResolveTurnEffectBinding`, whose null binding is the host's draw.
pub fn turn_draw(resource: &Resource, obj: &TurnObject, subset: Option<i32>) -> TurnDraw {
    let s = subset.unwrap_or(-1);
    let rows = &resource.default_effect;
    if obj.render_class != 0 || !shown(rows, obj, s) || value(rows, obj, s).is_none() {
        return TurnDraw::Hide;
    }
    resolve(resource, obj, s)
}

fn resolve(resource: &Resource, obj: &TurnObject, subset: i32) -> TurnDraw {
    let rows = &resource.default_effect;
    if !shown(rows, obj, subset) {
        return TurnDraw::Host;
    }
    let Some(v) = value(rows, obj, subset) else {
        return TurnDraw::Host;
    };
    let text = v.text(rows);
    if text == "none" || text == "hide" {
        return TurnDraw::Host;
    }
    // A row assigns the whole object; a subset takes it unless it has its own override.
    let explicit = obj.overrides.effects.contains_key(&subset);
    if subset >= 0 && !explicit && text != "main_default" {
        return resolve(resource, obj, -1);
    }
    let path = match (text, &v) {
        ("main_default", _) => {
            let main = obj.main;
            let path = match main.subsets.get(&subset) {
                Some(p) if subset >= 0 => p,
                _ if subset >= 0 => return resolve(resource, obj, -1),
                _ => &main.effect,
            };
            if path.is_empty() {
                return TurnDraw::Host;
            }
            (obj.resolve)(path)
        }
        (_, Value::Override(p)) => (obj.resolve)(p),
        (_, Value::Row(i)) => match &resource.default_effect_files[*i] {
            Some(f) => f.clone(),
            None => return TurnDraw::Host,
        },
    };
    TurnDraw::Effect(path)
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
