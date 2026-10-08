from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID


class CallState(StrEnum):
    RINGING = "RINGING"
    ANSWERING = "ANSWERING"
    CONNECTED = "CONNECTED"
    LISTENING = "LISTENING"
    TRANSCRIBING = "TRANSCRIBING"
    THINKING = "THINKING"
    TOOL_EXECUTION = "TOOL_EXECUTION"
    SPEAKING = "SPEAKING"
    ENDING = "ENDING"
    ENDED = "ENDED"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class TenantContext:
    tenant_id: UUID
    user_id: UUID


@dataclass(frozen=True, slots=True)
class AudioFrame:
    """Normalized little-endian signed PCM16. Adapter owns wire-format conversion."""

    pcm: bytes
    sample_rate: int
    sequence: int
    timestamp_ns: int
    channels: int = 1

    def __post_init__(self) -> None:
        if self.channels != 1 or self.sample_rate not in {8000, 16000, 24000, 48000}:
            raise ValueError("unsupported normalized audio format")
        if not self.pcm or len(self.pcm) % 2 or len(self.pcm) > self.sample_rate * 2:
            raise ValueError("audio frame must contain at most one second of PCM16")
        if self.sequence < 0 or self.timestamp_ns < 0:
            raise ValueError("negative audio metadata")


@dataclass(frozen=True, slots=True)
class CallSession:
    id: UUID
    tenant_id: UUID
    instance_id: str
    external_call_id: str
    state: CallState = CallState.RINGING
    metadata: dict[str, str] = field(default_factory=dict)
