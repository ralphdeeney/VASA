# Additive migration plan (0006 → 0007)

Existing revisions 0001–0006 remain unchanged. Preserve users, tenants, agents,
instances, calls, messages and knowledge data. Add SaaS companion tables and indexes
without changing existing columns. Backfill each legacy user with active legacy
profile, active owner membership in their existing tenant, and organization profile.
Legacy email verification is unknown: do not invent email_verified_at evidence.

Before staging: review generated SQL, obtain/verify operator backup and restore
plan, record row counts and current revision. Apply the reviewed migration through
an explicitly authorized operator path; never automatic deployment. Validate
constraints, backfill and unchanged existing IDs/rows before enabling SaaS.
Set canonical public origin, SMTP settings and enable flag only through the
private runtime configuration workflow. Bootstrap a platform admin explicitly
using the audited server command; do not auto-create users or reset passwords.

Downgrade is destructive to NEW SaaS records; no automatic downgrade. Prefer code
rollback with feature flag off, preserving additive tables. Existing deployment
controller must continue refusing schema-changing pushes until separately reviewed.

## Reviewable rollout artifact and operator gate

The exact PostgreSQL upgrade is in `docs/migrations/0007_saas_identity.sql`.
It creates eight companion tables and indexes and backfills legacy profiles,
organization profiles and owner memberships. It does not change existing user
password hashes, tenant IDs, agent configuration or WhatsApp instance records.
No platform roles, email proof, tokens or external resources are backfilled.
The local migration test upgrades and downgrades an isolated UUID-named database,
checks metadata agreement and exercises legacy rows through the actual backfill.

Staging is NOT migrated by CI, startup, health checks or the deployment controller.
The controller's explicit refusal remains:
“Schema changes require a separate operator-reviewed migration/backup plan.”
Pushing this change will therefore refuse normal deployment before checkout or
service updates. A green CI run is not staging acceptance.

Before proceeding, an operator must approve the exact target SHA and SQL, verify a
private PostgreSQL backup/restore procedure, and schedule the controlled migration
rollout. The reviewed procedure must record the previous source SHA and acquire a
verified previous-source rollback image using the existing deployment safeguards
before building target code. Keep existing services running while preparing the
new image; do not bootstrap, restart dependencies or expose environment values.
Use the same `deploy/compose.yaml`, rootless context and private environment files.
The core migration command, only once the approved target image has been prepared,
is `docker compose --env-file .local/vps.env -f deploy/compose.yaml run --rm --no-deps vasa alembic upgrade 0007`.
This is an operator action, NOT authorization for Codex to execute it.

Verify revision 0007, unchanged legacy IDs/password hashes and tenant row counts,
active legacy memberships, no platform assignments and unchanged provider/runtime
secret files. Complete the separately approved fast-forward checkout/image rollout
so normal Actions deployments resume from the reviewed baseline. Do not remove or
bypass the migration-path guard to make an automatic push deploy this change.

Enable `VASA_SAAS_ENABLED=true` only after schema and private SMTP delivery are
validated. Set `VASA_PUBLIC_ORIGIN=https://vasa.litatech.xyz` in private application
configuration; do not change tunnel or proxy forwarding trust. Provision the first
platform admin explicitly with an existing active user:
`python -m vasa.saas.bootstrap_admin --email <existing-user-email>`.
It prompts privately for the exact confirmation and writes an audit event. Public
signup and organization ownership never grant platform authority.

Rollback code with SaaS disabled rather than dropping new identity records. Even
with the flag disabled, migrated pending/suspended users and revoked sessions must
not regain access. The new auth compatibility tests cover this boundary. Do not
run Alembic downgrade on staging automatically.
