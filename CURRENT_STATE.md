# Current state

Current wave: 5 (Conversation runtime; Wave 4 CPU Voice Intelligence verified)
Current slice: Wave 5 component/native verified; live OpenAI acceptance pending secure key
Completed slices: Wave 0 governance/tooling/contracts; Wave 1 tenant PostgreSQL/pgvector/Redis and isolation; Wave 2 verified pinned-source Evolution adapter, authenticated instance mapping/control and QR dashboard; Wave 3 real-call media acceptance; Wave 4 CPU VAD/STT/TTS, bounded native cancellation and streamed LLM adapters; Wave 5 conversation runtime, trusted inbound worker and native local-WebSocket integration
Active agents: orchestrator final upload/remote verification; specialist implementations complete
Blockers:
- OpenAI is selected primary, but no secure usable binding is injected. The credential pasted in chat must be revoked/replaced through VASA_OPENAI_API_KEY in environment settings, saved/published. Do not store or use the exposed credential. Anthropic is optional. Live LLM acceptance awaits this prerequisite; independent checks continue.
- Historical cloud SSH to vasa-builder@2.25.172.155:22 was refused before authentication; proxy CONNECT closed without SSH banner. No successful VPS connection or remote changes are claimed. This does not block independent development or negate the user's accepted real call.
Failed checks: none outstanding. Native TTS callback polarity, repeated-cancel cache cleanup, delayed state callbacks and clipped initial speech regressions fixed and verified; no tests disabled or acceptance thresholds weakened.
Next action: securely configure a replacement VASA_OPENAI_API_KEY, save/publish, then verify real OpenAI behavior and proceed to the next permitted graph gate. No need to repeat the passed diagnostic media call. Do not claim Wave 5 live dialogue acceptance or unlock dependent behavioral completion from scripted results.

Real-call Gate 3: PASSED on the user's explicit report on 2026-10-08. Evolution
answered an actual inbound WhatsApp call; VASA received 98 live caller frames,
sent 20 diagnostic frames and the human caller heard three rising tones. This
is user-supplied real-world evidence, not a new cloud call. No dropped-frame,
latency trace, activated-license persistence or concurrency result is inferred.
The proven Evolution transport remains unchanged.

Wave 4 initial native accuracy: 6 errors / 77 reference words across three
independent pinned recordings, aggregate WER 7.79%, within the predefined 15%
threshold. Native CPU speech and scripted OpenAI/Anthropic SSE component checks
pass. Wave 5 reader, turn detection, per-call context, response chunking, pacing,
interruption generation guards and bounded cleanup are implemented. Tools fail
closed until Wave 6. Full persistence remains Wave 7; worker logs omit caller
identifiers, audio and transcripts. Live AI-call naturalness is unverified.

Earlier foundation/deployment evidence: 158 checks passed without skips; pinned
Evolution source tests/vet/build and healthy cloud startup passed. A separate
cloud deployment project passed migrations, HTTP readiness/Manager and database
identity persistence with volumes retained. Cloud-local vendor license was
inactive; this is distinct from the externally passed real call. Rootless VPS
runtime and active-license survival remain unrun. See TEST_RESULTS.md.

Final combined verification: 318 passed, zero failures/errors/skips; current JUnit inspected at reports/voice-wave-final.xml. Ruff lint/format and strict mypy pass. Actual WebRTC -> streaming Sherpa STT -> scripted LLM -> local Sherpa TTS -> unchanged Evolution WebSocket adapter passed with first-word accuracy retained. OpenAI/Anthropic loopback SSE components and two scripted dialogue evals passed. Worker preflight/ownership/admission/cleanup checks passed. Live OpenAI remains unrun.

Reusable setup was repeated twice with verified speech assets and dedicated
healthy PostgreSQL/Redis; migrations report no drift. Production voice image
built and native CPU TTS generated 29 frames as UID 1000 with read-only root.
Final image rebuilt after all fixes; packaged worker help and imports verified. Startup instructions and secure
provider requirements are saved in the environment draft; saving does not
publish or inject a key. Existing Ponytail preference and unrestricted network
are retained. Separate fresh-task restoration is not verified.

Work continues on build/vasa-foundation and draft PR #1:
https://github.com/ralphdeeney/VASA/pull/1. No browser/WhatsApp E2E framework is
built. All live-provider, real-call and component evidence remain distinct.
