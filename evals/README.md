# Evaluations

Run uv run --frozen pytest evals -v after starting development services and applying migrations. Every executed eval must assert actual behavior and fail on regression. Planned golden cases in golden_cases.json do not execute or count as passed.

Tenant isolation starts in Wave 1. Conversation/tool/knowledge/summary/latency suites start with their implementation waves and are explicitly unrun until then. Do not use mocked media as evidence for the human real-call gate.
