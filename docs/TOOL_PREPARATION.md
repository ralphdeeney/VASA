# Concrete tools and call storage

Historical build notes below describe the library stages. Current voice_worker
loads trusted per-tenant webhook actions and tool specifications at startup.
For the current n8n contract, operator activation gates and HTTP Request guide,
see [Connect VASA to n8n](integrations/N8N.md). Library or configuration tests do
not prove an external business workflow has been deployed or completed.

## Approved webhook actions

CustomWebhook owns one tenant's server-configured action map. Each WebhookAction
requires an exact HTTPS URL, optional server-only bearer token and strict
ToolPayload input/output models. The model supplies only action and payload;
unknown business fields fail before any request. Approved destination origins
are server configuration. Redirects, URL credentials/query/fragments, IP literals,
local/reserved hosts, non-JSON/compressed output and oversized responses fail.
Every response also has to match the action-specific schema.

The workflow receives one POST containing a trusted tenant_id and nested payload.
It must verify its credential and enforce that trusted envelope; payload fields
cannot override tenant identity. Action permissions remain server-owned. This
component does not implement booking/calendar/CRM-specific logic.

Deployment egress must enforce approved destinations, including DNS/proxy
behavior; application origin checks alone do not prove DNS rebinding protection.
Public HTTPS DNS hosts on port 443 are supported. There is no automatic retry.
A timeout/cancellation after dispatch leaves the external action's outcome
uncertain; reconcile with the workflow before retrying. Close reusable clients
explicitly at service shutdown.

## Current-call ending and knowledge

EndCall captures authenticated context, current CallSession, registry and the
existing verified Evolution client. Its only input is an optional reason.
It checks current registry identity/state before hangup. Successful repeated
requests are idempotent. requested=true means hangup was acknowledged, not that
remote termination was independently observed.

Create a gateway per call when registering the call-bound end_call object;
multiple calls for the same tenant need separate bindings. Shared webhook and
knowledge objects can be registered in those gateways. Future integration must
observe end_requested, stop local work and retain bounded worker final cleanup.
The current voice worker wires these tools per call; external actions still
require approved private configuration and separate live acceptance.

KnowledgeSearch passes trusted context, query and top_k (one to five) to an
injected KnowledgeRetriever. Matches carry tenant/source/chunk IDs, bounded text
and a finite score; foreign-tenant results fail. Without a backend it fails
unavailable. The integrated KnowledgeService now extracts bounded TXT/PDF/DOCX
documents, chunks them, embeds with the pinned CPU MiniLM model and performs
tenant- and embedding-identity-filtered pgvector search. Its SQL quota and
cancellation checks are covered in the full suite.

## Durable calls and transcripts

Migration 0004 creates calls, call_messages and tool_calls, with composite tenant
ownership constraints. Apply migrations explicitly with
`uv run --frozen alembic upgrade head`; application startup does not migrate.

CallRepository requires authenticated server context and tenant-filters every
operation. Calls attach only to that tenant's WhatsApp instance. Transcript roles
are customer, agent, tool and system. Append locks the call row to allocate a
unique sequence. Closed calls, more than 1000 messages or messages over 16384
characters are refused; reads use bounded pagination.

Finalization records timezone-aware ordered timestamps and optional summary and
outcome. Matching repeats are idempotent; conflicting repeats fail. Summary
fields are storage only, not generated/evaluated summaries.

Tool metadata records an execution UUID, controlled name, status, fixed error
code and timestamps. Argument/result bodies and credentials are omitted. Start
limits each call to 200 executions. Completion supports succeeded, failed,
cancelled and unknown; late audit completion after call closure is permitted.

Repositories flush but never commit. Integrators must commit audit start before
external dispatch and completion/uncertainty separately. Do not hold a database
lock or transaction during HTTP/media work. The voice worker now persists call
messages and tool execution status through this repository, including lossless
bounded segments for oversized tool output.

Tenant/instance deletion cascades to histories; future retention/deletion flows
must account for this. Caller identifiers/transcripts are sensitive tenant data.
These tables store no audio. No new client API exposes the prepared histories.
