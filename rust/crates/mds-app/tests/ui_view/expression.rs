use crate::labels;
use mds_app::actions;
use mds_app::ui::expression;

#[test]
fn the_labels_are_those_of_the_inventory() {
    labels::check("expression", expression::LABELS);
}

/// No row is registered until `mds_doc::Command` has the operation; a registered action that
/// edits the document some other way would bypass the undo history and the edited mark.
#[test]
fn no_row_is_faked() {
    assert!(expression::actions().is_empty());
    for (id, _, _) in expression::LABELS {
        assert!(actions::find(id).is_none(), "{id}");
    }
}
