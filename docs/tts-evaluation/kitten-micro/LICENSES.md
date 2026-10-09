# Kitten Micro provenance research

Verified 2026-10-09 against official KittenML and k2-fsa sources. This is
**KittenML/kitten-tts-micro-0.8**, the 40-million-parameter lightweight model;
it is neither Kitten Nano nor KittenTTS 2.

## Exact artifacts

- Official HF revision: `1ccf72b2c2048fd17efac7de2fab32d10e225084`.
- Official Sherpa release asset: `kitten-micro-en-v0_8.tar.bz2`, asset ID
  `418191833`, 44,423,643 bytes, created 2026-05-12.
- Download URL: https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/kitten-micro-en-v0_8.tar.bz2
- Archive SHA256: `85faaea7511ca9d1d2f251fed0a4553bdf0d1ee046102fa60ddd8046c751f76f`.
  Downloaded bytes match GitHub's release asset digest.
- Prepared file hashes and upstream LFS hashes are recorded in
  `model-provenance.json`.
- eSpeak data tree: 355 files; canonical VASA tree SHA256
  `e9c56f8c7cc79f16b1a2dc482074ed777e5b881da2a215a6f99630284dc4b3b8`,
  exactly matching the existing verified speech phonemizer data.

The upstream ONNX SHA differs from the prepared model SHA because the official
Sherpa conversion adds ONNX metadata. Voices NPZ is converted to contiguous
FP32 voice rows in `voices.bin`; generated `tokens.txt` maps phoneme symbols.

## Precision and native support

Installed sherpa-onnx/core **1.13.8** exposes `OfflineTtsKittenModelConfig` with
`model`, `voices`, `tokens`, `data_dir`, and `length_scale`. Use `model.onnx`,
`voices.bin`, `tokens.txt`, `espeak-ng-data`, length_scale=1, provider=cpu,
num_threads=1, max_num_sentences=1. Output is natively mono 24 kHz; VASA must
resample to mono PCM16 16 kHz and emit 60 ms frames.

Direct ONNX protobuf inspection, without loading inference or installing extra
dependencies, found mixed/dynamically quantized weights and operations:
90 DynamicQuantizeLinear, 100 MatMulInteger, 74 ConvInteger, 6
DynamicQuantizeLSTM. Initializer dtype counts: FP32 514, FP16 17, INT64 247,
BOOL 1, INT32 1, UINT8 148, INT8 158. Therefore the official Micro model is
**not a FP32-only model** and should not be described as an all-INT8 graph.

Metadata: version=8, native sample_rate=24000, eight speakers, style_dim=400,256,
max_token_len=400, start_id=0, end_id=10, pad_id=0,
add_pad_after_end=1. All eight Micro speed priors are 1.0.

Voice IDs: 0 Jasper, 1 Bella, 2 Bruno, 3 Luna, 4 Hugo, 5 Rosie, 6 Leo, 7 Kiki.
Bella (sid=1) gives a female voice for comparison with Kokoro's Maple.

## Streaming and cancellation limitations

Sherpa v1.13.8 `offline-tts-kitten-impl.h` calls `Process(batch_x,...)` and only
then calls the audio callback with the complete generated acoustic batch.
The callback can return false to stop subsequent batches. This is real
segment callback delivery, **not incremental decoder streaming**. A running
native inference cannot be interrupted through that callback; consumer audio
forwarding can stop immediately, while model ownership must remain held until
native work drains. Natural clause/sentence chunking therefore matters for
first audio and native cancellation cleanup.

## Licenses

The pinned Micro HF model card expressly declares `license: apache-2.0`.
The Sherpa Micro archive also contains the Apache-2.0 license text. KittenML's
library code is Apache-2.0, but the current upstream README explicitly says
model licenses are independent. Its newer **KittenTTS 2** weights use the
Stellon Labs Community License; those weights are **not selected** here.

Sherpa-onnx and sherpa-onnx-core 1.13.8 are Apache-2.0. Their native ONNX Runtime
is MIT; bundled third-party notices still apply. eSpeak NG phonemizer data uses
GPL-3.0-or-later; retain the corresponding source/license obligations.
NumPy 2.5.3's package metadata declares BSD-3-Clause AND 0BSD AND MIT AND Zlib
AND CC0-1.0. SciPy 1.18.1 is BSD-3-Clause and bundles additional software notices
in its installed LICENSE.txt. Exact installed dependency license file hashes
are in provenance JSON. No Kitten Python package, Torch, phonemizer Python
package, or standalone ONNX Runtime Python dependency is required by this
Sherpa inference path.

## Authoritative sources

- https://huggingface.co/KittenML/kitten-tts-micro-0.8/blob/1ccf72b2c2048fd17efac7de2fab32d10e225084/README.md
- https://huggingface.co/KittenML/kitten-tts-micro-0.8/blob/1ccf72b2c2048fd17efac7de2fab32d10e225084/config.json
- https://github.com/k2-fsa/sherpa-onnx/tree/9db1af1871ed78cee9357c23898e5a7d8702d21a/scripts/kitten-tts/v0_8
- https://github.com/k2-fsa/sherpa-onnx/blob/v1.13.8/sherpa-onnx/csrc/offline-tts-kitten-impl.h
- https://github.com/KittenML/KittenTTS/blob/8ed679c08e0976b236bd5d0dc4ec9ddd98b0da98/README.md
- https://github.com/espeak-ng/espeak-ng/blob/master/COPYING

The accompanying benchmark evidence is separate from these license findings.
Actual VPS verification and human listening remain pending.

Retained notice text is in `licenses/`. Piper's selected LibriTTS-R medium
model card is retained there for CC BY 4.0 attribution; Kokoro INT8 retains
its Apache-2.0 notice. `uv.lock` fixes the existing complete application
dependency graph and artifact hashes; no new Python dependency is added.
ONNX Runtime's installed MIT license and third-party notices are retained
for reference. Its separate Python wheel version is not asserted to be the
embedded native Sherpa runtime version.
