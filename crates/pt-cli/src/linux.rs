use pt_process::{Cleanup, ProcessReport, ProcessRequest, Termination, supervise};
use signal_hook::consts::signal::{SIGINT, SIGTERM};
use signal_hook::iterator::{Handle, Signals};
use std::collections::HashSet;
use std::ffi::OsString;
use std::fs::{self, File, OpenOptions};
use std::io::{self, Write};
use std::os::unix::fs::{MetadataExt, OpenOptionsExt};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::sync::atomic::{AtomicI32, Ordering};
use std::thread::{self, JoinHandle};
use std::time::Duration;

const HELP: &str = "PT development process supervisor (not a qualified pytest runner)

Usage: pt exec [--cwd PATH] [--timeout-seconds N] [--cleanup-seconds N]
               [--report NEW_JSON_FILE] -- PROGRAM [ARG ...]
       pt --version

exec launches a fresh process group without a shell. Environment and standard
streams are inherited; trailing arguments are forwarded exactly. Default execution
timeout: 300 s; default bounded cleanup: 1 s (maximum 30 s). A zero exec exit is a
process result only, not evidence of complete test work or valid generations.

--report is opt-in, mode 0600, published without overwrite after cleanup. A
publication error exits 3 even if the child exited zero. No daemon, caching,
preloading, dependency installation, automatic retry, or pytest plugin injection.
pt run is not implemented yet. See docs/baseline-contract-v1.md.";

struct Invocation {
    request: ProcessRequest,
    report: Option<PathBuf>,
}

fn duration(value: &std::ffi::OsStr) -> Result<Duration, String> {
    let number: f64 = value
        .to_str()
        .and_then(|value| value.parse().ok())
        .filter(|number: &f64| number.is_finite() && *number > 0.0)
        .ok_or("duration must be a finite positive number of seconds")?;
    let duration = Duration::try_from_secs_f64(number).map_err(|error| error.to_string())?;
    if duration.is_zero() {
        return Err("duration is below clock representation".into());
    }
    Ok(duration)
}

fn parse(args: Vec<OsString>) -> Result<Invocation, String> {
    let mut args = args.into_iter();
    if args.next().as_deref() != Some(std::ffi::OsStr::new("exec")) {
        return Err("only the diagnostic 'exec' command is available; use --help".into());
    }
    let mut cwd = std::env::current_dir().map_err(|error| error.to_string())?;
    let mut timeout = Duration::from_secs(300);
    let mut cleanup_timeout = Duration::from_secs(1);
    let mut report = None;
    let mut seen = HashSet::new();
    let mut separator = false;
    while let Some(option) = args.next() {
        if option == "--" {
            separator = true;
            break;
        }
        let name = option
            .to_str()
            .ok_or("invalid PT option (arguments must follow --)")?;
        if !matches!(
            name,
            "--cwd" | "--timeout-seconds" | "--cleanup-seconds" | "--report"
        ) {
            return Err(format!(
                "unknown PT option {name:?}; command arguments must follow --"
            ));
        }
        if !seen.insert(name.to_owned()) {
            return Err(format!("duplicate PT option {name}"));
        }
        let value = args
            .next()
            .ok_or_else(|| format!("missing value for {name}"))?;
        match name {
            "--cwd" => cwd = value.into(),
            "--timeout-seconds" => timeout = duration(&value)?,
            "--cleanup-seconds" => cleanup_timeout = duration(&value)?,
            "--report" => report = Some(PathBuf::from(value)),
            _ => unreachable!(),
        }
    }
    if !separator {
        return Err("an explicit -- separator before PROGRAM is required".into());
    }
    let executable = args
        .next()
        .filter(|arg| !arg.is_empty())
        .ok_or("missing PROGRAM")?;
    if cleanup_timeout > Duration::from_secs(30) {
        return Err("cleanup timeout exceeds 30 seconds".into());
    }
    Ok(Invocation {
        request: ProcessRequest {
            executable,
            args: args.collect(),
            cwd,
            timeout,
            cleanup_timeout,
        },
        report,
    })
}

/// Own only an exclusively created lock/staging file; never remove a preexisting
/// record or another writer's lock. A crash can leave the hidden lock, not a
/// partial final JSON record. Directory power-loss durability is not promised.
struct ReportTarget {
    target: PathBuf,
    staging: PathBuf,
    file: File,
}

impl ReportTarget {
    fn still_owned(&self) -> bool {
        match (self.file.metadata(), fs::symlink_metadata(&self.staging)) {
            (Ok(open), Ok(named)) => {
                named.is_file() && open.dev() == named.dev() && open.ino() == named.ino()
            }
            _ => false,
        }
    }

    fn reserve(target: &Path) -> io::Result<Self> {
        match fs::symlink_metadata(target) {
            Ok(_) => {
                return Err(io::Error::new(
                    io::ErrorKind::AlreadyExists,
                    "report already exists",
                ));
            }
            Err(error) if error.kind() == io::ErrorKind::NotFound => {}
            Err(error) => return Err(error),
        }
        let parent = target
            .parent()
            .filter(|path| !path.as_os_str().is_empty())
            .unwrap_or(Path::new("."));
        let name = target
            .file_name()
            .ok_or_else(|| io::Error::other("report must name a file"))?;
        let mut lock_name = OsString::from(".pt-report-");
        lock_name.push(name);
        lock_name.push(".lock");
        let staging = parent.join(lock_name);
        let file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(&staging)?;
        Ok(Self {
            target: target.to_owned(),
            staging,
            file,
        })
    }

    fn publish(&mut self, result: &ProcessReport) -> io::Result<()> {
        serde_json::to_writer_pretty(&mut self.file, result).map_err(io::Error::other)?;
        self.file.write_all(b"\n")?;
        self.file.sync_all()?;
        if !self.still_owned() {
            return Err(io::Error::other("report staging identity changed"));
        }
        fs::hard_link(&self.staging, &self.target)
    }
}

impl Drop for ReportTarget {
    fn drop(&mut self) {
        // This path was exclusively created by this invocation, not user data.
        if self.still_owned() {
            let _ = fs::remove_file(&self.staging);
        }
    }
}

struct Cancellation {
    flag: Arc<AtomicI32>,
    handle: Handle,
    thread: Option<JoinHandle<()>>,
}

impl Cancellation {
    fn register() -> io::Result<Self> {
        let mut signals = Signals::new([SIGINT, SIGTERM])?;
        let handle = signals.handle();
        let flag = Arc::new(AtomicI32::new(0));
        let copy = flag.clone();
        let thread = thread::Builder::new()
            .name("pt-cancellation".into())
            .spawn(move || {
                for signal in signals.forever() {
                    let _ = copy.compare_exchange(0, signal, Ordering::SeqCst, Ordering::SeqCst);
                }
            })?;
        Ok(Self {
            flag,
            handle,
            thread: Some(thread),
        })
    }
}

impl Drop for Cancellation {
    fn drop(&mut self) {
        self.handle.close();
        if let Some(thread) = self.thread.take() {
            let _ = thread.join();
        }
    }
}

pub fn main() -> u8 {
    let args: Vec<_> = std::env::args_os().skip(1).collect();
    if args == ["--help"] || args == ["-h"] || args == ["exec", "--help"] {
        println!("{HELP}");
        return 0;
    }
    if args == ["--version"] {
        println!(
            "pt {} (development; process-only)",
            env!("CARGO_PKG_VERSION")
        );
        return 0;
    }
    let invocation = match parse(args) {
        Ok(invocation) => invocation,
        Err(error) => {
            eprintln!("pt: configuration_error: {error}");
            return 4;
        }
    };
    let mut report = match invocation
        .report
        .as_deref()
        .map(ReportTarget::reserve)
        .transpose()
    {
        Ok(report) => report,
        Err(error) => {
            eprintln!("pt: configuration_error: cannot reserve new report: {error}");
            return 4;
        }
    };
    let cancelled = match Cancellation::register() {
        Ok(cancelled) => cancelled,
        Err(error) => {
            eprintln!("pt: infrastructure_error: cannot install cancellation handler: {error}");
            return 3;
        }
    };
    let result = supervise(&invocation.request, &cancelled.flag);
    drop(cancelled);
    let result = match result {
        Ok(result) => result,
        Err(error) => {
            eprintln!("pt: configuration_error: {error}");
            return 4;
        }
    };
    if let Some(report) = &mut report
        && let Err(error) = report.publish(&result)
    {
        eprintln!(
            "pt: infrastructure_error: report publication failed: {error}; process result: {result:?}"
        );
        return 3;
    }
    if !matches!(result.termination, Termination::ProcessExited)
        || matches!(result.cleanup, Cleanup::Uncertain { .. })
    {
        eprintln!(
            "pt: {:?}; cleanup: {:?}",
            result.termination, result.cleanup
        );
    }
    result.exit_code()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn invalid_or_ambiguous_cli_durations_and_options_are_rejected() {
        for args in [
            vec!["run"],
            vec!["exec", "python"],
            vec!["exec", "--", ""],
            vec!["exec", "--timeout-seconds", "NaN", "--", "python"],
            vec!["exec", "--timeout-seconds", "inf", "--", "python"],
            vec!["exec", "--timeout-seconds", "0", "--", "python"],
            vec!["exec", "--cleanup-seconds", "31", "--", "python"],
            vec!["exec", "--cwd", ".", "--cwd", ".", "--", "python"],
            vec!["exec", "--unknown", "--", "python"],
        ] {
            assert!(parse(args.into_iter().map(OsString::from).collect()).is_err());
        }
    }
}
