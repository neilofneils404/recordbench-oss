# Standalone Apple Silicon evaluation

This **very-alpha** installation runs entirely on one Apple Silicon Mac. It does
not connect to another RecordBench deployment or require a VPN. Linux remains
the production reference; a successful Mac launch is not production qualification.
Use synthetic material until the acceptance work below is complete.

## Runtime design

A dedicated Colima ARM64 Linux VM runs PostgreSQL/pgvector, ClamAV, the application,
OCR and media tools, CPU retrieval, and CPU WhisperX transcription. This retains
Linux `openat2` path containment, parser resource limits, internal Docker networks,
and the transcription worker's `network_mode: none`. Running the application
straight under macOS Python would lose those existing platform contracts.

The native Ollama generator uses Apple Metal and listens only on
`127.0.0.1:11435`. The app reaches it through the reserved
`host.docker.internal` alias. Lima maps the host loopback into the VM; this must
be tested on the installed Colima version rather than fixed by binding a model
server to the LAN. See [Lima host networking](https://lima-vm.io/docs/config/network/user/).
The native generator launcher disables cloud features and uses a macOS sandbox
that rejects outbound network access except loopback. It uses a dedicated model
vault, not the user's existing Ollama service or model directory.

The gateway alone publishes `127.0.0.1:8443`. Local accounts, secure session
cookies, CSRF, matter authorization, and the source-verification pipeline remain
enabled. The initial certificate is self-signed for localhost. No CA is installed
in the system trust store. Do not use this local profile for LAN or remote access.

## Initial setup

The development target is a 32 GB Apple Silicon Mac with enough SSD space for
models, images, temporary processing, and a 15 GiB data reserve. The VM starts
with four CPUs and 12 GiB RAM; its 40 GiB data disk is sparse. These are evaluation
settings, not validated minimums or performance guarantees. macOS and the VM
share physical storage; monitor both rather than adding their free-space totals.

Install these public dependencies with Homebrew:

```sh
brew install colima docker docker-compose docker-buildx ollama
```

Follow Homebrew's Docker plugin instructions so `docker compose version` and
`docker buildx version` work. Docker Compose 2.24.4 or later is required. Python
3.12 or later is needed for the launch scripts. Run from the repository root:

```sh
python3 scripts/mac-install.py plan
python3 scripts/mac-install.py vm
python3 scripts/mac-install.py configure --capabilities all
python3 scripts/mac-install.py build
python3 scripts/mac-install.py init
```

`init` asks for an administrator password without echo. The account is
`recordbench.admin`. For unattended synthetic evaluation, `init --generate-password`
stores a generated password in the node's owner-only
`secrets/initial-admin-password` file. Do not paste it into chat, commit it, or
include it in logs. The default node directory is
`~/Library/Application Support/RecordBench`; `--root` can select another dedicated
absolute directory outside the source tree. Configuration, accounts, certificates,
models, runtime data, and content-addressed release capsules stay there.

The VM is named `recordbench`; commands select Docker context `colima-recordbench`
explicitly and do not change the global Docker context or forward an SSH agent.
Docker commands ignore inherited RecordBench, Compose, and remote-daemon shell
overrides so the selected node's configuration controls its storage and services.
The VM only needs the node directory mounted writable. The initial installer
supports local accounts and optional `none`, `review`, or `all` capabilities.
`none` is core evaluation only; the full standalone target uses `all`.

## Model staging and launch

The native model artifact and its integrity/readiness commands are described in
[Mac models](MAC_MODELS.md). Stage the native generator once and run its `serve`
command in a dedicated terminal. Review staging is explicit and online; runtime
loading must be offline.

Stage the existing pinned embedding/reranking models without redundantly
fetching the Linux generator. Stage ASR and English alignment for transcription.
Use the installed release's Compose file and node environment, with the dedicated
Docker context, to run the `model-stager` tools service:

```sh
python3 scripts/mac-install.py stage-models
```

Then launch and check the selected capabilities:

```sh
python3 scripts/mac-install.py start
python3 scripts/mac-install.py doctor
```

`start` launches containers; `doctor` is the separate readiness check. Open
[the local application](https://localhost:8443) after readiness succeeds.
The self-signed localhost certificate may require a browser exception.

Retrieval runs synthetic offline embedding and reranking probes before serving,
so startup cannot deadlock waiting for its first application request. `doctor`
checks the selected service processes and the native generator artifact digest;
its separate `quality_accepted` field must not be inferred from runtime readiness.
Interrupted configuration can be retried with the same `configure` command before
storage/accounts initialization; completed nodes are never silently reconfigured.

Stop the application containers without deleting data:

```sh
python3 scripts/mac-install.py stop
```

Stop the native generator with Ctrl-C in its terminal. Stop the VM with
`colima stop recordbench`. Do not use `docker compose down --volumes` as a routine
stop operation. The Linux installer/update/backup scheduler does not manage this
Mac node. Upgrade and backup/restore automation for this profile remain open
qualification work; never repoint an installed node at an unreviewed checkout.

## Acceptance boundary

Passing configuration and unit tests does not establish model quality or a usable
full installation. Record the exact Mac/runtime versions and model artifacts;
verify these with synthetic inputs:

- offline generator integrity and frozen model evaluation;
- actual embedding and reranking load/inference, not only an HTTP response;
- login, rendered styling and interactive controls at the configured HTTPS port,
  matter creation, PDF/text/DOCX intake, OCR, search, and cited answers;
- timestamped transcription and export from a short synthetic recording;
- account/matter isolation, excluded-source notices, cancellation, closure,
  cleanup, and restart persistence;
- memory/disk pressure and clean backup/restore before production claims.

Diarization is optional, separately gated, and not enabled by this setup. CPU
transcription can be substantially slower than CUDA; no throughput claim is made.
Model results remain machine suggestions requiring source review.

## Reporting problems during the alpha

Track installation and portability findings in the
[Mac alpha issue](https://github.com/neilofneils404/recordbench-oss/issues/33).
Report the public software versions, the failed step, expected behavior, and a
synthetic reproduction. Keep account files, model/runtime state, certificates,
private paths, and real source material out of reports.

Fix shared application defects in the portable implementation and add a
regression before adopting them in another deployment. Platform-specific launch
settings belong in the Mac profile; Linux CUDA defaults remain unchanged.
A health response alone does not verify browser styling, interactive controls,
model output quality, or recovery. Check each separately.
