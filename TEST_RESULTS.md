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

2026-10-16 delivery verification (actual staging evidence):
- Local full suite: 1,147 passed in 83.50s (reports/api-pool-recycle.xml).
- Ruff lint/format, strict mypy69sources, actionlint, bash syntax and Node syntax pass.
- GitHub Verify38956878164 passed for 1c22f5e.
- Staging activation38953426795: restore-tested backup, approved 0007, app/voice
  health, private binding/auth boundary, VASA_DEPLOYMENT_OK for 858b5f8.
- Actual Chromium38954094961: all five live groups passed: login/session reload;
  tenant/platform denial; admin directory/audit; mobile/desktop; logout revocation.
  Job failed cleanup (not counted as overall acceptance success).
- PostgreSQL capacity diagnosed without raw logs:53300;100 max,95 Evolution,4 API,1 voice.
- Cleanup recovery38957178699 succeeded: API-only same-image/container recycle,
  other services unchanged, all audited disposable fixtures removed.
- Public HTTPS readiness/login 200; anonymous dashboard/auth-me 401; original
  bad-login origin probe now 401invalid_credentials instead of 403invalid_origin.
SMTP email flows remain UNRUN live. Evolution lifecycle fix is review-only pending
separate authorization; no protected dependency changed. Full acceptance blocked.

2026-10-16 live acceptance tooling: 1,103 full tests passed in81.05s
(reports/live-saas-tooling.xml); Ruff/format/strict mypy, workflow/shell/Node
validation pass. Private Actions payload and disposable fixture/runner tests
cover malicious output, credential containment, cleanup ownership and failure
paths. Actual staging release 858b5f8 passed migration and VASA_DEPLOYMENT_OK
in Actions 38953426795; public origin login probe now 401invalid_credentials
instead of 403invalid_origin. Authenticated live browser run remains pending.

2026-10-16 approved immutable activation controller: 1,072 full tests passed
(reports/release-activation.xml), Ruff/format/strict mypy, actionlint and shell/JS
syntax checks passed. Sixteen new tests cover exact approvals, private backup/SQL
integrity, revision0006/0007, targeted updates and app-only rollback preserving
canonical unknown files/private env/dependencies. Live activation pending.

# Test results

2026-10-16 recovery investigation: 1,047 full checks passed in 87.68s and 95
focused deployment checks passed. Final recovery suite: **1,056 passed** in 84.47s; Ruff/format (249 files),
strict mypy (69 sources), workflow/shell/Node validation pass. New stateful
preparation checks exercise backup
restore/clone migration isolation, failed restore/build cleanup, secret suppression
and preserved operator files. Complete browser acceptance passed six groups using
real PostgreSQL/Redis plus an isolated fake mailbox; all disposable accounts and
sessions cleaned up. Live SMTP and newly deployed staging acceptance remain pending.

2026-10-16 SaaS website/auth/admin: **1,041 passed** in 84.93s, zero failures,
errors or skips; one existing Starlette deprecation warning. Full unit/component/
integration/native/eval suite; Ruff, formatting (242 Python files), strict mypy
(69 sources), Actionlint, shell and all JavaScript syntax checks pass. JUnit:
reports/saas-site-final.xml. New coverage includes additive legacy migration/backfill,
password preservation, no platform-role auto-grants, token expiry/purpose/replay,
approval in both orders, legacy verification, reset/session revocation, feature-off
rollback restrictions, CSRF/origin/tenant/role isolation, last-role safeguards,
confirmed admin mutations, scoped connection audits, secret-safe failures and UI
contracts. Chromium checked 20 public/auth page layouts at mobile/desktop widths
without overflow or script errors. Authenticated real-HTTP login, profile edits,
team loading and dashboard/admin layouts pass at both widths. Contact delivery
tests use a fake mailbox; integration metadata tests prove scope and secret
exclusion with the existing strict private loader. These checks do not prove live SMTP, real-user
login or human voice reliability. Staging migrations remain explicitly forbidden
from the automatic deployment path.

2026-10-15 private bridge web publication: **925 passed** in 66.40s; zero
failures/errors/skips and one existing Starlette warning. Full checks include
Ruff/format (221 files), strict mypy (60 sources), Actionlint and shell syntax.
120 focused bind/deployment checks pass. New tests accept only the exact VASA
bridge and Evolution loopback endpoints, reject wildcard/wrong/extra/UDP/host
network bindings, verify actual Docker selected port metadata without Env, and
prove host checks use private login/dashboard/assets and unchanged Evolution.
JUnit: reports/private-web-bind.xml. Push is authorized for automatic staging;
actual reachability must be established by that workflow's post-deploy checks.

2026-10-15 bounded media recovery: **908 passed** in 67.94s, zero failures/
errors/skips; one existing Starlette warning. Full unit/component/integration/
native/eval suite, Ruff/format (219 files), strict mypy (60 sources), Actionlint
and shell syntax pass. 39 focused media/lifecycle/filter checks pass. Seven new
accelerated real-WebSocket checks cover recovery beyond the old deadline on the
same socket, independent outbound sends, valid PCM/order/timestamps, finite
permanent-loss expiry, immediate authenticated terminate/stop during grace,
malformed media rejection, cancellation/task cleanup and timing-marker privacy.
Provider, STT/TTS, pacing and bounded-queue regressions remain passing. No live
reconnect fix is claimed; push is authorized to deploy and human validation
remains required. JUnit: reports/media-recovery.xml.

2026-10-15 automatic staging: **901 passed** in 67.65s, zero failures/errors/
skips; one existing Starlette deprecation warning. Full unit/component/
integration/native/eval suite, Ruff/format (218 files), strict mypy (60 sources),
Actionlint across workflows and deployment shell syntax pass. New tests cover
push/default mode resolution, five-field summary redaction, web/auth/static/
license failures, response bounds, CLI secret suppression, capture allowlisting,
post-validation rollback and unexpected app restarts. Existing bootstrap and
deploy safety tests pass. JUnit: reports/automatic-staging.xml. This change's
push is explicitly authorized to trigger normal staging deploy; actual live
results belong to that Actions receipt, not these local tests.

2026-10-15 live-call lifecycle cleanup/diagnostics: **885 passed** in 64.96s,
zero failures/errors/skips; one existing Starlette deprecation warning. Full
unit/component/integration/native/eval suite via scripts/check.sh, Ruff/format
(214 files), strict mypy (59 sources), Actionlint and shell syntax pass. Added
actual local-WebSocket sequence tests for media continuity, duplicate/scoped/
authenticated terminate, upstream stop, socket-close-without-stop, normal and
failed/racing hangup cleanup, plus fixed log filter privacy/oversized input.
Existing cancellation, durable finalization and genuine local error tests pass.
Pinned public Go dependencies were source-reviewed and h1-verified against
Evolution go.sum; no Go code changed and no Go tests were run. Tests establish
cleanup semantics, not a fix for live reconnect. JUnit: reports/call-lifecycle.xml.
No VPS SSH, workflow dispatch, live call or provider request performed by Codex.

2026-10-15 terminal clean-EOF compatibility: **872 passed** in 67.67s, zero
failures/errors/skips; one existing Starlette warning. Full unit/component/
integration/native/eval suite via scripts/check.sh passed. Ruff/format (210
files), strict mypy (59 sources), Actionlint and shell syntax pass. Regression
tests match the operator-observed 9Router content/content/stop+usage/no-DONE
shape using synthetic content. Standard DONE and complete tool calls work on
both paths; incomplete calls/identities, premature EOF, malformed framing,
transport errors, invalid indexes/deltas/multiple choices, post-finish content
and limits still fail. JUnit: reports/openai-terminal-eof.xml. No deployment,
direct VPS SSH or live API request was performed for this change.

2026-10-15 safe SSE diagnostic: **843 passed** in 65.70s; zero failures/errors/
skips, one existing Starlette deprecation warning. Full scripts/check.sh suite,
Ruff/format (208 files), strict mypy (59 sources), Actionlint and shell syntax
pass. 21 new tests cover structural redaction (including malicious key names,
event names, indices, finish reasons and headers), single-request/cleanup,
standard text/tool compatibility, and rejection of synthetic missing/string
indices, empty choices, invalid delta and missing finish/DONE. No actual 9Router
response was available; these fixtures are not live gateway evidence. Parser
unchanged pending structural receipt. JUnit: reports/llm-sse-diagnostic.xml.

2026-10-15 nonzero smoke diagnostic fix: **822 passed** in 68.13s, zero
failures/errors/skips and one existing Starlette deprecation warning. Full unit,
component, integration, native and eval suite passed via scripts/check.sh;
Ruff/format (205 files), strict mypy (58 sources), Actionlint and shell syntax pass.
115 focused smoke/deployment/bootstrap tests pass. Added subprocess-boundary
checks prove nonzero exit preserves both approved failure markers, mixed success/
failure is reported, all six fixed codes are accepted, malicious stdout/stderr
and secrets are withheld, and unchecked capture is unavailable to other Compose
commands. Existing success timings, default-off behavior and app rollback pass.
JUnit: reports/provider-smoke-exit.xml. No live requests or deployment dispatched.

2026-10-15 normal deploy/optional provider smoke: **811 passed** in 66.60s;
zero failures/errors/skips, one existing Starlette deprecation warning. Full
unit/component/integration/native/eval suite ran through scripts/check.sh.
Ruff and format (205 files), strict mypy (58 sources), Actionlint and shell syntax
pass. JUnit: reports/live-provider-smoke.xml (ignored local test evidence).
New coverage includes default-off paid probes, opt-in post-health sequencing,
smoke-triggered rollback without repeat probes, configured model/base URL use,
independent provider failures, missing credentials without requests, timeout and
exception redaction, PCM validation, stream/client cleanup and Actions output
allowlisting. Existing five-service update and bootstrap safety tests pass.
No live provider request, Actions dispatch or direct VPS SSH was performed.

2026-10-15 voice lifecycle diagnostics:791 full unit/component/integration/native/
eval checks passed in68.02s, zero failures/errors/skips, one existing deprecation
warning. Ruff/format202 files, strict mypy57 sources, Actionlint1.7.7 and bash
syntax pass. All120 focused checks pass, covering precise startup failure-stage
injection, exceptions whose __str__ must not be called, CLI unexpected errors,
post-ready/reconciliation distinction, marker allowlist parity/malformed-line
rejection/history bounds, and target voice capture before removal/Git rollback.
Actions stdout never includes synthetic secrets/provider bodies/credential URLs;
post-rollback diagnostics suppress old-image markers. JUnit:
reports/voice-startup-diagnostics.xml. No direct VPS SSH or live deployment ran.

2026-10-15 provider-aware speech:754 full unit/component/integration/native/
eval checks passed in67.35s, zero failures/errors/skips, one existing deprecation
warning. Ruff/format200 files, strict mypy57 sources, Actionlint1.7.7 and bash
syntax pass. All87 focused checks pass. Coverage includes ASR-only cloud worker
startup, selected local asset absence/corruption/symlinks and phonemizer checks,
invalid ASR for every provider, no-download CLI/runtime paths, custom model
directories, preserved full-bundle checks, real SQL persisted voice isolation,
inert cloud legacy/injection strings and retained language/local voice rules.
JUnit: reports/provider-aware-speech.xml. No gateway/Deepgram configuration,
deployment topology, Evolution or provider interface changes; no live deploy.

2026-10-15 OpenAI gateway support:692 full unit/component/integration/native/
eval checks passed in64.28s, zero failures/errors/skips, one existing deprecation
warning. Ruff/format199 files, strict mypy57 sources, Actionlint1.7.7 and bash
syntax pass. Ten new cases verify settings defaults/env/key redaction, custom
URL path/trailing slash/model/bearer auth, streamed text/tool events, and real
worker constructor wiring/default/lifecycle without key logging. Existing SSE
loopback/tool continuation regressions pass. JUnit: reports/openai-base-url.xml.
Only dedicated local test database/cache services were started; no VPS deploy,
real key edits or live gateway requests occurred.

2026-10-15 rollback-image recovery:682 full unit/component/integration/native/
eval checks passed in62.73s, zero failures/errors/skips, one existing deprecation
warning. Ruff/format198 files and strict mypy57 sources pass; Actionlint1.7.7
and bash syntax pass. All83 deployment checks pass. New coverage exercises
inspect/tag success, untaggable/missing running images, previous-source build
and verification before checkout, acquisition failure preserving Git/containers,
image-only Compose stdin override, verified fallback-ID rollback, no app restart
before an attempted update, no docker commit/container-env inspection, and
secret-safe stage diagnostics for bootstrap and normal deploy. JUnit:
reports/actions-rollback-image.xml. No direct VPS SSH or live bootstrap ran.

2026-10-15 explicit voice bootstrap:666 full unit/component/integration/native/
eval checks passed in62.50s, zero failures/errors/skips; one existing deprecation
warning. Ruff/format198 files, strict mypy57 sources, Actionlint1.7.7 and bash
syntax pass. All67 deployment-focused checks pass, covering exact topology and
ownership, dirty/tracked secrets/missing-key refusals, targeted app/worker startup,
unchanged dependencies/private hashes, image reuse, app restoration, worker-only
cleanup, rollback failures, explicit mode routing and strict normal deploy.
JUnit: reports/actions-bootstrap.xml. Local stubs exercise SSH/Docker failure
paths; no direct Codex VPS SSH or actual staging bootstrap was attempted.

2026-10-15 exact VPS SSH origin alias: full630 tests passed in62.25s with zero
failures/errors/skips; one existing deprecation warning. All31 deployment checks
pass, including real preflight allowlist-path tests for the exact github-vasa
origin, all four canonical origins, and ten unrelated/malicious variants.
Ruff/format197 files, strict mypy57 sources, Actionlint and bash syntax pass.
JUnit: reports/actions-origin-alias.xml. No direct VPS SSH was attempted.

2026-10-15 Actions deployment: full615 unit/component/integration/native/eval
checks passed in63.29s, zero failures/errors/skips (one existing deprecation
warning). Ruff/format197 files and strict mypy57 sources pass. Actionlint1.7.7
and bash syntax validation pass. Sixteen focused tests exercise read-only mode,
dirty/schema refusals, targeted updates, docs-only nonrestart, rollback/failure,
offline image fallback, secret-safe logs/errors, pinned host trust and temporary
key cleanup. JUnit: reports/actions-deployment.xml. All SSH in these tests uses
local stubs; no direct VPS SSH or deployment was attempted.

2026-10-14 user-selected Deepgram default: full599 checks passed in62.24s,
zero failures/errors/skips. Ruff/format194 files and strict mypy57 sources pass.
JUnit: reports/deepgram-default.xml. Settings defaults, provider overrides and
missing-key worker preflight remain covered. No live API call or deployment.

2026-10-14 Deepgram Aura TTS:599 full unit/component/integration/native/eval
checks passed in62.42s,zero failures/errors/skips. Ruff/format193 files and
strict mypy57 source files pass. JUnit reports/deepgram-aura-final.xml. New
coverage:19 Deepgram provider/real TCP checks,5 benchmark component checks,
secret settings/model validation and worker key preflight/single shared setup.
All prior Speechify checks remain passing after shared protocol/profile hooks.
Real TCP tests prove local reuse/stream closure; mocked HTTP proves auth/query/
format/model validation and redaction, not live Deepgram performance. Compose
configuration passed. Real key/live validation is deliberately pending.

2026-10-12 Speechify: full571-check unit/component/integration/native/eval suite
passed in56.85s,zero failures/errors/skips. Ruff/format and strict mypy56 sources
pass. JUnit reports/speechify-simba-final.xml. Twenty provider/real TCP checks
cover framing/rate validation, connection reuse, secret-safe telemetry/errors,
repeat cancellation/shutdown and proxy TLS tracing. Nine benchmark checks cover
unique clauses, two excluded warmups, sequential direct/runtime buffering,
actual-VPS guards, optional STT orchestration and sanitized partial failures.
Worker sharing/key preflight and exact environment key alias also pass.
Compose configuration/shell syntax pass. No live API/VPS benchmark ran; static
pending receipts and verification are under the Speechify evaluation folder.

2026-10-09 Kitten Micro: 539 complete unit/component/integration/native/eval
checks passed, zero failures/errors/skips, 48.45s. Ruff/format and strict mypy
(55 sources) pass. JUnit reports/kitten-micro-final.xml is copied into evaluation
evidence. New coverage includes real Micro reuse/framing, cache restrictions,
callback cancellation/bounds, corrupt/symlink assets, three-provider worker
sharing and fresh benchmark child imports without project PYTHONPATH.
Six sequential native cloud A/B cohorts produced 54 responses and 108 verified
WAVs. Compose configuration and deployment script syntax passed; no deployment
occurred. Actual VPS A/B/C and human listening remain pending. Receipt:
docs/tts-evaluation/kitten-micro/verification.json.

2026-10-09 Kokoro-first optimizations: 521 full unit/component/integration/native
and eval checks passed, zero failures/errors/skips. Ruff/format and strict mypy
passed; JUnit reports/kokoro-first-final.xml. Native Kokoro now drives the actual
local-WebSocket speech pipeline test with the unchanged Evolution adapter.
New checks cover callback-before-return/no duplicates, carry framing, bounded
callback/playback backpressure, cache restrictions, natural chunks, read-ahead,
barge-in cleanup and no leaked speech tasks. An isolated UUID-named PostgreSQL
database verified migration0006 legacy-row conversion, default voice and custom
voice preservation, downgrade/re-upgrade and schema agreement. Compose config
validated. Three sequential cloud buffered native cohorts produced 18 WAVs;
actual VPS/human quality/phone-capacity checks are not inferred.

2026-10-09 Kokoro INT8 optional-provider integration: full existing unit,
component, integration, native speech and eval collection passed 512 checks,
zero failures/errors/skips. Ruff/format and strict mypy passed (54 source
files). JUnit: reports/kokoro-int8-final.xml. New checks cover single preload,
worker selection/model sharing, frame conversion, bounded admission, repeated
cancellation/cleanup, corrupt assets, and benchmark scope/timing semantics.
Actual native Kokoro/Piper cloud smoke A/B processes exited zero and wrote
24 WAVs plus raw measurements. Actual VPS A/B/C remain unrun by user-approved
manual execution; no production switch/deployment or human voice score claimed.

## Isolated Kokoro streaming evaluation — 2026-10-09

Full scripts/check.sh passed 487 checks, no failures, errors or skips; Ruff,
format and strict mypy passed. JUnit: reports/tts-streaming-final.xml. Three
new evaluation harness checks cover resampling bounds, measured playback-gap
rendering and ordered 60 ms TTSProvider frames. Native benchmark children
completed sequentially; production code, dependency declarations and transport
remain unchanged. Model/voice hashes, dependency lock and license notices are
recorded in docs/tts-evaluation/streaming/.

## Whole-project integration — 2026-10-09

`UV_CACHE_DIR=/workspace/.cache/uv UV_NO_SYNC=1 bash scripts/check.sh
--junitxml=reports/v1-integration.xml -q` passed **476 checks**, zero failures,
errors or skips. The run covered knowledge SQL isolation/quota/atomicity,
dashboard/API contracts, upload admission, tool protocol/runtime, durable
transcript finalization, worker supervision, native speech bounds and existing
transport regressions. Ruff, format and strict mypy also passed. The report is
at `reports/v1-integration.xml`; no provider key was used.

## Concrete tools and call storage — 2026-10-09

Remote source verification: push run 37863783680 and PR run 37863788777 both
passed for c4c2c193440d37a9fe733bd15300f79a3625b1c9 (gh run watch
--exit-status). Fresh dependencies/native assets, real services, migrations and
the full scripts/check.sh completed. The following CI-evidence documentation
commit changes no implementation and does not inherit a claim about its own CI.

Full `UV_CACHE_DIR=/workspace/.cache/uv UV_NO_SYNC=1 bash scripts/check.sh
--junitxml=reports/concrete-tools-storage.xml -q`: 384 passed, zero failures,
errors or skips. Current JUnit inspected; Ruff/format/strict mypy pass. One existing
Starlette deprecation warning remains. Dedicated PostgreSQL/Redis and restored
native assets were used, with no live provider credential.

33 new concrete-tool checks exercise approved destinations, credentials kept in
server headers, trusted tenant envelopes, action-specific input/output schemas,
nonfinite/malformed/oversized/compressed replies, redirects, cancellation stream
cleanup, no retries, current-call ownership/state and acknowledgment/idempotency,
and fail-closed knowledge backend/foreign matches. HTTP and hangup are component
stubs; no actual n8n business action or Evolution hangup is claimed.

Nine new real-PostgreSQL integration checks cover repository isolation, composite
FK denials for foreign instances/calls, immutable finalization, controlled tool
completion codes, bounded reads/messages/executions, duplicate external IDs,
rollback/no implicit commit and eight concurrent writers. Fresh full migrations,
0004 downgrade/re-upgrade and schema comparison passed in a UUID-named separate
database, removed afterward. Existing project history was never downgraded.
Alembic check on the development database also reports no drift. No wave/live
behavioral gate or ten-call performance target is inferred from these checks.

## Independent tool gateway preparation — 2026-10-09

User deferred live OpenAI setup and requested other work. New independent
gateway checks cover tenant isolation, denied permissions before handler work,
strict input/output validation, snapshot isolation, nonfinite/oversized/cyclic
payload rejection, finite deadlines, fail-fast capacity, cancellation cleanup,
duplicate registration and sanitized exception/audit output. The same tool name
resolves independently for two tenants with positive execution controls.

Initial combined run: 340 passed, two audit-test capture failures because
production disables propagation on the vasa logger. Tests now attach capture
directly and restore logger state; production audit/privacy assertions remain.
Aggregate text bounds were also tightened before JSON serialization.

Final `UV_CACHE_DIR=/workspace/.cache/uv UV_NO_SYNC=1 bash scripts/check.sh
--junitxml=reports/tool-gateway.xml -q`: 342 passed; zero failures/errors/skips.
Current JUnit inspected. Ruff/format and strict mypy pass. The environment's
restored dependencies/native assets were used without resync; dedicated vasa-dev
PostgreSQL/Redis restarted and explicit Alembic migrations succeeded. One existing
non-failing Starlette deprecation warning remains. No real provider, n8n action,
knowledge retrieval, new phone call or capacity benchmark is claimed. Gateway is
not wired into the voice runtime; live dialogue and dependent completion remain
deferred.

## Before publication

2026-10-08 combined command: `bash scripts/check.sh --junitxml=reports/current.xml -q`.

110 passed; zero failures, errors or skips. Current-run JUnit inspected. Ruff lint/format and strict mypy across 27 source files passed. The suite includes 8 foundation unit checks, 21 real-service integration checks, 2 foundation isolation evals, 50 adapter HTTP/local WebSocket checks, 22 authenticated control checks, 1 control isolation eval and 6 manual-probe component checks. One non-failing upstream TestClient deprecation warning remains.

Exercised: real PostgreSQL migrations/schema/pgvector distance, FK ownership, uncommitted writes/rollback, cache expiry/corruption/size/namespace boundaries; dependency/schema readiness failures without leakage; scrypt/session/CSRF/origin/rate limits and session revocation; real tenant-filtered control APIs with upstream stubs and failure compensation; dashboard auth/CSP/local asset responses; cumulative ASGI body limits; adapter local WebSocket signed handshake, bidirectional PCM, bounds and idle cancellation; probe cancellation/failure cleanup and pending human audibility confirmation.

`bash scripts/setup.sh` repeated successfully; `uv run --frozen alembic check` reports no drift. Controlled Uvicorn stop/restart succeeded. HTTP /health/live, /health/ready, /login and login asset returned 200; /dashboard without authentication returned 401. Source preparation repeated with unchanged validated manifest and preserved secrets. Compose config validates.

Evolution Docker build: FAILED initially on absent proxy CA trust; corrected with authoritative host CA bundle without disabling verification. The next build failed with HTTP 403 on an official Go artifact redirect to storage.googleapis.com. No go.mod/go.sum changes, checksum overrides or TLS bypasses. Go package tests/vet, server compilation, provider startup and live license/call requests are therefore UNRUN. No real WhatsApp acceptance is claimed from local mocks.

Remote GitHub CI and fresh-cloud restoration are UNRUN. The initial migration/model CASCADE mismatch was fixed with migration 0002; tests compare the actual DB revision to committed head. No assertions or suites were disabled to pass.

## After user publication

`bash scripts/setup.sh` restarted the dedicated PostgreSQL/Redis services and
applied migrations successfully. `bash scripts/check.sh
--junitxml=reports/published-restore.xml -q` passed all 110 checks, with zero
failures/errors/skips. Current-run JUnit inspected. Ruff and strict mypy pass;
Alembic reports no schema drift. A restarted API returns HTTP 200 for live,
ready and login, with database/Redis both healthy.

`bash scripts/evolution-setup.sh` completed with exit 0. Official Go dependency
downloads and `go mod verify` passed. Registry and stream package tests passed;
handler/service packages report no test files. `go vet` and CGO server
compilation succeeded, followed by successful Docker image creation and healthy
provider startup. Image: `vasa-evolution-calls:e21ce0dd`, local image ID
`sha256:51faa4aa3072321af7ed834a1c58e58e05e896fb82a38897011e56252a0574be`.

Real provider HTTP checks: `/server/ok` returns 200 with the expected status;
`/license/status` returns inactive; authenticated `/instance/create` returns
503 with `LICENSE_REQUIRED`. No upstream instance was created by that blocked
request. This confirms the activation prerequisite, not real calling.

GitHub API access and draft PR creation now work. GitHub Verify run
37818843714 for code/evidence commit 1dd7714326e35d2ef00d16e093fa753289349669
completed successfully (confirmed with `gh run watch --exit-status`). This
validates the remote foundation workflow; it does not build the licensed
provider or exercise WhatsApp. Later documentation-only commits can trigger
additional workflow runs; their results must not be inferred from this one.

Vendor activation, WhatsApp pairing, dynamic UDP relays, actual call
answering/media/hangup and a separate fresh task restoration remain unverified.

## Rootless VPS deployment preparation

`bash scripts/check.sh --junitxml=reports/vps-preparation.xml -q`: 158 passed,
zero failures/errors/skips; current JUnit inspected. Ruff lint/format and strict
mypy pass. The 48 additional checks exercise private-file ownership/modes,
symlink/parent rejection, strong credential generation and idempotent retention,
malformed bindings, actual loopback socket collisions/cleanup, project ownership,
stopped/public/unrelated container exclusions and sanitized CLI output.

`bash -n deploy/up.sh` passed. The helper deliberately refused the cloud's
system Docker daemon before starting deployment; it requires the existing
rootless user/context. Populated Compose configuration validated with --quiet;
credentials were not rendered. No SSH keys or passwords were requested in chat.

VASA image built successfully with TLS verification, pinned Python/uv and frozen
production dependencies. UID 1000, package assets, readable Alembic files and
status helper verified. Local image ID:
`sha256:f4dc8e0ad4dcf325d130c789fb56b9265b627333a366cdc089d7ed3e9bbd7cf6`.
Read-only root prevents writes; the initialized private diagnostics volume permits
the prepared probe's output/report writes. No caller audio is recorded.

Separate cloud project vasa-package-check: actual PostgreSQL/Redis/Evolution/
VASA startup healthy, explicit migrations passed, Manager/login/readiness HTTP
200, DB/cache healthy, and status helper correctly reported inactive licensing.
Cloud-injected lowercase no_proxy initially overrode NO_PROXY and caused
internal HTTP 403; setting both variants fixed routing without disabling TLS.
Docker down/up retained PostgreSQL runtime_configs instance identity. Test
containers were stopped and volumes retained. This is cloud engine component
evidence; actual rootless VPS behavior, active-license survival and live calls
remain unrun.

Direct SSH attempt to vasa-builder@2.25.172.155:22 returned Connection refused
before authentication. No successful VPS connection or remote mutation occurred.
After the user confirmed the host/port and verified SSH externally, a retry
returned the same error. The existing configured HTTP(S) proxy accepted CONNECT
but closed after an SSH identification string, without a server SSH banner.
No authentication attempt reached the server, no SSH identity is available in
this environment, and no password/private key was requested.

## Real-call bidirectional acceptance — PASSED

2026-10-08: the user confirmed an actual inbound WhatsApp call was answered
through Evolution Go Calls. VASA received 98 live caller audio frames and sent
20 diagnostic audio frames. The human caller confirmed hearing the three rising
diagnostic tones. Gate 3 is PASSED and permits Wave 4 progression. This evidence
comes from the user's real-world acceptance report; no additional cloud call,
latency trace or active-license persistence check is claimed.

## Wave 4 — native CPU Voice Intelligence

2026-10-08: 23 VAD tests, 20 native speech/security/lifecycle tests and 66
OpenAI/Anthropic/local SSE checks passed without skips. Recognition uses three
independent checksum-pinned upstream recordings; native inference actually runs.
Audio resampling/framing, per-utterance isolation, actual inference cancellation,
checksum corruption and archive/path/symlink defenses are exercised. Provider
stream bounds, context isolation, malformed/tool responses, cancellation,
timeouts and failover-before-output are verified with loopback HTTP servers.
No live API reasoning is claimed.

Review caught VITS callback polarity differing from the Python binding's docs;
the pinned C++ implementation establishes 1=continue/0=stop. Fixed callback and
actual multi-sentence native regression preserve both synthesized batches.
No acceptance threshold changed. The cache rejects symlink ancestors/component
directories before any network or mutation.

`bash scripts/setup.sh` repeated twice; verified speech cache reused, dedicated
PostgreSQL/Redis healthy, migrations applied and Alembic check found no drift.
Restarted API live/ready/login returned HTTP 200 with DB/cache healthy. Native
models run in the production image as UID 1000 with read-only root; local TTS
produced 29 valid frames. Image includes native CPU shared libraries and pinned
frozen dependencies; no models, secrets or caller recordings are embedded.

## Wave 5 — conversation runtime integration

23 scripted runtime component tests pass: interruptible greeting, streaming
transcription, per-call context snapshots, bounded history/audio, paced output,
LLM/TTS/STT/media failures/deadlines, concurrent tenant isolation, late stale
output rejection and cancellation. These providers are explicitly scripted;
live reasoning and audible dialogue are not established.

13 trusted worker checks pass, including actual SQL tenant ownership controls,
foreign instance rejection before upstream work, answer/media/runtime failures,
metadata privacy and independent hangup/Redis cleanup. A repeated-cancellation
regression initially skipped Redis deletion; the separately owned bounded
shielded cleanup task now passes that regression.

The final production image also passed native model initialization and TTS
under the deployed 512 MiB/one-CPU limits, UID 1000 and read-only root. Produced
26 valid frames; process maximum RSS was 269164 KiB. This is one controlled
native smoke, not a simultaneous-call or API-plus-worker load benchmark.
Worker help and missing-provider preflight returned sanitized actionable output;
no call was answered when a provider binding was absent.

Native transport integration initially failed the strict first-word assertion.
Measured WebRTC onset at frame 7 / 420 ms: old 120 ms rolling capture began at
frame 5 / 300 ms and recognized 3/18 words incorrectly (16.67% WER); earlier capture
recognized 1/18 (5.56%) and restored AFTER EARLY. Runtime capture pre-roll is now
bounded 480 ms / eight frames, separate from classifier segment 120 ms pre-roll.
Deterministic delayed-onset and bounded-idle-buffer regressions verify the fix;
the strict original pipeline quality assertion is retained. The same wave also
fixes delayed LISTENING state callbacks overwriting newer response phases with
state revision guards. Twenty repeated earlier runtime/eval rounds passed 520
executions; newer pre-roll regressions are included in final verification.

Final combined run: `bash scripts/check.sh --junitxml=reports/voice-wave-final.xml -q`
passed 318 tests with zero failures/errors/skips; current JUnit inspected. Ruff
lint/format and strict mypy pass. One existing non-failing Starlette TestClient
deprecation warning remains. This includes 26 runtime checks, 22 worker checks,
2 scripted conversation evals and the actual native speech/unchanged-adapter
local WebSocket pipeline, alongside the previous 158 foundation/deployment checks
and 109 speech/LLM checks. No disabled suites or silent missing-model skips.

Final production voice image rebuilt after all fixes:
`sha256:f8a007c0fc8edbb3af36d416a44443782ba728be5763446d74fdbb4d4184bf00`.
Installed worker help succeeds with read-only root; migrations have no drift.
Docker Compose deployment config and shell syntax validate without rendering
credentials. Actual rootless VPS run and live OpenAI dialogue remain unrun.

Remote CI at code 757e1be: PR run 37857727899 passed; parallel push 37857723710
failed one supplemental STT word assertion in the TTS completion regression
(appointment recognized as ultimate; final sentence still generated). Corrected
the regression to observe actual native VITS batch progress 0.5/1.0 and exact
resampled frame count; an inverted callback still fails by missing batch 2.
Native inference/audio remain real. Independent STT fixture WER acceptance is
unchanged. Updated 20 native checks passed; combined and new remote checks follow.

A subsequent full run also exposed randomized articulation in the separate
supplemental roundtrip (appointment transcribed as acquaintment). Production
VITS now disables stochastic noise for consistent business speech, verified with
byte-identical repeated output and the original appointment/tomorrow assertions.
All 43 native/VAD checks pass. Native batching regression directly verifies both
real progress callbacks plus exact resampled frame count and an actual wrong-
polarity negative control. Independent recording WER remains 7.79%, unchanged.
Benchmarks are regenerated for this final production setting.

Latest final combined run passed 318 tests, zero failures/errors/skips, with
original supplemental word assertions and the real batching negative control.
Ruff/format/strict mypy pass. Final production image
`sha256:5a89802d2f9addc649b42949c4bf8f0cae3b63d2d776c93d3e7d241120343b70`
produced 49 identical repeated speech frames under 512 MiB/one CPU/read-only root
as UID 1000. Updated benchmark evidence records the final zero-noise settings.

Final remote verification: GitHub push run 37858367544 and PR run 37858371785
both completed successfully for code 61b57d9e3d85a70ae6d49075a87ee1fa19e17e79
(confirmed via gh run watch --exit-status). Both fresh Ubuntu workflows prepared
verified native assets, migrated real PostgreSQL, and ran the full 318-check
suite with Ruff/format/strict mypy. Source tests were not excluded. A subsequent
documentation-only CI evidence commit does not inherit these workflow results.

## Authorized health-client recovery continuation — 2026-10-17

Full integrated local suite: 1,423 passed (one upstream Starlette deprecation
warning); two subsequent independent-runner fail-closed regression cases passed
in the focused orchestrator suite. Ruff, format, application strict mypy and seven
deployment modules' strict mypy passed. Actionlint, Bash syntax and diff checks
passed. Full pinned Go tests/vet, call/media race tests and real PostgreSQL
120-cycle lifecycle/reuse/shutdown/race verification passed. No live replacement
is inferred from these tests. Fresh automatic read-only readiness is next.

Fresh identified-health source/request CI runs39012987764/39013001437 each
passed1,425 tests; read-only request39013001527 succeeded with required public,
private, authorization, no-call and preservation gates. After binding the scoped
renewal, full local suite1,425 passed in80.70s; Ruff/format, strict mypy,
actionlint and shell checks pass. These results authorize proceeding through
fresh maintenance gates; they do not establish a deployed fixed Evolution image.
