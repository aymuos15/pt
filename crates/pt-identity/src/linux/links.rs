use super::{
    IdentityError, Result, TreeEntry, TreeKind, TreeManifest, TreeObservation, check, field, hex,
    require,
};
use sha2::{Digest, Sha256};
use std::collections::VecDeque;
use std::os::unix::ffi::OsStrExt;
use std::path::Path;

pub const RELATIVE_LINK_POLICY_ID: &str = "linux-declared-relative-link-closure-v1";

/// Additional explicit graph bounds; construction/graph verification and both
/// native tree walks share the manifest's original absolute deadline.
#[derive(Clone, Copy, Debug)]
pub struct LinkLimits {
    pub steps: u64,
    pub dereferences: u8,
    pub pending_components: usize,
}
impl LinkLimits {
    fn validate(self) -> Result<()> {
        require(
            (1..=1_000_000).contains(&self.steps)
                && (1..=40).contains(&self.dereferences)
                && (1..=4096).contains(&self.pending_components),
            "tree_link_limits_invalid",
        )
    }
}

/// A checked declared relative-link graph plus the same manifest's two native
/// byte walks. No outside referent is opened. This is not runtime/host/environment
/// closure, continuous immutability, generation currency or launch authority.
#[derive(Debug)]
pub struct ClosedLinkObservation {
    tree: TreeObservation,
    links: usize,
    steps: u64,
    max_hops: u8,
    digest: String,
}
impl ClosedLinkObservation {
    pub fn tree(&self) -> &TreeObservation {
        &self.tree
    }
    pub fn policy_id(&self) -> &'static str {
        RELATIVE_LINK_POLICY_ID
    }
    pub fn links(&self) -> usize {
        self.links
    }
    pub fn resolution_steps(&self) -> u64 {
        self.steps
    }
    pub fn maximum_dereferences(&self) -> u8 {
        self.max_hops
    }
    pub fn resolution_sha256(&self) -> &str {
        &self.digest
    }
    /// Explicitly discard the extra graph observation; this cannot upgrade the
    /// original tree token to complete environment/immutable-generation evidence.
    pub fn into_tree(self) -> TreeObservation {
        self.tree
    }
}

impl TreeManifest {
    /// Opt-in relative-link closure. Ordinary `verify` remains link-text-only.
    /// Absolute, escaping, dangling, cyclic/over-bound or non-directory traversal
    /// is unsupported, not normalized into agreement or resolved against the host.
    pub fn verify_with_closed_links(
        &self,
        root: &Path,
        limits: LinkLimits,
    ) -> Result<ClosedLinkObservation> {
        limits.validate()?;
        check(self.limits.deadline)?;
        let links = self
            .entries
            .values()
            .filter(|entry| matches!(entry.kind, TreeKind::Symlink { .. }))
            .count();
        let mut digest = Sha256::new();
        digest.update(b"pt-declared-link-resolution-v1\0");
        field(&mut digest, self.digest.as_bytes());
        digest.update((links as u64).to_be_bytes());
        let mut steps = 0;
        let mut max_hops = 0;
        for entry in self.entries.values() {
            check(self.limits.deadline)?;
            if let TreeKind::Symlink { target } = &entry.kind {
                let resolved = self
                    .resolve_relative_link(entry, target, limits, &mut steps)
                    .map_err(|error| error.for_path(&entry.path))?;
                max_hops = max_hops.max(resolved.hops);
                field(&mut digest, entry.path.as_os_str().as_bytes());
                field(&mut digest, &resolved.path);
                digest.update([if resolved.directory { 0 } else { 2 }]);
            }
        }
        check(self.limits.deadline)?;
        let tree = self.verify(root)?;
        require(
            tree.symlinks() == links,
            "tree_link_observation_domain_mismatch",
        )?;
        check(self.limits.deadline)?;
        Ok(ClosedLinkObservation {
            tree,
            links,
            steps,
            max_hops,
            digest: hex(&digest.finalize()),
        })
    }

    fn resolve_relative_link(
        &self,
        source: &TreeEntry,
        target: &[u8],
        limits: LinkLimits,
        steps: &mut u64,
    ) -> Result<Resolution> {
        let mut current = source
            .path
            .parent()
            .expect("relative leaf has a parent")
            .as_os_str()
            .as_bytes()
            .to_vec();
        let mut pending = VecDeque::new();
        enqueue(&mut pending, target, limits.pending_components)?;
        let mut hops = 1u8; // The initial source link counts toward Linux's bound.
        while let Some(component) = pending.pop_front() {
            check(self.limits.deadline)?;
            require(*steps < limits.steps, "tree_link_component_step_bound")?;
            *steps += 1;
            // Resolve in actual component order. In particular, neither a
            // symlink/.. nor a regular-file/.. may be lexically collapsed first.
            require(
                current.is_empty()
                    || self
                        .entries
                        .get(&current)
                        .is_some_and(|entry| matches!(entry.kind, TreeKind::Directory)),
                "tree_link_non_directory_component",
            )?;
            match component {
                b"" | b"." => {}
                b".." => {
                    require(!current.is_empty(), "tree_link_exits_declared_root")?;
                    parent(&mut current);
                }
                name => {
                    if !current.is_empty() {
                        current.push(b'/');
                    }
                    current.extend_from_slice(name);
                    require(current.len() <= 4096, "tree_link_resolved_path_bound")?;
                    let entry = self
                        .entries
                        .get(&current)
                        .ok_or_else(|| IdentityError::new("tree_link_target_not_declared"))?;
                    if let TreeKind::Symlink { target } = &entry.kind {
                        require(
                            hops < limits.dereferences,
                            "tree_link_dereference_bound_or_cycle",
                        )?;
                        hops += 1;
                        parent(&mut current);
                        enqueue(&mut pending, target, limits.pending_components)?;
                    }
                }
            }
        }
        let directory = current.is_empty()
            || self
                .entries
                .get(&current)
                .is_some_and(|entry| matches!(entry.kind, TreeKind::Directory));
        Ok(Resolution {
            path: current,
            directory,
            hops,
        })
    }
}

struct Resolution {
    path: Vec<u8>,
    directory: bool,
    hops: u8,
}
fn parent(path: &mut Vec<u8>) {
    let length = path.iter().rposition(|byte| *byte == b'/').unwrap_or(0);
    path.truncate(length);
}
fn enqueue<'a>(pending: &mut VecDeque<&'a [u8]>, target: &'a [u8], bound: usize) -> Result<()> {
    require(
        !target.starts_with(b"/"),
        "tree_link_absolute_target_unsupported",
    )?;
    for component in target.rsplit(|byte| *byte == b'/') {
        require(pending.len() < bound, "tree_link_pending_component_bound")?;
        pending.push_front(component);
    }
    Ok(())
}
