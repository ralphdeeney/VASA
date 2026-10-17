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
connected instance set. Unknown/nonzero state defers. After backups, pause voice
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
Evolution is restored if validation fails. Capacity is sampled three times after
rollout; total Evolution sockets must remain within the two existing 25-open
process pools, and decrease from an exhausted baseline.

SMTP is explicitly deferred by the operator. No credentials are requested or
invented and live email acceptance is not claimed. Human real-call stability
validation remains separate from pool health evidence.

# Staging deployment through GitHub Actions

2026-10-15 private ingress: VASA publishes exactly 172.16.2.1:18081 to 8080/tcp
for the host-private public Caddy path. Evolution stays 127.0.0.1:18080 to
4000/tcp. Target config and actual container bindings are checked, rejecting
wildcards/additional publications. Host checks use the private /login=200,
assets=200 and /dashboard=401. Rootless operation, health/readiness, private env
hashes, dependency identity and rollback remain required. No root-owned proxy
changes. References to VASA loopback below describe the earlier phase.

2026-10-15 push automation: every push to build/vasa-foundation now resolves
mode=deploy and provider_smoke=false. Manual check/bootstrap/deploy and opt-in
smoke remain available. Both triggers use the same SSH wrapper/controller.
Bootstrap and migrations never run on push. The five-field Actions job summary
contains trigger, target SHA, resolved mode, smoke boolean and deployment result.
Existing concurrency, exact SHA/branch, trust, rootless, private env hashing,
clean-tree, app-only update and rollback protections remain in force.

Post-deploy validation proves the target SHA, mandatory five-service health,
stable process counts, unchanged dependency identities, sanitizer availability,
VPS loopback 18081/18080 HTTP bindings, /login and its assets, the actual dashboard
401 auth boundary, internal Evolution process/license health and existing mapped
WhatsApp instance connected/logged-in status. No account/password/session is
created; actual authenticated login remains a human credential gate. Validation
prints only fixed markers and fails/rolls back on failure. Paid LLM/TTS smoke
remains off for push. Public URLs require the external ingress work described in
docs/PUBLIC_URL_PREPARATION.md; the deploy controller never edits that proxy.

Historical manual workflow instructions below remain valid for explicit runs;
statements below that there is no push trigger describe the earlier phase.

## Normal development after successful bootstrap

The operator confirmed the bridge and voice bootstrap succeeded. All five services
now exist: postgres, redis, evolution, vasa, voice. Use `deploy` for code updates;
it still refuses a missing voice service. Normal deploy and live provider tests
remain pending actual VPS verification. Do not repeat bootstrap on this topology.

1. Change code; run `bash scripts/check.sh` and Actionlint; commit and push
   `build/vasa-foundation`.
2. Dispatch the workflow against that branch; the dispatched SHA must still match
   the fetched branch tip. No automatic push trigger is installed.
3. Inspect sanitized results. API health, all five containers and stable voice
   readiness are mandatory. Expected success: `VASA_DEPLOYMENT_OK`.

```bash
gh workflow run vasa-vps-deploy.yml --repo ralphdeeney/VASA \
  --ref build/vasa-foundation -f mode=deploy -f provider_smoke=false
```

To explicitly enable paid live provider tests after the same health validation:

```bash
gh workflow run vasa-vps-deploy.yml --repo ralphdeeney/VASA \
  --ref build/vasa-foundation -f mode=deploy -f provider_smoke=true
```

Smoke is refused in `check` or `bootstrap` modes. It is off by default, runs outside
the call runtime, and uses the existing app container's private environment. A
smoke failure fails deployment and invokes the existing app-only rollback; probes
are not retried during rollback. No dependency service is restarted. Health is
checked again after a successful smoke and private runtime hashes must match.

Alternatively, an operator already on the VPS can run the standalone command
after deploying this tooling (Codex must never SSH directly):

```bash
cd /opt/vasa
docker compose --project-name vasa-vps --env-file .local/vps.env \
  -f deploy/compose.yaml --profile voice exec -T vasa \
  python scripts/live_provider_smoke.py
```

The script makes one bounded request to each provider, sequentially, even when the
other fails. It uses `VASA_LLM_PRIMARY=openai`, `VASA_OPENAI_BASE_URL`,
`VASA_OPENAI_MODEL`, `VASA_OPENAI_API_KEY`, `DEEPGRAM_API_KEY` and
`VASA_DEEPGRAM_MODEL` from private runtime configuration. Never supply keys as CLI
arguments. No models are loaded/downloaded, no tenant data queried, and no files
or WAVs are saved. Exit status is nonzero if either probe fails.

Success emits `LLM_SMOKE_OK`, `LLM_FIRST_TOKEN_MS`, `LLM_TOTAL_MS`,
`DEEPGRAM_SMOKE_OK`, `DEEPGRAM_FIRST_AUDIO_MS`, `DEEPGRAM_TOTAL_MS` and
`DEEPGRAM_AUDIO_MS`. Failure emits fixed `*_SMOKE_FAILED` codes; Actions captures
nonzero exits and prints approved failure markers before invoking rollback.
It withholds stderr and raw output, printing only allowlisted status/timing
lines, never arbitrary container output. No URLs, keys, prompts, response bodies
or exception strings are printed. HTTP/provider logging is disabled in the smoke
process. Generated audio duration includes final framing padding. This is a small
availability test, not a throughput or percentile benchmark. Human voice review
and a full live WhatsApp AI call remain separate pending gates.

Codex Cloud must not SSH directly to this VPS. Only the manually dispatched
`.github/workflows/vasa-vps-deploy.yml` connects. There is no push deployment
trigger. Select branch `build/vasa-foundation`; default mode is `check`.

The workflow uses the existing `/opt/vasa/deploy/compose.yaml`, project
`vasa-vps`, and `.local/vps.env`. Application services are `vasa` and `voice`;
only `vasa` has a build definition and both share `vasa-app:pinned`. `deploy`
is strictly update-only. Explicit `bootstrap` can create only the missing voice
worker in the healthy four-service topology described below. Neither mode
invokes `deploy/up.sh`, which also manages Evolution/bootstrap assets.

## GitHub configuration

Existing repository secrets (never print them): `VASA_VPS_HOST`,
`VASA_VPS_USER` (must resolve to `vasa-builder`), `VASA_VPS_SSH_KEY`.
The SSH key must support noninteractive authentication on port 22. VPS Git
authentication for `git fetch/pull` must already work as `vasa-builder`;
the workflow does not copy a GitHub token or other credentials to the server.
The existing VPS origin `git@github-vasa:ralphdeeney/VASA.git` is explicitly
accepted alongside the canonical GitHub origins. The `github-vasa` SSH config
alias remains under `vasa-builder`'s existing configuration; no remote rewrite,
GitHub password or PAT is required. Other aliases/repositories are not accepted.

Set repository **variable** `VASA_VPS_HOST_KEY_SHA256` to a trusted SSH host-key
fingerprint, obtained through the VPS provider console, not a network scan:

```bash
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub -E sha256
```

Use only the `SHA256:...` field. This is public host-key metadata. The runner
scans host keys into a temporary file and accepts only the key matching that
fingerprint. Missing/mismatched trust fails before SSH login in all modes.
It never prints the host, username secret, private key, scanned keys, or remote
environment. Strict host checking, a dedicated mode-0600 temporary key, no
agent/config forwarding, and cleanup on success/failure are enforced.

GitHub only registers a new `workflow_dispatch` workflow when its file exists
on the repository default branch. Registration PR
[ralphdeeney/VASA#2](https://github.com/ralphdeeney/VASA/pull/2) adds only the
workflow to `main`; helpers remain on `build/vasa-foundation` and are checked
out from the dispatched commit. Merge that PR through the normal review process.
Do not switch the repository default branch just to register this workflow.
An initial dispatch returned HTTP404 before registration; no VPS operation ran.
Then dispatch its `build/vasa-foundation` version:

```bash
gh workflow run vasa-vps-deploy.yml --repo ralphdeeney/VASA \
  --ref build/vasa-foundation -f mode=check
gh run list --repo ralphdeeney/VASA --workflow vasa-vps-deploy.yml --limit 5
gh run view RUN_ID --repo ralphdeeney/VASA --log
```

Expected final marker: `VASA_VPS_CONNECTIVITY_OK`. Check mode verifies exact
user, owned repository/path/identity, branch/SHA, Docker info/rootless security
options, Compose version, and the owned Unix socket. It does not create remote
files, fetch, change Git state, build, restart, or inspect application secrets.
Python 3, Git, Docker and Compose must already be installed on the server.

## One-time missing-worker bootstrap

The operator confirmed the Actions bridge works and the VPS has exactly these
healthy containers: `vasa-vps-postgres-1`, `vasa-vps-redis-1`,
`vasa-vps-evolution-1`, `vasa-vps-vasa-1`. No voice container exists. This is the
only topology accepted by `bootstrap` (including stopped containers in checks).
All four must have the expected project/service/working-directory ownership
labels. An existing worker, missing or unhealthy dependency, duplicate service,
or extra project container causes refusal. Unrelated Compose projects are ignored.

Run **VASA staging VPS**, branch **build/vasa-foundation**, mode **bootstrap**:

```bash
gh workflow run vasa-vps-deploy.yml --repo ralphdeeney/VASA \
  --ref build/vasa-foundation -f mode=bootstrap
```

Bootstrap uses the same trusted SSH, exact user/path/repository checks, rootless
Docker, clean-tree rule, project lock and Actions concurrency as deploy mode.
Before fetching, it verifies the private runtime environment files are untracked
and hashes them, validates Compose, checks the four-service health/readiness,
and requires a non-empty `DEEPGRAM_API_KEY` in the resolved voice environment.
If absent or blank it fails with **`DEEPGRAM_VPS_KEY_REQUIRED`**. Configure that
key privately on the VPS in `/opt/vasa/.local/llm.env`; do not commit it or
pass it through Actions. No provider secret is printed, copied or written by
bootstrap. Existing provider selection and all runtime files are preserved.

It records `PREVIOUS_SHA`/target SHA, fetches the existing authenticated origin,
requires the target to match `origin/build/vasa-foundation` with fast-forward
ancestry, and refuses schema/migration changes or tracked private files. It
checks out/pulls the staging branch, validates Compose and refuses dependency,
network or volume changes. It always builds only `vasa`'s shared image. The
existing API is updated only if its image ID or service configuration changed;
otherwise its running container is left alone. The worker is created separately
with `up -d --no-deps --wait voice` from that same image.

Success requires exactly one owned, running worker on the shared image, no OOM,
stable restarts, the worker readiness log marker, healthy API live/ready probes,
and unchanged dependency IDs/images/start times/restart counts. Private file
hashes must still match. Only then is **`VASA_BOOTSTRAP_OK`** printed. The
nonsecret receipt is `.local/actions-bootstrap.json`.

On failure, rollback removes only the newly attempted voice container after
validating its single-ID ownership. It restores the prior Git revision under
the clean-tree check and the verified rollback image described below. Only an API whose
update was attempted is restored with a targeted `up --no-deps vasa`. It never
recreates database, Redis or Evolution. Health validation runs for the original
four-service topology, with no worker expected, and checks unchanged dependencies
and private hashes again. It prints **`VASA_BOOTSTRAP_ROLLBACK_OK`** only after
successful recovery and still exits nonzero. Failed recovery prints
`VASA_BOOTSTRAP_ROLLBACK_FAILED`; raw logs and secrets remain withheld.

After success, use normal `deploy`. It still requires exactly one existing
worker and never falls back to bootstrap. Repeating `bootstrap` is refused.

## Provider-aware speech asset checks

Worker startup always checksum-verifies the local Sherpa ASR assets. It then
verifies only the selected TTS provider's assets:

| Trusted TTS provider | Additional local runtime assets |
| --- | --- |
| `deepgram` | None |
| `speechify` | None |
| `piper` | Pinned Piper model/files and eSpeak resource tree |
| `kokoro-int8` | Pinned Kokoro model/files and eSpeak resource tree |
| `kitten-micro` | Pinned Kitten model/files and eSpeak resource tree |

Test WAV/transcript fixtures are not required by the worker. Runtime verification
never downloads models and preserves all checksum/resource-tree checks. Trusted
Kokoro/Kitten model-directory settings are honored. A read-only operator check
is available in the runtime/repository environment with its speech cache mounted:

```bash
python scripts/prepare_speech.py --verify-runtime --tts-provider deepgram \
  --directory .local/speech
```

Use the matching `--tts-provider` for other providers; optional
`--kokoro-model-dir`/`--kitten-model-dir` select their trusted runtime paths.
Without `--verify-runtime`, the existing provisioning script still prepares the
complete ASR/Piper/Kokoro/fixtures bundle; `--verify-only` verifies that full
bundle, and `--kitten-micro` still adds/verifies the optional Kitten assets.

For Deepgram/Speechify, persisted tenant voice metadata (including legacy local
voice labels) is ignored. Cloud model/voice selection comes only from trusted
server settings, never tenant voice strings. English-language validation and
the existing fixed local-provider voice allowlist remain enforced. This changes
neither Deepgram/9Router configuration nor the deployment topology.

## Target worker startup diagnostics

Manual `compose run voice` after rollback starts the restored **old** pinned
image. Its traceback cannot diagnose the failed target image. The controller
therefore extracts bounded, secret-safe lifecycle markers from the owned target
voice container **before** removing it or resetting Git/image tags.

The worker flushes fixed `VOICE_STARTUP_STAGE=<stage>` lines around settings,
provider-aware speech verification, database, Redis, Evolution client, instance
resolution/status, persisted config, knowledge/tool initialization, LLM provider,
STT/TTS initialization, runtime construction and readiness. Startup failures emit
only fixed stage/code fields (plus the existing generic CLI message). Example
format, not a diagnosis of the current VPS failure:

```text
VOICE_STARTUP_STAGE=llm_provider
VOICE_STARTUP_FAILED=llm_provider
VOICE_STARTUP_ERROR=invalid_configuration
```

Failure codes are limited to `invalid_configuration`, `invalid_assets`,
`missing_assets`, `dependency_unavailable`, `initialization_failed`,
`operation_failed` and `internal_error`. Exception messages, response bodies,
prompts, keys, auth headers, credentials/URLs and caller identifiers are never
serialized into these fields. Unexpected exception types are also caught by
the CLI without a raw traceback. Failures after readiness use
`VOICE_RUNTIME_FAILED`/`VOICE_RUNTIME_ERROR`, including later reconciliation;
routine runtime stage transitions are tracked without continuous stage logging.

Pre-rollback diagnostics read the last 200 stdout/stderr lines across container
restarts (not only the latest `StartedAt` interval). Only exact ASCII lifecycle
markers with known keys and allowlisted values are reconstructed and printed,
limited to the last 64 markers. Other lines, malformed fields and suffixes are
discarded. Health validation rejects known lifecycle failure markers even when
a readiness marker appeared earlier in that attempt. Post-rollback diagnostics
do not emit lifecycle markers from the restored old worker image. An empty or
unreadable log cannot supply a diagnosis; raw logs are never dumped as fallback.

## Deploy

Only after the check passes, manually select `deploy`:

```bash
gh workflow run vasa-vps-deploy.yml --repo ralphdeeney/VASA \
  --ref build/vasa-foundation -f mode=deploy
```

The dispatched commit is the target. Branch movement after dispatch fails
safely; dispatch again rather than silently deploying a newer revision.
Deployment requires a clean tree (including untracked, nonignored files),
the staging branch already checked out, all five existing containers healthy,
and the existing worker readiness marker. Dirty state is never discarded.
A project-local advisory lock plus Actions concurrency serializes deployments.

The controller records `PREVIOUS_SHA` and `TARGET_SHA`, fetches origin, verifies
fast-forward ancestry, then uses `git checkout build/vasa-foundation` and
`git pull --ff-only origin build/vasa-foundation`. It validates Compose without
printing resolved environment. Existing runtime files, including `.local/llm.env`
and `.local/vps.env`, are hashed in memory for preservation, never copied or
printed. Deepgram credentials must already be in the VPS private environment;
workspace credentials are not transferred. Explicit existing provider settings
are preserved.

Source/dependency/image changes build only `vasa`, then update `vasa` and `voice`
with `up -d --no-deps --wait`. A per-service Compose change updates only that
app service. Documentation/workflow-only revisions do not build/restart apps.
Dependency service, network, volume, or database migration changes fail safely
and require separate operator planning. No automatic Alembic migration is run:
a Git/image rollback cannot safely undo arbitrary schema/data changes.

Existing rootless context/socket selection is preserved. If only the default
rootful socket is selected, the controller derives the user's rootless socket
from their owned runtime directory/UID. It requires a local owned Unix socket
and `name=rootless` in Docker security options. No `sudo`, systemd, Docker daemon
restart, pruning, Compose `down`, dependency recreation, or unrelated project
operation is performed. Evolution, n8n, Hermes and their containers are untouched.

## Health and rollback

Health checks verify Compose ownership labels and running/healthy state for
the expected containers, API `/health/live` and `/health/ready`, the existing
worker startup marker, bounded recent log failure markers, no OOM, and an
eight-second process/restart stabilization interval. Logs are inspected in
memory and classified; arbitrary raw lines and exception bodies are withheld.
Readiness does not establish live phone/media or vendor API acceptance.
`VASA_DEPLOYMENT_OK` is printed only after all checks pass.

Deployment failures return a nonzero job result even when rollback succeeds.
The controller prints sanitized VASA-only diagnostics, checks that no concurrent
local edits appeared, and performs the sole allowed `git reset --hard` to the
recorded `PREVIOUS_SHA` under the lock. It retags the preverified VASA-only
rollback image and restores only the selected app services if an update was
attempted. Recovery needs no image rebuild or registry access.
All health checks run again. Markers: `VASA_ROLLBACK_OK` or
`VASA_ROLLBACK_FAILED`. The latest nonsecret receipt is
`/opt/vasa/.local/actions-deployment.json`; rollback images are retained, not
pruned automatically. No environment, data, volume or dependency rollback occurs.

Ordinary command errors, bounded timeouts and catchable disconnect/termination
signals invoke rollback. Host power loss, SIGKILL, a killed runner, or Docker
daemon failure cannot guarantee automatic recovery; consult the receipt and
restore the recorded app commit/image through the provider console. Never
cancel an in-progress deployment to start a second one.

## Acquiring a rollback image when the running image is unavailable

Both `bootstrap` and `deploy` acquire and verify a rollback image before target
checkout/pull, target build, or any container update. The normal path inspects
the running container's image ID, tags it, and inspects the rollback tag.

A running container can remain healthy even though its image ID is no longer
available in Docker's local image store. If inspection or tagging fails, the
controller verifies that the checkout is still clean at `PREVIOUS_SHA`, then
builds from that source using the existing Compose build definition. An in-memory
Compose override changes only `vasa`'s output image name:

- Bootstrap: `vasa-app:bootstrap-rollback-<PREVIOUS_SHA>`
- Deploy: `vasa-app:rollback-<PREVIOUS_SHA>`

The existing context, Dockerfile, dependency lockfile, build arguments and trust
inputs are reused. The fallback build does not overwrite `vasa-app:pinned`, stop
or recreate the healthy API, or touch dependency containers. It does not use
`docker commit` or inspect container environment. Private runtime files remain
excluded from the build context by the existing Dockerignore allowlist.

The resulting rollback image is inspected successfully and the source revision,
clean tree and private hashes are checked again before proceeding. A failed
fallback build or verification aborts without changing the Git checkout or
running containers. A source rebuild can have a different image ID from the
unavailable original; its actual verified ID is retained for rollback validation.

Recovery retags the verified image to `vasa-app:pinned` without a second build or
registry dependency. App services are restored only if their update was attempted.
If target build failed before any app update, existing healthy containers keep
running and only the image tag/Git checkout are restored. Bootstrap still removes
only its newly created worker. Dependency containers are never restarted.

Secret-safe stage markers precede important operations, for example
`BOOTSTRAP_STAGE=rollback_image`, `BOOTSTRAP_STAGE=git_fetch`,
`BOOTSTRAP_STAGE=checkout`, `BOOTSTRAP_STAGE=target_build`,
`BOOTSTRAP_STAGE=vasa_update`, `BOOTSTRAP_STAGE=voice_create`, and
`BOOTSTRAP_STAGE=health`. Deploy uses `DEPLOY_STAGE=...`; recovery uses
`rollback`/`rollback_health`. Command failures identify the active stage while
withholding raw commands, build logs, credentials and environment values.

## SaaS rollout gate (2026-10-16)

Normal code-only updates remain `mode=deploy`, never bootstrap. The additive SaaS
change introduces migration 0007, so the unchanged controller must refuse that push
before modifying staging checkout/services. Do not disable this refusal or execute
an automatic migration. Review `docs/DB_MIGRATION_PLAN.md` and the committed exact
SQL first; the operator backup/migration/enablement process is a separate gate.
A failed staging run with the explicit schema-change refusal is expected and does
not authorize changing private environment files or infrastructure. After that
approved rollout, standard Actions deploy/health checks continue unchanged.

Optional operator-only auth diagnosis in the approved image:
`python -m vasa.control.diagnostics --origin https://vasa.litatech.xyz`.
It emits fixed sanitized status/category markers only; it does not take credentials
or reset/create users. Keep public proxy/tunnel policies separate from app auth.

Recovery investigation: manually run `mode=check`, `recovery=investigate`,
`provider_smoke=false`. It preserves the checkout, captures actual Git diffs
without forwarding them, reports safe structural metadata/configuration presence,
and performs one synthetic failed-login probe (normal Redis rate limiter applies).
No real password is accepted, no account is created, no environment values or raw
logs/diffs are printed. Normal deploy/bootstrap still refuse dirty working trees.

`recovery=prepare` is a separate explicit check-mode action: isolated sources,
private restore-tested backup, clone-only migration compatibility and separate
candidate/rollback images. It preserves the dirty canonical checkout and all
running services. It does not execute a live migration, enable SaaS, configure
SMTP or activate an image. See `docs/SAAS_RECOVERY_STRATEGY.md` for the exact gate.

## Explicit immutable recovery activation

Normal pushes retain the clean-checkout and migration refusal gates. When operator
files block that path, manual `mode=check,recovery=activate` requires an exact
`release_sha` and reviewed `migration_sql_sha256`. This is a mutating, separately
authorized recovery operation, despite its check-mode namespace. It first repeats
the isolated backup/restore and cloned migration checks. Only the reviewed 0007
SQL is applied; only VASA app/voice are recreated, using immutable release tags.
Canonical checkout, operator files, private env hashes, postgres/redis/evolution
configuration and container identities are preserved. A private release journal
records the actual active source/image independently of the canonical checkout.

Rollback restores verified previous app images; additive schema0007 remains,
without destructive downgrade or restoring stale database data. SMTP absence does
not block legacy login testing but keeps email-dependent flows unavailable.

## Verified isolated staging delivery and cleanup

Release `858b5f853957d719a34ea96f28b5ea726100d402` is active after approved
Actions run 38953426795 (`VASA_DEPLOYMENT_OK`). The original checkout stays at
502b8d8 with operator infrastructure files intact; normal automatic deploy keeps
refusing that dirty checkout. Do not infer runtime version from canonicalHEAD.

For an explicitly needed web-pool recycle followed only by audited test cleanup,
dispatch `mode=check,recovery=none,provider_smoke=false,saas_acceptance=true,
cleanup_only=true,recycle_api_pool=true`. This restarts only the exact existing
VASA web container; it does not rebuild/reconfigure it, restart voice/dependencies,
run migrations or provision more test users. Run38957178699 passed all preservation
and health checks and emitted `LIVE_SAAS_CLEANUP_ONLY_OK`. Never treat this as a
permanent fix for Evolution holding95 of 100 PostgreSQL connections. See the review-only
Evolution pool recovery plan; protected dependency changes need separate scope
authorization and an operator no-call window. SMTP-dependent live flows remain gated.
