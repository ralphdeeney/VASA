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
the successful read-only Actions39006681009 proved those permissions before
VPS execution. No extra credential was requested.

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

## Demonstration evidence and remaining gates

Read-only request e3a436f / Actions39006681009 succeeded automatically; Verify
39006681018 passed1,318 tests. The maintenance request7a76620 ran automatically
in39006923768 and passed source/image, backups/restore, repeated no-call,
identity/schema and connection gates. Its final public-health check failed and
verified rollback restored the old Evolution image. The one-shot maintenance
approval is consumed; correcting diagnostics does not authorize a second
replacement. Require explicit review/renewed approval after identifying the gate.

The pool candidate showed2 Evolution connections over three probes (total4),
compared with1 Evolution/3 total immediately before. The historical95-connection
incident was before external recovery; it is not a before/after reduction from
this attempt. Offline/logged-out WhatsApp is separately reported; no pairing or
call reconnect claim is made. Routine application pushes still refuse the dirty
canonical checkout without touching its operator-owned edge/tunnel files.

Read-only evolution_check now runs the same fixed public origin checks and emits
EVOLUTION_PUBLIC_STATUS=login/readiness/dashboard:<HTTP code>, or one fixed
EVOLUTION_PUBLIC_FAILURE code. TLS verification remains enabled; no arbitrary
URL, response, redirect destination or exception text reaches logs.

Post-rollback read-only request3ec8f9e / Actions39007779782 reproduced public
login403 from the VPS while all five services remained healthy and PostgreSQL
connections returned to3 total (Evolution1). Codex sees login/readiness200 and
dashboard401. The denial's precise edge/policy cause is not established yet.
403 is not accepted as a successful login probe. A bounded denial classifier
reports only a fixed Cloudflare-challenge/proxy-policy/Cloudflare-response/unknown
category; raw headers and bodies remain suppressed. No Cloudflare change is
within this task's authority.


### Final automated-delivery evidence — 2026-10-17

Code0fe9f2724902fc57eff3dc1632b128ea60588652 and read-only request envelope
71f0cb4a87c097b394a2c29f5e89d353fed91f8b passed Verify39008139299/39008142406
(1,337 tests each; local1,337 in78.21s, one upstream deprecation warning).
Ruff/format, strict mypy69 source+5 deployment modules, actionlint/Bash and
native Go full tests/vet, call/media race and real PostgreSQL120-cycle checks pass.

Automatic push request39008142381 and Codex-triggered workflow_dispatch
39008329597 both correctly blocked without mutation at public login403 from the
VPS. The allowlisted denial classifier reports cloudflare_response, not a
challenge; it does not identify the actual policy/rule/origin cause. External
Codex checks remain login200/readiness200/dashboard401. All five services remain
healthy, connections Evolution1/web1/voice1,total3, calls0, media sockets0; saved
paired-device membership remains intact and the instance is still offline.

The first read-only automatic demonstration39006681009 succeeded. The actual
pool attempt39006923768 passed backups/restoration, rollback-image preparation,
no-call and candidate identity/pool checks but rolled back at public health:
VASA_EVOLUTION_POOL_ROLLBACK_OK. Candidate Evolution connections2/2/2,total4;
there is no final VASA_EVOLUTION_POOL_DEPLOYMENT_OK and no fixed image deployed.
App/voice remain858b5f853957d719a34ea96f28b5ea726100d402. No call-reconnect
resolution or live WhatsApp acceptance is claimed.

Remaining gates: public login403 from the VPS requires approved edge/origin
investigation (no Cloudflare/security change is authorized here); canonical dirty
operator checkout still blocks ordinary app deployment; one-shot Evolution grant
is consumed and cannot be silently renewed after rollback. SMTP remains deferred.
Neither existing push nor direct workflow dispatch needs a new credential or
manual Actions operation. No protected gate was bypassed.

### Verified recovery/maintenance continuation (2026-10-17)

Controller/docs/test-only pushes now skip ordinary application replacement;
explicit request commits still trigger this orchestrator and exact-SHA CI.
Runtime/Compose changes retain normal application deployment behavior. Read-only
Evolution checks require independent-runner identified HTTPS readiness and
anonymous identity/instance/admin401 boundaries before SSH, then private/public
VPS health and unchanged-container/private-file verification. They write a
private completed receipt with time and identified-health contract attestation.

The separately approved renewal mechanism binds a distinct UUID/grant, absolute
expiry, fresh successful read-only receipt and exact source/safety-input manifest.
Request flags cannot confer approval or extend expiry. Source tip, readiness and
public health are rechecked before the single-use claim under the existing lock.
A successful replacement writes an append-only private per-request deployment
receipt. Historical grants remain untouched. The approved attempt succeeded in
39013405431 and is consumed; no automatic retry/replacement is authorized.
Routine read-only verification remains available without another maintenance
approval. See health-recovery/authorized-rollout-result.json for real evidence.
