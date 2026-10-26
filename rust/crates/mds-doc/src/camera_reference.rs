//! The camera reference check boxes of the camera panel (412 "model", 531
//! "bone"; `src/window/command_frame_edit.cpp` 1448-1466,
//! `command_frame_register.cpp` 559-578) and
//! `ApplyCameraReferenceModeChange` (`src/app/frame_modes.cpp` 741-789).

use crate::{not, Document, Error};
use mds_math::Mat4;

impl Document {
    /// [`crate::Command::SetCameraReference`].
    pub(crate) fn set_camera_reference(
        &mut self,
        mode: u8,
        pose: &mut crate::CameraPoseProvider<'_>,
    ) -> Result<(), Error> {
        if mode > 2 {
            return Err(not("no such camera reference mode"));
        }
        let old = self.pmm.timeline.camera_reference_mode;
        self.pmm.timeline.camera_reference_mode = mode;
        if !self.camera_mode() {
            self.reanchor_camera(old, mode, pose(self, crate::CameraPoseRequest::Current)?);
        }
        Ok(())
    }

    /// `ApplyCameraReferenceModeChange`: the view offset and the distance
    /// move by the difference of the two reference origins, rotated by the
    /// camera. The bone matrices are those of the saved pose without physics
    /// (the frame loop's `matInit` with physics off).
    fn reanchor_camera(&mut self, old: u8, new: u8, anchors: crate::CameraAnchors) {
        let s = &self.pmm.camera_state;
        let (pitch, yaw, roll) = (s[6], s[7], s[8]);
        let mut rot = Mat4::multiply(&Mat4::rotation_y(yaw), &Mat4::rotation_x(pitch));
        rot = Mat4::multiply(&rot, &Mat4::rotation_z(roll));
        let a = &self.pmm.appearance;
        if a.camera_parent_model >= 0 {
            rot = Mat4::multiply(&Mat4(a.camera_attachment_basis), &rot);
        }
        let origin = |mode: u8| -> Mat4 {
            let p = match mode {
                1 => anchors.selected_root,
                2 => anchors.selected_bone.map(|b| b.point()),
                _ => None,
            }
            .unwrap_or([0.0; 3]);
            Mat4::translation(-p[0], -p[1], -p[2])
        };
        let t_old = Mat4::multiply(&origin(old), &rot);
        let t_new = Mat4::multiply(&origin(new), &rot);
        let s = &mut self.pmm.camera_state;
        s[3] -= t_old.0[12] - t_new.0[12];
        s[4] -= t_old.0[13] - t_new.0[13];
        s[5] -= t_old.0[14] - t_new.0[14];
    }
}
