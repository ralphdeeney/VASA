# Test results

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
