# Live-call transport investigation — 2026-10-15

Later update: docs/MEDIA_RECOVERY_POLICY.md replaces the active-call 10-second
cutoff with bounded recovery. The 10-second active-read references below describe
the earlier investigation state; handshake/write deadlines remain unchanged.

## Findings before the fix

**Confirmed:** the misleading `hangup_failed` summary is caused by a redundant
local hangup after the upstream call has ended. **Not confirmed:** the cause of
WhatsApp's reconnect/disconnect, or that transport-message-type 3 means a network
switch. No relay/socket rebind change is justified by the available evidence.

The warning is emitted by Evolution's application event handler, not by the media
engine. meowcaller independently handles the same CallTransport event. Adding a
second transport handler that reconnects or acknowledges arbitrary nodes would
risk duplicating existing signaling and is deliberately not implemented.

## Pinned source trace

Evolution Go Calls: `e21ce0dd7634f3047410c893b5e4d1c082034b84`, from
`scripts/prepare_evolution.py`. The reviewed local tree already has VASA's
logging-only patch. No Go source, dependency, preparation patch or image changed.

Dependencies from its go.mod/go.sum were downloaded as public source and verified
against the module directory h1 hashes in the pinned go.sum:

| Module | Version | Verified h1 |
| --- | --- | --- |
| github.com/purpshell/meowcaller | v0.0.0-20260726180203-6d9b7b2c1807 | SnLX76CnagumooXRm63BK9Rn2/e/Th6aWWJJKTqOk2k= |
| go.mau.fi/whatsmeow | v0.0.0-20260722203353-e9a033b24933 | 7skZGs9q+rWKqYHok4ZufzhKpf6GmTKZnTjSm0aDtus= |

1. whatsmeow `types/events/call.go:37`: CallTransport embeds BasicCallMeta and
   CallRemoteMeta and carries a node pointer. It is not a typed reconnect enum.
2. whatsmeow `call.go:19,80`: handleCallEvent defers the normal acknowledgment,
   parses call metadata and dispatches a child tagged `transport` as CallTransport.
   It does not interpret transport-message-type. `client.go:924` iterates event
   handlers; Evolution's later default warning does not undo the earlier handler.
3. Evolution `pkg/whatsmeow/service/whatsmeow.go:426,519`: NewClient installs
   meowcaller before Connect and before the application's event handler.
4. meowcaller `engine.go:143–168`: engine.install registers CallTransport →
   onRelay(call ID, data), independently of Evolution's webhook/log switch.
5. `engine.go:752`: onRelay finds a nested relay, records parsed endpoints/keying
   data, may rekey to the elected peer, and calls maybeStartMedia. Without a relay
   node it returns; it does not inspect the numeric transport subtype.
6. `engine_media.go:42`: maybeStartMedia returns when m.started is already true.
   Existing one-to-one media is not reconnected just because m.relay changes.
   runMedia retains its connected relay channel and allocation, sends paced
   audio/silence and runs allocate/ping keepalive at 1 Hz. Group allocation has a
   separate update path. This is a real limitation for a genuinely changed active
   relay, but the supplied logs do not show whether such a change occurred.
7. `signaling/stanza.go:199–238`: TransportParams exposes an opaque optional
   string and optional endpoint/candidate round; only subtype 9 has a specific
   builder rule (omit net protocol). Neither the receiver nor the event defines
   subtype 3 as rebind/reconnect/network switch. Builder tests cover 1/9; lifecycle
   tests cover relay-elected peer rekeying. No subtype-3 socket-recovery contract
   or test was found in this pinned dependency. These source tests were inspected;
   Go tests were not executed because no Go source changed.
8. Evolution's application switch at `whatsmeow.go:1924–1969` forwards offer,
   accept, terminate and relay latency. There is no CallTransport branch; its
   default at 2088 prints “Unhandled”. It does not prevent meowcaller handling
   the event, nor does it forward transport events to VASA's event WebSocket.
9. meowcaller `engine.go:1232` onTerminate calls finishCall: removes engine state,
   cancels media and ends the Call. Evolution independently deletes its registry
   entry on CallTerminate. Stream handler registers Call.OnEnd → bridge.Close.
   bridge.Close sends `stop`, then closes the socket, idempotently. On readLoop
   return, serveStream calls Call.Hangup. Later REST hangup cannot find the deleted
   registry entry and returns the observed server error.

## VASA lifecycle and narrow changes

The conversation runtime runs its media reader concurrently with greeting,
STT and response tasks. No transport notification cancels these tasks: VASA
previously consumed offers only, and upstream does not forward CallTransport.
The reader ends on upstream stop, a read failure, or existing runtime limits.
The existing 10-second media read deadline can end a longer interruption; it is
unchanged because there is no verified renegotiation contract warranting a new
timeout policy. Closing on stop triggers runtime task cleanup, as intended.

- `evolution/client.py`: consume authenticated CallTerminate with the existing
  instance-token check, exact queue and validated call ID. Mark only the matching
  active media lifecycle; duplicate terminate is idempotent. Tracking is bounded
  to ten active streams and removed on context exit, including failed handshakes.
  It does not maintain an unbounded terminated-call cache or change APIs.
- `evolution/stream.py`: distinguish validated remote terminate from an upstream
  stop and from a local close/read failure. Record upstream stop before closing.
  Expose fixed markers for media gaps/recovered frames and read failures. A
  recovered frame proves media continuity resumed, not a socket rebind.
  If verified terminate races a socket close without stop, unavailable becomes
  normal EOF; malformed payload errors are still rejected.
- `voice_worker.py`: upstream stop means the pinned bridge owns hangup; do not
  repeat it. A known remote terminate likewise skips local hangup. Report
  `hangup_required=false`, `hangup_acknowledged=false`, and fixed termination
  source, without creating hangup_failed. Recheck authoritative state on an
  in-flight hangup failure. Preserve all preexisting runtime errors and run
  cache/durable cleanup. With no termination evidence, hangup failures still fail.
- `scripts/sanitize_call_diagnostics.py`: bounded stdin-only operator log filter.
  It emits only fixed type_1/type_3/other observations, remote terminate, local
  hangup and media continuity markers. It never emits captured field values,
  arbitrary log lines, numbers, nodes, URLs, relay payloads or credentials.

Existing raw Evolution logs contain node payloads: do not paste them or use
unfiltered `docker logs` output in Actions. The filter is retrospective, not a
change to upstream logging/security configuration. No transport algorithm,
provider, database schema, deployment topology or security setting was changed.

## Exact live validation procedure

No deployment or live call is performed by Codex. Operator:

1. Deploy via the existing GitHub Actions bridge, normal update mode:

   ```bash
   gh workflow run vasa-vps-deploy.yml --repo ralphdeeney/VASA \
     --ref build/vasa-foundation -f mode=deploy -f provider_smoke=false
   ```

   Require `VASA_DEPLOYMENT_OK`. No Evolution image/restart is needed for this
   Python lifecycle correction. Record existing container restart counts through
   selected inspect fields only, never container environment.
2. Place one inbound WhatsApp audio call at a time. Verify answer, greeting,
   bidirectional speech and completed turns. Keep the call active for at least
   90 seconds to exceed the previous 10–30 second failure window.
3. Repeat once with stable Wi-Fi and once with an intentional caller Wi-Fi/mobile
   data switch. Record whether WhatsApp reconnects and whether audio resumes.
   Do not infer a subtype's semantics solely from its temporal correlation.
4. On the VPS, capture only sanitized observations (host Python is sufficient):

   ```bash
   cd /opt/vasa
   set -o pipefail
   docker compose --project-name vasa-vps --env-file .local/vps.env \
     -f deploy/compose.yaml --profile voice logs --no-color --since 10m \
     --tail 2000 evolution voice 2>/dev/null \
     | python scripts/sanitize_call_diagnostics.py
   ```

   `CALL_TRANSPORT=type_3` reports an upstream observation only.
   `CALL_MEDIA=receive_gap` + `receive_recovered` reports resumed caller frames.
   No recovery marker means recovery is unproven. `read_timeout` identifies the
   existing bounded read timeout rather than a guessed remote termination.
5. End one call from the caller. Require authoritative terminate and/or upstream
   stop; final summary should have no newly introduced hangup_failed, false local
   acknowledgment, hangup_required=false and remote_terminate/upstream_stop source.
   Check frame/turn counters from the existing sanitized summary and confirm
   registry/durable finalization and unchanged container restart counts.
6. End a separate call locally. Require local hangup and successful cleanup.
   A genuine failed local hangup without end evidence must still report failure.
7. If reconnect persists, this change has **not** fixed its root cause. Report the
   fixed markers, duration, stable/switch scenario, frame/turn counters and restart
   counts only. Further upstream instrumentation must record structural transport
   subtype/relay-presence/endpoint-change booleans and relay receive/keepalive
   progress without payloads before implementing a relay rebind. That upstream
   behavioral change is deliberately deferred until supported by actual evidence.
