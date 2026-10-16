# SaaS compatibility plan — 2026-10-16

Preserve FastAPI, same-origin external JS/CSS, packaged templates, PostgreSQL,
Redis sessions, existing tenant UUIDs and the voice/Evolution services. No React,
new runtime service or provider change is required. Existing product APIs already
serve agent configuration, knowledge, calls and WhatsApp management. Reuse them.

New public pages and customer/admin navigation use the existing dashboard router.
Public previews must be labeled illustrative; pricing/contact must not invent
billing or delivery. Form/navigation typography is conventional system sans;
editorial serif is limited to large marketing headings. Customer data stays real.

New SaaS APIs are gated by trusted VASA_SAAS_ENABLED (default false), allowing
legacy 0006 deployments to keep operating. New models are additive companion
tables, not replacements for existing users/tenants. Staging deployment must
retain its migration refusal; no migration is automatically authorized.

Local public probing received HTTP 403 for both GET /login and a synthetic POST,
without an allowlisted application error. This does not prove the app's login
failure cause. A TLS-terminating proxy can cause the existing strict origin
comparison to reject HTTPS; add an explicit trusted canonical origin, not blanket
forwarded-header trust. Real password login remains a human credential gate.

## Implemented surfaces and explicit limits

Public pages, account flows, workspace membership/team/profile/business settings,
metadata administration and audited server-only admin provisioning extend the same
ASGI application and image. Redis remains the session store (including versioned
revocation), avoiding a second session system. Public previews are labeled;
billing, subscription plans and self-service runtime integration setup are marked
upcoming. Contact delivery uses optional trusted SMTP/recipient configuration and
is unavailable by default. Existing operator-managed runtime
tool metadata remains available without credentials. No new infrastructure exists.

Email/password verification is real application logic with mocked delivery in
local tests; live SMTP, real credentials, platform-admin review and new organization
WhatsApp onboarding still require human staging acceptance. Human call reliability
acceptance remains separate from website completion.
