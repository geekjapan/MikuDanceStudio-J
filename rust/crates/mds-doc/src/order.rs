//! The order dialogs: model draw order (menu 288) and calculation order
//! (menu 289, `src/window/model_order_dialog.cpp`), and the accessory order
//! dialog (menu 249, `AccessorySettingsDlgProc`,
//! `src/window/command_file_menu.cpp` 720-958).
//!
//! `pmm.accessories` is kept in combo order (`order`), so that the combo
//! text of row `r`, which the PMM saves by position ([`crate::save`]), is
//! the `list_name` of the accessory with order `r`.

use crate::{not, Document, Error};
use mds_formats::text::FixedSjis;

/// `slots` is every slot of `have`, once.
fn permutation(slots: &[u8], mut have: Vec<u8>) -> Result<(), Error> {
    let mut want = slots.to_vec();
    want.sort_unstable();
    have.sort_unstable();
    if want != have {
        return Err(not("the order does not list every slot once"));
    }
    Ok(())
}

impl Document {
    /// `ApplyModelDisplayOrderDialog` (VA 0x0045EC80): row `i` takes combo
    /// index `i + 1`, after the camera entry.
    pub(crate) fn set_model_draw_order(&mut self, slots: &[u8]) -> Result<(), Error> {
        permutation(slots, self.pmm.models.iter().map(|m| m.slot).collect())?;
        for (i, &slot) in slots.iter().enumerate() {
            let m = self.pmm.models.iter_mut().find(|m| m.slot == slot).unwrap();
            m.selection.combo_index = i as u8 + 1;
        }
        Ok(())
    }

    /// `ApplyModelCalculateOrderDialog`: row `i` takes calculation order
    /// `i`.
    pub(crate) fn set_model_calc_order(&mut self, slots: &[u8]) -> Result<(), Error> {
        permutation(slots, self.pmm.models.iter().map(|m| m.slot).collect())?;
        for (i, &slot) in slots.iter().enumerate() {
            let m = self.pmm.models.iter_mut().find(|m| m.slot == slot).unwrap();
            m.display_order = i as u8;
        }
        Ok(())
    }

    /// `ApplyAccessoryOrderIndices`: row `i` takes order `i` and its combo
    /// text as its name (`strcpy_s`); the combo is rebuilt from the rows,
    /// and the accessory of row 0 is selected.
    pub(crate) fn set_accessory_order(&mut self, slots: &[u8]) -> Result<(), Error> {
        let p = &mut self.pmm;
        permutation(slots, p.accessories.iter().map(|a| a.slot).collect())?;
        for (i, &slot) in slots.iter().enumerate() {
            let a = p.accessories.iter_mut().find(|a| a.slot == slot).unwrap();
            a.order = i as u8;
            let text = &a.list_name.raw;
            let len = text.iter().position(|&b| b == 0).unwrap_or(text.len());
            let mut raw = [0; 100];
            raw[..len].copy_from_slice(&text[..len]);
            a.name = FixedSjis {
                raw,
                text: a.list_name.text.clone(),
            };
        }
        p.accessories.sort_by_key(|a| a.order);
        if let Some(&first) = slots.first() {
            p.selected_accessory_slot = first;
        }
        Ok(())
    }

    /// Button 633: the row text of the accessory in `slot`
    /// (`LB_DELETESTRING`, `LB_INSERTSTRING`); an empty text changes
    /// nothing. The name follows on OK ([`Document::set_accessory_order`]).
    pub(crate) fn rename_accessory(&mut self, slot: u8, name: &str) -> Result<(), Error> {
        let a = self
            .pmm
            .accessories
            .iter_mut()
            .find(|a| a.slot == slot)
            .ok_or(not("no accessory in that slot"))?;
        if name.is_empty() {
            return Ok(());
        }
        let s = crate::add_model::sjis(name, usize::MAX).raw;
        if s.len() >= 100 {
            return Err(not("a name longer than its buffer (strcpy_s fails)"));
        }
        // The list box row holds the text alone; `CB_GETLBTEXT` copies it
        // with its NUL over the old row's bytes.
        let raw = &mut a.list_name.raw;
        raw[..s.len()].copy_from_slice(&s);
        raw[s.len()] = 0;
        a.list_name.text = name.to_string();
        Ok(())
    }
}
