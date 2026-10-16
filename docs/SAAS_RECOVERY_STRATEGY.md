# SaaS staging recovery strategy

This is a recovery design, not evidence that staging has been changed or that a
backup has been verified. The current target is commit
`55404243069c9c2d47088e9d4081f9715852c978`. Obtain actual staging state through the
GitHub Actions bridge; never connect directly from Codex.

## Preserve and classify the dirty checkout

Under the existing owned `/opt/vasa` and rootless context, collect Git status,
changed path names, base SHA, file sizes and whether tracked changes differ from
the target commit. Capture diffs privately for analysis; do not print arbitrary
diffs because configuration edits may contain credentials. Do not stash, clean,
reset, amend, move or replace unknown files. Hash private runtime files without
printing their contents. Check ownership, free space, repository origin, service
labels, healthy five-service topology, active revision and backup availability.
Report only bounded allowlisted metadata to Actions logs. A filename alone is not
proof that its contents are generated or disposable.

## Strategy A: detached source worktree (preferred preparation)

After exact branch/SHA and ancestry checks, create a new owned, non-symlink
`/opt/vasa/.local/releases/<full-target-sha>` using a detached Git worktree.
Refuse an existing destination unless its ownership, exact commit and clean state
are independently verified. This changes Git administrative metadata and adds
files; it does not resolve or alter the dirty tracked checkout. Serialize with the
existing deployment lock. Do not copy `.env` or application credentials into it.

The Dockerfile requires the public CA trust bundle at
`.local/evolution-source/vasa-host-trust.pem` inside its build context. Validate
the existing bundle as a regular certificate file, copy only that file to the
same relative path in the isolated context and compare hashes. Do not copy the
Evolution source tree, private environment directory, speech models or runtime
volume data. The existing `.dockerignore` excludes other private local data.
Build the existing VASA Dockerfile with its frozen lockfile into a distinct
candidate image tag; never overwrite `vasa-app:pinned` during preparation.

## Strategy B: immutable archive release

If worktree registration is unsuitable, extract `git archive <verified-sha>` into
a fresh owned release directory under `/opt/vasa/.local/releases/`, validate its
manifest against the exact Git tree and prepare the same certificate input.
This avoids worktree metadata changes and preserves the original checkout, but
has no independent Git identity/status. Record the source SHA and manifest as a
private receipt. Never archive the dirty filesystem or include `.local` secrets.
Build with the existing Dockerfile/dependency inputs and a separate candidate
tag, as in strategy A. No second application deployment system is introduced.

## Why neither strategy can blindly run Compose from its release directory

The existing deployment controller requires project `vasa-vps` and container label
`com.docker.compose.project.working_dir=/opt/vasa/deploy`. Merely executing the
release's Compose file changes this label and its relative build/env-file paths.
Existing Compose reads `/opt/vasa/.local/vps.env` for interpolation and
`/opt/vasa/.local/llm.env` for application environment; moving Compose must not
redirect those paths or create empty replacement files. The named project volumes
contain PostgreSQL, Redis, Evolution state/logs and model/diagnostic data.

A reviewed future image rollout can keep the canonical Compose file, working
directory, project name, private files and named volumes, while overriding only
the application image to a verified release image. It must first compare target
and existing normalized Compose configurations and refuse unreviewed topology,
network, volume, dependency or secret changes. Use targeted `vasa`/`voice` updates
with `--no-deps`; do not recreate dependencies. This needs an explicit tested
release-aware controller path: today's normal deploy still requires a clean
canonical checkout and correctly refuses the dirty tree. Do not weaken that
check or forge Compose ownership labels to conceal a changed deployment model.

## Preparation versus the migration authorization boundary

Authorized reversible preparation includes read-only diagnosis, private state
inventory, source isolation, SQL review, candidate image construction and offline
or isolated development-database tests. Capture successful/failed preparations
honestly. A locally built image is not a deployed service, and an existing backup
filename is not proof that restoration works.

`docs/DB_MIGRATION_PLAN.md` requires an operator-approved exact SHA/SQL,
verified private PostgreSQL backup/restore procedure and controlled rollout.
The normal controller refuses migration changes before checkout. Neither an
isolated release nor a feature flag bypasses that requirement. Do not execute
staging Alembic upgrade, admin bootstrap, private runtime configuration changes or
new image activation under the pretense of preparation. Obtain the specified
operator authorization after preparing the concrete reviewed rollout.

Before a subsequently approved activation, acquire and verify a rollback image;
if the running image is unavailable, build from verified previous source without
modifying the dirty checkout. Record application/container/image state and secret
hashes, preserve existing services during builds, and validate schema/backfill
invariants after the separately approved migration. Roll back application images
with SaaS disabled if necessary; preserve additive tables and new SaaS data. Never
automatically downgrade or restore a database over newer records.

SMTP availability is a separate gate. Report only whether approved private
configuration supplies the required settings; never expose values. Missing SMTP
does not block isolated builds, SQL review, legacy-auth diagnosis or existing
read-only health checks, but does block truthful live verification/recovery/email
invitation acceptance. Do not substitute fabricated credentials or publicly
return verification/reset tokens. Human-facing signup remains disabled until
schema and actual delivery are validated.

No approach here authorizes sudo, Compose down, prune, Docker restart, bootstrap,
changes to Caddy/n8n/Cloudflare/Evolution pairing or public port exposure.
