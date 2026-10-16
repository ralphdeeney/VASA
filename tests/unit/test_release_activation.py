"""Approved release activation must preserve the original checkout and data."""

from types import SimpleNamespace

import pytest

from deploy import actions_vps as deployment


@pytest.mark.parametrize("target", ["", "main", "b" * 39, "B" * 40, "b" * 40 + ";env"])
def test_activation_rejects_non_exact_commit_before_external_commands(monkeypatch, target):
    monkeypatch.setattr(deployment, "preflight", lambda: pytest.fail("Unsafe preflight"))
    with pytest.raises(deployment.Refusal):
        deployment.activate_recovery(target, "a" * 64)


@pytest.mark.parametrize("digest", ["", "a" * 63, "A" * 64, "a" * 64 + "\nsecret"])
def test_activation_rejects_non_exact_sql_digest_before_external_commands(monkeypatch, digest):
    monkeypatch.setattr(deployment, "preflight", lambda: pytest.fail("Unsafe preflight"))
    with pytest.raises(deployment.Refusal):
        deployment.activate_recovery("b" * 40, digest)


def test_release_compose_never_exposes_captured_error_output(tmp_path, monkeypatch, capsys):
    source = tmp_path / ".local/releases" / ("b" * 40)
    (source / "deploy").mkdir(parents=True)
    (source / "deploy/compose.yaml").write_text("services: {}")
    monkeypatch.setattr(deployment, "ROOT", tmp_path)
    secret = "private-key-Authorization-and-provider-body"
    monkeypatch.setattr(
        deployment,
        "capture",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout=secret, stderr=secret),
    )
    with pytest.raises(deployment.Refusal) as exc:
        deployment.release_compose(source, "vasa-app:release-" + "b" * 40, True, "config")
    assert secret not in str(exc.value)
    assert secret not in capsys.readouterr().out


@pytest.mark.parametrize("initial_revision", ["0006", "0007"])
@pytest.mark.parametrize("health_failure", [False, True])
def test_activation_migrates_once_and_rolls_back_only_apps(
    tmp_path, monkeypatch, capsys, initial_revision, health_failure
):
    import hashlib
    import json

    previous, target = "a" * 40, "b" * 40
    old_image, new_image = "sha256:" + "c" * 64, "sha256:" + "d" * 64
    local = tmp_path / ".local"
    release = local / "releases" / target
    (release / "docs/migrations").mkdir(parents=True)
    sql = "BEGIN; -- reviewed fixed migration\nCOMMIT;"
    (release / "docs/migrations/0007_saas_identity.sql").write_text(sql)
    digest = hashlib.sha256(sql.encode()).hexdigest()
    backup = local / "backups/verified.dump"
    backup.parent.mkdir()
    backup.write_bytes(b"verified-database-archive")
    receipts = local / "recovery-preparations"
    receipts.mkdir()
    receipt = receipts / (target + "-prepared.json")
    receipt.write_text(
        json.dumps(
            {
                "previous_sha": previous,
                "target_sha": target,
                "restore_verified": True,
                "migration_clone_verified": True,
                "backup": str(backup.relative_to(tmp_path)),
                "backup_sha256": hashlib.sha256(backup.read_bytes()).hexdigest(),
            }
        )
    )
    receipt.chmod(0o600)
    operator = tmp_path / "operator-notes.txt"
    operator.write_text("unknown user work remains byte-for-byte")
    monkeypatch.setattr(deployment, "ROOT", tmp_path)
    monkeypatch.setattr(deployment, "private_hashes", lambda: {"runtime": "unchanged"})
    topology = {
        name: {"id": name + "-id", "image": old_image, "restarts": 0}
        for name in deployment.DEPENDENCIES + deployment.SERVICES
    }
    monkeypatch.setattr(deployment, "snapshot_services", lambda _: topology.copy())
    preserved = []
    monkeypatch.setattr(deployment, "assert_unchanged", lambda state: preserved.append(state))
    calls = []
    revision = [initial_revision]
    current_image = [old_image]

    def git(*args):
        calls.append(("git", *args))
        if args[:1] == ("-C",):
            return (
                target
                if args[1] == str(release) and args[-1] == "HEAD"
                else (previous if args[-1] == "HEAD" else "")
            )
        if args == ("rev-parse", "HEAD"):
            return previous
        if args[:1] == ("status",):
            return "?? operator-notes.txt"
        if args[:1] == ("ls-files",):
            return "operator-notes.txt\0"
        return ""

    def run(*args, **kwargs):
        calls.append(("run", args, kwargs))
        if args[:3] == ("docker", "image", "inspect"):
            return new_image if args[-1].startswith("vasa-app:release-") else old_image
        if kwargs.get("input_text"):
            assert kwargs["input_text"] == sql
            assert args[:4] == ("docker", "exec", "-i", "postgres-id")
            revision[0] = "0007"
            return ""
        if args[-1] == "SELECT version_num FROM alembic_version":
            return revision[0]
        if args[-1].startswith("SELECT md5"):
            return "identity-and-passwords-digest"
        raise AssertionError("Unexpected command")

    def compose(source, image, saas, *args, **kwargs):
        calls.append(("compose", source, image, saas, args))
        if args[0] == "config":
            services = {
                name: {"image": old_image, "environment": {"PRIVATE": "never-print-this"}}
                for name in deployment.DEPENDENCIES + deployment.SERVICES
            }
            for name in deployment.SERVICES:
                services[name]["image"] = image
                if saas:
                    services[name]["environment"].update(
                        VASA_PUBLIC_ORIGIN="https://vasa.litatech.xyz", VASA_SAAS_ENABLED="true"
                    )
            return json.dumps({"services": services})
        assert args == (
            "up",
            "-d",
            "--no-deps",
            "--no-build",
            "--wait",
            "--wait-timeout",
            "150",
            "vasa",
            "voice",
        )
        current_image[0] = new_image if image.startswith("vasa-app:release-") else old_image
        return ""

    health_calls = []

    def health():
        health_calls.append(True)
        if health_failure and len(health_calls) == 1:
            raise deployment.Refusal("private provider response body")

    monkeypatch.setattr(deployment, "git", git)
    monkeypatch.setattr(deployment, "run", run)
    monkeypatch.setattr(deployment, "release_compose", compose)
    monkeypatch.setattr(deployment, "validate_web_bind", lambda _: None)
    monkeypatch.setattr(
        deployment, "container", lambda name: (name + "-id", {"image": current_image[0]})
    )
    monkeypatch.setattr(deployment, "health", health)
    monkeypatch.setattr(
        deployment, "post_validation", lambda sha, **kwargs: calls.append(("validated", sha))
    )
    monkeypatch.setattr(deployment, "diagnostics", lambda: None)
    if health_failure:
        with pytest.raises(deployment.Refusal):
            deployment.activate_recovery(target, digest)
    else:
        deployment.activate_recovery(target, digest)
    output = capsys.readouterr().out
    assert "never-print-this" not in output and "private provider" not in output
    assert operator.read_text() == "unknown user work remains byte-for-byte"
    assert revision[0] == "0007"
    migrations = [call for call in calls if call[0] == "run" and call[2].get("input_text")]
    assert len(migrations) == (initial_revision == "0006")
    updates = [call for call in calls if call[0] == "compose" and call[-1][0] == "up"]
    assert len(updates) == (2 if health_failure else 1)
    if health_failure:
        assert updates[-1][2] == "vasa-app:rollback-" + previous
        assert "VASA_RELEASE_ROLLBACK_OK" in output
        assert "VASA_DEPLOYMENT_OK" not in output
    else:
        assert "VASA_DEPLOYMENT_OK" in output
    assert preserved and all(set(state) == set(deployment.DEPENDENCIES) for state in preserved)
    journal = json.loads((local / "actions-release.json").read_text())
    assert journal["database_revision"] == "0007"
    assert journal["active_sha"] == (previous if health_failure else target)


def test_release_compose_limits_override_to_shared_apps_and_preserves_project_directory(
    tmp_path, monkeypatch
):
    import json

    release = tmp_path / ".local/releases" / ("b" * 40)
    release.mkdir(parents=True)
    monkeypatch.setattr(deployment, "ROOT", tmp_path)
    captured = []

    def capture(*args, **kwargs):
        captured.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(deployment, "capture", capture)
    image = "vasa-app:release-" + "b" * 40
    assert deployment.release_compose(release, image, True, "config") == "ok"
    command, options = captured[0]
    assert command[command.index("--project-directory") + 1] == str(tmp_path / "deploy")
    assert command[command.index("--env-file") + 1] == str(tmp_path / ".local/vps.env")
    patch = json.loads(options["input_text"])
    assert patch == {
        "services": {
            name: {"image": image, "environment": {"VASA_SAAS_ENABLED": "true"}}
            for name in ("vasa", "voice")
        }
    }
    assert command.count("-f") == 2


def test_changed_approved_sql_cannot_reach_migration_or_container_updates(tmp_path, monkeypatch):
    target = "b" * 40
    release = tmp_path / ".local/releases" / target
    (release / "docs/migrations").mkdir(parents=True)
    (release / "docs/migrations/0007_saas_identity.sql").write_text("tampered SQL")
    monkeypatch.setattr(deployment, "ROOT", tmp_path)
    monkeypatch.setattr(deployment, "git", lambda *args: target if args[-1] == "HEAD" else "")
    monkeypatch.setattr(
        deployment, "run", lambda *a, **k: pytest.fail("External command forbidden")
    )
    with pytest.raises(deployment.Refusal, match="hash differs"):
        deployment.activate_recovery(target, "a" * 64)
