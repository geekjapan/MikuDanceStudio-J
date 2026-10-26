//! VSQ lip sync (menu 224, `MDS_CMD_LOAD_LIP_SYNC`,
//! `src/window/command_file_menu.cpp` 1147-1173, and a dropped `.vsq`,
//! `src/window/ui_dropfiles.cpp` 249-262): `mds_vsq::lip_sync` with the
//! selected model's morph names, then the part of `LoadVsqFile`
//! (`src/io/vsq_load.cpp` 805-883) that edits the document.

use crate::{model, not, Document, Error};

impl Document {
    /// Lip sync from the VSQ bytes `vsq` onto the model in the selected
    /// slot. Menu 224's handler has no camera-mode gate, but camera mode
    /// grays the menu out (`ApplyModelComboSelection`, `ui_model_reload.cpp`
    /// 453), so the caller offers it in model mode only; a dropped file
    /// (`dropped`) is refused in camera mode, with the box "Not selected
    /// model!". A note at 0 s gives the key frame -2, stored as the unsigned
    /// 4294967294, and `lastRegisteredFrame` follows it to -2 (`vsq_load.cpp`
    /// 817-860; `script3/expected/lipsync/drop.pmm`).
    ///
    /// The document changes only when [`mds_vsq::Run::outcome`] is `Ok`: the
    /// marks of the three pools cleared, each key registered through
    /// `RegisterMorphKeyCurrent` with the morph's weight set first
    /// (`VsqMorphKey`), the current frame moved to the end of the last
    /// note, `lastRegisteredFrame` raised to the model's max frame, the
    /// seek, and the timeline start six frames before. Writing
    /// [`mds_vsq::Run::txt`] next to the VSQ ([`mds_vsq::txt_path`], with
    /// `\r\n` on Windows) and the message box of a failed run are the
    /// caller's.
    pub fn lip_sync(&mut self, vsq: &[u8], dropped: bool) -> Result<mds_vsq::Run, Error> {
        if dropped && self.camera_mode() {
            return Err(not("Not selected model! (a message box)"));
        }
        let (i, s) = self.keyed()?;
        let m = &mut self.pmm.models[i];
        let names: Vec<&[u8]> = m.morph_names.iter().map(|n| n.raw.as_slice()).collect();
        let run = mds_vsq::lip_sync(vsq, &names);
        let Ok(sync) = &run.outcome else {
            return Ok(run);
        };
        let mut rig = model::rig(m, &s, false);
        let mut first = Ok(());
        model::with_tracks(m, &mut self.edit.models[i].search_cursor, |t| {
            t.clear_marks();
            for k in &sync.keys {
                rig.morphs[k.morph].value = k.weight;
                // A full pool shows its box and the loop goes on.
                match t.register_morph_current(&rig, k.morph as i32, k.frame as u32) {
                    Ok(()) | Err(mds_edit::Error::Full { .. }) => {}
                    Err(e) => {
                        first = Err(e.into());
                        break;
                    }
                }
            }
        });
        for k in &sync.keys {
            m.morph_pose[k.morph] = k.weight;
        }
        if let Some(f) = sync.final_frame {
            self.pmm.timeline.current_frame = f;
        }
        let max = m.selection.max_frame;
        let t = &mut self.pmm.timeline;
        if (t.last_registered_frame as u32) < max {
            t.last_registered_frame = max as i32;
        }
        self.seek(i);
        let f = self.pmm.timeline.current_frame;
        self.pmm.timeline.start_frame = if f > 6 { f - 6 } else { 0 };
        first.map(|()| run)
    }
}
