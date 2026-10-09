# Test results

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
