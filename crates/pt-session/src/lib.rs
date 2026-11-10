//! One owned process/channel/accounting lifecycle; never a full test result.
//!
//! The exact invocation and bootstrap are supplied explicitly by the caller.
//! This layer does not select/probe Python, rewrite argv/environment, install or
//! suppress plugins, replay work, certify artifacts/environments/generations or
//! authorize the missing supported launcher. No full-success/CLI-result API exists.

#[cfg(target_os = "linux")]
mod linux;
#[cfg(target_os = "linux")]
pub use linux::*;
