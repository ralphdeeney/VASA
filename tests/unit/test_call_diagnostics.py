import subprocess
import sys

from scripts.sanitize_call_diagnostics import classify

SECRET = "private-caller-relay-auth-token"


def test_observed_transport_sequence_only_fixed_markers():
    raw = [
        "CallOffer " + SECRET,
        "POST /call/answer 200 " + SECRET,
        'WARN Unhandled event *events.CallTransport transport-message-type="1" ' + SECRET,
        'WARN Unhandled event *events.CallTransport transport-message-type="3" ' + SECRET,
        'WARN Unhandled event *events.CallTransport transport-message-type="3" ' + SECRET,
        "Got call terminate " + SECRET,
        "voice | CALL_LIFECYCLE=remote_terminate",
        "voice | CALL_MEDIA=upstream_stop",
    ]
    output = [marker for line in raw for marker in classify(line)]
    assert output == [
        "CALL_TRANSPORT=type_1",
        "CALL_TRANSPORT=type_3",
        "CALL_TRANSPORT=type_3",
        "CALL_UPSTREAM=terminate_observed",
        "CALL_LIFECYCLE=remote_terminate",
        "CALL_MEDIA=upstream_stop",
    ]
    assert SECRET not in str(output)


def test_unknown_transport_and_malicious_marker_suffix_are_not_echoed():
    assert classify(
        'Unhandled event *events.CallTransport transport-message-type="' + SECRET + '"'
    ) == ["CALL_TRANSPORT=other"]
    assert classify("CALL_LIFECYCLE=local_hangup_failed" + SECRET) == []


def test_filter_drops_oversized_input_and_never_prints_raw_stderr():
    result = subprocess.run(
        [sys.executable, "scripts/sanitize_call_diagnostics.py"],
        input=SECRET + "x" * 70000 + "\nCALL_MEDIA=receive_recovered\n",
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0 and result.stdout == "CALL_MEDIA=receive_recovered\n"
    assert not result.stderr
