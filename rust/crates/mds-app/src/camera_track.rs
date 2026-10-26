//! Native CameraTrackCursor/CameraTrackActive, independent of playback ownership.
use mds_formats::{key_pool::KeyPool, pmm::CameraKey};
use mds_scene::{
    frame::Camera,
    track::{evaluate_camera, CameraMode},
};

#[derive(Default)]
pub(crate) struct CameraTrackCursor {
    index: u32,
    active: bool,
}
impl CameraTrackCursor {
    pub(crate) fn start(
        &mut self,
        pool: &KeyPool<CameraKey>,
        cursor: f32,
    ) -> Result<Option<Camera>, String> {
        self.index = 0;
        self.active = true;
        let frame = mds_scene::playback_frame(cursor).ok_or("invalid playback camera cursor")?;
        if self.seek_end(pool, frame)? {
            evaluate_camera(pool, frame, CameraMode::Playback)
                .map(Some)
                .ok_or("invalid playback camera track".into())
        } else {
            Ok(None)
        }
    }
    pub(crate) fn advance(
        &mut self,
        pool: &KeyPool<CameraKey>,
        cursor: f32,
    ) -> Result<Option<Camera>, String> {
        if !self.active {
            return Ok(None);
        }
        let frame = mds_scene::playback_frame(cursor).ok_or("invalid playback camera cursor")?;
        let sample = evaluate_camera(pool, frame, CameraMode::Playback)
            .ok_or("invalid playback camera track")?;
        self.seek_end(pool, frame)?;
        Ok(Some(sample))
    }
    fn seek_end(&mut self, pool: &KeyPool<CameraKey>, frame: f64) -> Result<bool, String> {
        for _ in 0..pool.capacity() {
            let key = pool.get(self.index).ok_or("invalid camera track index")?;
            if f64::from(key.frame) >= frame {
                return Ok(false);
            }
            if key.next == 0 {
                self.active = false;
                return Ok(true);
            }
            let next = pool.get(key.next).ok_or("invalid camera track index")?;
            if next.previous != self.index || next.frame <= key.frame {
                return Err("invalid camera track links".into());
            }
            self.index = key.next;
        }
        Err("cyclic camera track".into())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use mds_doc::{Command, Document, GlobalTrack};
    fn track() -> Document {
        let mut doc = Document::startup();
        doc.apply(Command::SelectCameraMode).unwrap();
        doc.apply(Command::SetFrame(30)).unwrap();
        doc.apply(Command::SetCamera {
            position: [9.0, 3.0, 2.0],
            rotation: [0.1, 1.0, 0.3],
            distance: -30.0,
            fov: 37.0,
            perspective: true,
        })
        .unwrap();
        doc.apply(Command::RegisterGlobalKeys(vec![GlobalTrack::Camera]))
            .unwrap();
        doc
    }
    #[test]
    fn terminal_equality_remains_active_and_postterminal_copies_once() {
        let doc = track();
        let mut cursor = CameraTrackCursor::default();
        assert!(cursor.start(&doc.pmm.camera, 1.0).unwrap().is_none());
        assert!(cursor.active);
        assert!(cursor.advance(&doc.pmm.camera, 1.001).unwrap().is_some());
        assert!(!cursor.active);
        assert!(cursor.advance(&doc.pmm.camera, 2.0).unwrap().is_none());
        assert!(cursor.start(&doc.pmm.camera, 2.0).unwrap().is_some());
        assert!(!cursor.active);
    }
    #[test]
    fn fractional_cursor_uses_existing_playback_evaluator_and_loop_restarts() {
        let doc = track();
        let mut cursor = CameraTrackCursor::default();
        assert!(cursor.start(&doc.pmm.camera, 0.5123).unwrap().is_none());
        let sample = cursor.advance(&doc.pmm.camera, 0.5123).unwrap().unwrap();
        let at = mds_scene::playback_frame(0.5123).unwrap();
        assert_ne!(at, at.floor());
        assert_eq!(
            sample,
            evaluate_camera(&doc.pmm.camera, at, CameraMode::Playback).unwrap()
        );
        assert!(cursor.advance(&doc.pmm.camera, 2.0).unwrap().is_some());
        assert!(cursor.start(&doc.pmm.camera, 0.0).unwrap().is_none());
        assert!(cursor.active);
        assert_eq!(cursor.index, 0);
    }
}
