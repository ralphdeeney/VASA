# VPS deployment and activation through SSH

Current speech package: Kokoro INT8 is the default; Piper is optional through
`VASA_TTS_PROVIDER=piper`. `prepare_speech.py` prepares both pinned models in
the existing speech volume and no longer prepares LJSpeech. Apply migration
0006 before starting the current voice worker. STT/TTS default to one native
thread, and the prepared voice container has a two-CPU limit. See
[optimized evaluation and manual commands](tts-evaluation/kokoro-int8-vps/optimized/README.md).
These are prepared deployment changes; no live VPS activation is claimed.

This package is prepared for the existing `vasa-builder` rootless Docker user
at `2.25.172.155`, under `/opt/vasa`. No VPS connection or changes have been made
by Codex. The user confirmed the address/port and SSH availability externally;
the cloud's direct retry remains refused and its proxy closes before the SSH
handshake. Connectivity from this environment must be resolved before remote
deployment. It uses a separate Compose project,
`vasa-vps`; it does not change
existing host services, reverse proxies, firewall rules or Docker installations.

Evolution's API and bundled Manager share one port. The upstream README's
8080 is an example; this package runs Evolution on container port 4000 and
publishes it only on VPS loopback port 18080 by default. VASA uses loopback
18081. Both defaults must be free; preparation refuses unrelated occupied ports.
PostgreSQL and Redis have no published host ports.

## Prepare the existing rootless user

Connect from your computer:

```bash
ssh vasa-builder@2.25.172.155
```

Use the already configured rootless Docker context. The following commands must
work as this user, without sudo:

```bash
docker info --format '{{json .SecurityOptions}}'
docker compose version
git --version
patch --version
uv --version
```

Docker security options must include `name=rootless`; `deploy/up.sh` refuses
root and a system Docker daemon. If uv is not installed, use its official pinned
user installer, preserving HTTPS verification:

```bash
curl --fail --show-error --location https://astral.sh/uv/0.12.19/install.sh -o /tmp/vasa-uv-install.sh
sh /tmp/vasa-uv-install.sh
export PATH="$HOME/.local/bin:$PATH"
uv python install 3.12
```

`/opt/vasa` must be owned/writable by `vasa-builder`. If it is not yet prepared,
an administrator can create only that directory; no service changes are needed:

```bash
sudo install -d -m 0750 -o vasa-builder -g "$(id -gn vasa-builder)" /opt/vasa
```

Run the remaining work as `vasa-builder`. For a fresh, empty directory:

```bash
git clone --branch build/vasa-foundation https://github.com/ralphdeeney/VASA.git /opt/vasa
cd /opt/vasa
git rev-parse HEAD
```

Keep the recorded revision for rollback. If a checkout or files already exist,
inspect and preserve them instead of cloning over them or resetting local work.
Use existing GitHub authentication for a private repository; do not put a token
in the clone URL or chat.

## Generate private configuration and deploy

The generator creates independent VPS credentials with cryptographic randomness
and mode 0600, under a mode-0700 `.local/` directory. It never prints secret
values and preserves an existing valid file. Do not copy the cloud's private
configuration; generate it on the server where activation and sessions will live.

```bash
cd /opt/vasa
uv sync --frozen
uv run --frozen python scripts/prepare_vps.py --check-ports
bash deploy/up.sh
```

If a default port is occupied, choose two unused ports on the first preparation:

```bash
uv run --frozen python scripts/prepare_vps.py --evolution-port 18180 --api-port 18181 --check-ports
```

Once the file exists, passed defaults do not overwrite its ports. Edit only the
two non-secret port bindings in your private editor before starting/recreating
services if a change is needed. The Docker bind itself is the final collision
check; another process taking a port between checks causes startup to fail.

The deployment helper verifies rootless Docker, checks ports, prepares the exact
reviewed Calls source, builds both images, starts database/cache/Evolution, runs
explicit VASA migrations, and then starts VASA. It touches only this project.
An inactive vendor license is expected before activation; provider health does
not mean calls are enabled.

Inspect status without rendering the secret-containing Compose configuration:

```bash
docker compose --env-file .local/vps.env -f deploy/compose.yaml ps
docker compose --env-file .local/vps.env -f deploy/compose.yaml exec -T vasa python scripts/evolution_status.py
curl --fail --silent http://127.0.0.1:18081/health/ready
```

Substitute configured ports in curl/tunnel commands when using different ones.
The VASA container uses production settings and secure session cookies. Public
client access requires HTTPS; this package does not install or modify a host
reverse proxy. The SSH tunnel below is for private Evolution administration.

## Open the Manager from your computer

In a separate terminal on your computer, keep this SSH tunnel running:

```bash
ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:18080:127.0.0.1:18080 vasa-builder@2.25.172.155
```

Open `http://localhost:18080/manager/login` in that computer's browser.
Enter the API URL `http://localhost:18080`. In your own private SSH terminal,
open `/opt/vasa/.local/vps.env` in an editor and copy the `GLOBAL_API_KEY` value
directly into the official Manager. Do not share the key in chat, screenshots,
Git or logs. Do not change it to an activation code: it is the administrator
key, separate from the vendor's runtime license.

Complete the Manager's official vendor registration/activation flow. It uses
the server's registration endpoint and exchanges the vendor's authorization code
through `/license/activate`. No activation bypass is included. Registration or
payment terms must be checked with the vendor; this package does not establish
whether your use requires payment. The repository's licensing contact is
`suporte@evofoundation.com.br`.

Verify from the VPS:

```bash
cd /opt/vasa
docker compose --env-file .local/vps.env -f deploy/compose.yaml exec -T vasa python scripts/evolution_status.py
```

Expect `Evolution process: healthy; license: active.` If it remains inactive,
stop at the activation prerequisite and troubleshoot the supported vendor flow.
Do not proceed from `/server/ok` alone.

## Persistence, restart and backup

`vasa-vps_postgres-data` stores the VASA database and Evolution's separate
auth/users databases, including its `runtime_configs` license state and
WhatsApp session state. Evolution data/logs, Redis and VASA diagnostic reports
use separate project volumes. The diagnostic volume permits the prepared media
probe to write its outbound test recording and acceptance report while the
application root filesystem stays read-only; it does not record caller audio.
Credentials stay in `.local/vps.env`; preserve that file securely too.
Do not regenerate keys, change database passwords/user names or move license
state casually. Changing a Postgres initialization environment variable does
not rotate the password in an existing database. Vendor validity/heartbeats
still govern whether a persisted license remains active.

Restart only this project:

```bash
docker compose --env-file .local/vps.env -f deploy/compose.yaml restart
docker compose --env-file .local/vps.env -f deploy/compose.yaml exec -T vasa python scripts/evolution_status.py
```

Stop without deleting persistent volumes:

```bash
docker compose --env-file .local/vps.env -f deploy/compose.yaml down
```

Never use `down --volumes`, volume/system pruning, or removal of the project's
data directories to troubleshoot this installation. Take a restricted backup
before changes or upgrades:

```bash
umask 077
docker compose --env-file .local/vps.env -f deploy/compose.yaml exec -T postgres sh -c 'pg_dumpall -U "$POSTGRES_USER"' > .local/database-backup.sql
```

Keep database backups and the private configuration outside Git in your secure
backup storage. They contain sensitive business/session/license material.

## After activation

Create a VASA login using the secure password prompt:

```bash
docker compose --env-file .local/vps.env -f deploy/compose.yaml exec vasa python -m vasa.control.bootstrap --email owner@example.com --tenant "My business"
```

WhatsApp pairing and the real inbound-call diagnostic remain human gates.
For private VASA dashboard access from the same computer, forward its port too:

```bash
ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:18081:127.0.0.1:18081 vasa-builder@2.25.172.155
```

Open `http://localhost:18081/login`. Modern browsers permit Secure cookies on
localhost; if yours does not, use an HTTPS endpoint rather than weakening
production cookie settings. Public production access always needs HTTPS.
Create the tenant-owned instance through VASA and scan its QR with your phone.
Do not create unrelated instances outside VASA and assume ownership mappings exist.
Follow docs/EVOLUTION_TRANSPORT.md for the media probe after authenticated
provisioning/pairing is ready. Dynamic UDP relay connectivity and actual
audibility still require a real call on this VPS. The AI pipeline remains
behind that successful media proof.

Run the prepared probe from a VPS terminal, substituting the authenticated
client email and that client's VASA instance UUID:

```bash
docker compose --env-file .local/vps.env -f deploy/compose.yaml exec vasa python -m vasa.media_proof --email CLIENT_EMAIL --instance VASA_INSTANCE_UUID
```

Place one actual inbound WhatsApp call while it waits. Diagnostic reports remain
in the `vasa-vps_vasa-diagnostics` volume after container recreation. Sending
frames does not prove audibility; the caller must confirm hearing the response.

This package is a tested deployment preparation, not evidence that the VPS
was deployed, activated, paired or can carry a real call.

## Voice worker after the accepted media gate

The user has confirmed real bidirectional media acceptance. The deployment now
prepares checksum-pinned native CPU speech assets in the persistent VASA private
volume automatically. Keep that volume as well as Evolution/database volumes.
See [VOICE_RUNTIME.md](VOICE_RUNTIME.md) for secure OpenAI configuration and the
trusted worker command. The API process does not start answering calls by itself;
run the operator worker for a selected tenant-owned paired instance. Live AI
conversation acceptance remains separate from the passed diagnostic gate.
