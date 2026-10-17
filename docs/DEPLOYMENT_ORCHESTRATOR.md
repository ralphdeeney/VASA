# Autonomous staging delivery

VASA keeps its existing rootless Docker/Compose controller, rollback logic and
GitHub Actions SSH bridge. Codex never SSHes directly. Existing GitHub push and
workflow-dispatch authentication works; no additional credential is needed.
The connected actor's repository permission is admin. Reading repository-wide
Actions settings returns 403 for this integration; no setting was bypassed.
The branch protection audit reports protected=false. The request job and validator
both restrict the actor to the owner; repository writers remain trusted to change
workflow/policy code. Branch protection/required review is not configured or
changed by this task; broader team/production delegation needs separate review.
The new workflow declares contents:read, actions:read and deployments:write;
its actual execution must prove those permissions before any VPS operation.

Ordinary code pushes still select application deploy (never Evolution/bootstrap,
paid smoke or migrations), now waiting for successful exact-SHA Verify CI.
Manual legacy modes remain available for exceptional recovery. Request-only
pushes are excluded from that normal path and select VASA deployment request.
Both workflows share the existing vasa-staging-vps concurrency group, and the
existing VPS deployment lock remains authoritative.

## Requests and authorization

1. Implement, test, commit and push code on build/vasa-foundation.
2. Generate a request from a clean checkout, for example:
   `uv run --frozen python -m deploy.create_request evolution_check --reason "Read-only staging preflight"`.
3. Commit ONLY the generated `deploy/requests/<UUID>.json` and push. Do not amend
   unrelated code/docs into that commit. Codex performs these Git operations.
4. Monitor the automatically started VASA deployment request run and its GitHub
   deployment-status journal. Require the operation's exact success markers.
5. Diagnose fixed failure codes, correct supported engineering issues and
   continue. No manual Actions form is required. Codex may rerun a blocked
   pre-connection check using its existing GitHub Actions access.

A request names its exact parent code SHA. Its triggering commit is an immutable
request envelope with no other changes, avoiding the impossible requirement of
embedding a commit's own SHA in itself. Both exact SHAs require successful Verify
CI. Existing controllers execute/build the envelope SHA; application/vendor code
is identical to the requested parent. Reports distinguish source and deployed
SHAs. Both must belong to the trusted branch; a newer branch tip supersedes a
queued request. New/changed requests are validated against the triggering commit,
not discovered by scanning old request files.

Schema rejects unknown fields (including approved/command), unsupported operations,
wrong environments/branches, malformed JSON/duplicate keys, missing scope/profile,
invalid times and requests older than24h. Requests expire within24h (generator12h).
Trusted GitHub actor ralphdeeney must independently have write/maintain/admin
permission, including reruns. Requests cannot grant themselves authorization.

Routine authorization covers application_deploy, application_check and
 evolution_check. The separately approved existing pool fix has one grant:
 evolution-pool-2026-10-17, request6e1328c2-3554-4c2d-8153-5639304a6b18,
 pinned upstream e21ce0dd7634f3047410c893b5e4d1c082034b84 and reviewed pool
 patch SHA256 daba5ba8222345396ce5934e8a7ef07c353a4ed73fedcbeb785c75a6fb0b5361.
No ordinary push can invoke it. New maintenance requires new explicit human
scope authorization. provider_smoke is recognized but denied without an explicit
paid-operation grant; provider tests remain outside live WhatsApp handling.

## State, retry and recovery

GitHub deployment records/statuses persist request UUID, digest, source/envelope
SHAs and run URLs. States: REQUESTED, VALIDATING, TESTING, READY, PREFLIGHT,
DEPLOYING, VERIFYING, SUCCEEDED, BLOCKED, FAILED, ROLLBACK. Private VPS receipts
under /opt/vasa/.local/deployment-requests provide a second idempotency boundary,
using owned private files, per-request flock and atomic fsynced writes.

No completed UUID is executed again. Changed bodies cannot reuse a UUID.
An interrupted mutation is never blindly restarted: a matching successful
controller receipt, deployed image/checkout, unchanged private files and other
containers, and fresh health are required for verification-only resume. Unknown,
failed or rolled-back mutations stop for review. No rollback/destructive repair
can be encoded in request text.

Only proven pre-login SSH host-key scan connectivity failures retry automatically
(maximum3 attempts,10/30s backoff). Host-key mismatch, unknown SSH outcome, active
calls, missing backups/rollback material, schema uncertainty, CI failure and
unauthorized operations stop. No secret, prompt, body, arbitrary exception,
command output or container environment is printed. Only fixed markers, bounded
numeric metrics and source SHAs reach Actions logs. Captured raw stderr is dropped.

Evolution reuses existing no-call checks, paired-device/ownership checks, verified
three-database backups/restores, verified rollback image and targeted Compose.
Initially-online instances must recover. Uniformly offline paired instances stay
offline without pairing/reconnect changes and are reported separately; mixed
state blocks. Public login/readiness and dashboard auth, all five services,
unchanged credentials/schema, and repeated read-only instance/pool checks are
required. Success requires VASA_EVOLUTION_POOL_DEPLOYMENT_OK. Human live-call
acceptance remains mandatory before claiming reconnect fixed.

## Human boundaries

Never automatically bootstrap, migrate a live database, delete data, replace
pairing, alter secrets/host trust, touch n8n/Caddy/Cloudflare or unrelated services,
or interrupt an active customer call. Preserve unknown checkout files. Dirty
canonical checkout and migration gates remain hard gates, not permission to
reset/stash files or invent another deployment stack. SMTP remains deferred.
