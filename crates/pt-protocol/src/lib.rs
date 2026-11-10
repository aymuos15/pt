//! Bridge-channel necessary conditions, not authenticated work or full success.
//!
//! This crate never imports Python, certifies artifacts/environments/generations,
//! infers lost execution returns from files, or grants an optimization capability.

mod message;
pub use message::*;
mod serial;
pub use serial::{AttemptObservation, BridgeSnapshot, RequestMode, SerialContract, SerialLedger};

#[cfg(target_os = "linux")]
mod stream;
#[cfg(target_os = "linux")]
pub use stream::{FrameReader, StreamBudget};

use std::error::Error;
use std::fmt;

pub const MAX_FRAME_BYTES: usize = 1024 * 1024;
pub const MAX_STREAM_BYTES: u64 = 64 * 1024 * 1024;
pub const MAX_EVENTS: u64 = 1_000_000;
pub const MAX_DEPTH: usize = 32;
pub const MAX_NODES: usize = 65_536;

/// Evidence of an actual clean channel EOF, constructed only by FrameReader.
/// It is not evidence of a terminal message, process exit or completed test work.
#[derive(Debug, Clone)]
pub struct StreamEnd {
    pub(crate) source: std::sync::Arc<()>,
    pub(crate) identity: ChannelIdentity,
    pub(crate) events: u64,
    pub(crate) wire_bytes: u64,
}

#[derive(Debug)]
pub struct ProtocolError(String);

impl ProtocolError {
    pub(crate) fn new(detail: impl Into<String>) -> Self {
        Self(detail.into())
    }
}

impl fmt::Display for ProtocolError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.0)
    }
}

impl Error for ProtocolError {}

impl From<std::io::Error> for ProtocolError {
    fn from(error: std::io::Error) -> Self {
        Self::new(format!("private control I/O: {error}"))
    }
}

/// Bound nesting/tokens before serde can allocate nested payload structures.
/// Grammar, UTF-8, duplicate keys and typed shapes are checked by the decoder.
fn precheck(raw: &[u8]) -> Result<(), ProtocolError> {
    if raw.is_empty() || raw.len() > MAX_FRAME_BYTES {
        return Err(ProtocolError::new(
            "nonzero frame length must be at most 1 MiB",
        ));
    }
    let (mut stack, mut quoted, mut escaped, mut atom, mut nodes) =
        (Vec::new(), false, false, false, 0);
    for &byte in raw {
        if quoted {
            if escaped {
                escaped = false;
            } else if byte == b'\\' {
                escaped = true;
            } else if byte == b'"' {
                quoted = false;
            }
            continue;
        }
        match byte {
            b'"' => {
                quoted = true;
                atom = false;
                nodes += 1;
            }
            b'[' | b'{' => {
                stack.push(byte);
                if stack.len() > MAX_DEPTH {
                    return Err(ProtocolError::new("control JSON nesting bound exceeded"));
                }
                nodes += 1;
                atom = false;
            }
            b']' | b'}' => {
                if stack.pop() != Some(if byte == b']' { b'[' } else { b'{' }) {
                    return Err(ProtocolError::new("unbalanced control JSON containers"));
                }
                atom = false;
            }
            b',' | b':' | b' ' | b'\t' | b'\r' | b'\n' => atom = false,
            _ if !atom => {
                atom = true;
                nodes += 1;
            }
            _ => {}
        }
        if nodes > MAX_NODES {
            return Err(ProtocolError::new("control JSON token bound exceeded"));
        }
    }
    if quoted || !stack.is_empty() {
        return Err(ProtocolError::new(
            "truncated control JSON containers/string",
        ));
    }
    Ok(())
}
