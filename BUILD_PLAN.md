# Build plan

2026-10-15 Actions deployment implementation complete:615 checks pass, plus
Actionlint and shell syntax. Register manual workflow on main, configure trusted
VASA_VPS_HOST_KEY_SHA256 repository variable, then dispatch mode=check against
build/vasa-foundation. Deploy remains manual; no direct Codex-to-VPS SSH.

2026-10-14 Deepgram Aura is now the explicit user-selected interim default;
all599 checks pass. Configure a replacement DEEPGRAM_API_KEY securely and update
any existing VASA_TTS_PROVIDER override before operator restart/live validation.
The exposed chat credential is not stored or used; actual VPS validation remains
manual. This preference does not establish production readiness.

2026-10-14 optional Deepgram Aura TTS code/settings/worker/benchmark integration
is complete (599 combined checks). User-approved scope is TTS only. Next gate
requires securely setting DEEPGRAM_API_KEY before live model/auth/PCM validation
and labeled measurements. Defaults and actual production deployment are unchanged.

2026-10-12 Speechify optional-provider/benchmark integration is complete and
verified (571 full checks). Actual VPS streaming measurements and listening
are the next manual step under docs/tts-evaluation/speechify-simba-3.2-vps/.
Do not change defaults or claim production readiness from component evidence.

2026-10-09 Kitten Micro candidate slice is integrated and verified locally.
Pinned optional assets, trusted selection, preload/cancellation/framing and
matched cloud A/B evaluation are complete (539 full checks; 54 measured
responses/108 WAVs). Actual VPS A/B/C and human listening remain pending via
docs/tts-evaluation/kitten-micro/REPRODUCE.md. Do not promote the default until
those gates pass; preferred first-audio/gap targets are unmet in cloud results.

2026-10-09 user-selected Kokoro-first slice: LJSpeech retired, Kokoro INT8
default, Piper retained; callback delivery, intelligent chunks, independent
thread settings, one-time model/generic warmup, bounded audio prefetch/cache
implemented. Full521 checks pass. Actual VPS benchmarking/deployment is the
operator's pending manual step, and audible quality remains unverified.

The complete governing instructions are in docs/BUILD_HARNESS.md.

| Wave | Scope | Progress |
| --- | --- | --- |
| 0 | Repository/governance, config, contracts, checks, health, eval framework | Verified |
| 1 | PostgreSQL/Redis, tenant foundations, test fixtures and isolation evals | Verified |
| 2 | Verified Evolution client, instances/calls/media; mappings, registry, connect/QR UI | Verified transport; real answering/media confirmed by user |
| 3 | Real caller audio in, prerecorded audio out, heard by caller | PASSED: 98 live inbound frames, 20 diagnostic outbound frames, human confirmed tones |
| 4 | CPU speech, cancellation/barge-in, LLM adapters/context/fallback | Component/native verified; live provider credential pending |
| 5 | Integrated conversation state machine | Component/native verified; live OpenAI acceptance pending secure key |
| 6 | Generic validated tools and tool evals | Implemented and component/eval verified; live business action pending |
| 7 | Full tenant-owned call/message/tool/knowledge persistence | Implemented and SQL isolation/evidence verified |
| 8 | Tenant-isolated CPU embeddings/RAG and Knowledge UI | Implemented; native retrieval 19/20 first-result eval |
| 9 | Minimal authenticated dashboard | Implemented and API/UI contract verified |
| 10 | Combined tests/evals, profiling and repeated-call stabilization | 476 checks pass; live provider/VPS/phone gates remain |

Wave 1 establishes only the database models needed for tenancy; Wave 7 expands persistence. Wave 6 defines knowledge_search's contract, with functional knowledge retrieval verified after Wave 8. Thresholds must be documented before behavioral/performance gates; no invented passing results.

2026-10-09 user steering: defer secure OpenAI binding/live acceptance and continue
independent tasks. Gateway, approved webhook/current-call-ending handlers,
knowledge contract and call/message/tool metadata storage are independently
prepared and verified. The voice runtime still rejects tool output. Gate 5,
runtime integration, functional knowledge retrieval, complete Wave 7 knowledge
storage and live behavioral acceptance remain pending. Component preparation
does not count as passed graph gates.

Current Wave 2 deployment preparation: isolated rootless VPS package and
activation tunnel procedure implemented and cloud component-verified. Actual
SSH deployment is blocked because the confirmed address refuses port 22 from
this environment; a proxy-route probe also closes before the SSH handshake.
The user verified externally that SSH is listening. These historical deployment
limitations do not block independent speech/runtime development. The user's
subsequent real-call acceptance satisfies Gate 3; keep the proven transport.
