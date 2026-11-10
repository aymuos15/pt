//! Required-artifact content/publication prerequisites, never full-run success.
//!
//! No project code import, execution/replay, artifact recovery from stale files,
//! environment/generation certification or automatic raw-output retention exists.

#[cfg(all(target_os = "linux", target_env = "gnu"))]
mod linux;
#[cfg(all(target_os = "linux", target_env = "gnu"))]
pub use linux::*;
