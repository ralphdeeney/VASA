"""Evolution backup preparation must never restore the original databases."""

import json
from types import SimpleNamespace

import pytest

from deploy import evolution_backups as backups


class Refusal(RuntimeError):
    pass


@pytest.mark.parametrize("failure", ["none", "dump", "restore", "schema"])
def test_three_private_archives_restore_only_in_disposable_databases(
    tmp_path, monkeypatch, capsys, failure
):
    (tmp_path / ".local").mkdir()
    commands = []
    created = []
    dropped = []

    def run(*args, **kwargs):
        commands.append(args)
        if "createdb" in args[5]:
            created.append(args[-1])
        if "dropdb" in args[5]:
            dropped.append(args[-1])
        if args[-1] == "SELECT version_num FROM alembic_version":
            return "0007"
        if args[-1] == backups.SCHEMA_SQL:
            if failure == "schema" and args[-2].startswith("vasa_evo_verify_"):
                return "b" * 32
            return "a" * 32
        return "a" * 32

    def subprocess_run(command, **kwargs):
        commands.append(tuple(command))
        if "pg_dump" in command[5]:
            kwargs["stdout"].write(b"private database archive contents")
            return SimpleNamespace(returncode=int(failure == "dump"))
        assert command[-1].startswith("vasa_evo_verify_")
        assert kwargs["stderr"] == backups.subprocess.PIPE
        if "--list" not in command[6] and failure == "restore":
            return SimpleNamespace(returncode=1, stderr="private token")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(backups.subprocess, "run", subprocess_run)
    namespace = {
        "ROOT": tmp_path,
        "container": lambda _: ("owned-postgres", {}),
        "run": run,
        "Refusal": Refusal,
    }
    if failure == "none":
        result = backups.backup(namespace)
        assert set(result["archives"]) == {"app", "auth", "users"}
        for archive in result["archives"].values():
            path = tmp_path / archive["path"]
            assert path.stat().st_mode & 0o077 == 0
            assert path.parent.stat().st_mode & 0o077 == 0
            assert archive["restore_verified"] is True
        receipt = next((tmp_path / ".local/backups").glob("*/receipt.json"))
        assert receipt.stat().st_mode & 0o077 == 0
        assert json.loads(receipt.read_text()) == result
    else:
        with pytest.raises(Refusal, match="raw output withheld"):
            backups.backup(namespace)
    assert created == dropped
    assert all(name.startswith("vasa_evo_verify_") for name in dropped)
    assert capsys.readouterr().out == ("EVOLUTION_BACKUP_RESTORE_OK\n" if failure == "none" else "")
    assert all("ALTER" not in " ".join(command) for command in commands)


def test_snapshot_refuses_unreviewed_application_revision():
    def run(*args, **kwargs):
        return "0006" if args[-1] == "SELECT version_num FROM alembic_version" else "a" * 32

    with pytest.raises(Refusal, match="revision"):
        backups.snapshot(
            {"container": lambda _: ("owned-postgres", {}), "run": run, "Refusal": Refusal}
        )
