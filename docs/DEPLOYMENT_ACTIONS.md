# Staging deployment through GitHub Actions

Codex Cloud must not SSH directly to this VPS. Only the manually dispatched
`.github/workflows/vasa-vps-deploy.yml` connects. There is no push deployment
trigger. Select branch `build/vasa-foundation`; default mode is `check`.

The workflow uses the existing `/opt/vasa/deploy/compose.yaml`, project
`vasa-vps`, and `.local/vps.env`. Application services are `vasa` and `voice`;
only `vasa` has a build definition and both share `vasa-app:pinned`. This is an
update path for an already healthy staging installation, not a bootstrap path.
It never invokes `deploy/up.sh`, which also manages Evolution/bootstrap assets.

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
fingerprint. Missing/mismatched trust fails before SSH login in both modes.
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
recorded `PREVIOUS_SHA` under the lock. It rebuilds the prior app image and
restarts only the same selected services. A saved VASA-only rollback image tag
is used if the rollback build fails (for example, registry/network failure).
All health checks run again. Markers: `VASA_ROLLBACK_OK` or
`VASA_ROLLBACK_FAILED`. The latest nonsecret receipt is
`/opt/vasa/.local/actions-deployment.json`; rollback images are retained, not
pruned automatically. No environment, data, volume or dependency rollback occurs.

Ordinary command errors, bounded timeouts and catchable disconnect/termination
signals invoke rollback. Host power loss, SIGKILL, a killed runner, or Docker
daemon failure cannot guarantee automatic recovery; consult the receipt and
restore the recorded app commit/image through the provider console. Never
cancel an in-progress deployment to start a second one.
