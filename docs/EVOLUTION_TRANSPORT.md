# Verified Evolution Go Calls integration

## Source selection

User-selected repository: https://github.com/luis-kovi/evolution-go-calls.
Pinned commit: `e21ce0dd7634f3047410c893b5e4d1c082034b84`, branch `agent/call-stream-auth`, open PR #1 head. PR merge ref `5e6b42757caedcd321dc411b0bc60b2955ac6e82` had the same tree when inspected on 2026-10-08.

Default main `81cc815fdb2a29e8fa7ee17d158d30ad622f5c76` and develop `706c9a48576428005053971bb9ea73dc34c35462` expose rejection only. Initial investigation of EvolutionAPI/evolution-go also found rejection only; the user supplied the correct Calls fork. VASA uses the reviewed PR commit, not the default branch.

Actual service methods call meowcaller Answer(), Hangup(), Reject(); stream bridge connects Call.Receive and Call.Play. Relevant source: pkg/routes/routes.go, pkg/call/service/call_service.go, pkg/call/registry/call_registry.go, pkg/call/stream/handler.go and bridge.go, pkg/whatsmeow/service/whatsmeow.go. Source implementation is verified; live WhatsApp behavior is not.

## HTTP and event contracts

- Admin apikey header: POST /instance/create with explicit instanceId, name, token, rejectCall false; DELETE /instance/delete/:id for provisioning compensation.
- Instance apikey header: POST /instance/connect (CALL, CONNECTION, QRCODE subscriptions and websocketEnable true), POST /instance/disconnect, GET /instance/status, GET /instance/qr.
- Instance call controls: POST /call/answer and /call/reject with callId/callCreator; POST /call/hangup with callId. VASA does not integrate outbound dial or video features.
- Server event WebSocket: /ws?token=GLOBAL_API_KEY&instanceId=ID; private server-side use only. queue is <instance>.calloffer; payload is a JSON string with event, data, instanceId, instanceToken. Validate token/id binding and CallOffer CallID/CallCreator/From fields.
- Per-instance token derives from HMAC-SHA256(VASA_EVOLUTION_INSTANCE_KEY, 'vasa:instance:'+id). Only trusted tenant-owned mappings can select an instance. The key must remain stable; rotation requires reprovisioning upstream tokens. No token is stored in the mapping or returned to the browser.

## Media contract

GET /call/stream/:callId?instance=ID&exp=UNIX&token=HEX, with lowercase HMAC-SHA256(CALL_STREAM_SIGNING_KEY UTF8, 'ID|CALLID|EXP'). VASA issues a 60-second token. Legacy apikey query is not used for media.

JSON messages: start(callId,sampleRate,video), media(track=inbound/outbound,payload=base64), stop(reason). PCM16 little-endian mono at 16000 Hz; meowcaller commit 6d9b7b2c18072155a4581ab8c7fccc51b4fd0a73 uses 960 samples/60ms/1920 bytes. These fields have no remote sequence/timestamp; VASA timestamps/sequences represent local reception only.

At most four raced media frames are buffered before validating start (upstream Receive can run before writeStart). Wrong call/sample format/video is rejected. Bounds, deadlines, socket cleanup and actual local WebSocket component tests cover the adapter. Event sockets use ping/pong health, not a media idle deadline; calls may be hours apart.

Upstream has no playback acknowledgment or clear/flush message. Its outbound buffer can hold about three seconds. Pace output instead of filling that buffer. Do not promise instantaneous future barge-in clearing without a supported upstream change and actual measurements. Closing the media socket also hangs up.

## Automatic deployment and honest readiness

Run `bash scripts/evolution-setup.sh` from the repository after the required network settings are active. It fetches the exact commit through Git, verifies the cache manifest, applies the checked-in logging-only patch, generates paired local service secrets without printing values, and builds the dedicated Docker service. No upstream precompiled binary is used.

The source's default Docker ignore excludes tests; VASA retains them. Build runs go mod download/verify, go test and vet for pkg/call/..., then compiles the actual server. Normal compilation and runtime use non-root users. Dependencies retain Go checksums and HTTPS verification. A host-authoritative certificate-only CA bundle is copied into the build/runtime to trust the cloud proxy. This is not a TLS verification bypass.

The checked-in patch removes credential-bearing request query logging, token cache logs, partial license-key prints and registration URL logs; panic logging emits a fixed event without credential-bearing request dumps. It changes no API/media/licensing behavior. Source LICENSE/NOTICE and upstream branding are preserved.

Current build blocker: official Go module ZIP downloads redirect to storage.googleapis.com, denied by the cloud network policy. Trust was corrected after the initial missing-CA failure; checksums/signatures were not disabled. Source tests, compile and provider startup therefore remain unrun. Compose configuration and source preparation were validated; a valid recipe is not a successful deployment.

Saved network additions: storage.googleapis.com, license.evolutionfoundation.com.br, api.github.com. Apply/publish environment settings before retrying the affected build/license/PR operations.

## License, pairing and media prerequisites

The runtime requires vendor license activation. All call and pairing operations return 503 LICENSE_REQUIRED before activation. /server/ok establishes process health only; /license/status must be checked separately without exposing its partial key. A random local global key does not activate a license. The shipped operator-email auto path appears unreachable when the required global key is nonempty; do not rely on it.

Supported vendor registration is GET /license/register, browser registration, then GET /license/activate?code=...; do not place the authorization code in Git/chat/logs. VASA prepares the component automatically; installation is not delegated to the user. Personal license registration/activation remains an external prerequisite.

After activation, bootstrap a VASA user, use the authenticated dashboard to pair WhatsApp, then run the media probe. WhatsApp accounts can require a passkey ceremony beyond QR; do not bypass it. Media relays use dynamically negotiated outbound UDP/DTLS. Domain allowlisting for HTTPS does not demonstrate UDP capability. License, pairing, relay access and real media remain unverified.

## Manual acceptance probe

`uv run --frozen python -m vasa.media_proof --email CLIENT_EMAIL --instance VASA_INSTANCE_UUID`

The local administrative command checks user/tenant ownership and paired status, waits for an authenticated incoming event, creates expiring call state, answers, receives actual caller audio, and returns a known prerecorded three-tone diagnostic WAV, paced at 60 ms/frame. `--audio` can supply a mono PCM16/16000Hz WAV up to 10 seconds. This probe is transport acceptance, not an AI conversation or a simulated call.

Reports under ignored .local/ contain state transitions, real received/sent frame counts, local elapsed times, cleanup acknowledgments and errors. They never record caller audio. Sending frames does not prove audibility: caller_heard_response stays null until the human confirms it. The source does not expose remote timestamps or dropped-frame counters, so those transport metrics cannot be fabricated from local counts. The real gate is unrun.
