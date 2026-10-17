## 2026-10-17 — Authorized Evolution pool lifecycle remediation

Confirmed pinned upstream reconnect path creates an independent PostgreSQL
Whatsmeow store pool on each StartClient without closing the previous pool.
The reviewed patch borrows the existing process-owned bounded auth database
pool via NewWithDB; its owner retains shutdown responsibility. SQLite database
selection, transport, call/media APIs and speech providers are unchanged.

Local Go unit, race, real PostgreSQL 120-cycle reuse/shutdown and existing
call/media tests passed. The isolated source manifest pins both reviewed patches;
existing cached source and runtime secrets are preserved. Live rollout is pending.

GitHub Actions only: dispatch VASA staging VPS with mode=check,
recovery=evolution_check for read-only health/capacity/call inspection; use
recovery=evolution_deploy for the explicitly authorized Evolution-only rollout.
No bootstrap, application migration or automatic Evolution rollout on push.

The maintenance controller checks durable unfinished calls, bounded Redis call
state and all non-Docker-DNS Evolution UDP sockets, plus the exact registered
instance set and verified paired-device membership. A saved offline instance
is eligible for maintenance; post-rollout must be connected and logged in.
Unknown/nonzero call state defers. After backups, pause voice
and recheck to close the VASA answer-admission race; then replace only Evolution,
restore only existing registered device connections, resume voice and validate
all five services, unchanged other container identities and private files.
The private control endpoint must not have independent external call initiators.
The upstream image has no call-list API; zero UDP alone is never accepted as
proof of no calls. A stale unfinished durable record also blocks maintenance.

Backups cover application, Evolution auth and Evolution users databases, with
private receipts/hashes and restoration into disposable databases before restart.
Schema/device/instance credential fingerprints must remain unchanged; no live
schema upgrade is approved. A verified rollback image is retained and only
Evolution is restored if validation fails. If the old running image is missing
from Docker storage, build the pinned pre-fix vendor source with only the existing
logging patch in a separate verified cache, before any target/runtime change.
Never use docker commit or read container environment values. Capacity is sampled three times after
rollout; total Evolution sockets must remain within the two existing 25-open
process pools, and decrease from an exhausted baseline.

SMTP is explicitly deferred by the operator. No credentials are requested or
invented and live email acceptance is not claimed. Human real-call stability
validation remains separate from pool health evidence.

# Evolution database pool investigation and proposed recovery

Status: **review only; no Evolution source, service, pairing or configuration was
changed**. Evolution is a protected dependency. Its restart or image replacement
requires separate operator authorization and a no-call maintenance window.

## Observed allocation and limits of attribution

Sanitized VPS inspection attributed 95 PostgreSQL sockets to Evolution, four to
the VASA API and one to voice, against a configured 100-connection maximum.
This explains why another ordinary application connection can be refused:
PostgreSQL also reserves connection capacity. A healthy existing API connection
does not establish that a fresh acceptance process can open another connection.

The source contains a confirmed database-pool lifecycle defect described below.
The socket count alone does **not** establish that every one of Evolution's 95
sockets came from that defect. Quantitative attribution needs an isolated
reconnect/lifecycle test and aggregate connection counts by database/state over
time. Do not infer the number of leaked pools or reconnects from 95 alone.

## Exact source evidence

VASA pins `luis-kovi/evolution-go-calls` at
`e21ce0dd7634f3047410c893b5e4d1c082034b84`; see
`scripts/prepare_evolution.py:15` and `docs/EVOLUTION_TRANSPORT.md`. Locators below
refer to the prepared `.local/evolution-source` tree, including VASA's existing
reviewed logging patch.

| Locator | Finding |
| --- | --- |
| `pkg/whatsmeow/service/whatsmeow.go:313–343` | `StartClient` returns early for an already connected client, but otherwise calls `sqlstore.New` for every new/disconnected start. Both PostgreSQL debug branches allocate this way. |
| `pkg/whatsmeow/service/whatsmeow.go:350–365` | The new container provides the persisted device or a new device. Failures after successful allocation can return without closing it. |
| `pkg/whatsmeow/service/whatsmeow.go:184–247` | `ReconnectClient` disconnects the old websocket, removes map entries and starts the instance again. It never closes a SQL container. |
| `pkg/whatsmeow/service/whatsmeow.go:598–649` | The kill path disconnects the client and recursively invokes `StartClient` before the previous function returns. It does not close the previous SQL container. |
| `pkg/whatsmeow/service/whatsmeow.go:1989–2011` | A WhatsApp `Disconnected` event schedules `ReconnectClient`. |
| `pkg/whatsmeow/service/whatsmeow.go:2427` | `StartInstance` launches `StartClient` in a goroutine. |
| `pkg/whatsmeow/service/whatsmeow.go:2813–2836` | The service already receives and retains `authDB *sql.DB`. |
| `cmd/evolution-go/main.go:168–170,315–343,373–375` | The initialized PostgreSQL auth pool is passed to the service, capped at 25 open/five idle connections, with five-minute lifetime/one-minute idle expiry, and closed by its process owner. |
| `pkg/config/config.go:157–175` | The separate users/GORM pool also has explicit limits. These settings do not apply to pools independently opened inside `StartClient`. |

The exact pinned Whatsmeow dependency is
`go.mau.fi/whatsmeow v0.0.0-20260722203353-e9a033b24933`:

* `store/sqlstore/container.go:46–56`: `New` calls `sql.Open`, then wraps the
  resulting independent pool. It closes that pool only if upgrade fails.
* `store/sqlstore/container.go:78–90`: `NewWithDB` wraps an existing `*sql.DB`
  without opening another pool.
* `store/sqlstore/container.go:229–233`: `Container.Close` closes its database.
* `store/sqlstore/container.go:256–261`: the device retains the container and
  its SQL stores. The Whatsmeow client retains the device.
* `client.go:663–673,690–696`: `Client.Disconnect` closes the websocket and
  clears socket-related state; it does **not** close the database container.

No `container.Close` call exists in the Evolution service. The repeated
`sqlstore.New` path applies no `SetMaxOpenConns`, idle expiry or pool shutdown.
Consequently, disconnected starts create independent unmanaged pools whose
lifetime is not tied to explicit shutdown. Removing client map entries or
calling websocket `Disconnect` does not implement database ownership cleanup.

The pinned `go.mau.fi/util` dependency was also inspected at
`v0.9.12-0.20260717235539-f9ffa7eca58d`, `dbutil/database.go:184–204`:
`NewWithDB` retains the supplied SQL pool without overriding its limits.
`Configure`, which would alter limits, is a separate method. The publicly
downloaded pinned module ZIP used for this read-only check had SHA256
`a72adfd5150cab7750b17926e211a0f6cfdb4eb69c3ff31e417171e24ad83459`.

## Preferred narrow patch

For the PostgreSQL branch only, reuse the **existing process-owned bounded auth
pool** with `sqlstore.NewWithDB(w.authDB, "postgres", dbLog)` and explicitly
perform the upgrade currently performed by `sqlstore.New`. Fail safely when
the configured PostgreSQL backend has no initialized `authDB`; do not silently
fall back to opening another unmanaged pool. Preserve both logging branches,
the configured database, all device IDs, pairing records and media APIs.

Illustrative review fragment, not an applied patch:

```go
if w.authDB == nil {
    // Fixed sanitized startup failure; do not log a DSN or credentials.
    return
}
container = sqlstore.NewWithDB(w.authDB, "postgres", dbLog)
err = container.Upgrade(context.Background())
```

The shared auth pool remains owned by the existing process initializer/shutdown
path. **Never call `container.Close` on a per-client disconnect or failed start
when its wrapper shares that pool**: doing so would close the database for all
active instances and polling. This patch bounds aggregate PostgreSQL auth
connections across instances/reconnects rather than adding a limit separately
to every leaking pool. Retaining the present 25-connection cap is the smallest
behavior change; tuning that cap requires measured concurrency evidence.

Do not blindly share `w.sqliteDB` in the SQLite branch: that handle uses
`users.db`, while the Whatsmeow session branch currently opens `main.db`.
SQLite ownership needs a separately reviewed compatible lifecycle solution.

Alternative: introduce a dedicated, bounded, process-owned Whatsmeow SQL pool
and share it through `NewWithDB`, closing it exactly once only after all client
operations stop. This provides isolation from other auth queries but adds more
ownership/plumbing. Per-start pools with `defer Close` are risky here because
the start routine recursively restarts and multiple goroutines retain stores;
they require proven cancellation/join semantics before closure. The existing
unbuffered kill-channel and recursive restart behavior deserve separate review,
not an incidental transport redesign in this patch.

## Tests required before any rollout

Add focused Go tests alongside
`pkg/whatsmeow/service/session_store_test.go`, extracting a small store-construction
helper so tests do not connect to WhatsApp or expose pairing material:

1. Repeated PostgreSQL store creation/reconnect preparation uses the supplied
   pool; no new pool factory calls occur, and configured limits remain intact.
2. Missing auth pool and upgrade/device-read errors fail safely, without closing
   a shared pool or logging a DSN. A second active client can still query it.
3. Disconnect/reconnect and the kill/restart path preserve the shared pool;
   process shutdown closes it once after clients stop using it.
4. Two simultaneous instances cannot close each other's store or alter device
   ownership. Exercise reconnect concurrency with Go's race detector.
5. In dedicated local PostgreSQL, cycle at least 100 store/client lifecycle
   operations with bounded concurrent reads. Record only aggregate SQL pool
   stats and connection counts; verify they plateau within configured limits
   and return to baseline after owner shutdown.
6. Confirm persistent paired-device lookup/save remains valid across reconnects
   without deleting/recreating a device. Test SQLite separately for unchanged
   database selection and behavior.

Run focused tests, race checks, existing Evolution call/media tests, VASA's full
suite and the image/source-manifest checks. Extend the tracked reviewed patch
and hashes through `prepare_evolution.py`; do not hand-edit the ignored cached
tree or bypass its fingerprint guard. No such tests or patch are claimed run
by this investigation.

## Recovery and authorized rollout boundary

There is no discovered existing environment setting that changes these
`sql.DB` pool limits at runtime. Evolution reads configuration at startup, and
the per-start pool code contains no hot-reload/setter path. DSN parameters do
not configure Go's client-side `sql.DB` limits. An environment change therefore
does not safely reclaim the existing 95 sockets without restarting the process.

API-only recycling is a separate bounded recovery: it can release VASA API
sockets temporarily for orphan cleanup but cannot repair Evolution's retained
pools. It must not be represented as an Evolution fix or permanent capacity
solution. Do not enlarge PostgreSQL capacity, kill arbitrary backends, or change
role limits as an unreviewed substitute.

Before an approved Evolution change: confirm no active calls, record sanitized
aggregate capacity and current image identity, verify backup/rollback material,
and explicitly authorize the dependency maintenance window. Preserve existing
volumes, environment hashes, paired-device IDs and unrelated containers. Rebuild
and replace only the approved Evolution service through the Actions bridge;
never use compose down or re-pair instances. Validate health, existing instance
pairing/status, connection-count plateau, API/voice readiness and a human call.
Rollback only that image if validation fails. Restarting Evolution interrupts
its active WhatsApp sockets even when pairing data is preserved, so it is not
authorized by ordinary application-only deployment approval.
