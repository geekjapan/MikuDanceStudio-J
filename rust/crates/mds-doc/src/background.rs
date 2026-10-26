//! The background movie and picture (`src/media/media_load.cpp`):
//! `LoadAviFile` (155-314) and `LoadBackgroundPicture` (321-378) through
//! the `mds-media` decoders, with `MediaAspect` (116-128,
//! [`mds_media::background::media_aspect`]) on [`crate::EditState::viewport`].
//!
//! The PMM keeps the path, the enabled flag, the X and Y offset and the
//! scale. A load places the media at X 0, with the scale and Y offset that
//! fit it to the viewport width. The size, the frame range and the decoded
//! frames are the renderer's, which opens the saved path itself.

use crate::accessory::fixed;
use crate::{not, Document, Error};
use mds_formats::pmm::Background;
use mds_media::background::media_aspect;

impl Document {
    fn place_background(&self, width: i32, height: i32) -> Result<([i32; 2], f32), Error> {
        let vp = self
            .edit
            .viewport
            .as_ref()
            .ok_or(not("no viewport for MediaAspect"))?;
        let (scale, y) = media_aspect(vp, width, height);
        Ok(([0, y], scale))
    }

    /// [`crate::Command::LoadBackgroundMovie`]: on success the path, the
    /// placement and `enabled` 1 (menu 216 checked). A file the decoders
    /// refuse clears the path and `enabled` (`AviFailTail`), keeps the
    /// placement, and gives the message of the C++ box.
    pub(crate) fn load_background_movie(&mut self, path: &str, data: &[u8]) -> Result<(), Error> {
        if self.edit.viewport.is_none() {
            return Err(not("no viewport for MediaAspect"));
        }
        match mds_media::movie::Movie::open(std::io::Cursor::new(data)) {
            Err(e) => {
                self.pmm.avi.path = fixed("");
                self.pmm.avi.enabled = 0;
                Err(Error::Format(e.message(true)))
            }
            Ok(m) => {
                let (offset, scale) = self.place_background(m.info().width, m.info().height)?;
                set(&mut self.pmm.avi, path, offset, scale);
                Ok(())
            }
        }
    }

    /// [`crate::Command::LoadBackgroundPicture`]: on success the path, the
    /// placement and `enabled` 1 (menu 233 checked). A file the decoder
    /// refuses clears the path and keeps `enabled` and the placement
    /// (`media_load.cpp` 331-361).
    pub(crate) fn load_background_picture(&mut self, path: &str, data: &[u8]) -> Result<(), Error> {
        if self.edit.viewport.is_none() {
            return Err(not("no viewport for MediaAspect"));
        }
        match mds_media::picture::decode(data) {
            Err(e) => {
                self.pmm.picture.path = fixed("");
                Err(Error::Format(e.message(true)))
            }
            Ok(p) => {
                let (offset, scale) = self.place_background(p.width as i32, p.height as i32)?;
                set(&mut self.pmm.picture, path, offset, scale);
                Ok(())
            }
        }
    }
}

fn set(b: &mut Background, path: &str, offset: [i32; 2], scale: f32) {
    b.path = fixed(path);
    b.offset = offset;
    b.scale = scale;
    b.enabled = 1;
}
