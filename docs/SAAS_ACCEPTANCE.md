# SaaS staging acceptance — operator and human gates

Local implementation is not proof of live account delivery or staging migration.
The migration/backup gate in DB_MIGRATION_PLAN.md must be completed separately;
GitHub Actions remains the only Codex deployment bridge. Do not bootstrap
infrastructure, alter Cloudflare/Caddy, reset existing passwords, pair WhatsApp or
run a staging migration as an automatic CI step.

After approved schema/image/config rollout:

1. Confirm `/health/ready`, voice readiness and `VASA_DEPLOYMENT_OK` through normal
   `mode=deploy`. Preserve exact private bind and existing Evolution pairings.
2. Run the secret-safe auth diagnostic once from the target VASA image. Record
   category/status markers only. If requests fail at Cloudflare while local login
   works, investigate the existing edge policy separately; do not weaken app auth.
3. Using an intended test account, verify invalid password, valid login/logout,
   Secure/HttpOnly session cookie, refresh and unauthenticated dashboard boundary.
   An operator must establish that this is a disposable test identity first.
4. With real SMTP and canonical origin configured privately, register a new
   intended workspace. Confirm email delivery, single-use verification, optional
   approval policy, login, reset link expiry/reuse and old-session revocation.
   Signup must not create or pair any WhatsApp resource.
5. Grant platform authority only through the audited server-only command and
   explicit confirmation. Review users/organizations/registrations/audit/health.
   Verify a normal owner cannot open `/admin` or call platform APIs.
6. With two intended test organizations, verify cross-tenant call/knowledge/
   WhatsApp isolation, member write denials, invitation email matching and role
   management/last-owner protection. Switch workspace and confirm tenant context.
7. Review responsive UI at 390px and desktop widths with keyboard navigation.
   Review clear empty/error/permission states. Contact delivery and integration
   names must reflect trusted configuration rather than pretend live data.
8. Pair a NEW intended test WhatsApp account only with explicit owner action.
   Configure the assistant/knowledge and perform the human call acceptance test.
   Do not re-pair existing tenant instances. Reconnect/voice quality remains its
   own human gate; website tests do not establish speech reliability.

Do not record real passwords, verification/reset/invitation tokens, SMTP secrets,
provider keys, QR contents or customer transcripts in GitHub issues/Actions logs.
Record only acceptance outcomes and the approved deployed SHA.
