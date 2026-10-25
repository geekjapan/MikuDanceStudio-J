//! The file side of File > New, Open, Save, Save As and Exit, without the dialogs (those are in
//! [`crate::ui::file`]): reading a PMM into a document, writing it, and the unsaved-changes
//! prompts of the C++ (`CmdResetState`, `CmdOpenScene` and `CmdSaveScene` in
//! `src/window/command_impl.cpp`, `WM_CLOSE` in `src/window/wndproc.cpp`).

use crate::scene::read_model;
use mds_doc::Document;
use std::path::Path;

/// The scene the C++ application starts with, as its `--mds-script` saves it
/// (`tests/fixtures/rust/script/empty.txt`).
const EMPTY_SCENE: &[u8] =
    include_bytes!("../../../../tests/fixtures/rust/script/expected/empty/empty.pmm");

/// A PMM and the model files it names; model paths resolve against `dir` as
/// [`read_model`] does. Rejects a negative current frame, as `SceneSession::Load` does.
pub fn load(data: &[u8], dir: &Path) -> Result<Document, String> {
    let doc = Document::load(data, |p| read_model(dir, p).ok()).map_err(|e| e.to_string())?;
    if doc.pmm.timeline.current_frame < 0 {
        return Err("negative current frame".into());
    }
    Ok(doc)
}

pub fn read(path: &Path) -> Result<Document, String> {
    let data = std::fs::read(path).map_err(|e| format!("{}: {e}", path.display()))?;
    load(&data, path.parent().unwrap_or(Path::new(".")))
        .map_err(|e| format!("{}: {e}", path.display()))
}

pub fn empty() -> Document {
    load(EMPTY_SCENE, Path::new(".")).expect("the startup scene loads")
}

/// `SaveSceneFile` (`src/io/pmm_save.cpp`) without the `.emm` beside it.
pub fn write(doc: &Document, path: &Path) -> Result<(), String> {
    let bytes = doc.save().map_err(|e| e.to_string())?;
    std::fs::write(path, bytes).map_err(|e| format!("{}: {e}", path.display()))
}

/// An OK/Cancel question the C++ asks before it drops the scene (`MB_OKCANCEL`, English texts).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Prompt {
    /// File > New asks every time (`CmdResetState`, 0x46DE02).
    New,
    /// File > Open asks when the scene is modified (`CmdOpenScene`, 0x46DE66).
    Open,
    /// Closing the window asks when the scene is modified (`MainWndProc`, `WM_CLOSE`).
    Quit,
}

impl Prompt {
    /// `(caption, text)`, or `None` when the C++ asks nothing and goes ahead.
    pub fn text(self, modified: bool) -> Option<(&'static str, &'static str)> {
        match self {
            Prompt::New => Some(("new", "The existing state will be annulled.\n\nAre you OK?")),
            Prompt::Open if modified => Some((
                "open file data",
                "There is a change point not preserved.\n\nAre you OK?",
            )),
            Prompt::Quit if modified => Some((
                "quit",
                "There is a change point not preserved.\n\nDo you realy quit?",
            )),
            Prompt::Open | Prompt::Quit => None,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn prompts_follow_the_cpp_gates() {
        assert!(Prompt::New.text(false).is_some());
        assert!(Prompt::Open.text(false).is_none() && Prompt::Open.text(true).is_some());
        assert!(Prompt::Quit.text(false).is_none() && Prompt::Quit.text(true).is_some());
    }

    #[test]
    fn the_startup_scene_has_no_models() {
        let doc = empty();
        assert!(doc.pmm.models.is_empty() && doc.pmm.accessories.is_empty());
    }
}
