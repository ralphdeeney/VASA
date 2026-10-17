"""Recovery evidence must never leak operator configuration or alter topology."""

import json
from types import SimpleNamespace

import pytest

from deploy import recovery_audit as subject

IMAGE = "sha256:" + "a" * 64


def setup(tmp_path):
    (tmp_path / "edge").mkdir()
    (tmp_path / "edge/Caddyfile").write_text(
        "reverse_proxy 172.16.2.1:18081\nAuthorization SUPER_SECRET"
    )
    local = tmp_path / ".local"
    local.mkdir()
    (local / "deployment-requests").mkdir()
    receipt = local / "actions-release.json"
    receipt.write_text(json.dumps({"active_sha": "b" * 40}))
    receipt.chmod(0o600)
    grant = local / "deployment-requests/grant-evolution-pool-2026-10-17.json"
    grant.write_text("SUPER_SECRET")
    services = {
        name: {"id": "SECRET-ID" + name, "image": IMAGE, "restarts": 0} for name in subject.SERVICES
    }
    calls = []

    def capture(*args):
        calls.append(args)
        if args[0] == "git":
            if "status" in args:
                return SimpleNamespace(
                    returncode=0, stdout=" M edge/Caddyfile\0?? malicious-SUPER_SECRET\nname\0"
                )
            return SimpleNamespace(returncode=1, stdout="")
        value = subject.UPSTREAM if any(".Labels" in a for a in args) else IMAGE
        return SimpleNamespace(returncode=0, stdout=value)

    def git(*args):
        calls.append(("git", *args))
        return "a" * 40 if args[0] == "rev-parse" else "?? malicious-SUPER_SECRET\nname\0"

    def require(condition, message):
        assert condition, message

    ns = {
        "ROOT": tmp_path,
        "capture": capture,
        "git": git,
        "snapshot_services": lambda names: services,
        "private_hashes": lambda: {"x": "secret"},
        "assert_unchanged": lambda value: require(value == services, "changed"),
        "require": require,
    }
    return ns, {"backups": 'def snapshot(ns): return {"paired_devices": "secret"}'}, calls


def records(capsys):
    lines = capsys.readouterr().out.splitlines()
    assert lines
    assert all(subject.safe_line(line) for line in lines)
    assert "SUPER_SECRET" not in "\n".join(lines)
    assert "SECRET-ID" not in "\n".join(lines)
    return [json.loads(line[len(subject.PREFIX) :]) for line in lines]


def test_readonly_audit_preserves_topology_and_reports_official_rollback(tmp_path, capsys):
    ns, sources, calls = setup(tmp_path)
    before = sorted(str(p) for p in tmp_path.rglob("*"))
    subject.run(ns, {}, sources)
    result = records(capsys)
    assert before == sorted(str(p) for p in tmp_path.rglob("*"))
    evolution = next(r for r in result if r["kind"] == "evolution")
    assert evolution["grant_consumed"]
    assert evolution["upstream_matches"]
    assert evolution["rollback_image_matches"]
    assert evolution["identity_baseline"] == "unknown"
    assert all(r is True for k, r in result[-1].items() if k != "kind")
    assert all(c[1:3] == ("image", "inspect") for c in calls if c[0] == "docker")
    assert all(".Config.Env" not in str(c) for c in calls)


def test_operator_only_structural_flags_and_no_arbitrary_path(tmp_path, capsys):
    ns, sources, _ = setup(tmp_path)
    subject.run(ns, {}, sources)
    result = records(capsys)
    file = next(r for r in result if r.get("path") == "edge/Caddyfile")
    assert file["reverse_proxy"] and file["private_origin"]
    assert not file["tracked"]
    assert not any("malicious" in json.dumps(r) for r in result)
    inventory = next(r for r in result if r["kind"] == "inventory")
    assert inventory["tracked_changes"] == 1
    assert inventory["untracked"] == 1


def test_secret_symlink_not_followed(tmp_path, capsys):
    ns, sources, _ = setup(tmp_path)
    (tmp_path / "tunnel").symlink_to(tmp_path / "edge", target_is_directory=True)
    subject.run(ns, {}, sources)
    result = records(capsys)
    item = next(r for r in result if r.get("path") == "tunnel/docker-compose.yml")
    assert item["fingerprint"] == "unknown"


def test_private_receipt_permissions_and_bounded_input(tmp_path):
    path = tmp_path / "receipt"
    path.write_text('{"secret": "credential"}')
    path.chmod(0o644)
    assert subject.optional(path) == {}
    path.chmod(0o600)
    assert subject.optional(path) == {"secret": "credential"}
    link = tmp_path / "link"
    link.symlink_to(path)
    assert subject.optional(link) == {}
    path.write_text("x" * 65537)
    assert subject.optional(path) == {}


@pytest.mark.parametrize(
    "line",
    [
        'VASA_RECOVERY_AUDIT={"kind":"secret","secret":"API_KEY"}',
        'VASA_RECOVERY_AUDIT={"kind":"inventory","tracked_changes":0,"untracked":0,'
        '"unknown_paths_hash":"SUPER_SECRET"}',
        'VASA_RECOVERY_AUDIT={"kind":"inventory","tracked_changes":true,"untracked":0,'
        '"unknown_paths_hash":"' + "a" * 64 + '"}',
        "VASA_RECOVERY_AUDIT=" + "x" * 8192,
    ],
)
def test_malicious_output_rejected(line):
    assert not subject.safe_line(line)


def test_private_files_changed_is_fatal(tmp_path, capsys):
    ns, sources, _ = setup(tmp_path)
    values = iter([{"x": "first"}, {"x": "changed"}])
    ns["private_hashes"] = lambda: next(values)
    with pytest.raises(AssertionError, match="invariants changed"):
        subject.run(ns, {}, sources)
    assert records(capsys)[-1]["private_files_unchanged"] is False


def test_pairing_identity_baseline_matches_without_hash_disclosure(tmp_path, capsys):
    ns, sources, _ = setup(tmp_path)
    path = tmp_path / ".local/backups/evolution-abc"
    path.mkdir(parents=True)
    receipt = path / "receipt.json"
    receipt.write_text('{"identity":{"paired_devices":"secret"}}')
    receipt.chmod(0o600)
    subject.run(ns, {}, sources)
    evolution = next(r for r in records(capsys) if r["kind"] == "evolution")
    assert evolution["identity_baseline"] == "matches"


def test_duplicate_output_field_cannot_smuggle_secret():
    line = (
        subject.PREFIX + '{"kind":"inventory","tracked_changes":0,"untracked":0,'
        '"unknown_paths_hash":"Authorization SUPER_SECRET",'
        '"unknown_paths_hash":"' + "a" * 64 + '"}'
    )
    assert not subject.safe_line(line)


def test_private_receipt_duplicate_keys_fail_closed(tmp_path):
    path = tmp_path / "receipt"
    path.write_text('{"active_sha":"secret","active_sha":"' + "a" * 40 + '"}')
    path.chmod(0o600)
    assert subject.optional(path) == {}
