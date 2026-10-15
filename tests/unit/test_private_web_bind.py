import copy
import io
import json
from pathlib import Path

import pytest

from deploy import actions_vps as deploy


def config():
    return {
        "services": {
            "vasa": {"ports": [{"host_ip": "172.16.2.1", "published": "18081", "target": 8080}]},
            "evolution": {
                "ports": [{"host_ip": "127.0.0.1", "published": "18080", "target": 4000}]
            },
        }
    }


def test_exact_private_bind_allowed():
    deploy.validate_web_bind(config())
    text = Path("deploy/compose.yaml").read_text()
    assert '"172.16.2.1:18081:8080"' in text
    assert '"127.0.0.1:${EVOLUTION_PORT:-18080}:4000"' in text
    assert "${VASA_API_PORT" not in text


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "", None, "127.0.0.1", "172.16.2.2"])
def test_wildcard_loopback_or_wrong_bridge_refused(host):
    data = config()
    data["services"]["vasa"]["ports"][0]["host_ip"] = host
    with pytest.raises(deploy.Refusal):
        deploy.validate_web_bind(data)


@pytest.mark.parametrize("change", ["port", "target", "extra", "udp", "host_network", "evolution"])
def test_port_and_evolution_boundary_cannot_change(change):
    data = config()
    port = data["services"]["vasa"]["ports"][0]
    if change == "port":
        port["published"] = "18082"
    elif change == "target":
        port["target"] = 8000
    elif change == "extra":
        data["services"]["vasa"]["ports"].append(copy.copy(port))
    elif change == "udp":
        port["protocol"] = "udp"
    elif change == "host_network":
        data["services"]["vasa"]["network_mode"] = "host"
    else:
        data["services"]["evolution"]["ports"][0]["host_ip"] = "172.16.2.1"
    with pytest.raises(deploy.Refusal):
        deploy.validate_web_bind(data)


@pytest.mark.parametrize("host", ["172.16.2.1", "0.0.0.0", "::"])
def test_running_docker_port_metadata_checked_without_environment(monkeypatch, host, capsys):
    monkeypatch.setattr(deploy, "container", lambda name: (name, {}))

    def run(*args):
        assert args[:4] == ("docker", "inspect", "--format", "{{json .NetworkSettings.Ports}}")
        return json.dumps(
            {"8080/tcp": [{"HostIp": host, "HostPort": "18081"}]}
            if args[-1] == "vasa"
            else {"4000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "18080"}]}
        )

    monkeypatch.setattr(deploy, "run", run)
    if host == "172.16.2.1":
        deploy.verify_running_web_bind()
        assert "STAGING_PRIVATE_BIND_OK" in capsys.readouterr().out
    else:
        with pytest.raises(deploy.Refusal):
            deploy.verify_running_web_bind()


def test_server_side_checks_use_private_bridge_and_preserve_evolution(monkeypatch):
    requests = []

    class Response(io.BytesIO):
        def __init__(self, code):
            super().__init__(b"private-cookie-or-body-never-printed")
            self.code = code

    class Opener:
        def open(self, url, timeout):
            requests.append(url)
            return Response(401 if url.endswith("/dashboard") else 200)

    monkeypatch.setattr(deploy.urllib.request, "build_opener", lambda *a: Opener())
    deploy.host_web_checks()
    assert requests[0] == "http://172.16.2.1:18081/login"
    assert requests[1] == "http://172.16.2.1:18081/dashboard"
    assert requests[-1] == "http://127.0.0.1:18080/server/ok"
    assert all(url.startswith("http://172.16.2.1:18081/") for url in requests[:-1])
