# Readiness contract and public-edge recovery review

Status: diagnostic separation implemented; rollout policy changes NOT approved.
The Evolution maintenance grant remains consumed. This document and diagnostic
success do not authorize a replacement, a new grant, or an edge-policy change.

## Three independent questions

| Layer | Required evidence | Meaning of failure |
| --- | --- | --- |
| Private application | Existing `health()` verifies container ownership/state, worker-ready marker, stable processes and JSON live/ready values inside VASA; host-private `172.16.2.1:18081` login/ready GET must return200 | Origin/runtime health or private routing requires investigation |
| Public HTTPS/tunnel | Fixed `https://vasa.litatech.xyz` GET login/ready from VPS and GitHub runner, verified TLS, normal DNS/Host/SNI, no redirects or credentials | Origin failure, tunnel failure or source/client-specific edge denial; these must not be conflated |
| Authentication boundary | Unauthenticated private/public dashboard GET, no cookies/auth headers; current application policy is401 | Public200 is an access-boundary failure; an edge403 does not prove application authorization works |

The diagnostic `error=http` is an observed HTTP error, not a deployment verdict:
dashboard401 can be correct authentication behavior. HEAD405 is method evidence,
not proof GET readiness failed. IPv6/network failures remain explicit observations;
TLS verification is never disabled. Client identity is honest, fixed and public,
not a browser impersonation. Proxy/CA configuration remains inherited. Curl ignores
user curlrc so implicit credentials, redirects or insecure settings cannot affect
an unauthenticated probe. Redirect destinations and bodies are never printed.

## Existing acceptance remains authoritative

`deploy/actions_evolution_pool.py:public_health()` continues to use its original
urllib request and accepted statuses unchanged: login200, ready200, dashboard
302/303/307/308/401/403. Its failed public gate still prevents a success marker and
triggers the existing controlled rollback when reached after replacement.
No diagnostic result is ORed into this gate, and curl/runner/private success
cannot excuse a failing maintenance check. New diagnostics execute only for the
allowlisted read-only `evolution_check`, after actor/branch/exact-SHA CI gates.
They report data before the existing gate, so a failure preserves useful evidence.
All VASA container identities/restarts and private environment hashes are checked
across the diagnostic pass. The canonical checkout and operator files are audited
without moving, checking out, stashing, cleaning or changing tracked state.

## Proposed correction: approval required before use for maintenance

Initial controlled external evidence: default Python urllib gets403; the same
client, URL, method, Host/SNI and trusted TLS with `User-Agent:
VASA-Health-Diagnostic/1.0` gets login/ready200 and dashboard401. Curl succeeds.
VPS and GitHub-runner evidence is recorded in the automatic request run. This
isolates client identification as a reproducible trigger; it does not identify a
Cloudflare rule or distinguish every possible bot/edge/proxy policy source.

The smallest candidate correction is an explicitly identified health Request
using that honest User-Agent while retaining verified TLS, fixed endpoints,
GET/no-redirect behavior and all origin/authentication checks. It is already
exercised by diagnostics, but NOT selected by the maintenance gate. Approval must
specifically cover the readiness-policy revision; a future maintenance grant is
separate approval and cannot silently select a new health policy.

A reviewed future contract should keep independent origin, public/tunnel and
exact application-auth verdicts, including a GitHub runner observation. A
source-specific denial may be labelled `edge_denied` while origin is healthy,
but must remain blocking until the operator approves how that classification
participates in maintenance readiness. No forced-success/mock result is allowed.

## Operator Cloudflare security-event review

Use the diagnostic record's exact UTC timestamp (allow a small clock-skew window),
strictly validated CF Ray ID, hostname `vasa.litatech.xyz`, path/method and UA
profile. In Cloudflare Security Events inspect matched rule/ruleset ID, product
(WAF/bot/rate-limit/access), action, client ASN/country/IP family, bot score if
available, and whether the request reached origin. Compare a nearby successful
identified-UA request and its Ray ID from the same vantage. Source-address
fingerprints are emitted instead of raw addresses; the VPS owner can correlate
its known address privately. Do not paste credentials, cookies, full request
headers, caller data or response bodies. Share only rule category/action and
sanitized timestamps/Rays needed to identify the decision.

Cloudflare configuration, n8n/Caddy, tunnel credentials, rate limits and
application authentication remain untouched. Never whitelist by disabling WAF,
bot protection or authentication. If edge configuration changes are necessary,
they require separate operator authorization. SMTP remains deferred.
