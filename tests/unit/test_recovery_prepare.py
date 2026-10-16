"""Recovery preparation must stay isolated from the running release."""

import ast
from pathlib import Path

import pytest

CONTROLLER = Path(__file__).parents[2] / "deploy/actions_vps.py"


def recovery_source():
    """Inspect the integrated controller safety boundaries."""
    source = CONTROLLER.read_text()
    tree = ast.parse(source)
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "prepare_recovery"
    )
    return ast.get_source_segment(source, function)


def test_recovery_does_not_activate_or_modify_live_checkout():
    source = recovery_source()
    assert '"worktree", "add", "--detach"' in source
    assert '"checkout"' not in source
    assert '"pull"' not in source
    assert '"reset"' not in source
    assert '"compose"' not in source
    assert '"commit"' not in source
    assert "vasa-app:pinned" not in source
    assert '"alembic", "upgrade"' not in source
    assert "input_text=reviewed_sql" in source


def test_recovery_backup_is_verified_only_in_disposable_database():
    source = recovery_source()
    assert 'temporary = "vasa_verify_" + token' in source
    assert "--format=custom" in source
    assert "pg_restore --list" in source
    assert "--exit-on-error --no-owner" in source
    assert "createdb" in source and "dropdb" in source
    assert "finally:" in source
    assert "os.O_EXCL, 0o600" in source
    assert "stderr=subprocess.PIPE" in source


def test_recovery_preservation_checks_run_even_when_candidate_build_fails():
    source = recovery_source()
    tree = ast.parse(source)
    function = tree.body[0]
    guarded = [node for node in ast.walk(function) if isinstance(node, ast.Try)]
    assert any(
        any(
            isinstance(item, ast.Expr)
            and isinstance(item.value, ast.Call)
            and isinstance(item.value.func, ast.Name)
            and item.value.func.id == "unchanged"
            for item in node.finalbody
        )
        for node in guarded
    )
    assert "private_hashes() == hashes" in source
    assert "assert_unchanged(topology)" in source
    assert "== baseline" in source


def test_recovery_builds_frozen_sources_and_keeps_rollback_before_candidate():
    source = recovery_source()
    assert source.index("build(previous, rollback)") < source.index("build(target,")
    assert "path = source_tree(sha)" in source
    assert "docker/vasa.Dockerfile" in source
    assert "available.returncode == 0 and available.stdout.strip() == image" in source
    assert '"docker", "image", "tag", image, rollback' in source
    assert 'git("rev-parse", "origin/" + BRANCH) == target' in source
    assert 'git("merge-base", "--is-ancestor", previous, target)' in source


def test_recovery_prints_only_fixed_markers_and_numeric_or_digest_metadata():
    source = recovery_source()
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "print"
        ):
            expression = ast.unparse(node.args[0])
            assert expression.startswith("'RECOVERY_") or expression.startswith("'VASA_RECOVERY_")
            assert "stdout" not in expression and "stderr" not in expression
    assert 'b"PRIVATE KEY" not in payload' in source
    assert 'run("openssl", "x509"' in source
    assert "source_tree(sha)" in source


@pytest.mark.parametrize("failure", ["none", "build", "restore"])
def test_preparation_restores_and_migrates_only_disposable_clone(
    tmp_path, monkeypatch, capsys, failure
):
    import hashlib
    import json
    from types import SimpleNamespace

    from deploy import actions_vps as d

    previous, target = "a" * 40, "b" * 40
    image = "sha256:" + "c" * 64
    local = tmp_path / ".local"
    (local / "evolution-source").mkdir(parents=True)
    (local / "evolution-source/vasa-host-trust.pem").write_bytes(
        b"-----BEGIN CERTIFICATE-----\nTEST\n"
    )
    private = local / "llm.env"
    private.write_text("PRIVATE_SECRET=never-output-this-value")
    unknown = tmp_path / "operator-notes.txt"
    unknown.write_text("preserve operator work")
    monkeypatch.setattr(d, "ROOT", tmp_path)
    monkeypatch.setattr(d, "preflight", lambda: (d.BRANCH, previous))
    monkeypatch.setattr(
        d, "private_hashes", lambda: {"private": hashlib.sha256(private.read_bytes()).hexdigest()}
    )
    monkeypatch.setattr(
        d, "snapshot_services", lambda _: {"vasa": {"image": image}, "voice": {"image": image}}
    )
    monkeypatch.setattr(d, "assert_unchanged", lambda _: None)
    monkeypatch.setattr(d, "container", lambda _: ("postgres-id", {}))
    commands = []
    clone_revision = ["0006"]

    def git(*args):
        commands.append(("git", *args))
        if args[0] == "status":
            return "?? operator-notes.txt"
        if args == ("rev-parse", "HEAD"):
            return previous
        if args[0] == "rev-parse":
            return target
        if args[:2] == ("worktree", "add"):
            path = Path(args[3])
            path.mkdir()
            (path / "docs/migrations").mkdir(parents=True)
            (path / "docs/migrations/0007_saas_identity.sql").write_text("REVIEWED CLONE MIGRATION")
        if args[0] == "-C":
            if args[-1] == "HEAD":
                return Path(args[1]).name
            if args[-1] == "--git-common-dir":
                return str(tmp_path / ".git")
        return ""

    def run(*args, **kwargs):
        commands.append(args)
        if args[:2] == ("docker", "build") and failure == "build":
            raise d.Refusal("Candidate build failed.")
        if "psql" in " ".join(args):
            assert any(a.startswith("vasa_verify_") for a in args)
            if kwargs.get("input_text"):
                assert kwargs["input_text"] == "REVIEWED CLONE MIGRATION"
                clone_revision[0] = "0007"
            if args[-1] == "SELECT version_num FROM alembic_version":
                return clone_revision[0]
            return "unchanged-private-digest"
        if args[:3] == ("docker", "image", "inspect"):
            return image
        return ""

    def binary(args, **kwargs):
        commands.append(tuple(args))
        if "pg_dump" in " ".join(args):
            kwargs["stdout"].write(b"PGDMP-disposable-test")
        if "pg_restore -U" in " ".join(args) and failure == "restore":
            return SimpleNamespace(returncode=1, stderr=b"private restore error password")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(d, "git", git)
    monkeypatch.setattr(d, "run", run)
    monkeypatch.setattr(d, "capture", lambda *a, **k: SimpleNamespace(returncode=0, stdout=image))
    monkeypatch.setattr(d.subprocess, "run", binary)
    if failure == "none":
        d.prepare_recovery(target)
    else:
        with pytest.raises(d.Refusal):
            d.prepare_recovery(target)
    output = capsys.readouterr().out
    assert "never-output" not in output
    if failure == "none":
        assert "RECOVERY_MIGRATION_CLONE_OK" in output
        assert "VASA_RECOVERY_PREPARE_OK" in output
    else:
        assert "VASA_RECOVERY_PREPARE_OK" not in output
        assert "private restore" not in output
    assert unknown.read_text() == "preserve operator work"
    assert private.read_text() == "PRIVATE_SECRET=never-output-this-value"
    assert any("dropdb" in " ".join(c) for c in commands)
    assert not any("pinned" in " ".join(c) or "reset" in c or "compose" in c for c in commands)
    if failure != "none":
        assert not (local / "recovery-preparations").exists()
        return
    receipt = json.loads(next((local / "recovery-preparations").glob("*.json")).read_text())
    assert receipt["live_migration_applied"] is False
    assert receipt["restore_verified"] is True
    assert next((local / "backups").glob("*.dump")).stat().st_mode & 0o077 == 0


def test_staging_origin_is_explicit_and_does_not_enable_forwarded_header_trust():
    compose = (CONTROLLER.parent / "compose.yaml").read_text()
    assert "VASA_PUBLIC_ORIGIN: ${VASA_PUBLIC_ORIGIN:-https://vasa.litatech.xyz}" in compose
    assert "--forwarded-allow-ips" not in compose
    assert "172.16.2.1:18081:8080" in compose
    assert "127.0.0.1:${EVOLUTION_PORT:-18080}:4000" in compose
