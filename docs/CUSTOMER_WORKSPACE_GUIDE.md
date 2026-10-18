# Workspace content and actions

The dashboard uses the approved first-party VASA monogram/wordmark PNG, compact
setup summary and section navigation. WhatsApp displays a canonical linked phone
number where upstream metadata provides one. Unavailable metadata is explicit;
connection health does not depend on the optional number lookup.

| Place | What belongs here |
| --- | --- |
| Assistant → About your business | Short overview of the business, audience and service style. |
| Assistant → Instructions | How the assistant should behave and handle requests. |
| Knowledge | Maintained facts: services, prices, hours, policies, FAQs and documents. |
| Knowledge → a Contact & links source | Website, social profiles, address, public email and contact details. |
| Integrations | Approved business actions and their private operator-managed connections. |

A saved website/social link is text knowledge, not a crawler or automatic import.
Paste the relevant content or upload a supported document. Do not put API keys
or passwords in knowledge or assistant instructions.

## Business actions

VASA's existing Tool Gateway can invoke tenant-scoped approved webhook actions.
n8n production webhooks, Zapier webhooks and custom HTTPS services can sit behind
that boundary. These are webhook paths, not native OAuth connectors. An adapter
may be required, particularly for asynchronous workflows, to return the validated
result schema. Example actions include availability lookup, booking and CRM lead
creation. Showing a platform card does not mean an account is connected.

The operator configures approved destinations, private credentials, strict input
and result schemas and the tenant's action allowlist. Existing destination policy,
resource bounds, uncertain-action handling and tool authorization stay unchanged.
Customers cannot paste arbitrary execution URLs or credentials into this screen.
Self-service setup, API-key issuance, OAuth and arbitrary API-method execution
are not implemented by this UI change. An actual business action still requires
its approved endpoint, schemas and credential binding before live validation.
