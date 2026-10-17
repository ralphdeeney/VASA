# Preserve operator files and recover through isolated releases

The canonical `/opt/vasa` checkout is not disposable. Existing operator files
`edge/Caddyfile`, `edge/docker-compose.edge.yml` and `tunnel/docker-compose.yml`
may be untracked or locally changed. Normal deployment deliberately refuses any
dirty working tree before pulling or updating application services. This check
protects operator configuration; it is not evidence of an unhealthy application.
Do not move, overwrite, stash, clean or remove these files, change their tracking,
or modify the running tunnel simply to satisfy the check.

## Read-only evidence

The deployment-request `evolution_check` path can collect bounded
`VASA_RECOVERY_AUDIT` records before the existing public health gate. Records show:

- Fixed operator filenames, tracked/present/regular flags, SHA256 fingerprints and
  fixed structural flags: reverse proxy, tunnel, external network, private origin.
- Change counts and an opaque fingerprint of Git status, never unknown filenames.
- All five verified VASA services: hashed container identities, exact image IDs
  and restart counts. Existing controller ownership labels and health are checked.
- Canonical commit and active release journal SHA, without exposing receipt data.
- Evolution revision label, comparison against pinned pre-fix upstream, exact
  rollback image comparison, old request baseline comparison where available,
  and whether the already-consumed grant file exists.
- Database schema/pairing/credential identity equality against available private
  backup receipts; the identity digests themselves never leave the VPS.
- Before/after equality for services, private runtime file hashes, operator files,
  Git state and database identities.

An unknown baseline stays unknown. A matching archived identity proves agreement
with an available historical backup, not a fresh restoration test. A revision
label alone is not proof of binary provenance; it is reported alongside exact
running image and rollback-image equality. No record grants authorization or
changes readiness policy. Diagnostic output never contains configuration values,
credentials, caller/instance identifiers, database rows or arbitrary file paths.
The module does not write files, fetch, checkout, build, restart or reconnect.

## Existing isolated release model

Reuse `actions_vps.py` recovery helpers and the existing
`.local/releases/<exact-SHA>` model. The preparation controller verifies repository
identity, canonical dirty-state preservation, immutable source checkout, runtime
secret hashes, prior image, backup restoration evidence and Compose compatibility.
Preparation builds a candidate and a verified rollback image without activating
services. Runtime environment paths continue to resolve to the existing private
`/opt/vasa/.local` files; do not copy operator secrets into source or candidate
images. Use existing `release_compose()` overlays and original Compose project
and working-directory ownership. Do not introduce a second deployment project.

Before normal automated app updates can use isolated releases, add an explicitly
reviewed release-aware activation route reusing those helpers, comparing the
active release journal instead of pretending canonical HEAD is the active
application. Keep the legacy dirty-check refusal intact. Validate exact SHA,
ancestry, dependency and network/volume equality, private environment hashes,
backup/rollback availability, targeted app/voice changes and readiness. A changed
migration set still requires the documented explicit backup, restore-test and
migration approval gate; request authorization cannot approve migrations by itself.
No such activation or migration is authorized by this diagnostic task.

## Evolution remains separate

The previous pool rollout consumed its one-shot maintenance grant and rolled
back. This task may verify the previous image, preserved pairing/schema and
health, but must neither renew that grant nor restart Evolution. The dedicated
Evolution isolated-source model remains `.local/evolution-releases/<SHA>`.
Another replacement requires renewed authorization bound to the exact reviewed
patch/revision, a healthy private/public/authentication contract, no-call checks,
verified backup restoration and a verified rollback image. The current public
403 gate remains effective until an explicitly approved policy change. Offline
WhatsApp pairing state must be reported separately from container health. Human
real-call testing remains required before any reconnect-resolution claim.

SMTP, Cloudflare security configuration, n8n and unrelated services remain outside
this recovery operation.
