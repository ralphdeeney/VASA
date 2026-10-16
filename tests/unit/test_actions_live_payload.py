import json

import pytest

from deploy.actions_live_payload import build


def private_input(tmp_path, **changes):
    path = tmp_path / "input.json"
    path.write_text(
        json.dumps({"action": "prepare", "run": "a" * 32, "password": "secret" * 8, **changes})
    )
    path.chmod(0o600)
    return path


def test_payload_private_stdin_has_no_secret_command_argument(tmp_path):
    path = private_input(tmp_path)
    payload = build(path)
    compile(payload, "private_payload", "exec")
    assert "input_text=json.dumps(data)" in payload
    assert '"vasa_actions_acceptance"' in payload
    assert "result.stdout.strip() != expected" in payload
    assert "print(expected" in payload
    assert "print(result.stdout" not in payload


@pytest.mark.parametrize("mode", [0o644, 0o666, 0o777])
def test_payload_refuses_public_private_input(tmp_path, mode):
    path = private_input(tmp_path)
    path.chmod(mode)
    with pytest.raises(ValueError):
        build(path)


def test_payload_refuses_symlink(tmp_path):
    path = private_input(tmp_path)
    link = tmp_path / "link"
    link.symlink_to(path)
    with pytest.raises(ValueError):
        build(link)


@pytest.mark.parametrize("change", [{"action": "deploy"}, {"run": "arbitrary"}, {"key": "secret"}])
def test_payload_refuses_unapproved_task(tmp_path, change):
    with pytest.raises(ValueError):
        build(private_input(tmp_path, **change))
