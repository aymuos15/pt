use std::process::ExitCode;

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
mod linux;

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn main() -> ExitCode {
    ExitCode::from(linux::main())
}

#[cfg(not(all(target_os = "linux", target_arch = "x86_64")))]
fn main() -> ExitCode {
    eprintln!("pt: unsupported_profile: this development CLI targets Linux x86-64 only");
    ExitCode::from(4)
}
