# Decisions

- 2026-10-09: User explicitly defers configuring the replacement OpenAI key and
  requests other work. Prepare the generic tool validation gateway independently,
  without voice/runtime linking or advancing acceptance gates. Reuse the existing
  Tool protocol and Pydantic dependency; no provider credentials are required.

- 2026-10-08: Follow the user's full harness in docs/BUILD_HARNESS.md. Work in the current cloud environment, not a VPS.
- Wave 0 uses FastAPI, SQLAlchemy async/asyncpg, Redis asyncio, Alembic, pytest, Ruff, strict mypy and a committed uv lockfile.
- Shared contracts specify semantic boundaries only. Evolution wire details require upstream source verification; do not substitute ordinary messaging APIs for voice-call support.
- Development infrastructure is a dedicated compose project with loopback-bound ports and its own data volume; no Docker socket mount or unrelated service changes. Static database credentials in compose are local-only examples, never deployment credentials.
- Internal tenant context is not authentication. No public tenant CRUD APIs until trusted login/session enforcement is present.

- User-selected Calls fork: luis-kovi/evolution-go-calls; pin PR #1 head e21ce0dd7634f3047410c893b5e4d1c082034b84. Main/develop do not implement answering/streaming. No fabricated endpoints or substitution with voice messages.
- Wave 2 adds only required authenticated control/pairing screens. Passwords use bounded native scrypt off-thread; sessions are hash-keyed Redis with TTL/CSRF. Upstream instance tokens derive from a stable local master key and are never exposed/stored in mappings. Cross-service provisioning uses bounded deletion compensation; persistent compensation failure needs operator remediation, not a false success claim.
- Docker recipe builds source as non-root, retains Go verification and authoritative cloud CA trust, applies a logging-only patch to avoid credential leakage, and preserves notices/branding. Third-party license activation is retained; no bypass is attempted.
- Manual gate returns a known diagnostic three-tone recording after receiving real caller audio; no AI or caller audio recording. Frame transmission alone cannot prove audibility; caller confirmation remains required.
- Saved exact network additions are storage.googleapis.com (Go artifact ZIPs), license.evolutionfoundation.com.br (required vendor service), api.github.com (PR API). Draft persistence does not mean runtime policy changed or the environment was published.
- Reusable cloud setup uses the tested VASA script instead of the unrelated clone/placeholder script. Preserve the existing Ponytail startup preference and append concrete VASA service/readiness instructions. Publication and fresh-task restoration remain unverified.
- After user publication, official dependency verification, source tests/vet/compilation, Docker build and provider startup succeeded. The user-published unrestricted policy is preserved. Actual HTTP checks establish that vendor activation, not dependency access, now blocks pairing/calls. Attached-environment service restart is verified; separate fresh-task restoration is not.
- User now authorizes /opt/vasa deployment preparation and direct VPS connection, superseding the earlier deferral. Use only the existing rootless builder/context and dedicated vasa-vps project, preserving unrelated services. Keep all credentials in a generated private env file, reuse stable keys, reject occupied ports/foreign project ownership and preserve PostgreSQL/session/license volumes. Activate on the persistent VPS, not the temporary cloud.
- Both uppercase and lowercase NO_PROXY are required for private Docker hosts because cloud-injected lowercase variables take precedence. Retain external proxy routing and TLS verification. The read-only application uses only a dedicated diagnostics volume for the manual probe's outbound recording/report.
- Actual VPS SSH on the supplied port 22 is refused before authentication. Request correct host/port rather than guessing ports, modifying firewall/services or asking for secrets. Complete and upload independent deployment preparation while access is pending.
- The user confirmed that host/port and external SSH availability. Direct retry and a configured-proxy SSH probe still fail before handshake/authentication. Do not confuse a transport failure with a missing password/key; preserve host services and finish independent upload. No supported route has yet been demonstrated.

- User-reported real inbound call and confirmed tones satisfy Gate 3 (98 inbound/20 outbound frames). Preserve transport and enable CPU speech/runtime. Recognition threshold fixed before eval at aggregate WER <=15% over at least three independent pinned recordings. CPU native WebRTC/Zipformer/LJSpeech models, per-utterance isolation and bounded off-loop inference; models shared per worker. OpenAI is user-selected primary, Anthropic optional. Replace chat-exposed credentials securely.
- Barge-in invalidates output generations and cancels local pending work. No remote queue-clear/playback acknowledgment exists upstream; never claim already accepted frames were flushed or heard. Single selected-instance trusted worker resolves SQL ownership and logs only non-content metadata; persistence/tools remain later waves.

- Native VITS defaults randomize articulation and made appointment intermittently sound unclear to STT. Disable noise_scale/noise_scale_w for consistent business speech; repeated actual output must match. Independent recording WER acceptance remains unchanged. TTS batch completion is verified directly from native progress and resampled frame counts, including a real incorrect-polarity negative control.
