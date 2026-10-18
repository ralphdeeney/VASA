# VASA platform owner access

The platform owner uses `/admin/login` (username `admin`), then `/admin`.
Customers use `/login` and `/dashboard`. Ordinary workspace ownership does not
confer platform authority. The dashboard shows a Platform admin link only when
the server reports the signed-in user's platform assignment. Every admin API
and the admin HTML entry point independently enforce the database role.

The admin UI uses the supplied first-party VASA logo, cream/green/sage palette,
responsive sidebar, actual totals, searchable/paged directories, scoped connection
metadata, audit history, backend health and account Security. No generated chart
or mock figure is used in production. Tenant conversation content is not exposed.
The UI preserves confirmations and last-owner/platform-role protections.

## Initial owner grant

`VASA platform owner setup` is a manual-only, trusted repository-owner workflow;
Codex may dispatch it for the operator's explicitly requested setup. It is never
triggered by a push, request-file flag, public registration or tenant action.
It reuses the existing pinned SSH/rootless deployment bridge, CI gate, lock,
service/private/operator-state checks and activated release journal. An exact
healthy active release and a less-than-one-hour private backup receipt with
restore verification/checksum are required before the audited transaction.

The operator supplies the initial password through repository Actions secret
`VASA_PLATFORM_ADMIN_PASSWORD`. Never commit a default password. The connected
GitHub integration cannot write repository secrets; the operator must set it.
Workflow inputs contain only email and exact release SHA. Credentials travel in
0600 temporary files and encrypted SSH/Docker stdin, not command arguments.
Only fixed allowlisted outcome markers are emitted.

Provisioning creates an isolated owner workspace if needed, without a WhatsApp
instance or provider resource. Existing identities must be active, verified or
legacy-provisioned, and own their active organization. Unexpected existing
platform admins cause refusal. A retry of an already audited provision never
resets a password changed by its owner. Scope is the fixed staging origin.
Alias `admin` is accepted only for a single unambiguous active super-admin; if
additional admins are intentionally introduced later, use their existing email
login pending an explicit multi-admin username design. No role is inferred from
an alias or a client field. A real login/account/page/logout check follows grant.

Success markers: `PLATFORM_OWNER_PROVISIONED` (or `_ALREADY_PROVISIONED`),
`PLATFORM_OWNER_LOGIN_OK`, and `VASA_PLATFORM_OWNER_SETUP_OK`.
Failures never print credentials, response bodies or raw database exceptions.
A setup failure after a grant does not undo the grant silently; inspect its
fixed stage and use receipt/idempotency-aware recovery, never a blind reset.

## Password change

In Platform admin → Security, enter current password, new password (12+ characters)
and confirmation. Server checks current credentials, CSRF, platform role and
rate limits. The transaction writes only a salted scrypt hash, increments the
identity auth version, consumes pending reset tokens, and appends a safe audit
event. All prior sessions become invalid and the UI returns to `/admin/login`.
Public recovery uses the existing expiring, single-use email reset flow.
