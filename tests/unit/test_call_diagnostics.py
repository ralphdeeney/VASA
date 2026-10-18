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


def test_actions_call_evidence_drops_content_and_allowlists_structure():
    import json

    from deploy.actions_evolution_pool import call_evidence_lines

    raw = "\n".join(
        [
            SECRET,
            "CALL_MEDIA=receive_gap_started " + SECRET,
            json.dumps(
                {
                    "session_id": SECRET,
                    "error": None,
                    "received_frames": 123,
                    "sent_frames": 60,
                    "completed_turns": 0,
                    "interruptions": 1,
                    "state_transitions": ["LISTENING", "TRANSCRIBING", SECRET],
                    "messages": [SECRET],
                    "caller": SECRET,
                }
            ),
            json.dumps({"session_id": SECRET, "error": SECRET, "received_frames": True}),
        ]
    )
    lines = call_evidence_lines(raw)
    assert "CALL_MEDIA=receive_gap_started" in lines
    assert "CALL_SUMMARY_RECEIVED_FRAMES=123" in lines
    assert "CALL_SUMMARY_COMPLETED_TURNS=0" in lines
    assert "CALL_SUMMARY_STATE=TRANSCRIBING" in lines
    assert "CALL_SUMMARY_ERROR=none" in lines and "CALL_SUMMARY_ERROR=other" in lines
    assert SECRET not in str(lines)
    assert "CALL_SUMMARY_RECEIVED_FRAMES=True" not in lines


def test_actions_call_evidence_is_bounded_and_failure_is_sanitized(capsys):
    from deploy.actions_evolution_pool import call_evidence_lines, recent_call_evidence

    assert call_evidence_lines("x" * (4 * 1024**2 + 1)) == ["CALL_DIAGNOSTICS=limit_reached"]
    assert call_evidence_lines('{"error": "' + SECRET + '"}') == []
    recent_call_evidence({"container": lambda _: (_ for _ in ()).throw(ValueError(SECRET))})
    assert capsys.readouterr().out == "CALL_DIAGNOSTICS=unavailable\n"
