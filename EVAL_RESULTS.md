# Eval results

2026-10-08: 3 tenant-isolation evals passed. Two cover explicit tenant SQL agents and Redis call-state reads/deletes; one exercises authenticated foreign-instance API access denied with HTTP 404 before any upstream operation, with own-tenant positive controls. Real PostgreSQL/Redis and server-derived session contexts are used.

Conversation, tool, knowledge, summary and latency evals have not yet run. Planned golden cases are not passing results. Local WebSocket and diagnostic probe tests are component checks, not real-call evidence.

2026-10-08 real-media acceptance: PASSED on user-supplied human evidence.
Actual inbound call answered, 98 live inbound frames, 20 diagnostic outbound
frames, three rising tones heard by the caller. Wave 4 speech/turn/runtime
evals are now enabled; recognition accuracy, natural dialogue, interruption
quality and latency are not established by that transport check.

## Wave 4 native recognition — PASSED

Predefined aggregate WER <=15% over at least three independent pinned English
recordings. Actual native STT produced 6 errors /77 reference words =7.79%.
Five repetitions reproduced 30 errors/385 words; the three unique recordings
remain the independent dataset, not 15 independent recordings. Per-fixture
errors are 1/18, 2/48 and 3/11; the short 8 kHz fixture's 27.27% individual WER
shows the limitation hidden by aggregate accuracy. No speech was authored by
the TTS under test for this acceptance dataset.

Native TTS produced nonempty speech and a supplemental STT roundtrip recovered
appointment/tomorrow. That roundtrip is supplemental, not recognition ground
truth. Native WebRTC silence/independent-speech checks and controlled segment
logic passed. All model checksums remain authoritative and unchanged.

Source/measurements: docs/evidence/speech-benchmark.json. Live OpenAI behavior,
phone conversation naturalness and audible interruption recovery are UNRUN,
pending a secure replacement key and actual dialogue acceptance.

## Wave 5 scripted behavioral component evals

Two executed scripted evals cover trusted prompt/greeting forwarding, multi-turn
context snapshots and interruption recovery with future old audio discarded.
Assertions use scripted provider results; they prove orchestration and isolation,
not OpenAI factual accuracy, instruction following or dialogue quality. Golden
turn_cases.json is explicitly marked planned; those entries are not automatically
counted as executed evals. Live tool/knowledge/summary evals remain later waves.

Native capture quality regression: original 120 ms runtime pre-roll clipped quiet
opening speech (3/18 errors); measured earlier capture preserved initial words
(1/18 errors), motivating bounded 480 ms runtime pre-roll. Native classifier
segment policy and recognition threshold are unchanged. This is public fixture
speech evidence, not captured customer audio or phone playback evidence.

Final combined 318 passing checks include the strict native VAD/STT/TTS pipeline
through the unchanged Evolution adapter and two scripted conversation evals.
Native fixture first words survive the 480 ms runtime pre-roll fix. Three existing
tenant-isolation evals continue to pass. Provider/network tests exercise real
loopback SSE, not a live OpenAI account. No new human call acceptance is claimed.
