# Eval results

2026-10-08: 3 tenant-isolation evals passed. Two cover explicit tenant SQL agents and Redis call-state reads/deletes; one exercises authenticated foreign-instance API access denied with HTTP 404 before any upstream operation, with own-tenant positive controls. Real PostgreSQL/Redis and server-derived session contexts are used.

Conversation, tool, knowledge, summary and latency evals are UNRUN because those implementation waves are blocked by real media proof. Planned golden cases are not passing results. Local WebSocket and diagnostic probe tests are component checks, not real-call evidence.
