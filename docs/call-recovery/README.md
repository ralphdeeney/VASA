# Live call investigation

Read-only Actions [39121807464](https://github.com/ralphdeeney/VASA/actions/runs/39121807464)
inspected bounded recent logs. The content-free evidence is in
[2026-10-18-readonly.json](2026-10-18-readonly.json).

The greeting/audio output works in that observed call. It is not evidence of a
completed STT → LLM → TTS caller turn. Two transcription finalizations returned
from TRANSCRIBING to LISTENING without THINKING. In the current `respond()` code,
this is the empty-text path after the generation check. No provider exception or
recovery-grace expiry was observed; remote termination/upstream stop ended media.
Two receive gaps recovered. No transport type is interpreted as reconnect proof.

All pipeline components exist. The next evidence needed is why the received
utterances produce no usable recognition text, and whether repeated media loss
coincides with unintelligible input. Do not replace STT/TTS or change recovery
limits on this evidence alone. No caller audio was recorded or inspected.

After the guarded application release, the phone owner should make one authorized
call on a stable network, wait for the greeting, speak a clear complete English
sentence, and pause. Note approximate time and whether the AI responds/reconnects;
no telephone number or transcript needs to be shared. Do not use a customer call
for a deliberate network-switch experiment. This task has not placed a live call.

The existing Actions read-only `mode=check, recovery=evolution_check` now reports
only fixed media/lifecycle markers and numeric/allowlisted call-summary structure.
Codex triggers and monitors this check; no direct SSH is needed. A healthy idle
container check is not a successful conversation acceptance test. A real caller
turn and stable media must be demonstrated before claiming resolution.
