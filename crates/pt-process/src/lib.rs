//! Process-only records. These cannot certify test work or source generations.

use serde::Serialize;

/// The first terminal cause observed by the supervisor, never changed by a
/// later zero exit. A cleanup failure takes precedence in the CLI exit mapping.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum Termination {
    ProcessExited,
    BackendTerminated,
    Timeout,
    Interrupted { signal: i32 },
    LaunchError { detail: String },
    InfrastructureError { detail: String },
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum LeaderStatus {
    Exited { code: i32 },
    Signaled { signal: i32, core_dumped: bool },
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum Cleanup {
    NotLaunched,
    Complete,
    Uncertain { detail: String },
}

/// A process observation, not a full-run result. No test-count, conformance,
/// artifact, snapshot, or generation-valid-success field can be set here.
#[derive(Debug, Clone, Serialize)]
pub struct ProcessReport {
    pub schema_version: u32,
    pub scope: ProcessScope,
    pub pid: Option<u32>,
    pub termination: Termination,
    pub leader_status: Option<LeaderStatus>,
    pub cleanup: Cleanup,
    pub elapsed_ns: u128,
}

#[derive(Debug, Clone, Copy, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ProcessScope {
    ProcessOnly,
}

impl ProcessReport {
    /// Ordinary CLI exit; signal propagation is represented by 128 + signal,
    /// not by claiming PT itself was OS-terminated by the child's signal.
    pub fn exit_code(&self) -> u8 {
        if matches!(self.cleanup, Cleanup::Uncertain { .. }) {
            return 3;
        }
        match (&self.termination, &self.leader_status, &self.cleanup) {
            (
                Termination::ProcessExited,
                Some(LeaderStatus::Exited { code }),
                Cleanup::Complete,
            ) => u8::try_from(*code).unwrap_or(3),
            (
                Termination::BackendTerminated,
                Some(LeaderStatus::Signaled { signal, .. }),
                Cleanup::Complete,
            ) if (1..=64).contains(signal) => (128 + signal) as u8,
            (Termination::Interrupted { .. }, _, _) => 2,
            _ => 3,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn report(termination: Termination, status: Option<LeaderStatus>) -> ProcessReport {
        ProcessReport {
            schema_version: 1,
            scope: ProcessScope::ProcessOnly,
            pid: Some(123),
            termination,
            leader_status: status,
            cleanup: Cleanup::Complete,
            elapsed_ns: 1,
        }
    }

    #[test]
    fn diagnostic_process_codes_are_preserved_not_called_test_success() {
        for code in [0, 1, 2, 3, 4, 5, 7, 255] {
            assert_eq!(
                report(
                    Termination::ProcessExited,
                    Some(LeaderStatus::Exited { code })
                )
                .exit_code(),
                code as u8
            );
        }
    }

    #[test]
    fn timeout_or_interrupt_cannot_be_reversed_by_later_zero_exit() {
        let zero = Some(LeaderStatus::Exited { code: 0 });
        assert_eq!(report(Termination::Timeout, zero.clone()).exit_code(), 3);
        assert_eq!(
            report(Termination::Interrupted { signal: 2 }, zero).exit_code(),
            2
        );
    }

    #[test]
    fn cleanup_uncertainty_overrides_exit_without_discarding_raw_status() {
        let mut result = report(
            Termination::ProcessExited,
            Some(LeaderStatus::Exited { code: 7 }),
        );
        result.cleanup = Cleanup::Uncertain {
            detail: "group verification unavailable".into(),
        };
        assert_eq!(result.exit_code(), 3);
        assert_eq!(result.leader_status, Some(LeaderStatus::Exited { code: 7 }));
        result.termination = Termination::Interrupted { signal: 15 };
        assert_eq!(result.exit_code(), 3);
    }

    #[test]
    fn signals_have_explicit_shell_compatible_exit_mapping() {
        let result = report(
            Termination::BackendTerminated,
            Some(LeaderStatus::Signaled {
                signal: 15,
                core_dumped: false,
            }),
        );
        assert_eq!(result.exit_code(), 143);
    }

    #[test]
    fn missing_or_contradictory_status_cannot_yield_zero() {
        let cases = [
            report(Termination::ProcessExited, None),
            report(
                Termination::BackendTerminated,
                Some(LeaderStatus::Exited { code: 0 }),
            ),
            report(
                Termination::LaunchError {
                    detail: "not found".into(),
                },
                None,
            ),
            report(
                Termination::InfrastructureError {
                    detail: "I/O error".into(),
                },
                None,
            ),
        ];
        for result in cases {
            assert_eq!(result.exit_code(), 3);
        }
    }
}
