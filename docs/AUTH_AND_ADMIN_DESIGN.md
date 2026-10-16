# Identity and administration design

Reuse users.id/email/password_hash and users.tenant_id as a compatibility home
workspace pointer. Redis holds opaque hashed session keys, HttpOnly Secure cookies
and synchronizer CSRF tokens. Add profile auth_version for revocation and require
active user, active membership and active organization on every SaaS request.
Organization role is never a platform role. Legacy server-provisioned users retain
their existing tenant access through explicit migration backfill/legacy_access.

Signup creates pending user, tenant, profile and owner membership in one transaction;
it never contacts Evolution. Verification activates that membership/workspace.
SMTP delivery is a trusted operator dependency; without delivery configured, signup
must fail safely before creating records. No tokens/passwords/email bodies in logs.
Tokens are random, hashed, purpose-bound, expiring and single-use. Reset increments
auth_version. Recovery endpoints resist account enumeration and rate-limit abuse.

Platform admin is a separate server-side audited grant; public payloads cannot set
roles. Lists are paginated and contain safe fields only. Suspension cannot disable
the last active super-admin or remove the last active organization owner. Admin
tenant access is explicit and audited, not an automatic tenant-content bypass.
Team invitation acceptance requires matching verified identity and active org.
High-impact actions require explicit confirmation in the UI AND server permissions.

## Diagnostic and acceptance boundary

`python -m vasa.control.diagnostics --origin https://vasa.litatech.xyz` is an
operator-only container command. It reports only schema/category/status markers,
checks whether any users exist (no identities), and performs one synthetic failed
login through local HTTP with the canonical Host/Origin. It never accepts a real
password or resets an account. One probe consumes a normal rate-limit attempt;
do not loop it. `AUTH_LOGIN_PROBE_REASON=invalid_origin` isolates origin rejection;
`invalid_credentials` proves the request reached normal password validation, but
does not prove a real account can sign in. `unavailable`, inactive/verification
errors, page status and absent users must be investigated separately. Arbitrary
responses and exception material are discarded. This command has not been run
against the VPS; it becomes available in the approved target image.

The cloud's public GET /login and synthetic POST both returned 403, so the cause
of the reported real sign-in failure remains unconfirmed. Do not change passwords,
forwarded-header trust, proxy or Cloudflare policy on that evidence. A human must
verify the actual sign-in and SMTP inbox flows after the migration rollout.

## Public contact and integration metadata

`POST /api/site/contact` is independent of account signup, but accepts only bounded
plain text and always sends to the server's trusted `VASA_CONTACT_RECIPIENT` using
configured SMTP. Origin checks and rate limits apply. No destination may be chosen
by the visitor, no message body is logged/returned, and no delivery is claimed until
the send succeeds. The UI remains unavailable when delivery/recipient is absent.
Tests use a fake mailbox; live operator configuration and delivery remain pending.

`GET /api/saas/integrations` requires an active owner/admin membership. It reuses
the existing private webhook loader/validation, scopes by trusted tenant context,
returns only validated action names/kind/configured status, and closes its unused
client. It never executes an action, discloses schemas/URLs/credential bindings,
or accepts self-service configuration. Other organizations' actions stay hidden.

The existing explicit `vasa.control.bootstrap` command also supports the enabled
schema: it creates an audited active server-provisioned owner without inventing
email verification or assigning any platform role. It never overwrites accounts.
This command is not run automatically or as part of staging deployment.
