"""Resolve the real Compose model with fake secrets and prove web-only injection."""

import json
import os
import shutil
import subprocess
from pathlib import Path

from deploy import actions_vps


def test_smtp_private_file_is_preserved_and_excluded_from_image():
    assert ".local/smtp.env" in actions_vps.ENV_FILES
    assert ".local/" in Path(".gitignore").read_text().splitlines()
    dockerfile = Path("docker/vasa.Dockerfile").read_text()
    assert "scripts/check_smtp.py /opt/vasa/scripts/check_smtp.py" in dockerfile
    assert "smtp.env" not in dockerfile
    assert "!scripts/check_smtp.py" in Path(".dockerignore").read_text().splitlines()


def test_resolved_compose_injects_smtp_only_into_web(tmp_path):
    deploy = tmp_path / "deploy"
    local = tmp_path / ".local"
    deploy.mkdir()
    local.mkdir()
    shutil.copyfile("deploy/compose.yaml", deploy / "compose.yaml")
    fake = "fake-mail-key-web-only"
    (local / "smtp.env").write_text(
        "VASA_SMTP_HOST=smtp.reloop.sh\nVASA_SMTP_PORT=587\n"
        f"VASA_SMTP_USERNAME={fake}\nVASA_SMTP_PASSWORD={fake}\n"
        "VASA_SMTP_SENDER=VASA <noreply@example.invalid>\n"
        "VASA_SMTP_STARTTLS=true\nVASA_SMTP_DELIVERY_VERIFIED=false\n"
    )
    environment = dict(os.environ)
    environment.update(
        {
            name: "fake-config-only"
            for name in (
                "POSTGRES_USER",
                "POSTGRES_PASSWORD",
                "POSTGRES_DB",
                "REDIS_PASSWORD",
                "GLOBAL_API_KEY",
                "CALL_STREAM_SIGNING_KEY",
                "VASA_EVOLUTION_INSTANCE_KEY",
            )
        }
    )
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            "/dev/null",
            "-f",
            str(deploy / "compose.yaml"),
            "--profile",
            "voice",
            "config",
            "--format",
            "json",
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )
    data = json.loads(result.stdout)
    for name, service in data["services"].items():
        values = service.get("environment", {})
        smtp = {k: v for k, v in values.items() if k.startswith("VASA_SMTP_")}
        if name == "vasa":
            assert smtp["VASA_SMTP_USERNAME"] == smtp["VASA_SMTP_PASSWORD"] == fake
            assert smtp["VASA_SMTP_DELIVERY_VERIFIED"] == "false"
        else:
            assert smtp == {}, name
            assert fake not in json.dumps(service)
