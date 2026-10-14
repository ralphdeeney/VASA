"""Optional Deepgram Aura 2 raw-PCM streaming adapter.

https://developers.deepgram.com/reference/text-to-speech/speak-request
https://developers.deepgram.com/docs/tts-media-output-settings
Deepgram linear16 is signed little-endian PCM; container=none removes WAV headers.
The requested 16kHz mono format needs framing only, not resampling.
"""

import re
from typing import Any

import httpx

from vasa.speech.speechify import Observer, SpeechifyTTS


class DeepgramTTS(SpeechifyTTS):
    """Reuse bounded PCM framing, pooled HTTP ownership and cancellation cleanup."""

    _default_origin = "https://api.deepgram.com"
    _path = "/v1/speak"
    _provider_label = "Deepgram"

    def __init__(
        self,
        api_key: str,
        *,
        model: str = "aura-2-thalia-en",
        client: httpx.AsyncClient | None = None,
        observer: Observer | None = None,
        base_url: str = "https://api.deepgram.com",
        request_timeout: float = 60.0,
        max_audio_seconds: int = 120,
        max_streams: int = 10,
    ) -> None:
        if not re.fullmatch(r"aura-2-[a-z]{1,40}-en", model):
            raise ValueError("Invalid Deepgram English Aura 2 model")
        self._model = model
        super().__init__(
            api_key,
            client=client,
            observer=observer,
            base_url=base_url,
            request_timeout=request_timeout,
            max_audio_seconds=max_audio_seconds,
            max_streams=max_streams,
        )

    def _build_request(self, text: str, trace: Any) -> httpx.Request:
        return self._client.build_request(
            "POST",
            self._url,
            headers={
                "Authorization": f"Token {self._key}",
                "Accept": "audio/l16",
                "Accept-Encoding": "identity",
            },
            params={
                "model": self._model,
                "encoding": "linear16",
                "sample_rate": "16000",
                "container": "none",
            },
            json={"text": text},
            extensions={"trace": trace},
        )

    def _response_metadata(self, response: httpx.Response, metrics: dict[str, Any]) -> None:
        super()._response_metadata(response, metrics)
        metrics["requested_model"] = self._model
        for field, header in (
            ("response_model", "dg-model-name"),
            ("response_model_uuid", "dg-model-uuid"),
            ("request_id", "dg-request-id"),
        ):
            raw = response.headers.get(header, "")
            metrics[field] = (
                raw if re.fullmatch(r"[A-Za-z0-9_-]{1,128}", raw) and self._key not in raw else None
            )
        if response.status_code == 200 and response.headers.get("dg-model-name") is not None:
            if metrics["response_model"] != self._model:
                raise RuntimeError("Deepgram response model mismatch")
