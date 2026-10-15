# Bounded active-call receive recovery — 2026-10-15

## Evidence and causal chain

The operator reports 30–36 second calls, repeated reconnect UI, distorted audio,
working barge-in, recovered receive gaps, a read timeout and remote termination.
The supplied sanitized lines combine calls and event sources, and are not a
timestamped per-call trace. They establish recoverable interruptions and a timeout,
but cannot establish whether that timeout preceded the remote termination.
Transport type 3 is still opaque; it is not treated as a reconnect signal.

Before this change, `MediaStream._read` imposed 10 seconds per recv. On timeout,
`receive` closed the WebSocket and raised unavailable. ConversationRuntime's
reader failure ended the conversation and cancelled its other tasks. Evolution's
pinned `pkg/call/stream/bridge.go` ends readLoop on socket close, and
`handler.go:143–145` unconditionally calls Call.Hangup after that loop. Thus a
VASA timeout **can locally terminate a still-active upstream call**, rather than
merely observe WhatsApp's eventual decision. Worker cleanup can additionally
request hangup. The final CallTerminate alone cannot identify who initiated it.

The pinned meowcaller `engine_media.go:141` permits up to 12 seconds for relay
connection/DTLS setup. Ten seconds of missing inbound media is a shorter budget
than that single setup path. Its event handler remains independent of Evolution's
Unhandled-event warning; no new signaling or relay/socket reconnect is added.

## Policy and bounds

| Situation | Policy |
| --- | --- |
| Start/handshake | Existing 10-second whole-handshake deadline, unchanged |
| Active receive gap below 1 second | Wait silently; normal jitter does not end call |
| Gap reaches 1 second | Emit receive_gap_started; keep the SAME recv pending |
| Valid media resumes before 24 seconds | Emit locally measured receive_recovered_ms; continue same stream/conversation |
| No receive before 24 seconds since last valid frame/start | Emit recovery_grace_expired, close stream and fail as media loss |
| Authenticated remote terminate | Wake the pending reader immediately and end normally |
| Upstream stop | End immediately and retain upstream-owned cleanup |
| Malformed data, socket failure, write failure | Existing fatal behavior; no speculative retries |
| Cancellation/provider failure | Pending receive/terminate tasks are cleaned up; existing errors remain authoritative |

The 1-second threshold preserves the prior continuity diagnostic threshold (about
17 missing 60 ms frames). The **24-second maximum** budgets two source-sized
12-second connection windows: one setup-sized interval plus an equal recovery
margin. This is an explicit conservative staging policy, **not** a measured
optimal value or a claim that upstream retries twice. The reported 30–36 second
call durations are not receive-gap measurements and cannot determine a precise
grace. Numeric gap measurements and expiry markers are needed for live tuning.
We do not extend the maximum to a whole observed call duration on that evidence.
The soft 1-second observation does not add another 24 seconds; both deadlines
are absolute from the same last-frame/start time. Frame recovery resets the gap
budget; ConversationRuntime's existing maximum call duration remains unchanged.

Remote termination is matched through the existing authenticated instance token,
queue and call ID. It now signals a call-local Event as well as its state flag,
so an idle receive does not wait out grace after an authoritative terminate.
No unauthenticated event or opaque transport subtype can extend the deadline.
Grace expiry is recorded separately in the final summary as
media_recovery_expired=true; provider/STT/TTS error codes are never overwritten.

## Audio degradation investigation

- VASA still rejects anything except mono PCM16, 16 kHz, 1920 bytes per frame.
  It cannot detect RTP loss, reordering, concealment or remote capture age from
  those checks. Upstream JSON carries no RTP sequence/timestamp; VASA sequence
  and monotonic timestamps describe local receive order/time only.
  Missing caller audio is not reconstructed: VAD/STT can still see discontinuous
  speech as adjacent received frames. No reset/padding policy is guessed here.
- No synthetic caller frames, duplicated frames, accumulated recovery queue or
  conversation replay is added. The same pending recv survives soft-gap detection.
  Existing raced-handshake frames remain bounded to four and WebSocket buffering
  remains bounded by the existing connection configuration.
- ConversationRuntime's TTS playback queue is 16 frames (960 ms); it sends starts
  every 60 ms. A late send resets next_send to send_started+60 ms, so it does not
  intentionally catch up by replaying an overdue burst. Barge-in still cancels
  the current generation. There is no receive-gap-triggered TTS restart/replay.
- Evolution's bridge has 50 queued outbound frames, approximately 3 seconds.
  Its full-channel default drops NEW frames rather than evicting old ones. If
  relay consumption stalls, stale queued speech can remain. This is a source
  possibility, not measured queue age in the observed calls.
- Additional upstream risk: bridge.ReadFrame waits for incoming outbound audio;
  Player.nextFrame synchronously calls that source; engine_media's ticker calls
  nextFrame before its silence fallback. An empty bridge queue can therefore
  block the RTP send loop instead of reaching the intended silence fallback.
  Consent keepalive is separate. This path may merit a later isolated upstream
  test and outbound-RTP progress instrumentation; its role in these calls is
  unproven. No upstream Go source or media API is changed in this timeout fix.

Do not drop arbitrary PCM after recovery or flush a remote queue by inventing a
new API. Without remote timestamps/queue-age evidence that could lose fresh
caller speech or legitimate responses. Do not equate received frames with clear
audio or heard replies. The new timing proves local continuity, not voice quality.

## Sanitized evidence and human validation

The existing sanitizer now admits fixed receive_gap_started/grace_expired and
bounded integer receive_recovered_ms markers. It rejects trailing text, nonnumeric
values and oversized numbers. Caller IDs, raw nodes, relay payloads and secrets
are never included. Historical read_timeout markers refer to the old active
policy or the unchanged handshake path, not an active 10-second cutoff now.

Push deploys through Actions only, including mandatory health/web/Evolution checks.
After a successful deployment, place one call at a time: stable network for at
least 90 seconds and three turns, barge in, then caller hangup. Repeat with an
intentional Wi-Fi/mobile switch. Capture only the existing sanitizer output.
Compare gap durations, recovery vs grace expiry, completed turns, termination
source, and container restart counts. An interrupted call may still be ended
earlier by WhatsApp's authoritative terminate or upstream stop; grace never
overrides either. Successful tests are required before claiming reconnect solved.
