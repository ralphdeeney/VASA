## Current verified outcome — 2026-10-17

The authorized Evolution pool-fix rollout SUCCEEDED in Actions39013405431,
marker `VASA_EVOLUTION_POOL_DEPLOYMENT_OK`; independent post-rollout
Actions39013697523 also SUCCEEDED. Deployed Evolution revision:
`68e193f44cfd655597da36e1fee0d52ac15bce17`; source390aa0d4c784d9952bd93e3224d82cf9edfe02d9.
Image `sha256:ce9c60d7f0c26f45e3cbd3b628173a580957b747461b5592db210f9d63dd6ec9`.
Verified fresh backup restoration, rollback image, repeated zero-call gates,
pairing/schema/credential preservation, all five healthy services/restart_count0,
public/private readiness and authentication boundaries. Only Evolution replaced;
app/voice release858b5f8 and canonical502b8d8/operator/private files unchanged.
The historical and renewed grants are consumed. No additional replacement is
authorized. Idle connections3 before,4 across three immediate post-samples,
3 at settled independent audit (Evolution1/API1/voice1, max100). This is not a
claimed measured95-to3 reduction or proof that real-call reconnect is solved.
WhatsApp remains registered with paired metadata intact, disconnected/logged-out.
Human connection/pairing and live-call acceptance remain pending. SMTP deferred.
Full evidence: docs/health-recovery/authorized-rollout-result.json and README.md.
Historical entries below are superseded by this verified current outcome.

## 2026-10-17 — Public-health trigger verified; policy/rollout approvals held

Read-only Actions39010351757 reproduced the same controlled result on VPS and
GitHub runner: default Python urllib public login/ready/dashboard403; identical
urllib GET with honest VASA-Health-Diagnostic/1.0 UA200/200/401. Curl default and
identified UA also200/200/401. Private VPS origin default urllib200/200/401.
The proven trigger is client identification on public ingress, not a VPS-only IP
block or an unhealthy application. Exact edge/security rule still needs operator
Cloudflare-event review; response headers alone do not identify the enforcing rule.

VPS explicit IPv4/IPv6 login both200; HEAD405 is method behavior. urllib pairs
bothHTTP/1.1; curlHTTP/2. VPS/runner proxy absent; source fingerprints differ by
vantage but match between clients within each vantage. No TLS/proxy bypass.
Private API JSON live/ready and worker readiness pass. All five containers,
private files, operator files and database identities unchanged. PostgreSQL stays
Evolution1/web1/voice1,total3 before/after; calls0/media sockets0.

Exact active Evolution image:
sha256:d0b8a492d7976e56f90333ea4f472fbcc75c50ecdbe073df8ff78a268460c0d3
matches the verified previous-source fallback rollback tag, revision
 e21ce0dd7634f3047410c893b5e4d1c082034b84. Pairing/credential/schema identity
matches archived backup receipt; WhatsApp remains offline/logged-out. Grant
consumed, no renewal/restart/replacement; the pool fix is NOT deployed.

Canonical502b8d8 has zero tracked changes and exactly three untracked operator
files:edge/Caddyfile,edge/docker-compose.edge.yml,tunnel/docker-compose.yml.
Active app/voice remains858b5f853957d719a34ea96f28b5ea726100d402. Preserve files;
reuse the existing isolated-release preparation/activation model with its gates.
No tunnel/n8n/Cloudflare/provider/SMTP configuration changed.

Evidence and approval-ready, unapplied minimal client patch:
docs/health-recovery/README.md, http-observations.json, recovery-audit.json,
summary.json, proposed-identified-health-client.patch. Existing health gate and
trusted grant/schema policy are byte-unchanged. The read-only request correctly
ends BLOCKED at the legacy public403 gate after publishing diagnostic evidence.
Separate explicit readiness-policy approval and renewed maintenance authorization
are required before any new Evolution replacement. No mocked readiness or silent
policy override. See docs/HEALTH_READINESS_CONTRACT.md and RELEASE_RECOVERY_PLAN.md.

Codebe39ad7/requestd9a09e8 Verify39010346087/39010351765 each passed1,379 tests.
Local full1,377 plus two TLS-reporting regressions pass; Ruff/format, strict mypy
69source+7deployment modules, workflow/shell validation pass. Go full tests/vet,
call/media race and real PostgreSQL120-cycle lifecycle/race checks reran and pass.
SMTP remains explicitly deferred; no call-reconnect resolution is claimed.

## 2026-10-17 — Automatic requests proven; guarded pool rollout rolled back

The push-driven read-only request succeeded automatically in Actions39006681009
(source4ec0f3f; request e3a436f), with Verify39006681018 passing1,318 tests.
GitHub deployment-journal writes, existing authenticated SSH bridge, strict host
trust and request-only exclusion from normal application replacement are proven.

The separately approved pool request7a76620d3e670b3e52152ffd313308bb2045861e
ran automatically in Actions39006923768 after Verify39006923803. It built and
verified the previous-source rollback image, restored three-database backups in
disposable databases, confirmed zero durable/Redis calls and media sockets,
replaced only Evolution, preserved pairing/schema/private files/other containers,
and sampled Evolution connections2/2/2 (total4). Before:Evolution1,total3.
The old95-connection incident is not this rollout's baseline.

The final public-origin check failed before the deployment receipt/success marker.
The controller restored the previous Evolution image and verified rollback:
VASA_EVOLUTION_POOL_ROLLBACK_OK. No fixed image is claimed deployed. The grant is
consumed; it cannot be renewed by request data or blindly retried. The instance
remained disconnected/logged-out with its paired device preserved. Human live-call
acceptance and SMTP remain deferred. Actions39007779782 reproduced the hard gate without mutation:
EVOLUTION_PUBLIC_STATUS=login:403. Codex sees login200, readiness200 and
dashboard401. This proves a vantage-specific public health denial, not its
Cloudflare/policy cause; no security policy is bypassed. Final read-only Actions39008142381 and the direct-dispatch retry39008329597
reproduced the same gate:EVOLUTION_PUBLIC_DENIAL=cloudflare_response, login403.
There was no challenge indicator; the exact rule/origin cause is unproven.
Direct workflow dispatch using existing Codex GitHub auth succeeded; no new
credential is needed. Both blocked read-only runs changed no containers. Verify39007772940/39007779791 passed
1,330 tests. Verify39008139299/39008142406 also passed1,337 tests.
Final local suite:1,337 passed, one upstream deprecation
warning,78.21s. Ruff/format, strict mypy69 source modules plus5 new typed
deployment modules, actionlint and Bash validation pass. Native Go full tests/
vet, call/media race tests and real PostgreSQL120-cycle lifecycle tests pass.

Reporting/recovery hardening distinguishes a prepared rollback image from an
actual rollback, recognizes pre-login scan failures on stderr without logging
it, rechecks expiry/branch immediately before maintenance, and requires fresh
verification even for successful request replay. Public-origin diagnostics emit
only fixed endpoint labels/statuses and certificate/timeout/network/status codes.
No raw response, URL, exception body or secret is printed.

Ordinary app pushes still safely refuse the canonical dirty checkout (run
39006668584). Existing operator edge/tunnel files and the active immutable app/
voice release858b5f853957d719a34ea96f28b5ea726100d402 remain preserved. This is a
hard deployment gate, not permission to reset/stash operator files. No migrations,
provider changes, pairing changes, n8n/Caddy/Cloudflare changes or direct Codex SSH.

## 2026-10-17 — Autonomous request orchestration (implementation verification)

Strict push-driven deployment requests, trusted actor/CI gates, GitHub deployment
state journal and private VPS idempotency ledger implemented. Normal application
pushes retain their controller and now require CI; request-only commits are
excluded from application replacement. See docs/DEPLOYMENT_ORCHESTRATOR.md.
One-shot Evolution pool maintenance remains pinned and separately authorized;
SMTP, live migrations, destructive changes, secrets and human calls remain gated.
Local full checks:1,313 passed before the final two retry/grant tests; focused
request/orchestrator/remote tests pass. Full Go ./... tests and vet, targeted race
and real PostgreSQL120-cycle lifecycle tests passed. Final suite and automatic
read-only/maintenance demonstrations remain pending; no deployment is claimed.

## 2026-10-17 — Evolution fix tested; live rollout blocked by VPS access

Implementation: f7016fbe005c409cb01a73b11fbd8a913646683a (pushed).
Full automated suite: 1,223 passed, one upstream deprecation warning, 74.89s;
Ruff, formatting, strict mypy, actionlint and Bash validation pass. Native Go
lifecycle, race detector, real PostgreSQL 120-cycle reuse/shutdown, vet and
existing call/media tests passed separately. No speech/provider changes.

Last successful read-only Actions preflight: 38988440298. All five VASA
containers passed existing-state health checks; durable calls=0, Redis calls=0,
non-DNS media sockets=0. Exact registered/upstream instance count=1/1 and its
paired device exists. Its live status was disconnected/logged-out, so container
health must not be confused with WhatsApp readiness. PostgreSQL max=100;
Evolution sockets=95, API=1, voice=1, other=0, total=97.

Maintenance run 38988550199 stopped at rollback_image before target build,
voice pause or Evolution replacement. Raw Docker errors were withheld, so this
stage alone does not prove which image operation failed. The controller now
supports building a verified rollback from the pinned pre-fix public source plus
the existing logging patch, with dedicated lifecycle/failure tests. That fallback
has NOT yet been exercised on the VPS.

Subsequent Actions check 38988774741, including a fresh-runner retry, failed
SSH host-key scanning before login. Public /login and /health/ready both return
HTTP 530 with a Cloudflare Tunnel error. Current live container health cannot
be established. No direct Codex SSH, Cloudflare change, daemon restart, migration
or Evolution replacement was performed. There is no measured post-fix VPS
connection count because the fixed image has not been deployed.

Last verified active app/voice SHA remains
858b5f853957d719a34ea96f28b5ea726100d402; Evolution remains the previous pinned
build of upstream e21ce0dd7634f3047410c893b5e4d1c082034b84, not this fix.
Canonical /opt/vasa/operator files remain preserved; release preparation uses
an isolated .local/evolution-releases directory. SMTP remains explicitly deferred.

Required external action: restore VPS SSH availability to the existing Actions
bridge and the separately managed tunnel; do not weaken pinned SSH host trust.
Then run VASA staging VPS, mode=check/recovery=evolution_check, followed by
mode=check/recovery=evolution_deploy if preflight passes. Backups, repeated
no-call checks, paired-device checks, targeted replacement and rollback remain
mandatory. Require VASA_EVOLUTION_POOL_DEPLOYMENT_OK and record the actual
post-rollout counts/health before a human WhatsApp call. Delivery is NOT complete.

## 2026-10-17 — Authorized Evolution pool lifecycle remediation

Confirmed pinned upstream reconnect path creates an independent PostgreSQL
Whatsmeow store pool on each StartClient without closing the previous pool.
The reviewed patch borrows the existing process-owned bounded auth database
pool via NewWithDB; its owner retains shutdown responsibility. SQLite database
selection, transport, call/media APIs and speech providers are unchanged.

Local Go unit, race, real PostgreSQL 120-cycle reuse/shutdown and existing
call/media tests passed. The isolated source manifest pins both reviewed patches;
existing cached source and runtime secrets are preserved. Live rollout is pending.

GitHub Actions only: dispatch VASA staging VPS with mode=check,
recovery=evolution_check for read-only health/capacity/call inspection; use
recovery=evolution_deploy for the explicitly authorized Evolution-only rollout.
No bootstrap, application migration or automatic Evolution rollout on push.

The maintenance controller checks durable unfinished calls, bounded Redis call
state and all non-Docker-DNS Evolution UDP sockets, plus the exact registered
instance set and verified paired-device membership. A saved offline instance
is eligible for maintenance; post-rollout must be connected and logged in.
Unknown/nonzero call state defers. After backups, pause voice
and recheck to close the VASA answer-admission race; then replace only Evolution,
restore only existing registered device connections, resume voice and validate
all five services, unchanged other container identities and private files.
The private control endpoint must not have independent external call initiators.
The upstream image has no call-list API; zero UDP alone is never accepted as
proof of no calls. A stale unfinished durable record also blocks maintenance.

Backups cover application, Evolution auth and Evolution users databases, with
private receipts/hashes and restoration into disposable databases before restart.
Schema/device/instance credential fingerprints must remain unchanged; no live
schema upgrade is approved. A verified rollback image is retained and only
Evolution is restored if validation fails. If the old running image is missing
from Docker storage, build the pinned pre-fix vendor source with only the existing
logging patch in a separate verified cache, before any target/runtime change.
Never use docker commit or read container environment values. Capacity is sampled three times after
rollout; total Evolution sockets must remain within the two existing 25-open
process pools, and decrease from an exhausted baseline.

SMTP is explicitly deferred by the operator. No credentials are requested or
invented and live email acceptance is not claimed. Human real-call stability
validation remains separate from pool health evidence.

2026-10-16 delivery status — DEPLOYED, acceptance PARTIAL (not complete).
Active immutable staging release: 858b5f853957d719a34ea96f28b5ea726100d402.
Actions 38953426795 verified restored backup, approved 0007 migration, app/voice
activation, readiness and VASA_DEPLOYMENT_OK. Canonical/opt/vasa remains 502b8d8;
three operator-owned untracked edge/tunnel files and all private env hashes remain
unchanged. Automatic normal pushes still refuse that canonical dirty checkout;
this recovery uses detached immutable releases and a private active-release journal.
Original login 403invalid_origin is fixed; syntheticbad credentials now 401 as expected.

Actual browser run 38954094961 passed login/reload, tenant/platform boundaries,
admin directory/audit, public/auth/admin layouts at 390/1440px and logout revocation. Its
cleanup failed, so the job is not labelled successful. Investigation confirmed
PostgreSQL 53300: configured 100 slots, Evolution 95,VASA web 4,voice 1. Source review found
unmanaged SQL-store pools on Evolution reconnect; see
docs/EVOLUTION_DATABASE_POOL_RECOVERY.md. Evolution was NOT changed/restarted.
Actions 38957178699 recycled ONLY the existing VASA web container, preserved its
image/config, all four other services and private files, and removed all audited
disposable acceptance identities: VASA_API_POOL_RECYCLE_OK,
LIVE_SAAS_FIXTURE_CLEANUP_PENDING_OK, LIVE_SAAS_CLEANUP_ONLY_OK.
Full-suite/CI code 1c22f5ed79cf181a61e9127f5affd1a214e58d2c:1,147 passed,
Ruff/format/strict mypy/workflow/shell/JS checks pass; GitHub Verify38956878164 green.
Remaining external gates: private SMTP + operator-controlled test inbox for real
signup, verification, recovery and invitations; authorization/no-call window for protected
Evolution pool remediation. No email verification, permanent platform-admin grant,
full SaaS completion or solved WhatsApp reconnect claim is made.

2026-10-16 LIVE staging recovery: Actions 38953426795 successfully activated
immutable release 858b5f853957d719a34ea96f28b5ea726100d402, migrated0006 → 0007
through the operator-approved SQL/backup gate, and emitted VASA_DEPLOYMENT_OK.
Canonical checkout remains 502b8d8 with all three operator edge/tunnel files
preserved. Actual app/voice images use the858 release tag; private active-release
journal records that independently of canonicalHEAD. Postgres/Redis/Evolution
container identities and private env hashes unchanged. Host-private bind, health,
voice readiness, Evolution license/instances and dashboard auth checks passed.
Recovery controller commitab37384 is pushed; paid provider smoke not requested.
Live browser acceptance now being run with disposable audited identities; SMTP
email flows remain externally blocked (no credentials configured).

# Current state

2026-10-16 delivery recovery: Actions investigation 38914233338 confirms actual
staging remains 502b8d8 with three untracked files (no tracked changes), five healthy
services/zero restarts and DB 0006. Synthetic login reproduces 403 invalid_origin;
SMTP/canonical-origin bindings absent in approved VPS files/runtime. Candidate
Compose supplies trusted public HTTPS origin without weakening Origin checks.
Recovery check/prepare Actions options preserve unknown work and normal deploy
safety, isolate source/images, verify private backup restoration and migration 0007
only inside a disposable database. Actual preparation run 38915876226 passed: private PG backup restored; migration 0007
passed on a disposable clone; rollback/candidate images verified; canonical files,
all five containers and runtime secrets unchanged.
Local browser acceptance now covers six full workflow groups with real PG/Redis
and a test mailbox; live email/staging acceptance is not claimed. See recovery and
browser acceptance docs. No direct Codex SSH. Operator subsequently approved exact release 858b5f8 and
SQL SHA256 a6a226a785d60db0e00b46b301a46b2b033d198cde2b4db2a3736202cfda37c3.
Manual immutable activation tooling now refreshes backup/restore checks, validates
only approved config changes, applies reviewed additive SQL and updates only
vasa/voice with app-only rollback. Live activation is not yet claimed. SMTP
is absent from approved VPS/runtime/cloud/GitHub bindings; email acceptance remains blocked.

2026-10-16 SaaS implementation: existing FastAPI/template/static stack retained.
Public marketing/auth pages, responsive workspace/team/settings, separate platform
admin UI, signup, verification, recovery and invitations and audited server-only admin
provisioning implemented. Additive migration 0007 reviewed as generated SQL in
docs/migrations/0007_saas_identity.sql and exercised locally. Existing tenant/user
IDs and hashes retained; no fake verification/platform grants or Evolution pairing.
SaaS defaults OFF until separately approved migration and private SMTP setup.
Schema-change deploy refusal remains intact: this push must NOT automatically
migrate staging. See docs/DB_MIGRATION_PLAN.md for the concrete operator gate.
Full local suite: 1,041 passed; strict mypy/Ruff/format/workflow/shell/JS checks pass.
Twenty Chromium public/auth layouts checked at 390/1280px; authenticated real-HTTP login/profile/team and dashboard/admin layouts also pass
at both widths with no overflow or script errors. Live signup/email/admin/human call review
remain pending. Public cloud GET/login and synthetic POST returned 403; no claim
that the real sign-in failure is proven or fixed. Trusted canonical-origin support
and secret-safe operator diagnostics added without trusting forwarded headers.
Voice/provider/topology/private ingress/Cloudflare/n8n/Evolution remain unchanged.
GitHub Actions → VPS bridge and voice bootstrap: VERIFIED by prior operator run.
New SaaS staging deployment and real human acceptance: pending migration gate.

2026-10-15 private ingress: operator confirms public Caddy n8n-docker-caddy-1,
network n8n-docker_default (172.16.2.0/24), gateway 172.16.2.1. VASA publication
changes from loopback to exactly 172.16.2.1:18081; Evolution stays 127.0.0.1:18080.
Target Compose and actual container ports must match; host /login, assets and
dashboard auth checks use the private endpoint. Push is authorized to deploy
through Actions. No Caddy/n8n/root Docker, provider, migration, bootstrap or
private runtime environment changes.

2026-10-15 operator reports 30–36 second reconnecting calls, distorted audio,
working barge-in, recovered gaps and active read timeout. Confirmed local causal
path: 10-second receive timeout closes WebSocket; Evolution then calls Hangup.
Active media now observes gaps at 1 second and permits at most 24 seconds since
last frame/start (two pinned 12-second relay-connect budgets). Handshake/write
deadlines unchanged. Verified remote terminate immediately wakes the reader;
stop/malformed data/permanent loss/cancellation remain bounded and authoritative.
No provider, pacing, audio queue or upstream Go changes. Source-backed audio risks
and timing rationale are in docs/MEDIA_RECOVERY_POLICY.md. Reconnect success
remains a human live-call gate; implementation push is authorized to deploy.

2026-10-15 automatic staging phase: merged remote 79b5457 (push trigger was
already added, but its first run failed with empty dispatch-only mode). Fixed
push resolution to deploy/smoke=false and added allowlisted five-field summary.
Added read-only host/container web, Evolution license/instance and sanitizer
validation with unchanged dependency/restart checks. Push uses the same safe
update-only controller; public ingress remains externally blocked/unverified.
The implementation push is authorized to deploy this branch including e5431b4;
its live receipt is recorded in the Actions run and ignored VPS deployment journal.
No direct Codex SSH, bootstrap, migrations or account changes are authorized.

2026-10-15 live WhatsApp partial integration VERIFIED by operator: inbound
answer, caller frames and audible opening greeting; calls then reconnect/end
after roughly 10–30 seconds, with no container restart and no completed turn.
Disconnection root cause remains unconfirmed. docs/CALL_TRANSPORT_ANALYSIS.md
traces the pinned sources: CallTransport is handled independently by meowcaller;
Evolution's separate warning does not prove an ignored reconnect. Subtype 3 has
no documented reconnect semantics in the pin. No speculative relay change made.
Confirmed redundant hangup cleanup corrected: authenticated remote terminate or
upstream stop prevents duplicate REST hangup and misleading hangup_failed.
Socket shutdown after verified termination is normal; other read failures and
genuine local hangup failures remain errors. Added bounded safe log filter and
fixed media continuity/lifecycle markers. Providers/schema/topology/security
configuration unchanged. No deployment or live call performed by Codex.

2026-10-15 exact 9Router mismatch confirmed by operator: valid terminal stop
choice then clean EOF, no DONE sentinel. OpenAIProvider now shares terminal
finalization between DONE and clean SSE exhaustion; EOF requires prior valid
stop/tool_calls finish and all accumulated tool calls validate before emission.
Strict SSE framing, indices, limits and post-finish content checks remain intact.
Regression fixture uses synthetic text matching observed content/content/stop+
usage shape. No direct VPS SSH, API request or deployment dispatched here.

2026-10-15 operator confirms gateway auth/model/chat/streaming HTTP 200 and SSE,
but VASA LLM smoke still reports provider_error. Added one-request structural
SSE diagnostic, packaged in the app image; see docs/LLM_SSE_DIAGNOSTICS.md.
Exact mismatch remains pending operator structural output. No captured 9Router
fixture exists yet and no production parser compatibility change was guessed.
Existing strict text/tool parsing is preserved. Deploy tooling with smoke off,
then run the explicit diagnostic on the VPS. No direct SSH or live request here.

2026-10-15 operator reports normal deploy reached healthy API/voice and failed
only at optional provider_smoke. Fix diagnostic capture: a nonzero smoke exit now
preserves stdout/stderr in memory, prints only exact approved provider status/error
markers and numeric timings, then still fails deployment and invokes rollback.
Stderr and arbitrary stdout remain withheld. Default deploy remains unchanged;
no workflow dispatch, direct VPS SSH or live provider call made for this fix.

2026-10-15 normal development phase:

- GitHub Actions → VPS deployment bridge: VERIFIED (operator-confirmed).
- Voice bootstrap: VERIFIED (operator-confirmed `VASA_BOOTSTRAP_OK`, readiness OK).
- Normal deploy: pending live verification; five-service update path covered locally.
- Live 9Router provider test: pending.
- Live Deepgram provider test: pending.
- Full AI WhatsApp call: pending.

Normal updates use manual Actions `mode=deploy`, never bootstrap. Bootstrap remains
a special one-time/recovery operation. Optional `provider_smoke=true` enables two
bounded sequential paid requests after API/voice health passes; default false.
The standalone container command is `python scripts/live_provider_smoke.py`.
It uses trusted runtime configuration, prints fixed status/numeric timing markers,
and never participates in the WhatsApp path. No live API calls or deployment
dispatch were performed for this change. See docs/DEPLOYMENT_ACTIONS.md.

Earlier bootstrap instructions below are historical; use normal deploy now.

2026-10-15 target voice startup diagnostics are complete and verified. Each
worker run emits fixed startup stages; exceptions emit only allowlisted failed
stage/error codes, never exception strings, provider bodies or environment.
CLI also sanitizes unexpected exceptions. Readiness is sticky: later failures
use VOICE_RUNTIME_FAILED/ERROR even during reconciliation. Actions capture a
bounded target voice log tail across restarts before rollback/removal, print
only exact allowlisted markers, and suppress restored-image lifecycle markers
after rollback. Health rejects lifecycle failure codes despite an earlier ready
marker. All791 checks pass, including120 focused deployment/diagnostic checks;
static/type, Actionlint and shell validation pass. b1cac8 provider-aware asset
checks and provider settings/topology remain unchanged. No direct VPS SSH,
deployment dispatch or live diagnosis was attempted. Next operator bootstrap
can now report the target worker's sanitized failing stage before rollback.

2026-10-15 provider-aware speech startup fix is complete and verified. Worker
calls SpeechModels.verify_runtime, always checking ASR and only the configured
local TTS provider's assets; Deepgram/Speechify need no local TTS or fixtures.
Full verify()/provisioning still checks ASR/Piper/Kokoro/fixtures, with Kitten
optional as before. Read-only CLI: scripts/prepare_speech.py --verify-runtime
--tts-provider deepgram (supports trusted local-model directory overrides).
Cloud persisted voice strings are ignored and cannot select provider/model;
English and the existing fixed local voice allowlist remain enforced. All754
full checks pass, including87 focused asset/worker/persistence checks; static,
type, Actionlint and shell checks pass. No downloads at worker startup, no real
key/configuration edits, no direct VPS SSH and no deployment. Operator next:
VASA staging VPS, branch build/vasa-foundation, mode=bootstrap.

2026-10-15 custom OpenAI-compatible gateway support is wired end to end:
Settings.openai_base_url reads VASA_OPENAI_BASE_URL with official default
https://api.openai.com/v1; voice_worker passes it to the existing provider.
Provider URL construction remains base.rstrip('/') + '/chat/completions',
retaining model names, bearer auth, SSE and tools. The example uses only a
commented gateway placeholder. Real gateway keys/runtime files, Deepgram and
deployment configuration are untouched. All692 checks pass, plus static/type,
Actionlint and shell checks. JUnit: reports/openai-base-url.xml. No live gateway
call, direct VPS SSH or deployment. Operator next: VASA staging VPS, branch
build/vasa-foundation, mode=bootstrap.

2026-10-15 rollback-image recovery fix: user reports the healthy VPS API image
ID is unavailable in the local rootless Docker image store, causing bootstrap
backup tagging to fail. Shared bootstrap/deploy helper now inspects/tags when
possible, otherwise builds clean PREVIOUS_SHA source directly to the rollback
tag through the existing Compose build with an image-only stdin override. It
verifies the result/source/private hashes before checkout or container updates.
Failed acquisition leaves Git checkout/running containers unchanged. Recovery
uses the verified image ID (not the unavailable original); apps whose update
never started are not recreated. Fixed stage identifiers replace opaque command
errors without raw logs/secrets. No docker commit or container-env inspection.
All682 checks pass, including83 deployment-focused checks; static/type,
Actionlint and shell validation pass. No direct VPS SSH or live bootstrap ran.
Next operator action: rerun VASA staging VPS on build/vasa-foundation with
mode=bootstrap; expected success marker VASA_BOOTSTRAP_OK.

2026-10-15 explicit missing-worker bootstrap is implemented and verified locally.
User confirms the Actions bridge works and VPS postgres/redis/evolution/API are
healthy, with no voice container. Workflow modes are check/bootstrap/deploy,
default check. Bootstrap requires precisely that owned healthy topology, clean
Git, untracked private env files and nonempty resolved DEEPGRAM_API_KEY; missing
key emits DEEPGRAM_VPS_KEY_REQUIRED before fetch. It builds the existing shared
app image, updates API only if necessary, and creates only the missing worker.
Health checks, dependency snapshots and environment hashes gate success. Failure
removes only the new owned worker and restores Git/API image; health-checked
rollback stays nonzero. Normal deploy still requires its existing worker.
All666 full checks pass, including67 deployment-focused checks; static/type,
Actionlint and shell validation pass. No live bootstrap or direct VPS SSH ran.
Next operator action: VASA staging VPS, branch build/vasa-foundation,
mode=bootstrap. Expected success: VASA_BOOTSTRAP_OK. Runbook:
docs/DEPLOYMENT_ACTIONS.md; JUnit: reports/actions-bootstrap.xml.

2026-10-15 origin compatibility fix: exact git@github-vasa:ralphdeeney/VASA.git
is accepted alongside the four canonical origins. No wildcard matching, remote
rewrite, credential change or direct VPS SSH. All630 checks pass, including31
deployment checks exercising canonical/alias acceptance and malicious remote
rejection. Next operator action: VASA staging VPS -> mode=check.

2026-10-15 staging deployment bridge: manual Actions workflow supports default
read-only check and explicit deploy. Codex Cloud must never SSH to the VPS;
this supersedes earlier direct-SSH authorization. Existing rootless Compose
project vasa-vps/app services vasa+voice are reused with targeted updates,
secret preservation, health checks and controlled app-only rollback. Full615
checks pass; workflow Actionlint1.7.7 and shell syntax pass. No VPS deployment
or connectivity success is claimed. Registration on default branch main and
trusted repository variable VASA_VPS_HOST_KEY_SHA256 are prerequisites.
API access to repository Actions variables is denied to the connected GitHub
integration (403); no secret values were requested or exposed. Manual runbook:
docs/DEPLOYMENT_ACTIONS.md. Deepgram test configuration remains local/ignored;
the workflow does not transfer provider credentials to the VPS.
Registration PR: https://github.com/ralphdeeney/VASA/pull/2 (workflow only).
Initial mode=check dispatch returned HTTP404 because registration is pending;
no Actions SSH or deploy ran. Implementation is committed as ab64274.

2026-10-14 user explicitly selected Deepgram Aura as the interim default.
Settings, deployment Compose fallback and example environment now select deepgram
with aura-2-thalia-en. Kokoro INT8, Piper, Kitten and Speechify remain selectable.
This is a user preference, not a measured production-readiness recommendation.
The chat-pasted credential is exposed and is not stored or used. Configure a
replacement DEEPGRAM_API_KEY securely before live validation or worker startup.
Existing explicit VASA_TTS_PROVIDER overrides must be changed by the operator.
No live deployment or vendor benchmark has been performed for this change.

2026-10-14 current wave: stabilization / optional Deepgram Aura TTS.
Current slice: code/config/tests/benchmark complete; stopped at live-key gate.
User confirmed Aura TTS only. Deepgram is optional, uses one shared pooled
HTTP PCM streamer with Token auth/linear16/16kHz/no container, defaults to
aura-2-thalia-en and preserves Kokoro default/local STT/other providers/media.
DEEPGRAM_API_KEY is read through an exact secret environment alias, never
hardcoded/logged. Benchmark shares verified sequential direct/runtime buffering,
two excluded warmups, >=20 varied responses per mode, optional real STT and
safe partial failures/metadata. Full599 checks passed,0 failures/errors/skips;
Ruff/format/mypy57 sources pass; Compose configuration validates.
Active specialists:none. Automated failures:none outstanding. Blockers:real
Deepgram key is not configured; actual VPS access previously refused. Next
action:ask user to set DEEPGRAM_API_KEY securely, then validate live API/PCM and
run separate correctly labeled cloud/VPS evidence. No live Deepgram request,
vendor latency or listening WAV is claimed. Evidence and manual commands:
docs/tts-evaluation/deepgram-aura-2-vps/.

2026-10-12 current wave: stabilization / optional Speechify streaming benchmark.
Current slice: integration complete; actual VPS/API/listening pending.
Speechify Simba3.2 is selectable by trusted environment configuration; Kokoro
remains default and all existing providers/transport are preserved. One pooled
client, pinned API version2026-09-30, native PCM16/16kHz/60ms frames and bounded
cancellation cleanup are verified locally. Benchmark supports two excluded
warmups, >=20 sequential varied responses per direct/runtime-buffered mode,
first-byte/frame/percentiles/RTF/CPU/RSS/stalls/Server-Timing/connection evidence
and optional real one-thread STT contention with standalone fixture baseline.
Full checks:571 pass,zero failures/errors/skips; Ruff/format/mypy56 sources pass.
Real loopback TCP proves completed-request reuse and interrupted-stream closure.
Active specialists:none. Automated failures:none outstanding. Blockers:fresh
SSH to confirmed VPS returns Connection refused; cloud Speechify key absent.
No live vendor metrics or listening WAVs are claimed. Next action:run manual
VPS commands and listen before any production selection. Evidence/commands:
docs/tts-evaluation/speechify-simba-3.2-vps/.

2026-10-09 current wave: stabilization / optional Kitten Micro evaluation.
Current slice: complete locally; actual VPS A/B/C and human listening pending.
Kitten Micro 0.8 is selectable alongside Kokoro INT8/Piper, with one shared
preloaded model, one native thread, bounded PCM16/16kHz/60ms delivery and
existing cancellation. Kokoro remains the default. Exact model/dependency/
license pins and optional asset preparation are integrated. Six sequential
uncached A/B cloud cohorts measured 54 responses and 108 WAVs. STT1 sentence
P50: Kitten 2.136s / Kokoro 4.132s / Piper 0.219s; RTF maxima 0.313/1.282/0.093;
long gaps 1.764/4.099/0.001s. Kitten misses preferred 1s first/300ms gap targets.
Full checks: 539 pass, zero failures/errors/skips; Ruff/format/strict mypy pass
(55 sources). Native Micro reuse/framing and three-provider worker sharing are
covered. Compose configuration and deployment script syntax pass.
Active specialists: none. Failed checks: none outstanding. Blockers: manual
VPS workload validation and human listening. Prior refused SSH is skipped per
user instruction. Next action: run server commands and review matched WAVs
before promotion. Evidence: docs/tts-evaluation/kitten-micro/.
Earlier entries below are historical.

2026-10-09 user explicitly selected Kokoro and retired LJSpeech. Kokoro INT8
is now the code/Compose default; Piper remains selectable. Active source/API/
dashboard/model preparation no longer select or download LJSpeech. Migration
0006 moves legacy default voices to Maple while preserving tenant identities.
Worker preloads once and warms three generic-only cache phrases; STT/TTS
default to one thread. Callback queue8, playback queue16, pending text2,
120-character meaningful chunks and a bounded generic-only cache are integrated.
Full checks: 521 pass, static/type checks pass; native Kokoro local-WebSocket
pipeline passed. Cloud buffered STT1: cached ack0.6ms, uncached sentence4.071s,
long gap4.127s. TTS2 sentence3.800s costs ~57% more combined CPU seconds.
Actual VPS activation/benchmark and audible quality review remain pending;
user requested manual server execution after SSH refusal. New evidence:
docs/tts-evaluation/kokoro-int8-vps/optimized/. Earlier records below are historical.

2026-10-09 Kokoro INT8 candidate: optional environment selection is integrated,
default LJSpeech and WhatsApp transport unchanged. One verified model is shared
at worker setup, num_threads=1, bounded native admission/PCM and immediate
consumer cancellation with separately tracked non-preemptible native cleanup.
Full checks: 512 pass. SSH to the confirmed VPS was refused; user requested
skip and manual execution. Actual VPS A/B/C and voice-quality review remain
pending. Cloud single-pass STT contention: Kokoro sentence 4.637s/RTF1.432,
Piper 0.270s/RTF0.113; Kokoro long gap 5.857s and native cancel drain 3.011s.
Manual commands/results: docs/tts-evaluation/kokoro-int8-vps/.

2026-10-09 isolated TTS study: official Kokoro v1.0/v1.1, matching sherpa
v1.1 FP32 and Piper were measured with two-CPU affinity/quota, sentence and
whole-response policies, and actual paced STT contention. Official sentence
P95 under STT was 2.074–2.313s; memory exceeded the current 1 GiB worker
budget. Single-thread tuning was slower. Piper had no simulated starvation
and sentence P95 0.228s under STT. Human naturalness review and actual VPS
performance remain unverified. Production provider and transport are unchanged.
Results, hashes and WAVs: docs/tts-evaluation/streaming/. Full checks: 487 pass.

Current wave: 10 (integration and stabilization)
Current slice: Tenant knowledge, durable runtime evidence, dashboard and deployment package integrated; live OpenAI acceptance deferred by user
Completed slices: Wave 0 governance/tooling/contracts; Wave 1 tenant PostgreSQL/pgvector/Redis and isolation; Wave 2 verified pinned-source Evolution adapter, authenticated instance mapping/control and QR dashboard; Wave 3 real-call media acceptance; Wave 4 CPU VAD/STT/TTS, bounded native cancellation and streamed LLM adapters; Wave 5 conversation runtime, trusted inbound worker and native local-WebSocket integration
Active agents: none; integrated implementation is complete and locally verified
Blockers:
- OpenAI is selected primary, but no secure usable binding is injected. The credential pasted in chat must be revoked/replaced through VASA_OPENAI_API_KEY in environment settings, saved/published. Do not store or use the exposed credential. Anthropic is optional. Live LLM acceptance awaits this prerequisite; independent checks continue.
- Historical cloud SSH to vasa-builder@2.25.172.155:22 was refused before authentication; proxy CONNECT closed without SSH banner. No successful VPS connection or remote changes are claimed. This does not block independent development or negate the user's accepted real call.
Failed checks: none outstanding. Native TTS callback polarity, repeated-cancel cache cleanup, delayed state callbacks and clipped initial speech regressions fixed and verified; no tests disabled or acceptance thresholds weakened.
Next action: operator runs the prepared Kokoro INT8/Piper VPS A/B/C commands;
use the Kokoro-first prepared code/settings and migration 0006. Configure the deferred provider key when
ready, then perform live dialogue, real tool and phone-capacity gates. No need
to repeat the passed diagnostic media call.

2026-10-09 whole-project continuation: tenant-isolated knowledge ingestion now supports
bounded TXT/PDF/DOCX extraction, pinned CPU MiniLM embeddings and pgvector search;
the dashboard exposes agent, knowledge and call history controls; runtime tool calls,
durable transcript chunks, summaries and dynamic worker supervision are integrated.
The full verification run passed 476 checks with zero failures, errors or skips;
Ruff, formatting and strict mypy passed. A production image built successfully as
UID 1000 with a read-only root. The controlled native load report records P95 TTS
first audio 10.555s -> 1.083s and no residual tasks; this is not a phone-capacity
claim. The replacement OpenAI key remains intentionally unconfigured by user choice.

2026-10-09 continuation: prepared tenant-bound custom_webhook with approved
HTTPS actions and strict business schemas, call-bound end_call with current
registry checks/acknowledgment, and knowledge_search's tenant-tagged retriever
contract (no retrieval backend). Migration 0004 adds calls/messages/tool metadata;
every repository query is tenant-filtered, ownership is enforced by composite
FKs, concurrent messages use locked unique sequencing, and writes never commit
the caller transaction. No arguments/results/secrets or audio are stored in tool
metadata. See docs/TOOL_PREPARATION.md for configuration and integration limits.
Full verification: 384 checks pass, zero failures/errors/skips; Ruff/format and
strict mypy pass. Current JUnit inspected at reports/concrete-tools-storage.xml.
Fresh isolated DB upgrade/downgrade/re-upgrade and Alembic schema check passed.
Eight real concurrent SQL writers preserved all messages and unique sequences.
No live provider/n8n action/call, runtime transcript capture, model tool selection,
summary accuracy or concurrency capacity is claimed. No key was used.
Source c4c2c193440d37a9fe733bd15300f79a3625b1c9 is uploaded and passed both
remote Verify runs: push 37863783680, PR 37863788777. The subsequent evidence-only
documentation commit changes no implementation; its own CI is not inferred.

2026-10-09 independent slice: tenant-bound ToolGateway with server permissions,
strict input/output models, bounded JSON snapshots, fail-fast capacity,
timeouts/cancellation cleanup and sanitized per-attempt outcome logging.
24 new component checks; full verification passed 342 checks with no failures,
errors or skips. Ruff/format/strict mypy pass; current JUnit inspected at
reports/tool-gateway.xml. Restored native assets and dedicated vasa-dev DB/cache
were used. No provider key or live API was used. Tool handlers, durable audits,
provider tool streaming and voice runtime integration remain pending.

Real-call Gate 3: PASSED on the user's explicit report on 2026-10-08. Evolution
answered an actual inbound WhatsApp call; VASA received 98 live caller frames,
sent 20 diagnostic frames and the human caller heard three rising tones. This
is user-supplied real-world evidence, not a new cloud call. No dropped-frame,
latency trace, activated-license persistence or concurrency result is inferred.
The proven Evolution transport remains unchanged.

Wave 4 initial native accuracy: 6 errors / 77 reference words across three
independent pinned recordings, aggregate WER 7.79%, within the predefined 15%
threshold. Native CPU speech and scripted OpenAI/Anthropic SSE component checks
pass. Wave 5 reader, turn detection, per-call context, response chunking, pacing,
interruption generation guards and bounded cleanup are implemented. Tools fail
closed until Wave 6. Full persistence remains Wave 7; worker logs omit caller
identifiers, audio and transcripts. Live AI-call naturalness is unverified.

Earlier foundation/deployment evidence: 158 checks passed without skips; pinned
Evolution source tests/vet/build and healthy cloud startup passed. A separate
cloud deployment project passed migrations, HTTP readiness/Manager and database
identity persistence with volumes retained. Cloud-local vendor license was
inactive; this is distinct from the externally passed real call. Rootless VPS
runtime and active-license survival remain unrun. See TEST_RESULTS.md.

Final combined verification: 318 passed, zero failures/errors/skips; current JUnit inspected at reports/voice-wave-final.xml. Ruff lint/format and strict mypy pass. Actual WebRTC -> streaming Sherpa STT -> scripted LLM -> local Sherpa TTS -> unchanged Evolution WebSocket adapter passed with first-word accuracy retained. OpenAI/Anthropic loopback SSE components and two scripted dialogue evals passed. Worker preflight/ownership/admission/cleanup checks passed. Live OpenAI remains unrun.

Reusable setup was repeated twice with verified speech assets and dedicated
healthy PostgreSQL/Redis; migrations report no drift. Production voice image
built and native CPU TTS generated 29 frames as UID 1000 with read-only root.
Final image rebuilt after all fixes; packaged worker help and imports verified. Startup instructions and secure
provider requirements are saved in the environment draft; saving does not
publish or inject a key. Existing Ponytail preference and unrestricted network
are retained. Separate fresh-task restoration is not verified.

Work continues on build/vasa-foundation and draft PR #1:
https://github.com/ralphdeeney/VASA/pull/1. No browser/WhatsApp E2E framework is
built. All live-provider, real-call and component evidence remain distinct.

Remote verification note: initial PR CI for 757e1be passed; its parallel push CI
exposed a TTS completeness test coupled to stochastic supplemental STT spelling.
The corrected native regression directly measures both synthesized batches and
resampled frame completeness; no recognition acceptance threshold changed.
Final local verification passed all 318 checks; rebuilt read-only UID 1000
image verifies deterministic speech. Updated benchmarks are recorded; both remote
CI runs passed for code 61b57d9 (push 37858367544, PR 37858371785).

Final source and evidence uploaded to build/vasa-foundation. Code commit
61b57d9e3d85a70ae6d49075a87ee1fa19e17e79 passed both GitHub Verify workflows
with 318 checks. The subsequent CI-recording documentation commit changes no
implementation; do not infer its own workflow status from the source runs.
No secure provider binding is configured, no exposed key was stored or used,
and no live AI-call or ten-call capacity claim is made. Remaining graph gate:
live OpenAI behavior/real dialogue acceptance before dependent wave completion.

## 2026-10-17 — Approved identifying health-client correction

Operator Authorization A is implemented exactly: honest identifying User-Agent,
fixed HTTPS endpoints, GET, verified TLS, no redirects and original status/rollback
requirements. Independent runner readiness and anonymous tenant/admin boundaries
are now blocking checks. Controller-only pushes avoid unrelated app activation.
Authorization B is conditional; renewed grant support is dormant until fresh
read-only readiness succeeds. Existing consumed grant and operator files remain
untouched. Evolution remains undeployed pending fresh live proof.

## 2026-10-17 — Fresh health verified; one conditional maintenance grant bound

Read-only Actions39013001527 succeeded: real `EVOLUTION_PUBLIC_HEALTH_OK`,
identified public login/readiness/dashboard200/200/401 from runner and VPS,
private200/200/401 and anonymous identity/instances/admin401. Five containers,
operator/private files and database identities unchanged; calls/media0;
Evolution1/web1/voice1/other0,total3,max100. Existing WhatsApp remains registered,
paired metadata preserved, disconnected/logged out. App/voice active858b5f8.
The separately approved new one-use grant is bound to this private receipt,
exact reviewed source hashes and absolute expiry. Full local1,425 tests and all
static checks pass. No replacement has yet occurred. See the new authorization
record and sanitized readiness evidence in docs/health-recovery/.

## 2026-10-17 — Signup layout / Reloop SMTP implementation (not activated)

Signup navigation/footer and responsive spacing fixed; other identity routes
preserved.40 browser layouts at320/375/393/768/1280 pass. Original logo image was
not attached/available: exact asset integration remains pending; no invented logo.
First-party image CSP support added without external image sources.
SMTPMailer now requires complete authenticated STARTTLS configuration and actual
mailbox-delivery attestation before signup/email workflows are available. Both
Reloop API-key credential fields are SecretStr. Dedicated optional web-only
.local/smtp.env is private/untracked/image-excluded and controller-hashed; no SMTP
binding is added to voice/dependencies. Safe explicit scripts/check_smtp.py reports
SMTP acceptance separately from actual receipt. No real mail sent.
Read-only Actions39073685888 confirms five healthy services/restarts0, DB0007,
exactly three preserved untracked operator edge/tunnel files, approved GitHub and
VPS SMTP bindings absent. Full local1469 tests plus static/workflow/shell checks
pass. Existing application activation safety remains; isolated preparation is next.
No migration, Evolution/voice restart, provider or tunnel change is authorized.


Signup/SMTP delivery outcome: code c57931f pushed; CI39073902107 passed1469.
Normal deploy39073902103 safely refused preserved operator files. Isolated
prepare39074100085 succeeded (`VASA_RECOVERY_PREPARE_OK`): fresh backup restored,
schema0007 current, rollback verified and candidate vasa-app:release-c57931f...
built without any running service/file changes. App/voice remains858b5f8. Not
activated: exact-release approval, original logo and private SMTP/verified sender/
test inbox/real mailbox receipt remain gates. CLI auth expired; connected GitHub
integration recovered status/logs without new credentials or duplicate run.
See docs/signup-email/result.json. No real email sent or delivery claimed.
