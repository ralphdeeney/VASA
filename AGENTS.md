# VASA agent instructions

Read docs/BUILD_HARNESS.md, ARCHITECTURE.md, BUILD_PLAN.md, CURRENT_STATE.md, DECISIONS.md, TEST_RESULTS.md, EVAL_RESULTS.md and PERFORMANCE.md before work. Resume from recorded state.

Use the existing checkout; cloud tasks are already isolated. Do not create worktrees unless the user requests one. VPS deployment preparation and a connection attempt are now authorized. Deploy only under /opt/vasa as the existing rootless vasa-builder user after verifying SSH address/access and dedicated project ownership. Never modify unrelated VPS services, Docker installations, firewall rules or reverse proxies.

The orchestrator owns shared contracts, migrations, dependency declarations and integration. Assign specialists separate file ownership; no simultaneous edits of shared files. Freeze each wave's interfaces in docs/CONTRACTS.md before parallel work. Request interface changes from the orchestrator. Wave 0 is orchestrator only.

Follow the graph and engineering loop in the full harness. Never progress past the real bidirectional media gate with mocked evidence. No AI voice implementation before Gate 3. Use unit/integration/component/contract tests and evals, not a large automated E2E suite. Commit verified slices and update persistent state.

Python 3.12+, typed async I/O, Ruff and strict mypy. Run bash scripts/check.sh from the checkout. Tests requiring real services must fail with an actionable error if services are absent, rather than silently skip. Do not invent Evolution routes/codecs/authentication. Validate against a pinned authoritative upstream source.

Keep secrets outside Git and logs; never expose server credentials to clients. All tenant-owned queries require explicit trusted tenant context; client-supplied tenant headers are not authentication. Use bounded resources and cleanup. Keep n8n out of live audio. Respect V1 scope.

Use scoped VASA development services only. Do not alter unrelated Docker resources, host services or credentials. No normal build work as root. Do not claim unrun evals or benchmarks passed.

Autonomous delivery: follow docs/DEPLOYMENT_ORCHESTRATOR.md. For approved work,
implement/test/commit/push and monitor Actions without asking the operator to
open Actions or select routine modes. Use explicit request-only commits for
read-only checks and separately authorized maintenance. The exact code target
is the request commit's parent; the controller executes the code-identical
request envelope SHA. Require CI and success markers; never claim deployment
from a push alone. Ordinary pushes never authorize Evolution, bootstrap, paid
smoke, migrations, secret changes or active-call interruption. Single-use
maintenance grants cannot be renewed by a self-approved request. Hard safety
gates stop; known pre-login connectivity failures have bounded retries. Unknown
remote outcomes require receipt-based verification, never blind restart.
GitHub Actions is the only VPS bridge; no direct Codex SSH. Preserve live data,
private runtime files, pairing and all unrelated infrastructure. Human live-call
acceptance and unavailable external credentials remain explicit boundaries.
