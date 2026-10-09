# Official Kokoro CPU and streaming investigation

The requested `hexgrad/Kokoro-TTS` repository returns HTTP 404. The official
implementation is [hexgrad/kokoro](https://github.com/hexgrad/kokoro), inspected
at commit `dfb907a02bba8152ca444717ca5d78747ccb4bec` (version 0.9.4).

`KPipeline.__call__` in
[pipeline.py](https://github.com/hexgrad/kokoro/blob/dfb907a02bba8152ca444717ca5d78747ccb4bec/kokoro/pipeline.py)
calls `KPipeline.infer` and then yields a `Result` containing completed audio.
[model.py](https://github.com/hexgrad/kokoro/blob/dfb907a02bba8152ca444717ca5d78747ccb4bec/kokoro/model.py)
predicts duration, constructs the alignment and computes the complete decoder
waveform before returning it to CPU memory. Thus the generator offers text-chunk
streaming; it does not release small acoustic frames while a segment is still
being synthesized. The default split pattern is newlines, and English token
splitting limits each chunk to approximately 510 phonemes. It does not
automatically emit every English sentence as an independent response segment.

An evaluation adapter splits at sentence punctuation, processes the next
sentence while the previous PCM could be playing, resamples every segment to
16 kHz PCM16 and emits VASA's existing 60 ms `AudioFrame` contract. Whole-response
and sentence policies use identical input text. This adapter is only in
`scripts/evaluate_tts_streaming.py`; production imports and configuration are
unchanged.

The historical sherpa FP32 archive is Kokoro **v1.1-zh**, speaker 0 (`af_maple`),
not official v1.0. The conversion's ordered voice table is documented in
[generate_voices_bin.py](https://github.com/k2-fsa/sherpa-onnx/blob/9db1af1871ed78cee9357c23898e5a7d8702d21a/scripts/kokoro/v1.1-zh/generate_voices_bin.py).
The fair engine comparison is official v1.1 Maple versus sherpa v1.1 Maple.
Official v1.0 Heart is an additional voice/model comparison, not evidence that
the engines use identical weights. Piper uses the same LibriTTS-R model and
speaker 0 as the earlier evaluation.

The v1.1 model card describes it as "not a strict upgrade" and says its new
English voices use synthetic training data. Official voice guidance warns that
very short prompts may sound weak and long prompts may rush. Sentence chunking
may improve first-audio timing while changing intonation, punctuation pauses or
voice consistency. Listening review is therefore required even when scheduling
and waveform boundary measurements pass. No subjective naturalness score is
invented by this harness.

Proposed conversational screening targets from source review: warm first
playable audio P95 at most 1 second; RTF below 1 under STT contention, with
0.5 preferred for headroom; no measured post-start playback starvation. These
are evaluation targets, not previously established product acceptance criteria.
They do not include VAD, LLM token latency, network delivery or caller playback.

Torch is forced onto CPU with two intra-op threads and one inter-op thread.
Models and voices are loaded before warm measurements. Each candidate/mode
runs in a fresh process. Both STT and TTS share CPU affinity 0 and 1. The host
cgroup has `cpu.max = 200000 100000`, a two-core quota. This is cloud resource
approximation; the production VPS CPU architecture and noisy-neighbor behavior
are not reproduced and the production VPS is not contacted or changed.

Contention uses actual VASA SherpaSTT, two native threads, and the pinned
LibriSpeech `0.wav` fixture delivered as paced 60 ms caller frames. It is one
continuous active STT stream, not a ten-call capacity test. Process CPU seconds
and peak RSS in contention include both models. Startup, warmup, teardown and
file writes are excluded from per-response timing. Model loading is reported
separately; OS file caches are not flushed. Three repeats per case/policy limit
the precision of percentile estimates.

Boundary metrics include normalized last-to-first sample jumps and 100 ms RMS
on either side. They identify discontinuities but cannot certify naturalness.
Arrival timestamps produce a deterministic playback-buffer simulation; WAVs
ending in `-playback.wav` insert measured starvation gaps after first audio.
They do not represent a physical sound-device or WhatsApp delivery recording.
