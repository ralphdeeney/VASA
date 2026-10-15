"""Prepare private deployment bindings and refuse unrelated occupied loopback ports."""

import argparse
import json
import os
import re
import secrets
import socket
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECRET_NAMES = (
    "POSTGRES_PASSWORD",
    "REDIS_PASSWORD",
    "GLOBAL_API_KEY",
    "CALL_STREAM_SIGNING_KEY",
    "VASA_EVOLUTION_INSTANCE_KEY",
)
PORT_NAMES = ("EVOLUTION_PORT", "VASA_API_PORT")
NAMES = {*SECRET_NAMES, *PORT_NAMES, "POSTGRES_USER", "POSTGRES_DB"}


def check_private_parent(parent: Path) -> None:
    if parent.is_symlink():
        raise ValueError("Private configuration directory must not be a symlink.")
    info = parent.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("Private configuration directory must be owned and mode 0700.")


def validate(env_file: Path) -> dict[str, str]:
    check_private_parent(env_file.parent)
    if env_file.is_symlink():
        raise ValueError("Deployment configuration must not be a symlink.")
    info = env_file.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("Deployment configuration must be an owned private regular file.")
    values: dict[str, str] = {}
    for line in env_file.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        name, separator, value = line.partition("=")
        if not separator or name not in NAMES or name in values:
            raise ValueError("Deployment configuration has an unknown or duplicate binding.")
        values[name] = value
    if values.keys() != NAMES:
        raise ValueError("Deployment configuration is missing required bindings.")
    for name in SECRET_NAMES:
        if re.fullmatch(r"[0-9a-f]{64}", values[name]) is None:
            raise ValueError("Deployment credentials must use generated 64-character hex values.")
    for name in ("POSTGRES_USER", "POSTGRES_DB"):
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", values[name]) is None:
            raise ValueError("Deployment database identifiers are invalid.")
    for name in PORT_NAMES:
        if not values[name].isdigit() or not 1024 <= int(values[name]) <= 65535:
            raise ValueError("Deployment ports must be between 1024 and 65535.")
    if values[PORT_NAMES[0]] == values[PORT_NAMES[1]] or int(values[PORT_NAMES[0]]) == int(
        values[PORT_NAMES[1]]
    ):
        raise ValueError("Deployment ports must be distinct.")
    return values


def prepare(env_file: Path, evolution_port: int = 18080, api_port: int = 18081) -> None:
    parent = env_file.parent
    if parent.is_symlink():
        raise ValueError("Private configuration directory must not be a symlink.")
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    check_private_parent(parent)
    if env_file.exists() or env_file.is_symlink():
        validate(env_file)
        return
    if not 1024 <= evolution_port <= 65535 or not 1024 <= api_port <= 65535:
        raise ValueError("Deployment ports must be between 1024 and 65535.")
    if evolution_port == api_port:
        raise ValueError("Deployment ports must be distinct.")
    values = {"POSTGRES_USER": "postgres", "POSTGRES_DB": "vasa"}
    values.update({name: secrets.token_hex(32) for name in SECRET_NAMES})
    values.update(EVOLUTION_PORT=str(evolution_port), VASA_API_PORT=str(api_port))
    descriptor = os.open(env_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        handle.write("".join(f"{name}={value}\n" for name, value in values.items()))
    validate(env_file)


def check_ports(values: dict[str, str], owned_ports: set[int] | None = None) -> None:
    sockets: list[socket.socket] = []
    try:
        for name in PORT_NAMES:
            port = int(values[name])
            if port in (owned_ports or set()):
                continue
            stream = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sockets.append(stream)
            try:
                stream.bind(("127.0.0.1", port))
            except OSError:
                raise ValueError(f"Loopback port {port} is occupied; choose another.") from None
    finally:
        for stream in sockets:
            stream.close()


def deployment_ports() -> set[int]:
    # Only this project's known service bindings may bypass the restart collision check.
    ids = subprocess.check_output(
        ["docker", "ps", "-aq", "--filter", "label=com.docker.compose.project=vasa-vps"],
        text=True,
    ).split()
    ports: set[int] = set()
    for identifier in ids:
        raw = subprocess.check_output(
            [
                "docker",
                "inspect",
                "--format",
                '{"labels":{{json .Config.Labels}},"ports":{{json .HostConfig.PortBindings}},'
                '"running":{{json .State.Running}}}',
                identifier,
            ],
            text=True,
        )
        details = json.loads(raw)
        labels, bindings = details["labels"], details["ports"] or {}
        if labels.get("com.docker.compose.project.working_dir") != str((ROOT / "deploy").resolve()):
            raise ValueError(
                "Existing vasa-vps project belongs to a different checkout; preserve it."
            )
        if not details["running"]:
            continue
        service = labels.get("com.docker.compose.service")
        container_port = {"evolution": "4000/tcp", "vasa": "8080/tcp"}.get(service)
        if container_port:
            for binding in bindings.get(container_port, []) or []:
                if binding["HostIp"] == "127.0.0.1":
                    ports.add(int(binding["HostPort"]))
    return ports


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".local/vps.env")
    parser.add_argument("--evolution-port", type=int, default=18080)
    parser.add_argument("--api-port", type=int, default=18081)
    parser.add_argument("--check-ports", action="store_true")
    arguments = parser.parse_args()
    try:
        prepare(arguments.env_file, arguments.evolution_port, arguments.api_port)
        if arguments.check_ports:
            check_ports(validate(arguments.env_file), deployment_ports())
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        if isinstance(error, ValueError):
            parser.exit(1, str(error) + "\n")
        parser.exit(1, "Deployment preflight failed; check private file and Docker access.\n")
    print("Private deployment configuration preserved; preflight passed. No credentials printed.")


if __name__ == "__main__":
    main()
