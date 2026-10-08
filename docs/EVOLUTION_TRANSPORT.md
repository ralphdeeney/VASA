# Evolution transport prerequisite

## Evidence checked on 2026-10-08

Public upstream: https://github.com/EvolutionAPI/evolution-go (README identifies the project as evolution-foundation/evolution-go).

- main commit `9337afc47e10b86cc896a6f432240e40fee95dd1`
- develop commit `7f7924097ce89a1cd50121d1cd0beb29a2c7fcb7`
- Both branches expose only `POST /call/reject` in `pkg/routes/routes.go` and the CallService interface contains only RejectCall.
- `docs/wiki/guias-api/api-call.md` explicitly states programmatic acceptance is unavailable in that version. The ordinary `/ws` is an event transport; it does not establish inbound/outbound call audio.
- `README.md` describes license activation for that product. It has not been installed or activated.

No public Calls-specific repository was confirmed from the names tested. This does not prove that no private or separate version exists. The user has been asked for the intended Calls repository/API documentation.

## Required before the Wave 2 adapter can be verified

A pinned authoritative Calls source/version or API specification must establish:

1. instance creation, pairing/QR and connection status;
2. scoped authentication and signed/authenticated incoming call events;
3. answer, reject, hangup and lifecycle semantics;
4. media stream handshake, direction, codec/sample rate, frame format, ordering and close behavior;
5. reconnect/timeout limits and required licenses/runtime dependencies.

After source validation, inspect existing cloud binding names and declare only missing service/credential requirements. Do not request API secrets in chat. Do not build an ordinary messaging adapter and describe it as an audio-call transport.

Wave 2 cannot pass without a real supported integration. Wave 3 cannot pass with mocks, generated tones or an open WebSocket alone: caller audio must reach VASA and a known prerecorded response must be heard by the real caller.
