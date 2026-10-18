# Connect VASA to n8n

This guide describes the existing VASA implementation, not an activated integration.
Examples use a placeholder host and tenant. No n8n service, credential or runtime
configuration is changed by this document.

## Choose the direction

**Supported action path:** VASA assistant → Tool Gateway → n8n production Webhook
→ HTTP Request node for your business API → Respond to Webhook → VASA.

Use this for availability lookup, CRM lead creation, orders or bookings once each
action has its own approved schema, permissions and confirmation rules. Start with
a read-only lookup. There is no native n8n OAuth connector or self-service setup yet.

**n8n → VASA:** VASA's customer/admin APIs currently use authenticated browser
sessions and CSRF for mutations. It does not currently provide scoped integration
API keys, a general external tool-execution endpoint or an outbound-call trigger
API. Do not automate with your platform-admin password/cookies or invent a Bearer
API-key endpoint. A tenant-scoped service-account API would need a separate reviewed
implementation. Public health endpoints can be polled without credentials.

## 1. Create the n8n webhook

In your existing n8n editor, create a new workflow. Do not change its Docker, proxy
or hosting configuration.

1. Add **Webhook**: method **POST**, path `vasa-availability`.
2. Authentication: **Header Auth**, with a private n8n credential whose header name
   is `Authorization` and value is `Bearer <private-shared-token>`.
3. Set the response mode to **Using Respond to Webhook node**.
4. Publish/activate the workflow and copy its **Production URL**. A sample is
   `https://automation.example.com/webhook/vasa-availability` — replace the host.
   The temporary `/webhook-test/` URL is not a production connection.
5. Use the final public HTTPS URL on port 443. VASA rejects redirects, IP-literal
   destinations, non-HTTPS/local hostnames, URL credentials, query strings and
   fragments. Put authentication in the header, not the URL.

VASA sends exactly this envelope, not the model's entire tool call:

```json
{
  "tenant_id": "11111111-1111-4111-8111-111111111111",
  "payload": {
    "service": "consultation",
    "date": "2026-11-02"
  }
}
```

The request includes `Authorization: Bearer <private-shared-token>`,
`Accept: application/json`, and `Accept-Encoding: identity`. The tool action name
selects the configured URL; it is not an extra field in this HTTP envelope.

## 2. Validate and normalize

After Webhook, validate that `{{$json.body.tenant_id}}` equals the tenant this
workflow is approved to serve. Never select another customer's credentials based
only on arbitrary incoming fields. Reject unexpected tenants and invalid service/
date values. The JSON-schema date pattern checks shape; n8n must also check that
it is a real permitted date.

An **Edit Fields** node can keep only:

| Field | Expression |
| --- | --- |
| `service` | `{{$json.body.payload.service}}` |
| `date` | `{{$json.body.payload.date}}` |

Keep credentials in n8n's credential store. Review execution-data retention so
Authorization headers and customer details are not retained in raw debug logs.
Do not export a workflow with credentials or request headers in sample data.

## 3. Add the HTTP Request node

For a business availability API (example only):

| Setting | Value |
| --- | --- |
| Method | `GET` |
| URL | `https://api.example.com/availability` — replace with your approved business API |
| Authentication | The appropriate stored n8n credential for that API |
| Query parameter `service` | `{{$json.service}}` |
| Query parameter `date` | `{{$json.date}}` |
| Response | JSON |
| Timeout | For example 5000 ms, leaving room for the complete VASA round trip |

The HTTP Request node calls **your business API**, not an undocumented VASA URL.
Keep its host/method fixed by operator configuration; do not accept a destination
URL from caller speech. Map the real API result to the response below. A CRM or
booking action might instead use POST and a validated JSON body.

## 4. Return the result VASA expects

Use Edit Fields/Code to produce only these approved keys, then **Respond to
Webhook**: status 200, Respond With JSON, body `={{$json}}` (the current item).
The response to VASA must be this object directly:

```json
{
  "available": true,
  "slots": ["2026-11-02T10:00:00+01:00"],
  "message": "One appointment is available."
}
```

Do **not** return an n8n execution object, an array, a workflow-started message,
HTML, or `{ "result": ... }`. VASA adds its internal `result` wrapper after it
validates the HTTP response. Replace all example values with actual API results;
do not report success when the downstream operation failed.

Requirements enforced by VASA:

- HTTP 2xx, `Content-Type: application/json`, no response compression
  (`Content-Encoding` omitted or `identity`). No redirect following.
- Response must match the action's schema exactly, including field types and
  `additionalProperties: false`.
- At most32,768 response bytes and a 10-second external deadline; the outer Tool
  Gateway is also time-bounded. This is a limit, not a measured latency promise.
- No automatic retries. Timeout/cancellation after dispatch can leave the outcome
  unknown. A booking must not be reported as failed/succeeded without reconciliation.

For writes, add a caller-confirmed action and a stable business request identifier
to the approved schema. Enforce deduplication in the destination using tenant +
request identifier. VASA does not automatically send an Idempotency-Key header
or guarantee exactly-once delivery. Do not blindly retry a timed-out booking.
Long jobs need an explicit durable accepted-job contract; “accepted” is not
“completed.” Do not block a live conversation with a long n8n execution.

## 5. Prepare the VASA-side configuration (operator step)

Copy [n8n-action.example.json](n8n-action.example.json), replacing the example UUID
with the actual authorized **organization/tenant ID**, and the example URL/origin
with the production webhook. The selected workspace must already have a configured
assistant and connected WhatsApp account before a human call test.

Required trusted runtime bindings for this example:

```text
VASA_WEBHOOK_CONFIG_PATH=/opt/vasa/.local/workflows/actions.json
VASA_WEBHOOK_AVAILABILITY_TOKEN=<private-shared-token>
```

The token must match n8n's Header Auth credential. These lines are placeholders,
not a command to overwrite the existing runtime environment.

The JSON file must be a regular file owned by the process UID (1000 **inside**
VASA containers), mode 0600, maximum 65,536 bytes, with no symlink in its path. Both
voice (execution) and web (Integration metadata) need the same trusted config and
token binding. Use the existing rootless deployment's private read-only mount/
volume and secret injection model. A host file is not automatically visible inside
the containers: current Compose mounts a named diagnostics volume at
`/opt/vasa/.local`. Do not make the file world-readable to work around ownership.

**The checked-in Compose does not currently wire these webhook bindings.** An
operator must prepare the private asset and a reviewed deployment/environment
change through the existing Actions bridge, compatibility/backup/no-call/rollback
gates. Editing `.env` or pasting a URL into Knowledge is not sufficient. Do not
bypass environment-compatibility refusals. Do not put the token in Knowledge,
assistant instructions, Git, images, URL parameters or frontend JavaScript.
No Evolution/n8n restart or proxy change is part of this setup.

At worker startup, `load_webhooks()` validates each tenant's private actions and
exposes them to the LLM as `custom_webhook`. The action name must be lower-case
snake_case, and credential references must begin `VASA_WEBHOOK_`. Origins are
exact `https://hostname` allowlist entries. Deployment egress must enforce allowed
destinations too; an application hostname check is not DNS-rebinding protection.

A model tool call for the example has this structure (not an HTTP API endpoint):

```json
{
  "action": "check_availability",
  "payload": {"service": "consultation", "date": "2026-11-02"}
}
```

## 6. Test before a real customer action

1. In an approved disposable/test workflow, send a known valid envelope using n8n's
   test tools or an HTTP client with its private credential stored outside logs.
   Confirm the response schema and real downstream result.
2. Verify bad credentials and the wrong tenant are rejected, and malformed fields
   never invoke the downstream API. Confirm failure bodies do not expose secrets.
3. Check the complete path remains within the deadline and returns uncompressed
   JSON. Exercise downstream errors/timeouts and deduplication for write actions.
4. Through the approved VASA configuration/deployment path, confirm the action
   appears in the customer's Integrations metadata and worker tool configuration.
   Metadata presence alone is not evidence the business action completed.
5. With an explicitly authorized human call, ask for the read-only action first.
   Verify the real downstream result and sanitized tool outcome before adding
   write/booking actions. No human call is performed by this documentation task.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| No configured action in Integrations | Correct tenant, shared private file, token binding and restarted/reloaded approved worker release |
| Invalid private configuration | UID/mode/path, exact keys, strict JSON schemas, token variable and approved origin |
| 401/403 from n8n | Header Auth value must be `Bearer <token>` and match VASA |
| `invalid_output` | Raw object, schema/types, JSON Content-Type, response size and compression |
| `timeout` / uncertain outcome | Workflow deadline, business API latency and deduplication; reconcile before retrying |
| HTML/redirect/challenge response | Use the final approved automation URL; do not globally disable edge security |
| n8n wants a VASA API key | Scoped machine API keys are not implemented; do not use platform-owner credentials |

Official n8n references:
- https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.webhook/
- https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.httprequest/
- https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.respondtowebhook/

VASA source of truth: `src/vasa/tools/webhooks_config.py`,
`src/vasa/tools/concrete.py`, `src/vasa/tools/gateway.py`, `src/vasa/voice_worker.py`.
