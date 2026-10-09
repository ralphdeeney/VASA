# Build plan

The complete governing instructions are in docs/BUILD_HARNESS.md.

| Wave | Scope | Progress |
| --- | --- | --- |
| 0 | Repository/governance, config, contracts, checks, health, eval framework | Verified |
| 1 | PostgreSQL/Redis, tenant foundations, test fixtures and isolation evals | Verified |
| 2 | Verified Evolution client, instances/calls/media; mappings, registry, connect/QR UI | Verified transport; real answering/media confirmed by user |
| 3 | Real caller audio in, prerecorded audio out, heard by caller | PASSED: 98 live inbound frames, 20 diagnostic outbound frames, human confirmed tones |
| 4 | CPU speech, cancellation/barge-in, LLM adapters/context/fallback | Component/native verified; live provider credential pending |
| 5 | Integrated conversation state machine | Component/native verified (318 combined checks); live OpenAI acceptance pending secure key |
| 6 | Generic validated tools and tool evals | Blocked by Gate 5 |
| 7 | Full tenant-owned call/message/tool/knowledge persistence | Blocked by Gate 6 |
| 8 | Tenant-isolated CPU embeddings/RAG and Knowledge UI | Blocked by Gate 7 |
| 9 | Minimal authenticated dashboard | Blocked by Gate 8 |
| 10 | Combined tests/evals, profiling and repeated-call stabilization | Blocked by prior gates |

Wave 1 establishes only the database models needed for tenancy; Wave 7 expands persistence. Wave 6 defines knowledge_search's contract, with functional knowledge retrieval verified after Wave 8. Thresholds must be documented before behavioral/performance gates; no invented passing results.

2026-10-09 user steering: defer secure OpenAI binding/live acceptance and continue
independent tasks. Generic gateway preparation is now implemented separately;
the voice runtime still rejects tool output. Gate 5, Wave 6 integration, concrete
tools and live behavioral acceptance remain pending. Do not count component
preparation as passed graph gates.

Current Wave 2 deployment preparation: isolated rootless VPS package and
activation tunnel procedure implemented and cloud component-verified. Actual
SSH deployment is blocked because the confirmed address refuses port 22 from
this environment; a proxy-route probe also closes before the SSH handshake.
The user verified externally that SSH is listening. These historical deployment
limitations do not block independent speech/runtime development. The user's
subsequent real-call acceptance satisfies Gate 3; keep the proven transport.
