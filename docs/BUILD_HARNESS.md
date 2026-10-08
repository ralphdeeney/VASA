# VASA V1 — AUTONOMOUS BUILD HARNESS

## 1. Mission

Build **VASA V1** as a minimal multi-tenant WhatsApp AI voice-agent runtime.

The objective is:

Customer calls a connected WhatsApp number → VASA answers → understands speech → reasons with OpenAI or Claude → optionally executes tools → speaks back → supports interruption → stores the conversation.

VASA V1 must also provide a minimal client dashboard where a client can:

1. log in;
2. connect WhatsApp by scanning an Evolution QR code;
3. configure their AI agent;
4. add lightweight business knowledge;
5. view previous calls and transcripts.

Do not expand V1 beyond this scope.

---

# 2. Core V1 architecture

Use:

- Python 3.12+
- asyncio
- FastAPI
- WebSockets
- PostgreSQL
- Redis
- pgvector
- Evolution Go Calls
- sherpa-onnx or equivalent CPU-native speech components
- OpenAI API
- Anthropic API
- n8n for external business integrations

No GPU requirement.

Heavy local processing should use native C/C++/Rust/ONNX-backed libraries where practical.

Python is the orchestration layer.

---

# 3. Runtime architecture

The real-time call path is:

WhatsApp
→ Evolution Go Calls
→ VASA Media Gateway
→ VAD
→ Streaming STT
→ VASA Agent Runtime
→ OpenAI/Claude
→ optional Tool Gateway
→ local CPU TTS
→ VASA Media Gateway
→ Evolution
→ WhatsApp

n8n must NOT sit in the real-time audio path.

n8n is used only when the AI needs to perform a business action.

Example:

AI
→ check_availability()
→ VASA Tool Gateway
→ n8n
→ Calendar
→ result
→ AI
→ spoken response.

---

# 4. Explicit V1 non-goals

Do NOT build:

- outbound WhatsApp calling;
- GPU inference;
- billing;
- subscriptions;
- advanced analytics;
- mobile apps;
- regional infrastructure;
- SIP;
- WebRTC;
- CRM-specific logic inside VASA Core;
- email marketing;
- marketplace features;
- omnichannel support;
- complex organization hierarchies;
- customer-selectable LLM providers;
- local LLM hosting platform;
- advanced enterprise administration.

---

# 5. VPS execution environment

The autonomous coding harness will work directly on a VPS.

Everything must remain inside an isolated VASA sandbox.

Example:

/opt/vasa/

The agent must not modify unrelated host services.

Prefer a dedicated operating-system user:

vasa-builder

Do not run normal build work as root.

Do not assume unrestricted Docker socket access.

Prefer rootless Docker or a tightly scoped VASA deployment mechanism.

Secrets must remain outside Git.

Example:

/opt/vasa/secrets/.env

The application references environment variables only.

Never print, commit, expose, or copy real secrets into documentation.

---

# 6. Persistent project state

Maintain these files continuously:

AGENTS.md  
ARCHITECTURE.md  
BUILD_PLAN.md  
CURRENT_STATE.md  
DECISIONS.md  
TEST_RESULTS.md  
EVAL_RESULTS.md  
PERFORMANCE.md

CURRENT_STATE.md must always contain:

- current wave;
- current slice;
- completed slices;
- active agents;
- blockers;
- failed checks;
- next action.

Example:

Current wave: 2  
Current slice: Media Gateway

Completed:
- Foundation
- Evolution adapter
- WhatsApp instance manager
- Incoming call controller
- Bidirectional media proof

Active:
- Voice Agent: audio normalization
- Eval Agent: media test fixtures

Blocked:
- none

Next:
- VAD integration

If the coding session restarts, the orchestrator must read these files and continue from the recorded state.

---

# 7. Multi-agent build model

Use one primary orchestrator.

Recommended agents:

## Orchestrator

Owns:

- architecture;
- task graph;
- dependency management;
- work assignment;
- interface locking;
- integration;
- progression decisions;
- final verification.

The orchestrator should not casually rewrite work owned by specialist agents.

---

## Voice / Media Agent

Owns:

- Evolution calls;
- WebSocket media;
- codecs;
- audio normalization;
- jitter buffering;
- VAD;
- STT;
- TTS;
- barge-in;
- latency instrumentation.

---

## Backend / Runtime Agent

Owns:

- API;
- PostgreSQL;
- Redis;
- tenants;
- agent configuration;
- call persistence;
- conversation state;
- LLM adapters;
- Tool Gateway.

---

## Dashboard Agent

Owns:

- authentication UI;
- WhatsApp connection screen;
- QR display;
- agent quick setup;
- knowledge setup;
- calls/transcripts UI.

---

## Test / Eval Agent

Owns:

- unit tests;
- integration/component tests;
- mocks;
- fixtures;
- golden eval dataset;
- behavioral evals;
- tenant-isolation evals;
- performance regression checks.

---

# 8. Parallelism rules

Parallel execution is allowed only when modules are independent.

Do NOT allow multiple agents to modify the same unstable interfaces simultaneously.

Before parallel work begins, the orchestrator must freeze shared contracts.

Examples:

CallSession  
EvolutionClient  
STTProvider  
TTSProvider  
LLMProvider  
Tool  
TenantContext  
AudioFrame

Once an interface is frozen for a build wave, specialist agents must implement against it.

Interface changes require orchestrator approval.

---

# 9. Build graph

Use dependency-aware build waves.

## WAVE 0 — Repository and governance

Orchestrator only.

Create:

- repository structure;
- environment configuration;
- architecture rules;
- coding conventions;
- test configuration;
- eval framework;
- logging;
- health checks;
- CI/local verification commands.

Then freeze initial interfaces.

↓

## WAVE 1 — Foundation

Parallel:

Backend Agent:
- PostgreSQL
- Redis
- tenant foundation
- configuration
- structured logging

Test Agent:
- test harness
- fixtures
- integration environment
- eval framework

↓

Verification Gate 1

All foundation checks must pass.

↓

## WAVE 2 — WhatsApp transport

Voice Agent:
- Evolution typed client
- instance management
- incoming call handling
- answer/reject/hangup
- media WebSocket

Backend Agent:
- tenant ↔ Evolution instance mapping
- call-session registry

Dashboard Agent:
- WhatsApp connect screen
- QR state UI

Test Agent:
- Evolution mocks
- instance lifecycle integration tests

↓

Verification Gate 2

↓

## WAVE 3 — Critical media proof

Mostly sequential.

This is the highest-risk milestone.

Implement:

WhatsApp call
→ Evolution
→ VASA
→ receive caller audio
→ return known prerecorded audio
→ caller hears response.

Do not build the AI voice pipeline until this works.

The harness may automate everything around this test, but two human actions are permitted:

HUMAN_GATE_WHATSAPP_PAIRING  
HUMAN_GATE_REAL_CALL

No automated E2E test suite is required.

The real WhatsApp call is a manual acceptance check.

↓

Verification Gate 3

If bidirectional media fails:

STOP GRAPH PROGRESSION.

Diagnose and fix until proven.

↓

## WAVE 4 — Voice intelligence

Parallel after media proof.

Voice Agent:
- audio normalization
- VAD
- streaming STT
- CPU TTS
- cancellation
- barge-in

Backend Agent:
- OpenAI adapter
- Anthropic adapter
- conversation context
- model fallback rules

Test Agent:
- STT fixtures
- TTS fixtures
- VAD tests
- provider mocks
- latency instrumentation

↓

Verification Gate 4

↓

## WAVE 5 — Conversation runtime

Integrate:

VAD
→ STT
→ conversation state
→ LLM
→ TTS
→ media output.

Implement explicit call states:

RINGING  
ANSWERING  
CONNECTED  
LISTENING  
TRANSCRIBING  
THINKING  
TOOL_EXECUTION  
SPEAKING  
ENDING  
ENDED  
ERROR

Critical behavior:

If customer speech begins while VASA is speaking:

SPEAKING
→ detect customer speech
→ cancel TTS
→ clear queued output
→ LISTENING.

↓

Verification Gate 5

↓

## WAVE 6 — Tools

Backend Agent:

Build generic Tool Gateway.

Initial tools:

- knowledge_search
- custom_webhook
- end_call

n8n-backed tools must be generic.

VASA Core must not contain HubSpot-specific, Salesforce-specific, calendar-specific, or other client-specific code.

Validate:

- input schema;
- tenant ownership;
- permissions;
- timeout;
- response schema.

Log every tool execution.

↓

Test/Eval Agent simultaneously builds tool-call evals.

↓

Verification Gate 6

↓

## WAVE 7 — Persistence

Backend Agent:

Create at minimum:

tenants  
users  
agents  
whatsapp_instances  
calls  
call_messages  
tool_calls  
knowledge_sources  
knowledge_chunks

Every tenant-owned record must carry tenant_id.

Store call messages individually.

Roles:

customer  
agent  
tool  
system

Do not record audio by default.

↓

Verification Gate 7

↓

## WAVE 8 — Knowledge

Backend Agent:

Implement lightweight tenant-isolated RAG.

Input:

- business information;
- FAQ;
- TXT;
- PDF;
- DOCX.

Pipeline:

document
→ extract
→ chunk
→ local CPU embeddings
→ pgvector.

Runtime:

question
→ tenant-filtered vector search
→ top relevant chunks
→ model context.

Cross-tenant retrieval must be impossible.

↓

Dashboard Agent simultaneously builds Knowledge UI.

↓

Verification Gate 8

↓

## WAVE 9 — Minimal dashboard

Dashboard must contain only:

### WhatsApp

- Connect WhatsApp
- QR code
- connected number
- connection state
- disconnect

### Agent Quick Setup

- business name
- agent name
- greeting
- business description
- instructions
- language
- voice

### Knowledge

- business information
- FAQs
- file upload

### Calls

- caller
- start time
- duration
- transcript
- summary
- outcome

Do not add unnecessary SaaS features.

↓

Verification Gate 9

↓

## WAVE 10 — Integration and stabilization

Orchestrator integrates all modules.

Test Agent runs complete test/eval suite.

Voice Agent runs performance profiling.

Backend Agent resolves integration faults.

Dashboard Agent resolves UI/API mismatches.

Repeat until all completion criteria pass.

---

# 10. Runtime conversation graph

Use this call graph:

INCOMING_CALL
↓
Resolve Evolution Instance
↓
Resolve Tenant
↓
Load Agent Configuration
↓
Create Call Session
↓
Answer Call
↓
Open Media Stream
↓
LISTENING
↓
Receive Audio
↓
VAD
↓
STT
↓
Final User Turn
↓
Load Conversation Context
↓
LLM
↓

Branch:

TEXT RESPONSE
→ TTS
→ stream audio
→ LISTENING

or:

TOOL CALL
→ validate
→ Tool Gateway
→ execute tool
→ receive result
→ LLM continuation
→ TTS
→ stream audio
→ LISTENING

Repeat until:

CUSTOMER HANGUP

or:

END_CALL TOOL

↓

Finalize transcript
↓
Generate summary
↓
Generate outcome
↓
Persist
↓
Release WebSocket
↓
Release memory/session resources
↓
ENDED

---

# 11. Autonomous engineering loop

Every agent must use:

DISCOVER
↓
PLAN CURRENT TASK
↓
IMPLEMENT SMALLEST CHANGE
↓
UNIT TEST
↓
INTEGRATION / COMPONENT TEST
↓
STATIC CHECKS
↓
RELEVANT EVALS
↓
PERFORMANCE CHECK IF APPLICABLE
↓
VERIFY
↓

If FAIL:

inspect failure
→ determine root cause
→ patch
→ rerun relevant checks
→ repeat

If PASS:

document
→ commit
→ update CURRENT_STATE.md
→ report result to orchestrator.

The orchestrator then decides whether dependent nodes may begin.

---

# 12. No automated E2E suite

Do NOT spend V1 development time building a large browser/WhatsApp E2E automation framework.

Use:

- unit tests;
- integration tests;
- component tests;
- contract tests;
- mocks;
- evals;
- manual real-WhatsApp acceptance tests.

Real WhatsApp validation is performed through explicit human gates.

---

# 13. Evals

Passing tests alone does not mean a behavioral slice is complete.

Any code affecting agent behavior must pass relevant evals.

Create:

/evals
  /conversation
  /tool_calls
  /knowledge
  /tenant_isolation
  /summaries
  /latency
  golden_cases.json

Evaluate at minimum:

### Conversation

- follows agent instructions;
- follows greeting;
- maintains context;
- asks for missing information;
- does not hallucinate business information;
- responds appropriately to interruptions.

### Knowledge

- retrieves relevant business knowledge;
- does not fabricate unsupported answers;
- never retrieves another tenant's knowledge.

### Tool calling

- selects correct tool;
- uses correct schema;
- does not trigger tools unnecessarily;
- waits for tool results where required;
- handles failures gracefully.

### Tenant isolation

Attempt deliberately to:

- access another tenant's agent;
- access another tenant's transcript;
- retrieve another tenant's knowledge;
- invoke another tenant's tool configuration.

All must fail.

### Summaries

Call summary must accurately reflect:

- customer need;
- actions taken;
- appointment/order information;
- unresolved issues;
- final outcome.

### Latency

Measure:

- VAD end-of-turn delay;
- STT finalization;
- LLM time-to-first-token;
- TTS time-to-first-audio;
- end-of-user-speech → first VASA audio;
- dropped audio frames;
- queue sizes.

Track P50 and P95.

Do not fake benchmark results.

---

# 14. Regression policy

A slice may not progress if:

- tests fail;
- type/static checks fail;
- relevant evals regress materially;
- tenant-isolation checks fail;
- critical latency regression occurs;
- architecture boundaries are violated.

A new implementation must not silently reduce previously achieved eval performance.

---

# 15. Parallel agent integration policy

Each specialist agent owns designated directories/files during a build wave.

Avoid simultaneous edits to shared files.

The orchestrator handles:

- shared interfaces;
- merges;
- migrations affecting multiple modules;
- architecture changes.

Before merging parallel work:

1. rebase/update from shared branch;
2. run module tests;
3. run integration tests;
4. run affected evals;
5. inspect interface compatibility;
6. merge;
7. rerun combined verification.

Do not resolve merge conflicts by blindly choosing one version.

---

# 16. Human gates

Only require human interaction when unavoidable.

## HUMAN_GATE_WHATSAPP_PAIRING

When QR is ready:

- expose QR through dashboard;
- clearly report that pairing is required;
- wait for WhatsApp instance connection state.

Once connection is detected, continue automatically.

## HUMAN_GATE_REAL_CALL

When bidirectional media testing is ready:

- expose test number/session status;
- request one real inbound WhatsApp call.

During that call automatically record:

- call state transitions;
- media reception;
- media transmission;
- timestamps;
- dropped frames;
- transport latency.

After the call ends, automatically analyze logs and continue fixing if necessary.

Do not require the human to manually inspect server logs.

---

# 17. Failure handling

Never blindly retry indefinitely.

For each operation define:

- timeout;
- maximum retries;
- backoff;
- failure state;
- cleanup behavior.

A failed call must not leave:

- orphan WebSockets;
- zombie workers;
- Redis call-state leaks;
- incomplete database transactions;
- stuck TTS tasks;
- audio queues consuming memory.

---

# 18. Performance principles

Do not optimize blindly.

Measure first.

Critical real-time path must use:

- async I/O;
- bounded queues;
- backpressure;
- streaming;
- reusable connections;
- native accelerated libraries where useful.

Do not:

- repeatedly initialize STT/TTS models per call;
- block event loop with CPU-heavy Python;
- send audio through n8n;
- query PostgreSQL for every audio packet;
- call LLM for deterministic system operations.

---

# 19. Initial concurrency target

Optimize V1 for approximately:

10 simultaneous active calls

on a CPU-only server.

Do not promise the concurrency target until measured under load.

Use shared service/worker pools rather than spawning expensive model runtimes per call where practical.

---

# 20. Security requirements

Never trust model output.

All tool calls require validation.

Never expose:

- Evolution global key;
- OpenAI key;
- Anthropic key;
- database credentials;
- n8n secrets

to browser clients.

Sanitize uploaded files.

Enforce tenant boundaries at repository/query level.

Use authenticated dashboard sessions.

Rate-limit public APIs.

Do not log secrets.

---

# 21. Definition of VASA V1 Done

VASA V1 is done when a new client can:

1. log into VASA;
2. create/configure an agent;
3. click Connect WhatsApp;
4. scan a QR code;
5. see WhatsApp connected;
6. add basic business knowledge;
7. receive a real inbound WhatsApp voice call;
8. have VASA answer;
9. conduct natural bidirectional conversation;
10. interrupt VASA while it speaks;
11. have VASA recover naturally;
12. ask a knowledge-based question;
13. trigger an n8n-backed tool;
14. receive a spoken response based on the tool result;
15. end the call;
16. see the call transcript;
17. see a correct call summary and outcome.

The system must then successfully handle repeated calls without:

- leaking tenant data;
- leaking call state;
- leaving orphan processes;
- mixing conversations;
- requiring a server restart.

---

# 22. Autonomous completion rule

Continue working through the graph until:

- all required slices are implemented;
- all relevant tests pass;
- all required evals pass;
- architecture checks pass;
- performance results are documented;
- only explicitly defined human gates remain.

Do not stop merely because one implementation attempt fails.

Diagnose, patch, verify and continue.

Do not redesign stable working components without evidence that redesign is necessary.

Do not expand V1 scope.

Prioritize:

working voice transport
→ reliable conversation
→ safe tools
→ tenant isolation
→ persistence
→ minimal dashboard
→ knowledge
→ stabilization.

The highest priority is a reliable real-time WhatsApp AI voice conversation.