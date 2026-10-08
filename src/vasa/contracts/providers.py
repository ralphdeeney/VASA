from collections.abc import AsyncIterator
from typing import Any, Protocol

from vasa.contracts.models import AudioFrame, TenantContext


class EvolutionClient(Protocol):
    """Semantic boundary only: paths/auth/media are pending authoritative upstream verification."""

    async def connection_state(self, instance_id: str) -> str: ...
    async def answer(self, instance_id: str, call_id: str) -> None: ...
    async def reject(self, instance_id: str, call_id: str) -> None: ...
    async def hangup(self, instance_id: str, call_id: str) -> None: ...
    def media(self, instance_id: str, call_id: str) -> AsyncIterator[AudioFrame]: ...
    async def send_audio(self, instance_id: str, call_id: str, frame: AudioFrame) -> None: ...


class STTProvider(Protocol):
    def transcribe(self, frames: AsyncIterator[AudioFrame]) -> AsyncIterator[str]: ...


class TTSProvider(Protocol):
    def synthesize(self, text: str) -> AsyncIterator[AudioFrame]: ...


class LLMProvider(Protocol):
    def respond(
        self, context: TenantContext, messages: list[dict[str, str]]
    ) -> AsyncIterator[dict[str, Any]]: ...


class Tool(Protocol):
    name: str

    async def execute(
        self, context: TenantContext, arguments: dict[str, Any]
    ) -> dict[str, Any]: ...
