# Safe LLM SSE shape inspection

The operator confirmed HTTP 200 for model listing, chat completion and streaming
with cx/gpt-5.6-sol through the configured 9Router gateway. This does not yet
identify the stream shape rejected by VASA. No actual gateway SSE structure has
been captured here. Production parser validation is deliberately unchanged.

Deploy this tooling through GitHub Actions with smoke disabled, then an operator
already on the VPS can run one bounded request:

```bash
cd /opt/vasa
docker compose --project-name vasa-vps --env-file .local/vps.env \
  -f deploy/compose.yaml --profile voice exec -T vasa \
  python scripts/diagnose_llm_sse.py
```

Deployment remains Actions-only; Codex must not SSH directly. Do not put this
command in a real call. It uses the private configured key, base URL and model;
no command-line secrets. Request settings match the existing smoke request,
including max_completion_tokens=32. It makes exactly one POST, no retries and
no tool/business actions. Deadline, bytes, event/line limits and cleanup are
bounded. It does not save raw input, output or WAV files. HTTP logging is disabled.

Output is JSON structural metadata only. Known key names, event names, finish
reasons, media types and encodings are explicitly allowlisted. Unknown names or
values become `other`, null or an unknown-key count. Index values are printed
only for integers/string digits 0–15; no arbitrary strings are echoed. Content,
reasoning and tool argument values are never printed. Header parameters are
reported only as a presence boolean. Stderr exceptions/tracebacks are suppressed.
Exit zero means the structural probe saw DONE, not that OpenAIProvider accepted
the stream. Nonzero can still produce useful structural output.

Compare the sanitized output with current parser rules:

| Structure | Current behavior |
| --- | --- |
| Content-Type text/event-stream with parameters | Accepted |
| Non-identity Content-Encoding | Rejected before reading raw SSE |
| Extra top-level or reasoning delta fields | Ignored, never emitted as text |
| Empty choices with usage present | Accepted, including after finish |
| Empty choices without usage | Rejected |
| Missing/string/bool/nonzero choice.index | Rejected; integer zero required |
| delta absent/null/non-object | Rejected |
| role delta assistant | Accepted; other role rejected |
| finish_reason stop | Requires subsequent DONE |
| finish_reason length | output_limit; 32 completion tokens may be insufficient |
| finish_reason tool_calls | Requires approved tools and accumulated calls |
| Duplicate/post-finish choice events | Rejected |
| DONE before finish or EOF without DONE | Rejected |

The model's reasoning may consume a small completion budget, but that is only a
hypothesis until the diagnostic shows finish_reason=length. Likewise missing or
string indices are hypotheses, not confirmed gateway behavior. Synthetic tests
cover these rejection cases; they are not labeled as captured 9Router fixtures.
Provide only the sanitized JSON output for the next compatibility change. Once
the actual mismatch is established, add its regression fixture and make the
smallest supported change; do not broadly coerce indices or accept truncated
streams. Never share raw SSE, response bodies or private runtime files.
