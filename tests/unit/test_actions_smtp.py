"""Explicit preactivation SMTP acceptance is bounded and never activates services."""

import json
from types import SimpleNamespace

import pytest

from deploy import actions_vps as controller

TARGET = "d" * 40
RECIPIENT = "operator@example.invalid"
SECRET = "MUST-NOT-REACH-ACTIONS-LOGS-private-key"


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    monkeypatch.setattr(controller, "ROOT", tmp_path)
    source = tmp_path / ".local/releases" / TARGET
    source.mkdir(parents=True)
    private = tmp_path / ".local/smtp.env"
    private.write_text(SECRET)
    private.chmod(0o600)
    monkeypatch.setattr(controller, "snapshot_services", lambda services: {"stable": True})
    monkeypatch.setattr(controller, "private_hashes", lambda: {"smtp": "unchanged"})
    monkeypatch.setattr(controller, "assert_unchanged", lambda before: None)
    monkeypatch.setattr(controller, "run", lambda *args: "sha256:" + "e" * 64)

    def git(*args):
        if "rev-parse" in args:
            return TARGET
        if "remote" in args:
            return "git@github-vasa:ralphdeeney/VASA.git"
        return ""

    monkeypatch.setattr(controller, "git", git)
    return source, private


@pytest.mark.parametrize("returncode", [0, 1])
def test_only_allowlisted_smtp_failure_survives_nonzero_exit(
    prepared, monkeypatch, capsys, returncode
):
    monkeypatch.setattr(
        controller,
        "release_compose",
        lambda *a, **k: SimpleNamespace(
            returncode=returncode,
            stdout=SECRET + '\n{"status":"failed","code":"authentication_failed"}',
            stderr=SECRET + " Authorization: private",
        ),
    )
    with pytest.raises(controller.Refusal):
        controller.smtp_acceptance(TARGET, RECIPIENT)
    assert capsys.readouterr().out == "SMTP_ACCEPTANCE_FAILED=authentication_failed\n"


def test_success_uses_only_prepared_oneoff_web_container_no_attestation(
    prepared, monkeypatch, capsys
):
    calls = []

    def compose(*args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(
            returncode=0,
            stderr=SECRET,
            stdout=SECRET + '\n{"status":"smtp_accepted","mailbox_delivery_verified":false}\n',
        )

    monkeypatch.setattr(controller, "release_compose", compose)
    controller.smtp_acceptance(TARGET, RECIPIENT)
    args, kwargs = calls[0]
    assert args == (
        prepared[0],
        "vasa-app:release-" + TARGET,
        None,
        "run",
        "--rm",
        "--no-deps",
        "-T",
        "--entrypoint",
        "python",
        "vasa",
        "scripts/check_smtp.py",
        "--recipient",
        RECIPIENT,
    )
    assert kwargs == {"unchecked": True}
    assert capsys.readouterr().out == "VASA_SMTP_ACCEPTANCE_OK\nSMTP_MAILBOX_VERIFIED=false\n"
    assert prepared[1].read_text() == SECRET


@pytest.mark.parametrize(
    "output",
    [
        SECRET,
        '{"status":"failed","code":"' + SECRET + '"}',
        '{"status":"smtp_accepted","mailbox_delivery_verified":true}',
        "\n".join(
            [json.dumps({"status": "smtp_accepted", "mailbox_delivery_verified": False})] * 2
        ),
    ],
)
def test_arbitrary_or_duplicate_reports_cannot_claim_delivery(
    prepared, monkeypatch, capsys, output
):
    monkeypatch.setattr(
        controller,
        "release_compose",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout=output, stderr=SECRET),
    )
    with pytest.raises(controller.Refusal):
        controller.smtp_acceptance(TARGET, RECIPIENT)
    assert capsys.readouterr().out == "SMTP_ACCEPTANCE_FAILED=invalid_response\n"


@pytest.mark.parametrize("mode", [0o644, 0o666])
def test_private_permissions_are_required_before_running_container(prepared, monkeypatch, mode):
    prepared[1].chmod(mode)
    monkeypatch.setattr(
        controller, "release_compose", lambda *a, **k: pytest.fail("Private key required")
    )
    with pytest.raises(controller.Refusal, match="SMTP_PRIVATE_CONFIGURATION_REQUIRED"):
        controller.smtp_acceptance(TARGET, RECIPIENT)


@pytest.mark.parametrize(
    "recipient", ["x@example.invalid';touch /tmp/pwn", "a@b.invalid\nsecret", "a,b@b.invalid"]
)
def test_mailbox_injection_rejected_before_commands(prepared, monkeypatch, recipient):
    monkeypatch.setattr(controller, "git", lambda *a: pytest.fail("Must reject before Git"))
    with pytest.raises(controller.Refusal, match="Invalid SMTP test mailbox"):
        controller.smtp_acceptance(TARGET, recipient)


def test_preservation_verification_runs_even_when_container_times_out(prepared, monkeypatch):
    checked = []
    monkeypatch.setattr(controller, "assert_unchanged", lambda before: checked.append(before))
    monkeypatch.setattr(
        controller,
        "release_compose",
        lambda *a, **k: (_ for _ in ()).throw(controller.Refusal("fixed timeout")),
    )
    with pytest.raises(controller.Refusal, match="fixed timeout"):
        controller.smtp_acceptance(TARGET, RECIPIENT)
    assert checked == [{"stable": True}]


@pytest.mark.parametrize(
    "mode,smoke", [("deploy", "false"), ("bootstrap", "false"), ("check", "true")]
)
def test_smtp_sending_is_explicit_check_only(monkeypatch, mode, smoke):
    monkeypatch.setattr(
        controller.sys,
        "argv",
        ["controller", mode, TARGET, smoke, "smtp_check", TARGET, "", RECIPIENT],
    )
    monkeypatch.setattr(controller, "preflight", lambda: pytest.fail("Invalid invocation"))
    assert controller.main() == 1
