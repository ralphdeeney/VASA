"""Delivery requests fail closed and never publish untrusted bridge output."""

import subprocess

import pytest

from deploy import deployment_orchestrator as subject


def result(code=0, stdout="", stderr=""):
    return subprocess.CompletedProcess([], code, stdout, stderr)


def test_bridge_output_discards_secrets_and_only_keeps_structural_markers():
    hostile = "\n".join(
        [
            "Authorization: Bearer secret",
            "LLM_SMOKE_FAILED=secret",
            "DEEPGRAM_SMOKE_OK",
            "EVOLUTION_CALL_GATE_FAILED=active_calls",
            "DB_SOCKET_EVOLUTION=95",
            "EVOLUTION_POOL_STAGE=health?token=secret",
            "VASA_EVOLUTION_POOL_DEPLOYMENT_OK",
        ]
    )
    assert subject.markers(hostile) == [
        "DEEPGRAM_SMOKE_OK",
        "EVOLUTION_CALL_GATE_FAILED=active_calls",
        "DB_SOCKET_EVOLUTION=95",
        "VASA_EVOLUTION_POOL_DEPLOYMENT_OK",
    ]


def test_retry_only_proven_preconnection_scan_failure():
    assert (
        subject.transport_failure(
            result(1, "SSH host-key scan failed; no connection was attempted.")
        )
        == "ssh_scan_unavailable"
    )
    with pytest.raises(subject.Blocked, match="ssh_outcome_unknown"):
        subject.transport_failure(result(255, "secret remote body"))
    with pytest.raises(subject.Blocked, match="ssh_host_trust"):
        subject.transport_failure(result(1, "Host trust is missing or mismatched."))
    assert subject.transport_failure(result(1, "EVOLUTION_CALL_GATE_FAILED=active_calls")) is None


@pytest.mark.parametrize("failure", ["failure", "cancelled", "timed_out", "action_required"])
def test_ci_failure_stops_without_sleep(monkeypatch, failure):
    monkeypatch.setattr(subject, "ci_status", lambda sha: failure)
    monkeypatch.setattr(subject.time, "sleep", lambda delay: pytest.fail("failed CI was retried"))
    with pytest.raises(subject.Blocked, match="ci_failed"):
        subject.wait_ci(["a" * 40])


def test_ci_waits_for_both_source_and_envelope(monkeypatch):
    statuses = iter(["success", "pending", "success", "success"])
    observed = []
    monkeypatch.setattr(subject, "ci_status", lambda sha: observed.append(sha) or next(statuses))
    monkeypatch.setattr(subject.time, "sleep", lambda delay: None)
    subject.wait_ci(["source", "envelope"])
    assert observed == ["source", "envelope", "source", "envelope"]


def test_journal_reuses_identical_request_identity(monkeypatch):
    request = {"request_id": "request", "target_commit": "a" * 40}
    journal = subject.Journal(request, "b" * 40)
    calls = []

    def api(path, body=None):
        calls.append((path, body))
        if "/statuses" in path:
            return [{"description": "VASA_REQUEST_STATE=SUCCEEDED"}]
        return [
            {
                "id": 7,
                "sha": "b" * 40,
                "payload": {"vasa_request_id": "request", "digest": journal.digest},
            }
        ]

    monkeypatch.setattr(subject, "api", api)
    journal.claim()
    assert journal.identifier == 7
    assert journal.previous == "SUCCEEDED"
    assert all(body is None for _, body in calls)


def test_journal_rejects_changed_request_with_reused_id(monkeypatch):
    journal = subject.Journal({"request_id": "request"}, "b" * 40)
    monkeypatch.setattr(
        subject,
        "api",
        lambda *args: [
            {
                "id": 7,
                "sha": "b" * 40,
                "payload": {"vasa_request_id": "request", "digest": "different"},
            }
        ],
    )
    with pytest.raises(subject.Blocked, match="replayed_request"):
        journal.claim()


def test_journal_failed_attempt_requires_review(monkeypatch):
    journal = subject.Journal({"request_id": "request"}, "b" * 40)

    def api(path, body=None):
        if "/statuses" in path:
            return [{"description": "VASA_REQUEST_STATE=FAILED"}]
        return [
            {
                "id": 7,
                "sha": "b" * 40,
                "payload": {"vasa_request_id": "request", "digest": journal.digest},
            }
        ]

    monkeypatch.setattr(subject, "api", api)
    with pytest.raises(subject.Blocked, match="failed_attempt_requires_review"):
        journal.claim()


def configured_run(monkeypatch, results):
    request = {
        "request_id": "request",
        "operation": "application_check",
        "target_commit": "a" * 40,
        "expected_markers": ["VASA_VPS_CONNECTIVITY_OK"],
    }
    monkeypatch.setenv("GITHUB_SHA", "b" * 40)
    monkeypatch.setattr(
        subject,
        "context",
        lambda trigger: {
            "changed_paths": ["deploy/requests/00000000-0000-0000-0000-000000000000.json"],
            "parent_sha": "a" * 40,
        },
    )
    monkeypatch.setattr(subject, "load_request", lambda path: request)
    monkeypatch.setattr(subject, "validate_request", lambda *args: None)
    monkeypatch.setattr(subject, "wait_ci", lambda *args: None)
    monkeypatch.setattr(subject, "api", lambda *args: {"object": {"sha": "b" * 40}})
    states, commands, sleeps = [], [], []

    class Journal:
        identifier = 1
        previous = "REQUESTED"

        def __init__(self, *args):
            pass

        def claim(self):
            pass

        def state(self, value):
            states.append(value)

    monkeypatch.setattr(subject, "Journal", Journal)
    outcomes = iter(results)

    def command(*args, **kwargs):
        commands.append(args)
        return next(outcomes)

    monkeypatch.setattr(subject, "command", command)
    monkeypatch.setattr(subject.time, "sleep", sleeps.append)
    return states, commands, sleeps


def test_scan_failure_retries_bounded_and_reports_no_raw_output(monkeypatch, capsys):
    states, commands, sleeps = configured_run(
        monkeypatch,
        [result(1, "SSH host-key scan failed; no connection was attempted.\nsecret-token")] * 3,
    )
    assert subject.run_request() == 1
    assert len(commands) == 3
    assert sleeps == [10, 30]
    output = capsys.readouterr().out
    assert "ssh_retry_limit" in output
    assert "secret-token" not in output
    assert states[-1] == "BLOCKED"


@pytest.mark.parametrize(
    "marker",
    [
        "EVOLUTION_CALL_GATE_FAILED=active_calls",
        "EVOLUTION_POOL_FAILURE=backup_failed",
        "EVOLUTION_POOL_FAILURE=rollback_unavailable",
    ],
)
def test_hard_gate_never_retries(monkeypatch, capsys, marker):
    states, commands, sleeps = configured_run(monkeypatch, [result(1, marker + "\nsecret")])
    assert subject.run_request() == 1
    assert len(commands) == 1
    assert sleeps == []
    assert states[-1] == "BLOCKED"
    output = capsys.readouterr().out
    assert "VASA_REQUEST_BLOCKED=remote_safety_or_health_gate" in output
    assert "secret" not in output


def test_rollback_is_reported_without_retrying(monkeypatch):
    states, commands, sleeps = configured_run(
        monkeypatch, [result(1, "VASA_EVOLUTION_POOL_ROLLBACK_OK")]
    )
    assert subject.run_request() == 1
    assert "ROLLBACK" in states
    assert len(commands) == 1
    assert sleeps == []


def test_success_requires_expected_verification_not_merely_zero_exit(monkeypatch):
    states, commands, sleeps = configured_run(monkeypatch, [result(0, "untrusted success")])
    assert subject.run_request() == 1
    assert "SUCCEEDED" not in states
    assert len(commands) == 1


def test_verified_success_records_terminal_state(monkeypatch):
    states, commands, sleeps = configured_run(
        monkeypatch, [result(0, "VASA_VPS_CONNECTIVITY_OK\nprivate response")]
    )
    assert subject.run_request() == 0
    assert states[-2:] == ["VERIFYING", "SUCCEEDED"]
    assert len(commands) == 1


def test_unknown_lowercase_marker_values_are_not_a_covert_log_channel():
    assert (
        subject.markers(
            "EVOLUTION_POOL_STAGE=secret\n"
            "EVOLUTION_CALL_GATE_FAILED=secret\n"
            "VASA_REQUEST_BLOCKED=secret"
        )
        == []
    )
