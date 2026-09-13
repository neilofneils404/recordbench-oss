# Understand an installation blocker

Run commands from the reviewed checkout as the dedicated service account. Start
with the [installation playbook](INSTALL.md) for account creation and a complete
CPU installation. These diagnostics do not change permissions, stop workloads,
download models, or repair the node automatically.

## Docker access

Preflight distinguishes a denied diagnostic, an unreachable engine, a timeout,
and an unclassified failure. A permission error does not mean Docker is absent.

1. Start a fresh service-account login session and run `docker info` and
   `docker compose version` there. Supplementary group changes need a new session.
2. Check the selected Docker context and any `DOCKER_HOST` or `DOCKER_CONTEXT`
   override locally. A remote or rootless engine may have different access
   requirements from the usual local socket.
3. Have the administrator verify access to the selected endpoint. For a Unix
   socket, inspect its actual group and ACL rather than assuming a group name.
   Grant only approved engine access; it is privileged. Never make the socket
   world-writable or run the application as root to bypass preflight.

If the connection is unavailable, check engine startup and supervision. The
[atypical-host guidance](INSTALL.md#atypical-docker-hosts) covers hosts without
systemd as PID 1. A timeout or unclassified failure needs local inspection of the
underlying command. Raw Docker output can contain private host information and
does not belong in a public issue.

## Storage ancestors

The node directory and its existing creation directory must belong to the
service account. Every parent must remain accessible and protected from
replacement by another account. Owning only the final directory is insufficient.

Preflight now identifies the reason without printing the path or account name:
relative path, symlink, reserved root, directory type, ownership, read/search
access, or shared write permissions. It distinguishes the existing creation
directory from a protected ancestor.

An administrator can inspect a proposed standard location locally with:

```bash
namei -l /srv/recordbench
```

If `namei` is unavailable, inspect each directory's owner, mode and ACL with the
distribution's filesystem tools. Keep that output private. The usual correction
is to prepare a dedicated directory beneath a trusted parent, following the
playbook. Do not recursively change ownership of a shared workspace or weaken
the ancestry checks to make a leaf directory pass.

## Available memory

The nonblocking `memory` row reports the installer's process view of total and
available RAM. It uses Linux `MemAvailable`, then applies finite visible cgroup
v1/v2 limits and remaining budgets through mounted ancestors. An unreadable or
unsupported hierarchy is explicitly unknown. Unlimited cgroups retain the
system memory observation.

The planning targets are 16 GiB for CPU evaluation, 32 GiB for review models,
and 64 GiB for transcription or all models. A smaller total or less than half
the target currently available produces a note. These are advisory planning
figures, not measured minimums, and a passing observation does not guarantee
build or runtime capacity.

Memory belongs to the installer process's environment. A Docker daemon reached
through a Unix socket can still have different host or cgroup limits. A remote
or TCP endpoint is explicitly unmeasured, and an unknown endpoint never receives
a positive engine-memory claim. Check the actual engine host before proceeding.
Coordinate competing builds or existing nodes with their owners; the installer
does not stop another workload to free RAM.

## Share a diagnostic receipt

```bash
./install diagnostics --root /srv/recordbench
```

This command always prints one JSON document. For a saved installation it restores
the validated node's choices automatically. For a fresh node, supply the same
non-secret selection flags intended for preflight. Exit status is 0 if the
reported blocking prerequisites pass, and 1 otherwise. A failed command still
prints a receipt, so capture its output before checking the exit status.

The version 1 receipt contains:

- The public launcher version and a strictly shaped installed release identifier
  when available.
- Fixed authentication/profile choices and the content-free preflight checklist.
- Saved phase enums labelled `historical-not-refreshed`, or an unavailable state.
- Explicit `not-probed`/`not-verified` states for live health, model bytes and
  browser sign-in.

It never runs Compose service commands, changes the phase receipt, consumes
passwords/tokens, hashes the model cache, or includes raw logs, hostnames, paths,
account names, URLs, source content, or arbitrary configuration fields. Unsafe
saved coordinates produce a fixed failure; they do not trigger a fresh install.
Saved phases can be stale even when marked complete. Use `doctor` and the
[first-run acceptance steps](FIRST_RUN.md) to establish current runtime and
browser results separately.

Review the JSON before attaching it to a public issue. Do not append raw logs,
shell environment dumps or configuration files. The receipt describes the
limited checks performed; it does not certify an installed node or a workload.

## Selected capability health

New installations record `CASE_INTELLIGENCE_MODEL_PROFILE` from the selected
`none`, `review`, `transcription`, or `all` profile. The application's `/health`
response includes fixed `selected_capabilities` booleans. Unselected answers,
meaning search and transcription say `not selected`; configured capabilities
that are unavailable retain `temporarily unavailable`.

The response also exposes the running `release_id` supplied by the release's
Compose environment. Only the public version-plus-capsule-digest shape is
accepted; missing or invalid values produce `development`, never arbitrary
environment text. Installed acceptance compares that value to the selected
installation record. A matching checkout alone does not identify a running node.

Top-level `ok` requires source review, storage, required malware scanning, and
the selected optional capabilities to pass their readiness interfaces. Healthy
CPU evaluation can therefore be `ok` with word search. A ready generator cannot
hide failed scanning or a selected missing retrieval/transcription capability.
The installer keeps useful basic review separate from a selected model failure.

Older nodes without the profile field conservatively infer optional selection
from retained configuration. A configured retrieval URL can keep such a node
degraded even if it was intended for CPU use; record the reviewed node's actual
profile explicitly rather than hiding an unknown selection. The reviewed update path records the saved installation profile in the new
application environment; update rollback restores the prior environment.
Explicitly supplied generator/media clients still count as selected, including
synthetic test clients.

Readiness has practical limits. Remote retrieval health is checked when the
runtime initialized its remote adapters, while database readiness also depends
on the retained projection state. The existing transcription client reports
local credential readiness; it does not establish worker model loading or a
completed recording. The synthetic first-run and selected-model acceptance
steps remain necessary before reporting those outcomes.
