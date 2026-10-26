//! The `physics` area of the UI through the action table, with no window: each action runs through
//! `Ctx::run`'s path (`actions::run`) and the document, the live world or the egui memory is the
//! result.

mod bodies;
mod labels;
mod modes;
mod rig;
mod rows;
mod world;
