# TTS evaluation licensing record

This is a research benchmark record. It does not grant redistribution rights
for any model or voice data.

| Candidate/artifact | Evidence inspected | Recorded license/caveat |
| --- | --- | --- |
| Existing LJSpeech Medium | Existing `.local/speech/tts/manifest.json` and model card | Existing project verification and notices apply; unchanged by this evaluation. |
| Kokoro 82M FP32 / INT8 | Extracted archive `LICENSE`, `README.md`; upstream [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) | The extracted archive contains Apache License 2.0 text. Review the upstream model card and voice terms before redistribution. |
| Piper LibriTTS-R Medium | Extracted `MODEL_CARD` and `.onnx.json`; [Piper voices](https://huggingface.co/rhasspy/piper-voices), [LibriTTS-R](https://www.openslr.org/141/) | The model card identifies LibriTTS-R data as CC BY 4.0. The archive has no standalone license file, so the upstream voice repository and dataset terms must remain part of release review. |
| MeloTTS sherpa-onnx conversion | Extracted archive `LICENSE`, `README.md`; [MeloTTS](https://github.com/myshell-ai/MeloTTS) | The extracted license is MIT for the supplied conversion. The upstream model/dataset terms still require review. |
| sherpa-onnx runtime | Installed package metadata and project [license](https://github.com/k2-fsa/sherpa-onnx) | Apache License 2.0 project; the pinned dependency remains the existing `sherpa-onnx-core==1.13.8` / `sherpa-onnx` dependency set. |
| NumPy / SciPy measurement dependencies | Installed wheel metadata and bundled package notices | NumPy and SciPy retain their upstream BSD-family notices; SciPy distributions may include separately licensed OpenBLAS, Fortran runtime and related components. They are existing project dependencies and are not copied into production model assets. |

The official sherpa-onnx release URLs, observed SHA256 values and source links
are in [report.json](report.json). A changed archive fails the harness's pinned
hash check rather than being silently accepted.
