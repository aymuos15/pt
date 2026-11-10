use crate::{
    BridgeMessage, ChannelIdentity, MAX_EVENTS, MAX_FRAME_BYTES, MAX_STREAM_BYTES, ProtocolError,
    StreamEnd, decode_bridge,
};
use std::io::{ErrorKind, Read};
use std::os::unix::net::UnixStream;
use std::time::Instant;

#[derive(Debug, Clone, Copy)]
pub struct StreamBudget {
    pub bytes: u64,
    pub events: u64,
}

impl StreamBudget {
    fn validate(self) -> Result<(), ProtocolError> {
        if self.bytes == 0
            || self.bytes > MAX_STREAM_BYTES
            || self.events == 0
            || self.events > MAX_EVENTS
        {
            Err(ProtocolError::new(
                "explicit positive private-channel budgets exceed revision-1 bounds",
            ))
        } else {
            Ok(())
        }
    }
}

/// Single owned bridge socket, absolute deadlines, no recovery/replay. Counters
/// refer to confirmed complete frames; a failed read may have consumed bytes.
pub struct FrameReader {
    source: std::sync::Arc<()>,
    stream: UnixStream,
    identity: ChannelIdentity,
    budget: StreamBudget,
    confirmed_bytes: u64,
    confirmed_events: u64,
    failed: bool,
    ended: bool,
}

impl FrameReader {
    pub fn new(
        stream: UnixStream,
        identity: ChannelIdentity,
        budget: StreamBudget,
    ) -> Result<Self, ProtocolError> {
        identity.validate()?;
        budget.validate()?;
        if !stream.local_addr()?.is_unnamed() || !stream.peer_addr()?.is_unnamed() {
            return Err(ProtocolError::new(
                "private control requires an unnamed connected socket pair",
            ));
        }
        stream.set_nonblocking(false)?;
        Ok(Self {
            source: std::sync::Arc::new(()),
            stream,
            identity,
            budget,
            confirmed_bytes: 0,
            confirmed_events: 0,
            failed: false,
            ended: false,
        })
    }

    pub fn confirmed_frames(&self) -> u64 {
        self.confirmed_events
    }
    pub fn confirmed_wire_bytes(&self) -> u64 {
        self.confirmed_bytes
    }
    pub fn end_evidence(&self) -> Option<StreamEnd> {
        (self.ended && !self.failed).then(|| StreamEnd {
            source: self.source.clone(),
            identity: self.identity.clone(),
            events: self.confirmed_events,
            wire_bytes: self.confirmed_bytes,
        })
    }

    fn exact(
        &mut self,
        raw: &mut [u8],
        deadline: Instant,
        eof: bool,
    ) -> Result<bool, ProtocolError> {
        let mut position = 0;
        while position < raw.len() {
            let remaining = deadline
                .checked_duration_since(Instant::now())
                .filter(|value| !value.is_zero())
                .ok_or_else(|| ProtocolError::new("absolute private control deadline expired"))?;
            self.stream.set_read_timeout(Some(remaining))?;
            let result = self.stream.read(&mut raw[position..]);
            if Instant::now() >= deadline {
                return Err(ProtocolError::new(
                    "absolute private control deadline expired",
                ));
            }
            match result {
                Ok(0) if position == 0 && eof => return Ok(false),
                Ok(0) => return Err(ProtocolError::new("truncated private control frame")),
                Ok(size) => position += size,
                Err(error) if error.kind() == ErrorKind::Interrupted => continue,
                Err(error) => return Err(error.into()),
            }
        }
        Ok(true)
    }

    pub fn receive(&mut self, deadline: Instant) -> Result<Option<BridgeMessage>, ProtocolError> {
        if self.failed || self.ended {
            return Err(ProtocolError::new(
                "failed/ended control stream cannot be resumed",
            ));
        }
        let result = self.receive_inner(deadline);
        if result.is_err() {
            self.failed = true;
        }
        result
    }

    fn receive_inner(&mut self, deadline: Instant) -> Result<Option<BridgeMessage>, ProtocolError> {
        let mut prefix = [0; 4];
        if !self.exact(&mut prefix, deadline, true)? {
            self.ended = true;
            return Ok(None); // EOF is not a semantic terminal or full-test verdict.
        }
        let size = u32::from_be_bytes(prefix) as usize;
        if size == 0 || size > MAX_FRAME_BYTES {
            return Err(ProtocolError::new("zero/oversize private control frame"));
        }
        let wire_bytes = size as u64 + 4;
        if self.confirmed_events >= self.budget.events
            || wire_bytes > self.budget.bytes - self.confirmed_bytes
        {
            return Err(ProtocolError::new(
                "private control budget exceeded before payload allocation",
            ));
        }
        let mut raw = vec![0; size];
        self.exact(&mut raw, deadline, false)?;
        let mut message = decode_bridge(&raw, &self.identity)?;
        if message.sequence() != self.confirmed_events {
            return Err(ProtocolError::new(
                "lost/duplicate/reordered private control event",
            ));
        }
        if Instant::now() >= deadline {
            return Err(ProtocolError::new(
                "absolute private control deadline expired during decoding",
            ));
        }
        self.confirmed_events += 1;
        self.confirmed_bytes += wire_bytes;
        message.source = Some(self.source.clone());
        Ok(Some(message))
    }
}
