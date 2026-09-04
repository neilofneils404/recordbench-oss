# Public-release checklist

No GitHub publication or public image push is authorized until every item is
complete.

## Required local gates

Run the generic gate against the complete candidate history:

```bash
python scripts/publication-check.py
```

During the private publication review, keep organization-specific names,
domains, network markers, and known secret fingerprints in an owner-only file
outside the clone, then run:

```bash
python scripts/publication-check.py --deny-file /secure/path/private-deny.txt
```

Never commit that deny file or copy its matched values into a report. The
scanner reports only rule names and redacted locations. `--skip-history` is for
diagnosing a proposed clean tree; it is not a publication gate.

If an owner deny term also appears inside the repository's exact public GitHub
clone URL or verified GitHub no-reply identity, keep the deny term and pass an
explicit, owner-approved adjudication. `--allow-public-clone-url` applies only
to an exact URL token in `README.md`; `--allow-public-git-identity` requires an
exact username/no-reply pair; and `--allow-public-baseline-git-identity`
requires an exact commit boundary, display name, and no-reply address. These
options do not suppress the same deny term in files, commit messages, later
legacy-identity commits, or near-match URLs.

Run the repository's supported quality commands from a fresh environment:

```bash
make compile
make compose-check
make publication-check
make test
make test-transcription
```

The scanner depends on `ffprobe` for media metadata and `pypdf` for PDF
inspection. Missing inspection tooling blocks rather than silently skipping the
artifact.

## Approval checklist

- Organization approves the project name, copyright ownership, and full
  Apache-2.0 license text.
- First-party transcription code is approved for release.
- Dependency, container, font/icon, and model license/attribution inventory is
  complete; gated model terms are documented but no token is present.
- Full tree and every commit pass the internal-domain, private-IP, personal-name,
  path, private key/certificate, database, secret-shaped literal, extracted
  PDF/archive, and known-secret scanners.
- Synthetic fixtures contain no case/client material or derived text.
- Images and dependencies are pinned with an update policy and vulnerability
  scan; no critical unreviewed finding remains.
- Main and bundled transcription tests, static checks, Compose validation,
  container health, and browser acceptance pass.
- A clean Linux host completes local, OIDC, and Kerberos playbooks as applicable.
- OCR, RAG, partial-source, 1k/10k metadata, transcription, export, close/purge,
  backup, and new-target restore acceptance pass.
- Installer works interactively, without color, non-interactively, in dry-run,
  on failure, and on resume without printing secrets.
- Public README states limitations, hardware expectations, retention, privacy,
  and support policy accurately.
- Private-repository review completes before changing visibility to public.

## History and identity decision

A follow-up cleanup commit is insufficient when a prior reachable commit or tag
contains attribution or deployment residue. Prefer a newly initialized clean
root made only from the approved tree. Alternatively, an owner may explicitly
authorize a history rewrite and force push after reviewing the exact diff and
rollback bundle. Before either action, decide whether a personal author email
may be public or whether release commits should use the maintainer's verified
GitHub no-reply address.
