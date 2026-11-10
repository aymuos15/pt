//! Read-only identity prerequisites for explicitly declared Unix file trees.
//! No index, Python import, installer, execution/launch approval, complete host /
//! environment verification or immutable/current generation assurance exists.

#[cfg(target_os = "linux")]
mod linux;
#[cfg(target_os = "linux")]
pub use linux::*;
