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


def test_safe_scan_retry_recognizes_stderr_without_logging_it():
    error = "SSH host-key scan failed; no connection was attempted.\nprivate-key-sentinel"
    assert subject.transport_failure(result(1, stderr=error)) == "ssh_scan_unavailable"


def test_prepared_rollback_image_does_not_mean_a_rollback_was_executed(monkeypatch):
    states, _, _ = configured_run(
        monkeypatch,
        [result(0, "EVOLUTION_ROLLBACK_IMAGE_VERIFIED\nVASA_VPS_CONNECTIVITY_OK")],
    )
    assert subject.run_request() == 0
    assert "ROLLBACK" not in states
    assert states[-1] == "SUCCEEDED"


def test_public_health_markers_cannot_print_urls_bodies_or_exception_text():
    assert subject.markers(
        "EVOLUTION_PUBLIC_STATUS=login:200\n"
        "EVOLUTION_PUBLIC_STATUS=readiness:530\n"
        "EVOLUTION_PUBLIC_FAILURE=certificate\n"
        "EVOLUTION_PUBLIC_STATUS=login:200?token=secret\n"
        "EVOLUTION_PUBLIC_FAILURE=private-exception\n"
        "EVOLUTION_PUBLIC_STATUS=arbitrary:200"
    ) == [
        "EVOLUTION_PUBLIC_STATUS=login:200",
        "EVOLUTION_PUBLIC_STATUS=readiness:530",
        "EVOLUTION_PUBLIC_FAILURE=certificate",
    ]


def test_optional_provider_smoke_keeps_only_fixed_failures_and_bounded_timings():
    assert subject.markers(
        "LLM_SMOKE_FAILED=timeout\n"
        "DEEPGRAM_SMOKE_FAILED=provider_error\n"
        "LLM_FIRST_TOKEN_MS=123.45\n"
        "DEEPGRAM_TOTAL_MS=456.78\n"
        "LLM_SMOKE_FAILED=Authorization: Bearer secret\n"
        "DEEPGRAM_TOTAL_MS=456.78?token=secret"
    ) == [
        "LLM_SMOKE_FAILED=timeout",
        "DEEPGRAM_SMOKE_FAILED=provider_error",
        "LLM_FIRST_TOKEN_MS=123.45",
        "DEEPGRAM_TOTAL_MS=456.78",
    ]


def test_external_comparison_runs_only_after_ci_for_readonly_evolution(monkeypatch):
    from deploy import health_diagnostics

    events = []
    states, commands, _ = configured_run(monkeypatch, [result(0, "VASA_VPS_CONNECTIVITY_OK")])
    document = subject.load_request("")
    document["operation"] = "evolution_check"
    monkeypatch.setattr(subject, "wait_ci", lambda *args: events.append("ci"))
    monkeypatch.setattr(health_diagnostics, "run", lambda vantage: events.append(vantage) or [])
    monkeypatch.setattr(
        health_diagnostics,
        "verify_identified_public_health",
        lambda vantage: events.append("public_gate"),
    )
    monkeypatch.setattr(
        health_diagnostics,
        "verify_auth_boundaries",
        lambda vantage: events.append("auth_gate"),
    )
    assert subject.run_request() == 0
    assert events == ["ci", "github", "public_gate", "auth_gate"]
    assert len(commands) == 1
    assert states[-1] == "SUCCEEDED"


def test_ci_failure_prevents_even_readonly_comparison(monkeypatch):
    from deploy import health_diagnostics

    states, commands, _ = configured_run(monkeypatch, [])
    subject.load_request("")["operation"] = "evolution_check"

    def failed(*args):
        raise subject.Blocked("ci_failed")

    monkeypatch.setattr(subject, "wait_ci", failed)
    monkeypatch.setattr(health_diagnostics, "run", lambda *args: pytest.fail("CI was bypassed"))
    assert subject.run_request() == 1
    assert commands == []
    assert "SUCCEEDED" not in states


def test_malicious_json_cannot_smuggle_secrets_through_diagnostic_markers():
    assert (
        subject.markers(
            'VASA_HEALTH_DIAGNOSTIC={"vantage":"secret","vantage":"vps"}\n'
            'VASA_RECOVERY_AUDIT={"kind":"secret","kind":"release"}\n'
            'VASA_RECOVERY_AUDIT={"kind":"operator","path":"private-secret"}'
        )
        == []
    )


@pytest.mark.parametrize("gate", ["verify_identified_public_health", "verify_auth_boundaries"])
def test_independent_gate_failure_blocks_ssh(monkeypatch, gate):
    from deploy import health_diagnostics

    states, commands, _ = configured_run(monkeypatch, [])
    subject.load_request("")["operation"] = "evolution_check"
    monkeypatch.setattr(subject, "wait_ci", lambda *args: None)
    monkeypatch.setattr(health_diagnostics, "run", lambda *args: [])
    monkeypatch.setattr(health_diagnostics, "verify_identified_public_health", lambda *args: None)
    monkeypatch.setattr(health_diagnostics, "verify_auth_boundaries", lambda *args: None)

    def fail(*args):
        raise ValueError("untrusted body secret")

    monkeypatch.setattr(health_diagnostics, gate, fail)
    assert subject.run_request() == 1
    assert commands == []
    assert "SUCCEEDED" not in states
