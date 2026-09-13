# Try RecordBench on Linux

Start with two invented records: upload them, find a word, read the originals,
save a case note and export it. The **CPU evaluation** profile needs no GPU,
model download, Hugging Face account or token. Generated answers, meaning-based
retrieval and transcription are optional later profiles.

Use a dedicated **Ubuntu 24.04 x86-64** host or VM with systemd, an administrator
login with sudo, and internet access for packages, images and ClamAV signatures.
The current planning target is 8 CPU cores, 16 GB RAM and **150 GB free SSD**
before source data, including a 100 GiB safety reserve. These are alpha planning
figures, not validated minimums or an installation-time guarantee. For a smaller
contributor machine, [make dev](../CONTRIBUTING.md#open-the-synthetic-development-preview)
provides a disposable synthetic preview.

This guide defines a repeatable alpha path. A complete fresh-host installation
and the Firefox trust journey still need independent acceptance on the exact
candidate revision; local tests alone do not establish either. Use synthetic
material throughout. Other distributions and nested Docker hosts use the
[operator playbook](INSTALL.md).

## Prepare the new host once

As your **administrator login**, install Docker from its official Ubuntu
repository. These commands are for a fresh Ubuntu 24.04 amd64 machine; if Docker
or containerd already exists, follow [Docker's installation instructions](https://docs.docker.com/engine/install/ubuntu/)
to reconcile its packages first.

```bash
sudo apt-get update
sudo apt-get install --yes ca-certificates curl git openssl python3
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<'EOF'
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: noble
Components: stable
Architectures: amd64
Signed-By: /etc/apt/keyrings/docker.asc
EOF
sudo apt-get update
sudo apt-get install --yes docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo groupadd --system recordbench
sudo useradd --system --gid recordbench --groups docker \
  --home-dir /var/lib/recordbench-home --shell /bin/bash recordbench
sudo install -d -m 0700 -o recordbench -g recordbench /var/lib/recordbench-home /srv/recordbench
sudo -iu recordbench
```

The last command enters a fresh **recordbench service-account** session with the
correct HOME and Docker group. Docker group membership grants privileged engine
access ([Docker documentation](https://docs.docker.com/engine/install/linux-postinstall/)).
Keep the account dedicated to this node. The steps deliberately create only its
home and empty node directory; do not rerun account creation on an existing node.

## Prepare and start the CPU node

Run these commands as the **recordbench service account**:

```bash
docker info >/dev/null
docker compose version
git clone https://github.com/neilofneils404/recordbench-oss.git recordbench-src
cd recordbench-src
git rev-parse HEAD
python3 scripts/evaluation-tls.py --output /var/lib/recordbench-home/evaluation-tls
./install preflight --root /srv/recordbench --models none --auth local \
  --enable-account-management --server-name localhost --bind-address 127.0.0.1 \
  --tls-cert /var/lib/recordbench-home/evaluation-tls/tls.crt \
  --tls-key /var/lib/recordbench-home/evaluation-tls/tls.key --no-color
```

Record the commit ID. The TLS helper creates a 30-day localhost certificate and
a dedicated public CA certificate; it discards the CA signing key. It refuses
to overwrite an existing directory. Resolve any preflight **BLOCK** before
continuing. The [prerequisite reference](INSTALL.md#inspect-prerequisites-without-installing)
explains each check. Keep more than the reserve free after image builds too.

The next commands run in Bash. Choose a password of 14–1,024 characters. Silent
terminal input keeps it out of shell history and command arguments; the installer
receives it through stdin. Do not enable shell tracing (`set -x`). No model token
is needed.

```bash
(
  set +x
  set -e
  trap 'unset alpha_password' EXIT
  read -r -s -p 'Initial alpha administrator password: ' alpha_password
  printf '\n'
  printf '%s\n' "$alpha_password" | ./install install \
    --root /srv/recordbench --models none --auth local --enable-account-management \
    --server-name localhost --bind-address 127.0.0.1 \
    --tls-cert /var/lib/recordbench-home/evaluation-tls/tls.crt \
    --tls-key /var/lib/recordbench-home/evaluation-tls/tls.key \
    --admin-username alpha-admin --admin-display-name 'Alpha administrator' \
    --non-interactive --password-stdin --prepare-only --no-color
)
```

Continue only when preparation succeeds. **Prepared** means configured and built;
the browser is not running yet. Start the prepared node and check it:

```bash
./install install --root /srv/recordbench --resume --non-interactive --no-color
./install doctor --root /srv/recordbench
```

Wait for **Basic review** to become ready. CPU evaluation can report optional AI
as unavailable. If startup fails, follow the reported next action and
[startup troubleshooting](INSTALL.md#startup-troubleshooting), then rerun resume
and doctor. Avoid repeated image builds or tight signature-download retries.
Use `./install diagnostics --root /srv/recordbench` for a content-minimized
JSON receipt and [installation diagnostics](INSTALL_DIAGNOSTICS.md) for remedies.
If preparation stopped before administrator creation, resume with
`--password-stdin` and supply the password through the same protected pipe.
Existing accounts do not need their password supplied again. See
[interrupted-install recovery](FIRST_RUN.md#continue-an-interrupted-installation).

## Open it from your laptop

Keep the server listener on loopback. Use your existing SSH administrator login;
the service account does not need remote login. In the server's service-account
terminal, print the public CA fingerprint and return to the administrator shell:

```bash
openssl x509 -in /var/lib/recordbench-home/evaluation-tls/ca.crt -noout -fingerprint -sha256
exit
sudo cat /var/lib/recordbench-home/evaluation-tls/ca.crt > "$HOME/recordbench-evaluation-ca.crt"
```

On your **laptop**, substitute your existing SSH destination for `alpha-host`.
Use the same verified SSH host identity you used to prepare the machine:

```bash
scp alpha-host:recordbench-evaluation-ca.crt ./recordbench-evaluation-ca.crt
openssl x509 -in recordbench-evaluation-ca.crt -noout -fingerprint -sha256
ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:8443:127.0.0.1:8443 alpha-host
```

Compare the two SHA-256 fingerprints before trusting the certificate. Copy only
`ca.crt`; never copy `tls.key`. Leave the tunnel terminal open. If local port
8443 is occupied, stop its known owner before proceeding so the browser URL and
configured origin remain identical. On the server itself, the same browser URL
works without a tunnel.

Use a separate **Firefox evaluation profile**, with no personal browsing or
Sync account. Open `about:profiles`, create a profile named **RecordBench alpha**,
and launch it without making it your default. In that profile's settings, find
**Certificates → View/Manage Certificates → Authorities → Import**, select
`recordbench-evaluation-ca.crt`, and enable trust for identifying websites.
This is explicit trust of your generated evaluation CA in that profile, not a
browser certificate-error exception or system-wide trust change. Mozilla
documents [profiles](https://support.mozilla.org/en-US/kb/profile-management)
and [manual CA trust](https://wiki.mozilla.org/CA/Changing_Trust_Settings).

Open **https://localhost:8443** in that profile. The name must be `localhost`;
the remote hostname is not on this certificate. The browser must accept TLS
without an exception before you sign in as **alpha-admin**. A certificate error
means stop and check the fingerprint, profile trust, name, clock and 30-day
expiry. Do not proceed through a warning. Remove the evaluation profile when
finished. For ongoing or staff access, provision trusted operator TLS and use
the [installation playbook](INSTALL.md); this certificate is temporary.

## Review your first two records

Download the two `.txt` files from
[the synthetic practice folder](../examples/synthetic-alpha/) to your laptop.
Create **Lantern practice**, upload both through **Sources**, wait for readiness,
then search for **lantern** and read both originals. Save the case note in the
[practice instructions](../examples/synthetic-alpha/README.md). Open **Work product
→ Export matter bundle**, download the ZIP and verify the saved note. The bundle
exports work product; it does not include the original uploaded files.

You have now exercised a small solo review without an AI model. Next, try
[team setup](FIRST_RUN.md#first-administrator-in-the-browser), or follow
[backup and restore](STORAGE_AND_BACKUP.md) before relying on saved work.
Matters are temporary; export before stopping a disposable experiment or closing
a matter. Tell us the commit, generic OS/CPU/RAM, last successful step and the
content-free symptom if anything failed. Do not attach raw logs, credentials,
private host details or real records. The [contributor backlog](CONTRIBUTOR_BACKLOG.md)
welcomes installation feedback as well as code.
