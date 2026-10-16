# Live staging acceptance without SMTP

These helpers are for an explicitly approved disposable acceptance run after
the reviewed schema migration and SaaS activation. GitHub Actions remains the
only VPS bridge. They do not alter existing users, provider configuration,
WhatsApp instances, or existing tenants.

`scripts/live_saas_fixture.py` accepts a bounded private JSON document on stdin:

```json
{"action":"prepare","run":"<32 random lowercase hex characters>","password":"<random 32–128 character password>"}
```

Generate both values privately in the Actions runner. Never echo the document,
pass the password in command-line arguments, upload it as an artifact, or log
raw subprocess output. Send it through the authenticated SSH bridge to the
trusted helper running inside the existing VASA application environment. The
helper requires enabled SaaS and the exact configured public origin
`https://vasa.litatech.xyz`. Its source is not included by the current Docker
allowlist; the bridge can execute the reviewed source through a Python `-c`
argument while reserving stdin for the private document.

Preparation creates exactly two new owner identities and separate organizations.
One receives an audited disposable platform role. They use the existing explicit
server-provisioned `legacy_access` mechanism: **email_verified_at remains NULL**.
This does not simulate email delivery or email verification. Existing matching
identities cause refusal. The generated `example.invalid` addresses cannot
receive real email.

On the runner, write the same private document into a mode-0600 file and set:

```text
VASA_LIVE_ACCEPTANCE_INPUT=<absolute private input file>
VASA_LIVE_ACCEPTANCE_RESULT=<absolute not-yet-existing private result file>
```

Run `node scripts/live_saas_acceptance.cjs` with Playwright and Chromium
installed. The browser accepts only `https://vasa.litatech.xyz`; it checks actual
rendered form login, reload persistence, workspace isolation, platform permission
boundaries, the rendered administrator user directory, audit API accessibility,
390/1440px overflow and logout/session invalidation. It prints only fixed status
markers. A private, exclusively created mode-0600 result contains exact session
tokens for cleanup; do not print it or upload it.

Always perform cleanup through the same bridge, including after browser failure:

```json
{"action":"cleanup","run":"<same run>","sessions":["<tokens from private result>"]}
```

Cleanup verifies exact disposable ownership before removing tenant/user records.
It removes only supplied Redis session keys whose payload belongs to these
identities, without scanning or flushing Redis. Server provision/grant and
cleanup audit events remain as safe operational history. Remove private runner
files afterward. A failed cleanup is an operational failure requiring attention.

Required fixed markers are `LIVE_SAAS_FIXTURE_PREPARE_OK`, the browser's
`LIVE_SAAS_ACCEPTANCE_PARTIAL_OK`, and `LIVE_SAAS_FIXTURE_CLEANUP_OK`. The browser
also emits `LIVE_SAAS_EMAIL_FLOWS=blocked_smtp`. This is intentionally partial:
signup, real verification delivery, forgot/reset email delivery, and real
invitation acceptance remain external SMTP acceptance gates. Do not describe
the full SaaS task as complete from this partial run.

The fixture preparation/duplicate refusal/cleanup has been exercised against
dedicated local PostgreSQL/Redis, and both scripts pass static/syntax checks.
That does not constitute a live staging browser result; record the actual
Actions result separately.

## Actions execution

Dispatch **VASA staging VPS** on `build/vasa-foundation` with `mode=check`,
`recovery=none`, `provider_smoke=false`, `saas_acceptance=true`. The
manual-only option installs pinned Playwright outside the repo, generates private
runner credentials, and uses the existing pinned-host SSH bridge. A private SSH
stdin task invokes the trusted fixture source inside the existing app container;
it neither rebuilds the runtime nor changes existing users. It always attempts
exact fixture/session cleanup. No credentials or browser artifacts are uploaded.
Success is deliberately `LIVE_SAAS_ACCEPTANCE_PARTIAL_OK` while SMTP is absent.

A separate new workflow could not be dispatched from this feature branch because
GitHub registers manual workflows on the default branch. The existing registered
workflow provides this optional path; automatic pushes never enable acceptance.
