import json

import pytest

from vasa.runtime_finalization import transcript_segments


@pytest.mark.parametrize(
    "content",
    [
        "x" + " " * 32766 + "y",
        "\n" * 16000 + "a" * 16000,
        '\\"' * 10000,
        "é" * 32768,
        "\t\r" * 10000,
    ],
)
def test_oversized_segments_are_lossless_and_fit_storage_bound(content: str) -> None:
    encoded = transcript_segments(content)
    assert all(len(part) <= 16384 and part.strip() for part in encoded)
    assert "".join(json.loads(part)["content"] for part in encoded) == content


def test_short_content_stays_unmodified_and_overlimit_rejected() -> None:
    assert transcript_segments("short") == ["short"]
    with pytest.raises(ValueError):
        transcript_segments("x" * 32769)
