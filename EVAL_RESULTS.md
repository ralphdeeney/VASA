# Eval results

2026-10-15 existing evals pass within the791-check suite after safe startup
diagnostics. Local failure injection and stateful deployment fixtures prove
marker privacy, phase classification and pre-rollback target capture. They do
not identify the VPS b1cac8 failure; that requires a new manual target run.
Provider-aware speech validation and provider/deployment settings are unchanged.

2026-10-15 existing evals pass within the754-check suite after provider-aware
speech verification. Checksum fixtures and worker stubs establish asset selection
and no-download behavior; real SQL tests establish persisted voice isolation.
Existing native checks retain real pinned model verification. No live phone,
Deepgram/gateway quality or staging deployment success is inferred.

2026-10-15 existing evals pass within the692-check suite after OpenAI base URL
wiring. Synthetic gateway HTTP/SSE and worker fixtures verify request routing,
model/key handling and unchanged tool contracts; they do not establish real
gateway/model quality or live phone acceptance. Deepgram/media are unchanged.

2026-10-15 existing evals pass in the682-check suite after rollback-image recovery
and stage diagnostics. Local stateful Docker/Git stubs exercise the user-reported
missing-image condition, preserving running topology before target updates and
recovering with a verified previous-source image. Actual VPS bootstrap remains
the operator's next run through Actions; no live deployment success is inferred.

2026-10-15 all existing evals pass in the666-check suite after explicit staging
bootstrap support. Local controller evidence proves bounded service selection,
secret-safe refusals and rollback orchestration, not live VPS/phone acceptance.
User-reported healthy four-service topology and working Actions bridge motivate
the new mode; operator bootstrap/worker acceptance remains pending.

2026-10-15 existing evals remain passing in the615-check suite after adding the
Actions staging path. Deployment controller failures/rollback are locally stubbed
evidence, not VPS acceptance. No live connectivity, deployment, phone or TTS
benchmark is inferred. Only GitHub Actions may perform future VPS SSH.

2026-10-14 all existing evals pass within the599-check combined suite after
optional Aura TTS integration. No STT provider, default, tenant/runtime policy
or media wire contract changes. Mock/loopback evidence does not establish
Deepgram pronunciation, latency, quality or phone acceptance. Stop at secure
DEEPGRAM_API_KEY gate before live validation, as explicitly requested.

2026-10-12 Speechify optional integration preserves all existing evals within
the571-check full suite. Real TCP tests establish adapter reuse/cancellation,
and component fixtures establish runtime buffering/benchmark statistics only.
They are not Speechify latency, naturalness, actual VPS or phone evidence.
Actual Simba3.2 measurements and human preference remain pending due refused
SSH and absent key; no automatic provider promotion is made.

2026-10-09 Kitten Micro: all existing evals pass within the 539-check full suite,
including tenant isolation, knowledge, tools, summaries and interruption.
Matched cloud A/B records are under docs/tts-evaluation/kitten-micro/. Real STT
fixture WER remained 1/18 for all candidates; Kitten had no observed processing
deadline overruns in 21 complete fixture runs. One fixture and three repetitions
remain limited evidence. Actual VPS A/B/C and human naturalness are pending;
automated evidence does not promote a model or establish phone acceptance.

2026-10-09 integration: the pinned CPU embedding evaluator scored 19/20
independent paraphrase queries with the expected passage first (0.95), above
the declared 0.90 threshold. Tenant SQL isolation, identity filtering and
quota-race checks passed. These are local retrieval and policy evaluations;
they do not establish live model answer quality or a phone conversation.

2026-10-09 concrete tools: three deterministic policy checks are marked evals:
webhook ownership/action/URL and business-field injection denial before network,
current-call ownership/identifier injection denial before hangup, and knowledge
trusted-context forwarding/foreign-result rejection. They pass with positive
controls, using component handlers. Real PostgreSQL persistence isolation also
passes at repository and composite-FK boundaries. No live model tool selection,
actual n8n actions, retrieval accuracy or summary quality is evaluated here.

2026-10-09 independent tool gateway preparation: deterministic component
checks exercise tenant-bound registry lookups, server-grant denial before handler
execution, strict input/output schemas and failure cleanup. They do not evaluate
live model tool selection, n8n actions or knowledge retrieval. No new live
behavioral acceptance or graph gate is claimed; OpenAI setup is deferred by user.

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
