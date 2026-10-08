# Current state

Current wave: 2 (source build and provider startup verified; activation pending)
Current slice: vendor activation prerequisite before WhatsApp pairing and media proof
Completed slices: Wave 0 governance/tooling/contracts; Wave 1 tenant PostgreSQL/pgvector/Redis and isolation; Wave 2 typed verified-source adapter, authenticated instance mapping/control, login/QR/status dashboard, unit/component/real-service checks; manual media probe preparation
Active agents: none; independent implementation, evidence and GitHub upload complete
Blockers:
- Evolution vendor license is inactive. Real POST /instance/create returns HTTP 503 LICENSE_REQUIRED, preventing provisioning/pairing/calls.
- WhatsApp pairing and real inbound-call gate are unrun; dynamic UDP relay connectivity is unverified
Failed checks: none outstanding in source build or VASA verification. Earlier artifact-download denial is resolved after user publication. License enforcement is an expected prerequisite, not a passing call test.
Next action: complete the supported vendor activation flow without sharing codes/keys in chat, confirm active license, bootstrap a client login, pair WhatsApp and run the manual incoming-call probe. Wait for human audibility confirmation before Gate 3 progression.

Latest post-publication verification: 110 passing checks, zero failures/errors/skips, including 3 tenant-isolation evals; Ruff and strict mypy pass. Current JUnit: reports/published-restore.xml. Alembic no drift. Restarted API /health/live, /health/ready and /login return HTTP 200; database and Redis are healthy. Evolution Go modules download/verify, call-package tests/vet, CGO server compilation and Docker startup all passed. Real /server/ok returns 200, /license/status is inactive, and instance provisioning is blocked with 503 LICENSE_REQUIRED. No AI/speech/tools/knowledge implementation, live media gate or voice benchmark is claimed.

VPS remains deferred. No automated browser/WhatsApp E2E framework is built. The verified work is uploaded to build/vasa-foundation. GitHub API access works after publication. Remote CI results and restoration into a separate fresh task remain unverified; the attached published environment's service restart and functional checks passed.

Cloud publication is confirmed by configuration metadata and actual successful operations. The published installation/startup instructions remain usable; user-published network policy is unrestricted and has not been changed by the agent. No additional network-setting action is needed for the previously blocked Go/GitHub operations. See docs/CLOUD_ENVIRONMENT.md for reproducible commands and limitations.
