# Public-health diagnosis and reviewed recovery preparation

Live read-only evidence, 2026-10-17. No maintenance gate change is active.
No Evolution grant was created and no container was restarted/replaced.

## Proven request trigger

On both the VPS and GitHub runner, default Python urllib receives403 through
public ingress. The same urllib client with the honest identifying User-Agent
`VASA-Health-Diagnostic/1.0` receives login200, readiness200 and dashboard401.
Only the UA changes in this controlled urllib pair: GET, URL, Host/SNI, TLS
validation and HTTP/1.1 remain the same. Curl with default or identifying UA also
succeeds. This reproduces in the separate cloud environment as well.

| Origin / client | Login GET | Ready GET | Dashboard unauthenticated GET |
| --- | --- | --- | --- |
| VPS private origin, default urllib | 200 | 200 | 401 |
| Public VPS, default urllib | 403 | 403 | 403 |
| Public VPS, identified urllib | 200 | 200 | 401 |
| Public GitHub runner, default urllib | 403 | 403 | 403 |
| Public GitHub runner, identified urllib | 200 | 200 | 401 |
| Public curl, both vantages and both UAs | 200 | 200 | 401 |

This is a client-dependent public-ingress denial, not proof of an unhealthy VASA
application or a VPS-only source-IP block. The exact Cloudflare ruleset/product,
matched rule, and whether an upstream ingress component contributes remain
unproven without operator security-event review. Cloudflare response headers do
not, by themselves, prove a specific WAF/bot rule.

## Other controlled observations

- VPS explicit IPv4 and IPv6 curl login GET both return200. DNS resolves two
  addresses in each family. GitHub-runner IPv6 fails at the network layer, while
  its default/IPv4 requests succeed; this does not establish an application fault.
- The paired urllib requests both use HTTP/1.1. Curl negotiates HTTP/2. Success of
  identified urllib HTTP/1.1 shows HTTP/2 is not required to avoid the denial.
- No proxy environment is configured on VPS/runner. Cloud has an inherited proxy;
  it is retained. Trace fingerprints differ between vantages but match between
  clients within each vantage. Raw source/destination addresses are not recorded.
- Public Host/SNI stays `vasa.litatech.xyz`; private HTTP uses the fixed bridge
  origin. TLS remains verified for actual public responses. No redirect is followed.
- HEAD login returns405 while GET succeeds. Readiness must use GET.
- Responses do not carry a challenge indicator. Approved metadata includes
  content-type category and proxy-header presence only, never raw header values.
- Exact UTC start times and measured elapsed milliseconds are in the observations.

## Operator event correlation

VPS default urllib denied request:
`2026-10-17T06:37:05Z`, `/login`, GET, Ray `a4bd4aeaac4f0956-EWR`.
Nearby successful identified-urllib request:
`2026-10-17T06:37:05Z`, Ray `a4bd4aeb7bff255d-EWR`.

GitHub runner denied request:
`2026-10-17T06:36:37Z`, Ray `a4bd4a406dbb30d4-SEA`;
identified request200: same UTC second, Ray `a4bd4a40bdb390db-SEA`.

Search Security Events by Ray and UTC (allow clock-skew margin), hostname/path,
method and UA profile. Compare matched product/rule/action and origin reachability
with the successful pair. Do not share credentials/cookies/full headers/bodies.
No Cloudflare security changes are authorized or performed.

## Preserved runtime and checkout

All five VASA containers remained healthy, unchanged and restart_count0. The
internal API JSON liveness/readiness and worker readiness checks passed. Private
runtime hashes, operator files and database identities are unchanged. Evolution
uses `sha256:d0b8a492d7976e56f90333ea4f472fbcc75c50ecdbe073df8ff78a268460c0d3`,
exactly matching the previously verified fallback rollback image. Its revision is
pre-fix upstream `e21ce0dd7634f3047410c893b5e4d1c082034b84`. The original missing
image differs, as expected after a previous-source fallback rebuild. Paired-device,
instance-credential and schema identities match an archived private backup receipt;
that comparison does not constitute a new backup-restoration test.

PostgreSQL before/after: Evolution1, web1, voice1, other0,total3. Calls/media sockets0.
The existing instance remains disconnected/logged-out; no reconnect or pairing
operation was attempted. The pool fix is NOT deployed or claimed production-fixed.

Canonical checkout: `502b8d8715aaeb34d3f129628fa754ccba447f13`.
Active app/voice release: `858b5f853957d719a34ea96f28b5ea726100d402`.
Tracked changes0; untracked files exactly `edge/Caddyfile`,
`edge/docker-compose.edge.yml`, `tunnel/docker-compose.yml`. The first is a reverse
proxy file referencing the private origin; the third is tunnel configuration.
Normal deploy refuses them at its clean-tree gate before fetch/build/update.
Their content was inspected only for bounded structural flags and fingerprints.
No file was moved, overwritten, stashed, cleaned, removed or tracked.

Use the existing isolated-release model; see [the recovery plan](../RELEASE_RECOVERY_PLAN.md).
Do not attempt to fix this refusal by modifying running infrastructure files.

## Approval-ready correction, not applied

[The minimal proposed patch](proposed-identified-health-client.patch) identifies
health urllib requests honestly and retains fixed URLs, GET, TLS, no redirects
and every existing status/rollback check. It is syntax-compiled and
`git apply --check` passes, but the patch has NOT been applied. Its exact request
shape is exercised by live diagnostics. See [the readiness contract](../HEALTH_READINESS_CONTRACT.md).

Required approvals remain distinct:

1. Explicit approval of this health-client/readiness-policy correction before it
   can permit maintenance. No diagnostic success automatically overrides a gate.
2. A renewed, bounded Evolution maintenance authorization for the pinned fix,
   including fresh no-call, backup/restoration and rollback gates. The old grant
   remains consumed; this task did not create a replacement grant.
3. Any future application isolated-release activation/migration remains subject to
   its own existing review; this task only prepares its safe design.

## Evidence, reproduction and tests

- [HTTP observations](http-observations.json):60 sanitized records from cloud,
  GitHub runner and VPS (including private origin).
- [Recovery audit](recovery-audit.json):12 sanitized image/file/preservation records.
- [Summary](summary.json):machine-readable actual outcome and approval state.
- Actions read-only run39010351757, request envelope
  `d9a09e8d92a7968debb15e7be6d15c3fddd16405`, source
  `be39ad7be11d5546c4fd6b304dfb17d54600407d`. The run correctly ends BLOCKED at
  the unchanged legacy public urllib403 gate, after publishing all safe evidence.
- Verify39010346087/39010351765 each passed1,379 tests; local full suite1,377
  plus two additional TLS-reporting tests passed. Ruff/format, strict mypy69source
  and7deployment modules, actionlint and Bash checks pass. Go full tests/vet,
  call/media race and real PostgreSQL120-cycle lifecycle/race checks pass.

Codex can reproduce from a clean trusted branch checkout by generating a fresh
routine `evolution_check` request with `python -m deploy.create_request`, committing
only that request, and pushing. Exact-SHA CI precedes runner probes and the existing
Actions SSH bridge; no direct Codex SSH or manual Actions selection is necessary.
The private payload carries reviewed diagnostic code without changing canonical
VPS source. A local standalone public probe is
`python -m deploy.health_diagnostics --vantage cloud`.
SMTP and all unrelated infrastructure remain untouched.
