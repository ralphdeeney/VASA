# Build plan

The complete governing instructions are in docs/BUILD_HARNESS.md.

| Wave | Scope | Progress |
| --- | --- | --- |
| 0 | Repository/governance, config, contracts, checks, health, eval framework | Verified |
| 1 | PostgreSQL/Redis, tenant foundations, test fixtures and isolation evals | Verified |
| 2 | Verified Evolution client, instances/calls/media; mappings, registry, connect/QR UI | Components/source build/provider startup verified; license activation pending |
| 3 | Real caller audio in, prerecorded audio out, heard by caller | Probe prepared; human pairing/real-call gates unrun; downstream blocked |
| 4 | CPU speech, cancellation/barge-in, LLM adapters/context/fallback | Blocked by Gate 3 |
| 5 | Integrated conversation state machine | Blocked by Gate 4 |
| 6 | Generic validated tools and tool evals | Blocked by Gate 5 |
| 7 | Full tenant-owned call/message/tool/knowledge persistence | Blocked by Gate 6 |
| 8 | Tenant-isolated CPU embeddings/RAG and Knowledge UI | Blocked by Gate 7 |
| 9 | Minimal authenticated dashboard | Blocked by Gate 8 |
| 10 | Combined tests/evals, profiling and repeated-call stabilization | Blocked by prior gates |

Wave 1 establishes only the database models needed for tenancy; Wave 7 expands persistence. Wave 6 defines knowledge_search's contract, with functional knowledge retrieval verified after Wave 8. Thresholds must be documented before behavioral/performance gates; no invented passing results.

Current Wave 2 deployment preparation: isolated rootless VPS package and
activation tunnel procedure implemented and cloud component-verified. Actual
SSH deployment is blocked because the confirmed address refuses port 22 from
this environment; a proxy-route probe also closes before the SSH handshake.
The user verified externally that SSH is listening. Licensing will be completed on
the persistent VPS instead of the temporary cloud instance. Gate 3 is unchanged.
