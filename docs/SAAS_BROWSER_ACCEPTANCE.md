# Disposable SaaS browser acceptance

## Scope and result

On 2026-10-16, `scripts/acceptance_saas_browser.cjs` passed against an isolated
loopback VASA HTTP server using the existing dedicated development PostgreSQL
and Redis services. Chromium ran actual page JavaScript and followed browser
navigation; authentication cookies, CSRF checks, database persistence and session
revocation were exercised rather than mocked.

The following groups passed:

| Group | Evidence |
| --- | --- |
| Signup and verification | Two disposable accounts created separate workspaces; unverified login was refused; private email links verified both accounts. |
| Login and sessions | Browser form login succeeded and survived page reload. |
| Tenant boundaries | Workspace IDs differed; switching into an unrelated organization was denied; ordinary owners could not access the platform directory. |
| Invitations and roles | The invitation form sent a member invitation; its intended recipient accepted it, gained a second workspace and switched between both. A member could not view the manager-only team directory or invite an administrator. |
| Recovery and logout | Browser reset flow changed the password; a separate already-authenticated browser session was revoked. Login with the replacement password succeeded; logout invalidated that session. |
| Administration and audit | A fixture-only server grant enabled the disposable administrator; the rendered directory found both test users and the audit API included the password-reset event. |
| Responsive frontend | Home, signup, login, dashboard and admin had no document-width overflow at 390px and 1440px. |

The run emitted six `SAAS_BROWSER_PASS` markers, then
`SAAS_BROWSER_ACCEPTANCE_OK`, and exited zero. Fixture teardown deleted the
created tenant/user records, associated audit data and the exact Redis session
keys created by the run.

This is **local browser acceptance**, not acceptance of the staging deployment.
It does not prove external SMTP delivery, Cloudflare ingress behavior, actual
VPS credentials or real WhatsApp calls. Mail was captured by a private in-memory
test adapter. Only a disposable local identity received a fixture administrator
grant. The fixture periodically cleared its own loopback login throttle key;
production throttling remains covered by the existing security tests.

## Harness contract

The harness deliberately accepts only HTTP loopback target and fixture origins.
It refuses remote hosts to prevent accidental disposable-account mutations on
production. It prints fixed stages and pass/fail markers only; passwords, private
links, cookies, response bodies and exception messages are not printed. Do not
enable browser tracing, screenshots or raw request logging for private accounts.

Provide the following environment variables through the local test process:

```text
VASA_ACCEPTANCE_ORIGIN=http://127.0.0.1:18888
VASA_ACCEPTANCE_FIXTURE_ORIGIN=http://127.0.0.1:18888
VASA_ACCEPTANCE_FIXTURE_KEY=<random private fixture key>
VASA_ACCEPTANCE_RUN=<unique lowercase disposable run prefix>
VASA_ACCEPTANCE_CHROMIUM=/usr/bin/chromium
```

The fixture adapter must authenticate `x-acceptance-key` and expose only:

* `GET /_acceptance/mailbox?email=...&page=...`: returns `{ "link": "..." }`
  for the latest matching disposable-recipient verification, reset or invitation
  message. Tokens stay in URL fragments. Refuse recipients outside the run.
* `POST /_acceptance/admin` with `{ "email": "..." }`: grants the disposable
  run identity an audited platform role. This endpoint must **never** be added
  to the production application.

Inject the mailbox through the test application's `app.state.mailer` after its
normal lifespan starts; implement `configured()` and asynchronous `send()`.
Keep SMTP capability settings test-only. Bind the adapter to loopback, disable
raw access/error logs, and clean up all run-owned data in lifespan teardown.

`tests/acceptance/fixture_server.py` is the reusable local adapter. It refuses
database hosts/ports other than `127.0.0.1:54329/vasa` and Redis other than
`127.0.0.1:6389/0`. It is excluded from the production image by the existing
Docker build allowlist. It does not run migrations or start any containers.

With the dedicated local services already running, their schema migrated to
0007, and Playwright available to Node, run from the repository root:

```bash
export VASA_ACCEPTANCE_ORIGIN=http://127.0.0.1:18888
export VASA_ACCEPTANCE_FIXTURE_ORIGIN=http://127.0.0.1:18888
export VASA_ACCEPTANCE_FIXTURE_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export VASA_ACCEPTANCE_RUN="acceptance-$(python -c 'import secrets; print(secrets.token_hex(8))')"

# Start only the disposable loopback app; never use --host 0.0.0.0.
.venv/bin/python -m uvicorn tests.acceptance.fixture_server:app \
  --host 127.0.0.1 --port 18888 --no-access-log --log-level critical \
  >/dev/null 2>&1 &
fixture_pid=$!
trap 'kill "$fixture_pid" 2>/dev/null; wait "$fixture_pid" 2>/dev/null' EXIT

.venv/bin/python - <<'PY'
import time
import urllib.request
for attempt in range(100):
    try:
        urllib.request.urlopen('http://127.0.0.1:18888/health/ready', timeout=1)
        break
    except Exception:
        time.sleep(0.1)
else:
    raise SystemExit('LOCAL_FIXTURE_NOT_READY')
PY
node --check scripts/acceptance_saas_browser.cjs
node scripts/acceptance_saas_browser.cjs

# SIGTERM invokes lifespan cleanup; do not use SIGKILL.
kill "$fixture_pid"
wait "$fixture_pid"
trap - EXIT
unset VASA_ACCEPTANCE_FIXTURE_KEY
```

Exit zero and the final success marker are required. A failure prints only
`SAAS_BROWSER_FAILED=<fixed stage>`; investigate privately without dumping
credentials or mail contents. Live staging acceptance remains a separate gate
after deployment, reviewed migration, approved mail delivery and disposable
operator-controlled accounts are available.
