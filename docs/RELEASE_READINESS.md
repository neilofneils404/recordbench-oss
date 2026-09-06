# Release readiness

RecordBench is a serious alpha, not yet a self-service public release. Feature
work should not outrun proof that an unfamiliar operator can install, recover,
update, and support the product without private deployment knowledge.

## Supported-profile objective

- **Evaluation:** CPU-only, synthetic data, local identity, document intake,
  extraction, lexical search, manual review, export, and deletion.
- **Review:** one or more supported NVIDIA GPUs, learned retrieval and
  reranking, and a pinned local generator.
- **Full:** Review plus modular ASR/alignment and optional separately accepted
  diarization.

GPU count is adaptive rather than an edition boundary. One supported GPU is a
valid full-profile target; larger hosts separate service lanes automatically or
accept explicit assignments. Hardware support still requires a receipt from
the exact card, VRAM, driver, runtime, collection, and concurrency shape.

## First-party release authorization

The maintainer has confirmed that release of RecordBench's first-party code
under Apache-2.0 is approved. This records the maintainer-confirmed approval
status; it does not complete third-party license review, sanitization, or
deployment acceptance. Keep any supporting private approval records outside
this repository.

## Contributor source publication

The maintainer authorizes an environment-neutral public contributor alpha
under the [public-alpha requirements](PUBLIC_ALPHA.md). This separates source
collaboration from a supported binary/container release. Sanitization, private
data exclusion, ownership, applicable license notices, and review gates remain
mandatory. No supported-deployment or quality claim follows from public access.

## Supported-release requirements

The following evidence is required before declaring a supported release or
distributing first-party production images:

1. documented first-party ownership/publication authorization;
2. complete dependency, container, and model-license review;
3. a clean new root or explicitly approved history rewrite and author-email
   decision;
4. locked Python resolution, digest-pinned build inputs, image SBOMs,
   vulnerability scans, checksummed release artifacts, and provenance;
5. green hosted CI plus clean-host CPU evaluation acceptance;
6. acceptance receipts from a supported one-GPU review node and full media
   node;
7. browser/accessibility, OIDC, and representative Kerberos acceptance;
8. encrypted backup, bare-metal restore, update, rollback, and queued-work
   restart evidence;
9. versioned retrieval, citation, classification, transcription, latency, and
   resource evaluation artifacts before publishing quality claims;
10. an installation performed by an unfamiliar operator using only the public
    playbook.

No bundled synthetic-policy benchmark is a production quality or throughput
claim. Until an executable evaluation artifact exists, the UI reports that
deployment evaluation is required.

## Supported-release procedure

1. Freeze and hash a private rollback bundle.
2. Run the generic scanner and an external private deny file over the tree and
   every reachable Git object.
3. Run an independent secret scanner and adjudicate every candidate without
   copying possible values into logs.
4. Inspect document, archive, image, audio, and video metadata and render
   documents visually.
5. Complete all tests and deployment acceptance lanes.
6. Review the complete local diff, GitHub access, deploy keys, Actions
   artifacts, variables, releases, Pages, and packages.
7. Obtain the required approvals.
8. Create the approved clean history, verify it again, and only then request
   explicit authorization to push or change visibility.
