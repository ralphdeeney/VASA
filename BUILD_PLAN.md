# Build plan

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
