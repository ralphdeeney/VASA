import json
import os
import re
import socket
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from scripts import prepare_vps

SECRET_NAMES = {
    "POSTGRES_PASSWORD",
    "REDIS_PASSWORD",
    "GLOBAL_API_KEY",
    "CALL_STREAM_SIGNING_KEY",
    "VASA_EVOLUTION_INSTANCE_KEY",
}
REQUIRED_NAMES = SECRET_NAMES | {"POSTGRES_USER", "POSTGRES_DB", "EVOLUTION_PORT", "VASA_API_PORT"}


@pytest.fixture
def available_ports() -> tuple[int, int]:
    with socket.socket() as evolution, socket.socket() as api:
        evolution.bind(("127.0.0.1", 0))
        api.bind(("127.0.0.1", 0))
        return evolution.getsockname()[1], api.getsockname()[1]


@pytest.fixture
def occupied_port() -> Iterator[int]:
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        yield server.getsockname()[1]


@pytest.fixture
def prepared_env(tmp_path: Path, available_ports: tuple[int, int]) -> Path:
    path = tmp_path / ".local" / "vps.env"
    prepare_vps.prepare(path, evolution_port=available_ports[0], api_port=available_ports[1])
    return path


def rewrite(path: Path, replacements: dict[str, str], *, omit: str | None = None) -> None:
    lines = []
    for line in path.read_text().splitlines():
        name, _, value = line.partition("=")
        if name != omit:
            lines.append(f"{name}={replacements.get(name, value)}")
    path.write_text("\n".join(lines) + "\n")


def test_fresh_configuration_has_private_permissions_unique_secrets_and_no_output(
    tmp_path: Path, available_ports: tuple[int, int], capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / ".local" / "vps.env"
    prepare_vps.prepare(path, evolution_port=available_ports[0], api_port=available_ports[1])
    values = prepare_vps.validate(path)
    assert set(values) == REQUIRED_NAMES
    assert values["POSTGRES_USER"] == "postgres"
    assert values["POSTGRES_DB"] == "vasa"
    assert (int(values["EVOLUTION_PORT"]), int(values["VASA_API_PORT"])) == available_ports
    assert all(re.fullmatch(r"[0-9a-f]{64}", values[name]) for name in SECRET_NAMES)
    assert len({values[name] for name in SECRET_NAMES}) == len(SECRET_NAMES)
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    assert path.stat().st_uid == os.getuid()
    assert capsys.readouterr() == ("", "")


def test_existing_configuration_preserves_all_values_ports_comments_and_bytes(
    prepared_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    content = b"# Existing private configuration\n" + prepared_env.read_bytes()
    prepared_env.write_bytes(content)
    before = prepare_vps.validate(prepared_env)
    prepare_vps.prepare(prepared_env, evolution_port=23456, api_port=23457)
    assert prepared_env.read_bytes() == content
    assert prepare_vps.validate(prepared_env) == before
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("invalid", ["a" * 63, "A" * 64, "z" * 64, "$(echo private)", ""])
def test_malformed_secret_is_rejected_without_rotation_or_disclosure(
    prepared_env: Path, invalid: str
) -> None:
    rewrite(prepared_env, {"GLOBAL_API_KEY": invalid})
    content = prepared_env.read_bytes()
    with pytest.raises(ValueError):
        prepare_vps.validate(prepared_env)
    with pytest.raises(ValueError) as failure:
        prepare_vps.prepare(prepared_env)
    assert prepared_env.read_bytes() == content
    if invalid:
        assert invalid not in str(failure.value)


@pytest.mark.parametrize("missing", sorted(REQUIRED_NAMES))
def test_missing_requirement_is_rejected_without_filling_or_rotating_existing_file(
    prepared_env: Path, missing: str
) -> None:
    rewrite(prepared_env, {}, omit=missing)
    content = prepared_env.read_bytes()
    with pytest.raises(ValueError):
        prepare_vps.prepare(prepared_env)
    assert prepared_env.read_bytes() == content


@pytest.mark.parametrize(
    "replacements",
    [
        {"POSTGRES_USER": "contains spaces"},
        {"POSTGRES_DB": "vasa;DROP DATABASE vasa"},
        {"POSTGRES_DB": "123invalid"},
        {"POSTGRES_USER": "éclair"},
        {"EVOLUTION_PORT": "1023"},
        {"VASA_API_PORT": "65536"},
        {"EVOLUTION_PORT": "not-a-port"},
        {"EVOLUTION_PORT": "18081", "VASA_API_PORT": "18081"},
    ],
)
def test_invalid_identifiers_and_ports_are_rejected_without_file_mutation(
    prepared_env: Path, replacements: dict[str, str]
) -> None:
    rewrite(prepared_env, replacements)
    content = prepared_env.read_bytes()
    with pytest.raises(ValueError):
        prepare_vps.prepare(prepared_env)
    assert prepared_env.read_bytes() == content


@pytest.mark.parametrize("target_exists", [True, False])
def test_symlink_secret_file_cannot_overwrite_or_create_target(
    tmp_path: Path, target_exists: bool
) -> None:
    directory = tmp_path / ".local"
    directory.mkdir(mode=0o700)
    target = tmp_path / "unrelated.env"
    if target_exists:
        target.write_text("Preserve this unrelated file\n")
        target.chmod(0o600)
    path = directory / "vps.env"
    path.symlink_to(target)
    with pytest.raises(ValueError):
        prepare_vps.prepare(path)
    assert path.is_symlink()
    assert target.exists() == target_exists
    if target_exists:
        assert target.read_text() == "Preserve this unrelated file\n"


def test_symlink_parent_is_rejected_without_creating_configuration(tmp_path: Path) -> None:
    actual = tmp_path / "actual"
    actual.mkdir(mode=0o700)
    linked = tmp_path / ".local"
    linked.symlink_to(actual, target_is_directory=True)
    with pytest.raises(ValueError):
        prepare_vps.prepare(linked / "vps.env")
    assert list(actual.iterdir()) == []


@pytest.mark.parametrize("mode", [0o640, 0o604, 0o644, 0o666])
def test_group_or_world_accessible_secret_file_is_rejected_and_preserved(
    prepared_env: Path, mode: int
) -> None:
    content = prepared_env.read_bytes()
    prepared_env.chmod(mode)
    with pytest.raises(ValueError):
        prepare_vps.prepare(prepared_env)
    assert prepared_env.read_bytes() == content
    assert prepared_env.stat().st_mode & 0o777 == mode


def test_permissive_parent_is_rejected_instead_of_modified(prepared_env: Path) -> None:
    content = prepared_env.read_bytes()
    prepared_env.parent.chmod(0o755)
    with pytest.raises(ValueError):
        prepare_vps.validate(prepared_env)
    with pytest.raises(ValueError):
        prepare_vps.prepare(prepared_env)
    assert prepared_env.parent.stat().st_mode & 0o777 == 0o755
    assert prepared_env.read_bytes() == content


def test_configuration_not_owned_by_current_user_is_rejected(
    prepared_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = prepared_env.read_bytes()
    owner = os.getuid()
    with monkeypatch.context() as patch:
        patch.setattr(prepare_vps.os, "getuid", lambda: owner + 1)
        with pytest.raises(ValueError):
            prepare_vps.validate(prepared_env)
        with pytest.raises(ValueError):
            prepare_vps.prepare(prepared_env)
    assert prepared_env.read_bytes() == content


def test_validate_rejects_symlink_parent_even_when_existing_secret_file_is_private(
    prepared_env: Path,
) -> None:
    content = prepared_env.read_bytes()
    actual = prepared_env.parent.with_name("private-original")
    prepared_env.parent.rename(actual)
    prepared_env.parent.symlink_to(actual, target_is_directory=True)
    with pytest.raises(ValueError):
        prepare_vps.validate(prepared_env)
    assert (actual / prepared_env.name).read_bytes() == content


def test_individually_foreign_owned_file_rejected_under_owned_private_parent(
    prepared_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = prepared_env.read_bytes()
    original_stat = Path.stat

    def attributed_stat(path: Path, *args: object, **kwargs: object) -> os.stat_result:
        info = original_stat(path, *args, **kwargs)
        if path != prepared_env:
            return info
        fields = list(info)
        fields[4] = info.st_uid + 1
        return os.stat_result(fields)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "stat", attributed_stat)
        with pytest.raises(ValueError):
            prepare_vps.validate(prepared_env)
        with pytest.raises(ValueError):
            prepare_vps.prepare(prepared_env)
    assert prepared_env.read_bytes() == content


def test_occupied_loopback_port_rejected_unless_exactly_owned(
    prepared_env: Path, occupied_port: int
) -> None:
    values = prepare_vps.validate(prepared_env)
    values["EVOLUTION_PORT"] = str(occupied_port)
    # Allocate while the occupied server remains bound, ensuring distinct actual ports.
    with socket.socket() as available:
        available.bind(("127.0.0.1", 0))
        values["VASA_API_PORT"] = str(available.getsockname()[1])
    with pytest.raises(ValueError):
        prepare_vps.check_ports(values)
    with pytest.raises(ValueError):
        prepare_vps.check_ports(values, owned_ports={occupied_port + 1})
    prepare_vps.check_ports(values, owned_ports={occupied_port})


def test_available_ports_are_bound_only_for_preflight_and_released(prepared_env: Path) -> None:
    values = prepare_vps.validate(prepared_env)
    prepare_vps.check_ports(values)
    for name in ("EVOLUTION_PORT", "VASA_API_PORT"):
        with socket.socket() as server:
            server.bind(("127.0.0.1", int(values[name])))


def test_partial_port_preflight_failure_releases_prior_successful_binding(
    prepared_env: Path, occupied_port: int
) -> None:
    values = prepare_vps.validate(prepared_env)
    values["VASA_API_PORT"] = str(occupied_port)
    with socket.socket() as available:
        available.bind(("127.0.0.1", 0))
        values["EVOLUTION_PORT"] = str(available.getsockname()[1])
    with pytest.raises(ValueError):
        prepare_vps.check_ports(values)
    with socket.socket() as subsequent_owner:
        subsequent_owner.bind(("127.0.0.1", int(values["EVOLUTION_PORT"])))


def test_cli_success_uses_fixed_message_without_printing_any_secret(prepared_env: Path) -> None:
    values = prepare_vps.validate(prepared_env)
    content = prepared_env.read_bytes()
    process = subprocess.run(
        [sys.executable, str(prepare_vps.__file__), "--env-file", str(prepared_env)],
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )
    assert process.returncode == 0
    assert process.stdout == (
        "Private deployment configuration preserved; preflight passed. No credentials printed.\n"
    )
    assert process.stderr == ""
    assert all(values[name] not in process.stdout for name in SECRET_NAMES)
    assert prepared_env.read_bytes() == content


def test_cli_invalid_configuration_is_sanitized_and_never_rotates_secrets(
    prepared_env: Path,
) -> None:
    secret = "private-malformed-value-never-print"
    rewrite(prepared_env, {"GLOBAL_API_KEY": secret})
    content = prepared_env.read_bytes()
    process = subprocess.run(
        [sys.executable, str(prepare_vps.__file__), "--env-file", str(prepared_env)],
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )
    assert process.returncode == 1
    assert secret not in process.stdout + process.stderr
    assert "Traceback" not in process.stderr
    assert prepared_env.read_bytes() == content


def mocked_discovery(
    monkeypatch: pytest.MonkeyPatch, containers: dict[str, dict[str, object]]
) -> list[list[str]]:
    commands: list[list[str]] = []

    def check_output(command: list[str], *, text: bool) -> str:
        commands.append(command)
        assert text
        if command[:2] == ["docker", "ps"]:
            assert command == [
                "docker",
                "ps",
                "-aq",
                "--filter",
                "label=com.docker.compose.project=vasa-vps",
            ]
            return "\n".join(containers)
        assert command[:3] == ["docker", "inspect", "--format"]
        assert len(command) == 5
        # Only routing ownership metadata may be inspected; never a full config/env dump.
        fields = set(re.findall(r"\.(?:Config|HostConfig|State)(?:\.[A-Za-z]+)*", command[3]))
        assert fields == {".Config.Labels", ".HostConfig.PortBindings", ".State.Running"}
        assert ".Config.Env" not in command[3] and "{{json .}}" not in command[3]
        return json.dumps(containers[command[-1]])

    monkeypatch.setattr(prepare_vps.subprocess, "check_output", check_output)
    return commands


def container_metadata(
    service: str,
    bindings: dict[str, list[dict[str, str]]],
    *,
    running: bool = True,
    working_directory: str | None = None,
) -> dict[str, object]:
    return {
        "labels": {
            "com.docker.compose.project": "vasa-vps",
            "com.docker.compose.service": service,
            "com.docker.compose.project.working_dir": (
                working_directory
                if working_directory is not None
                else str((prepare_vps.ROOT / "deploy").resolve())
            ),
        },
        "ports": bindings,
        "running": running,
    }


def test_deployment_port_discovery_recognizes_only_own_running_known_services(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands = mocked_discovery(
        monkeypatch,
        {
            "own-evolution": container_metadata(
                "evolution", {"4000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "18080"}]}
            ),
            "own-vasa": container_metadata(
                "vasa", {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": "18081"}]}
            ),
        },
    )
    assert prepare_vps.deployment_ports() == {18080, 18081}
    assert len(commands) == 3


def test_stopped_project_container_cannot_authorize_an_unrelated_occupied_port(
    prepared_env: Path, occupied_port: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    mocked_discovery(
        monkeypatch,
        {
            "stopped-evolution": container_metadata(
                "evolution",
                {"4000/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(occupied_port)}]},
                running=False,
            )
        },
    )
    owned = prepare_vps.deployment_ports()
    assert owned == set()
    values = prepare_vps.validate(prepared_env)
    values["EVOLUTION_PORT"] = str(occupied_port)
    with pytest.raises(ValueError):
        prepare_vps.check_ports(values, owned_ports=owned)


@pytest.mark.parametrize("running", [True, False])
def test_project_name_collision_from_foreign_working_directory_is_refused(
    monkeypatch: pytest.MonkeyPatch, running: bool
) -> None:
    mocked_discovery(
        monkeypatch,
        {
            "foreign-project": container_metadata(
                "vasa",
                {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": "18081"}]},
                running=running,
                working_directory="/opt/unrelated-existing-stack",
            )
        },
    )
    with pytest.raises(ValueError):
        prepare_vps.deployment_ports()


@pytest.mark.parametrize(
    "service,bindings",
    [
        ("postgres", {"5432/tcp": [{"HostIp": "127.0.0.1", "HostPort": "18080"}]}),
        ("evolution", {"4000/tcp": [{"HostIp": "0.0.0.0", "HostPort": "18080"}]}),
        ("vasa", {"8080/tcp": [{"HostIp": "::", "HostPort": "18081"}]}),
        ("evolution", {"9000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "18080"}]}),
    ],
)
def test_unknown_services_public_bindings_and_wrong_container_ports_do_not_confer_ownership(
    monkeypatch: pytest.MonkeyPatch, service: str, bindings: dict[str, list[dict[str, str]]]
) -> None:
    mocked_discovery(monkeypatch, {"unrecognized": container_metadata(service, bindings)})
    assert prepare_vps.deployment_ports() == set()
