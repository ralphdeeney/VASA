import re
from typing import Literal

from vasa.contracts.models import ConnectionStatus as ConnectionStatus
from vasa.contracts.models import IncomingCall as IncomingCall
from vasa.contracts.models import PairingQR as PairingQR

ErrorCode = Literal["license_required", "unavailable", "invalid_response"]
MAX_BODY_BYTES = 1_048_576


class EvolutionError(RuntimeError):
    """Only safe codes cross this boundary; upstream messages and URLs never do."""

    def __init__(self, code: ErrorCode) -> None:
        self.code = code
        super().__init__(code)


def validate_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise ValueError("invalid Evolution identifier")
    return value
