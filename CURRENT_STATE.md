# Current state

Current wave: 2 (component implementation verified; live integration blocked)
Current slice: Evolution pinned-source Docker deployment
Completed slices: Wave 0 governance/tooling/contracts; Wave 1 tenant PostgreSQL/pgvector/Redis and isolation; Wave 2 typed verified-source adapter, authenticated instance mapping/control, login/QR/status dashboard, unit/component/real-service checks; manual media probe preparation
Active agents: none; orchestrator finalizing evidence and GitHub upload
Blockers:
- storage.googleapis.com is denied, preventing official Go module ZIP downloads and Evolution source build
- license.evolutionfoundation.com.br is denied; vendor activation remains required before pairing/call operations
- api.github.com is denied, preventing PR creation through CLI; native Git upload works
- WhatsApp pairing and real inbound-call gate are unrun; dynamic UDP relay connectivity is unverified
Failed checks: Evolution Docker build (403 artifact destination); initial CA error corrected through host-authoritative trust bundle, no TLS/checksum bypass; no outstanding VASA test/static failures
Next action: review/save/publish the saved environment draft to apply exact domain additions; rerun bash scripts/evolution-setup.sh, verify actual provider startup/license state, then complete activation/pairing and real-call acceptance. Continue debugging build issues if new failures emerge; do not assume source compilation passed.

Latest combined verification: 110 passing checks, zero failures/errors/skips, including 3 tenant-isolation evals; Ruff and strict mypy pass. Alembic no drift. Local API and login/assets HTTP200, unauthenticated dashboard401. Source cache preparation and compose configuration validated. Evolution go test/vet/compile and real provider requests are unrun because dependency download is blocked. No AI/speech/tools/knowledge implementation or voice benchmark is claimed.

VPS remains deferred. No automated browser/WhatsApp E2E framework is built. GitHub upload uses build/vasa-foundation; remote CI results and fresh-cloud restoration are not verified.
