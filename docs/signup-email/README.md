# Signup layout and Reloop transactional email

## Implemented scope

Signup alone now removes navigation back to signup and shows “Already have an
account? Sign in”. Other shared identity routes retain their existing navigation
and endpoints. Scoped form spacing/mobile rules preserve deep green #07372D,
cream #FFFCF6 and soft sage #EDF3ED, serif identity headings and sans-serif labels/
operational text. Empty status regions do not draw a blank notice; populated
messages remain accessible. First-party image CSP is supported without allowing
external images or inline scripts.

The authoritative monogram/wordmark image is NOT present in this task's message,
repository or available attachments. No logo was invented and no broken image or
placeholder logo route was added. Actual transparent, tightly cropped brand-asset
integration remains blocked on the original image; current text branding remains.

Existing SMTPMailer is reused; no email SDK or dependency was added. Reloop's
[official SMTP introduction](https://reloop.sh/docs/examples/smtp/introduction)
specifies smtp.reloop.sh:587, STARTTLS, and the same API key as username/password.
Both credential settings are SecretStr, including the API-key username. Certificate
and hostname verification remain enabled. SMTP capacity is bounded to four and
retained until cleanup even if an HTTP request is cancelled before its executor
thread starts. Failures expose fixed codes, never provider details/messages.

Complete SMTP transport plus VASA_SMTP_DELIVERY_VERIFIED=true is required before
transactional workflows/signup are available. This is an operator attestation
only AFTER verified sender/domain and an actual successful mailbox receipt.
Presence of host/sender, successful AUTH or SMTP250 acceptance cannot attest it.
Contact additionally requires its separate trusted VASA_CONTACT_RECIPIENT.

Verification, resend, recovery and invitations retain hashed/single-use tokens,
expiry, rate limits, enumeration resistance, tenant/session boundaries and
transaction rollback. Verification/recovery body text now carries VASA branding
and existing expiry instructions; URLs still carry tokens only in fragments.
No new account notification workflow or provider resource is invented.

## Private web-only configuration

Provision /opt/vasa/.local/smtp.env as vasa-builder, mode0600, untracked and outside
all images. The web service alone loads it. Do not put email credentials in the
shared .local/llm.env or inherited service environment. Voice, Evolution, Redis
and PostgreSQL do not receive this file. Rootless project/volumes/ports are unchanged.
The controller hashes and preserves smtp.env alongside existing private files.
A real Compose resolution test uses fake credentials to verify service isolation.

Configure these names through the protected operator channel, never chat/Git/logs:

- VASA_SMTP_HOST=smtp.reloop.sh
- VASA_SMTP_PORT=587
- VASA_SMTP_USERNAME and VASA_SMTP_PASSWORD: the same private API key
- VASA_SMTP_SENDER: the domain-verified VASA sender mailbox
- VASA_SMTP_STARTTLS=true
- VASA_SMTP_DELIVERY_VERIFIED=false until the real mailbox test is confirmed

The original request prohibited the exposed screenshot key; subsequent operator
steering explicitly permits it for a test only. No screenshot/key is actually
available in this task. No exposed or replacement credential was accessed, logged,
committed or used. Rotation remains operator-controlled; prefer a new private key.

## Acceptance procedure and truthful statuses

Once the reviewed image is deployed with protected SMTP configuration, the
operator test entrypoint is:

    python scripts/check_smtp.py --recipient <operator-test-inbox>

Run only inside the web service through the existing Actions bridge. Do not print
container environments or place credential arguments in a command. The helper
sends one fixed VASA message with no account tokens/customer data, verifies
STARTTLS and AUTH, and prints only fixed JSON. SMTP acceptance returns
`{"status":"smtp_accepted","mailbox_delivery_verified":false}`. It does NOT prove
inbox receipt or flip the delivery setting. Confirm the intended inbox actually
receives it and the sending domain is verified before setting the attestation.
Then use disposable accounts to validate actual verification, resend, recovery
and team invitation links and single-use/session/tenant rules. Do not use a
mock mailbox or the SMTP acceptance reply as real delivery evidence.

## Current evidence and deployment gates

Local browser fixture:40 layouts across320/375/393/768/1280 on signup, login and
six other identity routes. No horizontal overflow, clipped controls, page errors,
external requests or POSTs; keyboard skip navigation, labelled fields, palette,
CSP and missing-SMTP disabled submission passed. This is UI evidence, not live
backend/email acceptance. See browser-results.json.

Read-only Actions39073685888 succeeded against staging before implementation.
Approved GitHub SMTP bindings HOST/USER/PASSWORD/SENDER absent. Existing VPS
runtime/private-file SMTP bindings absent; public origin and SaaS flag present.
Five services healthy/restart_count0; database0007. Canonical checkout still has
exactly the three preserved untracked edge/tunnel files. No direct Codex SSH.

Normal application deploy must continue refusing this dirty checkout. Use existing
check/recovery=prepare through Actions to prepare an immutable isolated source,
verified backup/restore, rollback image and candidate without activation. Do not
remove/stash/move operator files or touch Evolution/voice/tunnel/n8n to deliver
this change. The existing activation route requires separately reviewed exact
release/migration authorization; this task does not bypass that gate.

Real email delivery is NOT operational/verified. Logo input, private SMTP sender/
credential/test inbox, mailbox receipt and permitted release activation remain
external gates. Final local/CI/preparation results are recorded after execution.

Local full suite:1,469 passed in77.18s; Ruff/format, strict mypy, actionlint,
all shell syntax and diff checks passed. Signup screenshots show local fixture UI
with the existing text wordmark, NOT the missing authoritative logo or deployed UI.
They are saved under screenshots/ at320/375/393/1280px.

## Actual CI and isolated preparation outcome

Source c57931fb5ab9e76f1ed3e2fc73dbe3918d8c1f5a passed CI39073902107 with
1,469 tests. Automatic normal deploy39073902103 correctly refused the preserved
three-file dirty checkout before changes. Codex then triggered the existing
check/recovery=prepare, Actions39074100085, which SUCCEEDED with
`VASA_RECOVERY_PREPARE_OK`. It restored/tested a fresh48,670-byte application
backup (hash in result.json), confirmed schema0007 already current, verified the
rollback image and built `vasa-app:release-c57931fb5ab9e76f1ed3e2fc73dbe3918d8c1f5a`.
The controller verified unchanged running container identities, operator/private
files and canonical checkout. No service was replaced/restarted, no live migration
ran and no release was activated. Existing active app/voice remains858b5f8.

CLI GitHub authentication expired during monitoring; Codex recovered through the
connected GitHub integration and fetched the successful job status and only fixed
allowlisted preparation markers. No duplicate operation or credential request was
needed. Both GitHub and VPS approved SMTP bindings remain absent. Actual sender/
mailbox delivery and original logo remain unavailable, so these are genuine
external acceptance gates, not implied successes from mocks or image preparation.

Activation remains held by the existing exact-target/SQL review gate documented
in ../DB_MIGRATION_PLAN.md; no approval was fabricated from a request flag. The
prepared candidate is concrete and reviewable. See result.json for actual facts.
