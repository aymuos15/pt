//! Explicit development request/process/artifact/failure-result integration.
//! Qualified launch is rejected before work: complete environment/startup,
//! immutable-generation and supported-profile prerequisites are not implemented.
//! No boolean supplied by a bridge, saved file or caller can enable success.

#[cfg(target_os = "linux")]
mod linux;
#[cfg(target_os = "linux")]
pub use linux::*;
