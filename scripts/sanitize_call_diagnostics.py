"""Pipe VPS Compose logs here; never prints raw input or captured remote values."""

import re
import sys

MARKERS = frozenset(
    {
        "CALL_MEDIA=upstream_stop",
        "CALL_MEDIA=receive_gap",
        "CALL_MEDIA=receive_recovered",
        "CALL_MEDIA=read_timeout",
        "CALL_MEDIA=read_closed",
        "CALL_LIFECYCLE=remote_terminate",
        "CALL_LIFECYCLE=local_hangup",
        "CALL_LIFECYCLE=local_hangup_failed",
    }
)


def classify(line: str) -> list[str]:
    markers = [
        marker
        for marker in sorted(MARKERS)
        if re.search(r"(?:^|\s)" + re.escape(marker) + r"(?:\s|$)", line)
    ]
    if "Unhandled event *events.CallTransport" in line:
        kind = re.search(r'transport-message-type="([13])"', line)
        markers.append("CALL_TRANSPORT=type_" + kind[1] if kind else "CALL_TRANSPORT=other")
    if "Got call terminate" in line:
        markers.append("CALL_UPSTREAM=terminate_observed")
    return markers


def main() -> int:
    total = 0
    oversized = False
    while raw := sys.stdin.buffer.readline(65537):
        total += len(raw)
        if total > 8 * 1024 * 1024:
            print("CALL_DIAGNOSTICS=limit_reached")
            return 1
        skip = oversized or len(raw) > 65536
        oversized = not raw.endswith(b"\n")
        if skip:
            continue
        for marker in classify(raw.decode("utf-8", errors="replace")):
            print(marker, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
