# Source and dependency license findings

Official Kokoro code and both pinned model cards declare Apache 2.0. The code
license text is retained as `official-code-LICENSE`; both upstream model cards
are retained beside the measurements. These cards also document training-data
provenance and limitations. Voice weights are pinned separately in
`artifacts.json`; model and voice hashes are checked before benchmark startup.

The isolated runtime adds the following components. These findings come from
installed package metadata, retained notices and upstream source, not an
assumption that a model license covers all runtime dependencies.

| Dependency | Version tested | License finding |
| --- | --- | --- |
| Kokoro official source | 0.9.4, immutable Git commit | Apache 2.0 |
| Misaki | 0.9.4 | Apache 2.0 |
| Torch CPU | 2.6.0+cpu | BSD 3-Clause; bundled third-party notices also apply |
| Transformers | 4.51.3 | Apache 2.0 |
| spaCy | 3.8.16 | MIT |
| en_core_web_sm | 3.8.0 | MIT, pinned model wheel |
| phonemizer-fork | 3.3.2 | GPL version 3 text in installed metadata |
| espeakng-loader | 0.2.4 | MIT loader; bundled eSpeak NG library/data has separate GPL terms |
| Sherpa ONNX/core | 1.13.8 | Apache 2.0; phonemizer and bundled notices remain separate |
| NumPy / SciPy | 2.5.3 / 1.18.1 | BSD-family project licenses and bundled component notices |

The MIT loader license is verified at
[espeakng-loader commit 0ddc87ad](https://github.com/thewh1teagle/espeakng-loader/blob/0ddc87adf77e5850d7eeb542ac8a87d421b64daa/LICENSE).
The bundled eSpeak NG library is not made MIT by its loader; see the
[eSpeak NG COPYING file](https://github.com/espeak-ng/espeak-ng/blob/master/COPYING).
Redistribution of this runtime must retain applicable notices and satisfy the
separate copyleft components. No production distribution is made by this study.

`dependency-licenses.json` records exact dependency versions, available license
metadata, direct-source provenance and SHA256 hashes of installed license
notices. `requirements.lock.txt` pins the complete isolated environment. The
existing sherpa model/data license findings are retained in the parent
`LICENSES.md`: Kokoro Apache 2.0 and Piper LibriTTS-R's CC BY 4.0 dataset
attribution, with existing phonemizer notices. This evaluation changes no
production dependency declaration or container image.
