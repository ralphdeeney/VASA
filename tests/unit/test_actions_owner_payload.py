"""Private owner grant bridge, backup/identity gates and fixed-output filtering."""

import ast
import hashlib
import json
import os
from pathlib import Path

import pytest

from deploy import actions_owner_payload as payload

KEY = "fixture-password-value-not-real"
SHA = "c" * 40


@pytest.fixture
def protected(tmp_path, monkeypatch):
    import sys

    for name, value in {
        "GITHUB_ACTIONS": "true",
        "GITHUB_ACTOR": "ralphdeeney",
        "GITHUB_REPOSITORY": "ralphdeeney/VASA",
        "GITHUB_REF": "refs/heads/build/vasa-foundation",
        "VASA_OWNER_PROVISION": "true",
        "VASA_PLATFORM_ADMIN_PASSWORD": KEY,
        "VASA_OWNER_EMAIL": "fixture@example.invalid",
        "VASA_OWNER_RELEASE": SHA,
    }.items():
        monkeypatch.setenv(name, value)
    local = tmp_path / ".local"
    (local / "backups").mkdir(parents=True)
    (local / "recovery-preparations").mkdir()
    backup = local / "backups/bak.sql"
    backup.write_bytes(b"verified-backup-fixture")
    receipt = local / ("recovery-preparations/" + SHA + "-fixture.json")
    receipt.write_text(
        json.dumps(
            {
                "target_sha": SHA,
                "restore_verified": True,
                "migration_clone_verified": True,
                "backup": ".local/backups/bak.sql",
                "backup_sha256": hashlib.sha256(backup.read_bytes()).hexdigest(),
            }
        )
    )
    journal = local / "actions-release.json"
    journal.write_text(
        json.dumps(
            {
                "status": "active",
                "active_sha": SHA,
                "active_image": "fixture-image",
                "backup_receipt": ".local/recovery-preparations/" + SHA + "-fixture.json",
            }
        )
    )
    for path in [backup, receipt, journal]:
        path.chmod(0o600)
    original = Path.read_text
    stub = f"""import os,fcntl
from pathlib import Path
from types import SimpleNamespace
ROOT=Path({str(tmp_path)!r})
DEPENDENCIES=("postgres","redis","evolution")
SERVICES=("vasa","voice")
def preflight(): pass
def health(): pass
def prepare_recovery(target,exact_tip=True): assert target=={SHA!r} and exact_tip is False
def snapshot_services(services): return {{s:{{"image":"fixture-image"}} for s in services}}
def assert_unchanged(before): assert before==snapshot_services(DEPENDENCIES+SERVICES)
def private_hashes(): return {{"private":"unchanged"}}
def git(*args): return "preserved operator tree"
def require(value,message):
    if not value: raise ValueError("SECRET-EXCEPTION")
def container(name): return "owned-vasa",{{}}
def capture(*args,**kwargs):
    if args[5]=="-c":
        return SimpleNamespace(returncode=0, stdout="PLATFORM_OWNER_LOGIN_OK")
    assert args==("docker","exec","-i","owned-vasa","python","-m","vasa.saas.provision_owner")
    assert "input_text" in kwargs
    return SimpleNamespace(returncode=int(os.environ.get("FAKE_RETURN",0)),
        stdout=os.environ.get("FAKE_STDOUT","PLATFORM_OWNER_PROVISIONED"),stderr="SECRET-STDERR")
"""

    def read(path, *args, **kwargs):
        return stub if path == Path("deploy/actions_vps.py") else original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    monkeypatch.setattr(sys, "argv", ["controller", "check", "d" * 40, "false", "none"])
    return tmp_path


def test_private_bridge_only_emits_approved_receipt(protected, capsys):
    code = payload.build()
    ast.parse(code)
    assert KEY in code
    exec(compile(code, "private-stdin", "exec"), {})
    assert (
        capsys.readouterr().out
        == "PLATFORM_OWNER_PROVISIONED\nPLATFORM_OWNER_LOGIN_OK\nVASA_PLATFORM_OWNER_SETUP_OK\n"
    )


@pytest.mark.parametrize(
    "output",
    [
        "secret-body " + KEY,
        "PLATFORM_OWNER_PROVISIONED\nsecret-body",
        "PLATFORM_OWNER_PROVISION_FAILED=owner_conflict\nsecret-body",
    ],
)
def test_failed_output_is_filtered(protected, monkeypatch, capsys, output):
    monkeypatch.setenv("FAKE_STDOUT", output)
    monkeypatch.setenv("FAKE_RETURN", "1")
    with pytest.raises(SystemExit):
        exec(compile(payload.build(), "private-stdin", "exec"), {})
    result = capsys.readouterr()
    assert KEY not in result.out and "secret-body" not in result.out and "SECRET" not in result.out
    assert result.out.endswith("PLATFORM_OWNER_SETUP_FAILED=provision\n")
    assert not result.err


@pytest.mark.parametrize("gate", ["checksum", "expired", "restoration", "wrong_release"])
def test_hard_gates_block_provision(protected, capsys, gate):
    local = protected / ".local"
    if gate == "checksum":
        (local / "backups/bak.sql").write_bytes(b"tampered")
    if gate == "expired":
        os.utime(local / ("recovery-preparations/" + SHA + "-fixture.json"), (1, 1))
    if gate == "restoration":
        p = local / ("recovery-preparations/" + SHA + "-fixture.json")
        data = json.loads(p.read_text())
        data["restore_verified"] = False
        p.write_text(json.dumps(data))
    if gate == "wrong_release":
        p = local / "actions-release.json"
        data = json.loads(p.read_text())
        data["active_sha"] = "b" * 40
        p.write_text(json.dumps(data))
    with pytest.raises(SystemExit):
        exec(compile(payload.build(), "private-stdin", "exec"), {})
    result = capsys.readouterr()
    assert "PLATFORM_OWNER_PROVISIONED" not in result.out
    assert result.out in {
        "PLATFORM_OWNER_SETUP_FAILED=backup\n",
        "PLATFORM_OWNER_SETUP_FAILED=release\n",
    }


@pytest.mark.parametrize(
    "name,value",
    [
        ("GITHUB_ACTOR", "untrusted"),
        ("GITHUB_REF", "refs/heads/other"),
        ("GITHUB_ACTIONS", "false"),
        ("VASA_PLATFORM_ADMIN_PASSWORD", ""),
    ],
)
def test_untrusted_or_missing_private_input_refused(protected, monkeypatch, name, value, capsys):
    monkeypatch.setenv(name, value)
    assert payload.main() == 1
    assert capsys.readouterr().err == "PLATFORM_OWNER_PRIVATE_INPUT_REQUIRED\n"
