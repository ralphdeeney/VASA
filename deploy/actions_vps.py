"""Actions-streamed staging controller; stdlib only, no credentials in output.

Uses the existing deploy/compose.yaml and .local/vps.env. Check mode has no
filesystem writes. Docker/Git output is captured, never dumped to Actions logs.
"""

import fcntl
import hashlib
import json
import os
import pwd
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path("/opt/vasa")
BRANCH = "build/vasa-foundation"
PROJECT = "vasa-vps"
SERVICES = ("vasa", "voice")
DEPENDENCIES = ("postgres", "redis", "evolution")
ENV_FILES = (".local/vps.env", ".local/llm.env", ".local/vasa.env", ".env", "deploy/.env")
ORIGINS = {
    "https://github.com/ralphdeeney/VASA",
    "https://github.com/ralphdeeney/VASA.git",
    "git@github.com:ralphdeeney/VASA.git",
    "ssh://git@github.com/ralphdeeney/VASA.git",
}
READY_MARKER = "Voice worker ready for registered instances; caller audio is not recorded."
BAD_LOG = re.compile(r"Traceback \(most recent call last\)|\b(?:ERROR|CRITICAL|FATAL)\b")


class Refusal(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise Refusal(message)


def run(*args, timeout=60):
    """Never include command output/arguments in exceptions (may contain secrets)."""
    try:
        result = subprocess.run(
            args,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Refusal("A required command failed or timed out; raw output withheld.") from exc
    require(result.returncode == 0, "A required command failed; raw output withheld.")
    return result.stdout.strip()


def git(*args):
    return run("git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", *args)


def compose(*args, timeout=180):
    return run(
        "docker",
        "compose",
        "--project-name",
        PROJECT,
        "--env-file",
        ".local/vps.env",
        "-f",
        "deploy/compose.yaml",
        "--profile",
        "voice",
        *args,
        timeout=timeout,
    )


def rootless():
    uid = os.getuid()
    require(uid != 0, "Root is forbidden.")
    endpoint = os.environ.get("DOCKER_HOST")
    if not endpoint:
        endpoint = run("docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}")
    # Prefer the user's explicitly selected existing socket. Only fall back to
    # this user's runtime socket when the default rootful socket was selected.
    if endpoint == "unix:///var/run/docker.sock":
        runtime = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{uid}"))
        require(
            runtime.is_dir() and runtime.stat().st_uid == uid,
            "No owned rootless runtime directory.",
        )
        endpoint = "unix://" + str(runtime / "docker.sock")
        os.environ.pop("DOCKER_CONTEXT", None)
        os.environ["DOCKER_HOST"] = endpoint
    require(endpoint.startswith("unix:///"), "An owned local Unix Docker socket is required.")
    socket = Path(endpoint.removeprefix("unix://"))
    require(socket.is_socket() and socket.stat().st_uid == uid, "Rootless socket is unavailable.")
    options = json.loads(run("docker", "info", "--format", "{{json .SecurityOptions}}"))
    require("name=rootless" in options, "Selected Docker daemon is not rootless.")
    run("docker", "compose", "version")


def preflight():
    require(pwd.getpwuid(os.getuid()).pw_name == "vasa-builder", "Unexpected remote user.")
    require(
        ROOT.is_dir() and ROOT.resolve() == ROOT and ROOT.stat().st_uid == os.getuid(),
        "Project directory is missing, redirected, or not owned by vasa-builder.",
    )
    os.chdir(ROOT)
    os.environ["GIT_OPTIONAL_LOCKS"] = "0"
    os.environ["GIT_TERMINAL_PROMPT"] = "0"
    require(git("rev-parse", "--show-toplevel") == str(ROOT), "Unexpected Git working tree.")
    require(git("remote", "get-url", "origin") in ORIGINS, "Unexpected repository identity.")
    branch = git("branch", "--show-current")
    sha = git("rev-parse", "HEAD")
    require(re.fullmatch(r"[0-9a-f]{40}", sha) is not None, "Invalid current commit.")
    rootless()
    print(
        "Remote user: vasa-builder; owned project/repository: verified; branch: "
        + (branch if re.fullmatch(r"[\w/.-]+", branch) else "(detached)")
        + "; commit: "
        + sha,
        flush=True,
    )
    print("Rootless Docker info, Compose, and owned Unix socket: OK", flush=True)
    return branch, sha


def config():
    compose("config", "--quiet")
    data = json.loads(compose("config", "--format", "json"))
    require(data["name"] == PROJECT, "Unexpected Compose project.")
    require(set(data["services"]) == set(SERVICES + DEPENDENCIES), "Unexpected Compose services.")
    require(
        data["services"]["vasa"]["image"] == "vasa-app:pinned"
        and data["services"]["voice"]["image"] == "vasa-app:pinned",
        "Unexpected app image.",
    )
    return data


def container(service):
    ids = compose("ps", "--all", "--quiet", service).splitlines()
    require(
        len(ids) == 1 and re.fullmatch(r"[a-f0-9]{12,64}", ids[0]) is not None,
        "Expected exactly one existing VASA container for " + service,
    )
    # Inspect only selected metadata: never inspect/dump container environment.
    value = json.loads(
        run(
            "docker",
            "inspect",
            "--format",
            '{"labels":{{json .Config.Labels}},"state":{{json .State}},'
            '"image":{{json .Image}},"restarts":{{.RestartCount}}}',
            ids[0],
        )
    )
    labels = value["labels"]
    require(
        labels.get("com.docker.compose.project") == PROJECT
        and labels.get("com.docker.compose.service") == service
        and labels.get("com.docker.compose.project.working_dir") == str(ROOT / "deploy"),
        "Container ownership labels do not match the existing deployment.",
    )
    return ids[0], value


def state_ok(value):
    state = value["state"]
    return (
        state["Status"] == "running"
        and not state.get("OOMKilled", False)
        and state.get("Health", {}).get("Status", "healthy") == "healthy"
    )


def log_health(cid, started, worker=False):
    # Docker writes stderr logs to stderr even on success: capture both streams.
    # No raw log line reaches Actions.
    result = subprocess.run(
        ["docker", "logs", "--since", started, "--tail", "200", cid],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    require(result.returncode == 0, "Cannot inspect VASA startup logs.")
    logs = result.stdout + "\n" + result.stderr
    failures = len(BAD_LOG.findall(logs))
    require(failures == 0, "VASA startup failure markers found; raw logs withheld.")
    return not worker or READY_MARKER in logs


def health(timeout=150):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ready = True
        for service in DEPENDENCIES + SERVICES:
            cid, value = container(service)
            if not state_ok(value):
                ready = False
                continue
            if service in SERVICES:
                ready &= log_health(cid, value["state"]["StartedAt"], service == "voice")
        if ready:
            break
        time.sleep(3)
    else:
        raise Refusal("Timed out waiting for VASA containers/worker startup.")
    compose(
        "exec",
        "-T",
        "vasa",
        "python",
        "-c",
        "import json,urllib.request; "
        "assert json.load(urllib.request.urlopen('http://127.0.0.1:8080/health/live',"
        "timeout=5))['status']=='alive'; "
        "assert json.load(urllib.request.urlopen('http://127.0.0.1:8080/health/ready',"
        "timeout=5))['status']=='ready'",
    )
    baseline = {service: container(service) for service in SERVICES}
    time.sleep(8)
    for service, (cid, before) in baseline.items():
        after_id, after = container(service)
        require(
            cid == after_id
            and state_ok(after)
            and after["restarts"] == before["restarts"]
            and after["state"]["StartedAt"] == before["state"]["StartedAt"],
            "VASA process restarted or became unhealthy during stabilization.",
        )
        require(
            log_health(cid, after["state"]["StartedAt"], service == "voice"),
            "Voice worker readiness marker is missing.",
        )
    print("VASA API live/ready, container health, worker readiness and stability: OK", flush=True)


def private_hashes():
    result = {}
    for name in ENV_FILES:
        path = ROOT / name
        require(not path.is_symlink(), "Runtime environment symlinks are not supported.")
        result[name] = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
    return result


def diagnostics():
    for service in SERVICES:
        try:
            cid, value = container(service)
            state = value["state"]
            print(
                f"{service}: running={state['Status'] == 'running'}, "
                f"oom={bool(state.get('OOMKilled'))}, restarts={value['restarts']}",
                flush=True,
            )
            try:
                log_health(cid, state["StartedAt"], service == "voice")
                print(service + ": no startup failure markers in recent bounded logs", flush=True)
            except Refusal:
                print(
                    service + ": startup log failure markers detected (content withheld)",
                    flush=True,
                )
        except (Refusal, ValueError, KeyError, subprocess.TimeoutExpired):
            print(service + ": container diagnostic unavailable", flush=True)


def signal_failure(_signum, _frame):
    raise Refusal("Deployment interrupted; attempting controlled rollback.")


def deploy(target, branch, previous):
    require(branch == BRANCH, "Staging checkout must already be on build/vasa-foundation.")
    require(re.fullmatch(r"[0-9a-f]{40}", target) is not None, "Invalid target commit.")
    local = ROOT / ".local"
    require(
        local.is_dir() and not local.is_symlink() and local.stat().st_uid == os.getuid(),
        "Missing owned .local directory.",
    )
    lock_path = local / "actions-deploy.lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise Refusal("Another staging deployment holds the project lock.") from exc
        require(
            not git("status", "--porcelain", "--untracked-files=all"),
            "Working tree has local modifications; nothing was overwritten.",
        )
        hashes = private_hashes()
        before_config = config()
        # This is an update path, not a bootstrap: all existing dependencies and
        # both app services must be healthy before any code/image mutation.
        health()
        old_images = {container(s)[1]["image"] for s in SERVICES}
        require(len(old_images) == 1, "App/worker do not share the expected existing image.")
        print("Preflight healthy; fetching the staging branch.", flush=True)
        git("fetch", "origin")
        require(
            git("rev-parse", "origin/" + BRANCH) == target,
            "Branch moved after dispatch; rerun against its current commit.",
        )
        git("merge-base", "--is-ancestor", previous, target)
        changed = git("diff", "--name-only", previous, target).splitlines()
        require(
            not any(p.startswith("migrations/") or p == "alembic.ini" for p in changed),
            "Schema changes require a separate operator-reviewed migration/backup plan.",
        )
        require(
            not git("ls-tree", "-r", "--name-only", target, "--", *ENV_FILES),
            "Target attempts to track private runtime environment files.",
        )
        backup_tag = "vasa-app:rollback-" + previous
        run("docker", "image", "tag", next(iter(old_images)), backup_tag)
        print("PREVIOUS_SHA=" + previous + "\nTARGET_SHA=" + target, flush=True)
        receipt = local / "actions-deployment.json"
        receipt.write_text(
            json.dumps({"previous_sha": previous, "target_sha": target, "status": "in_progress"})
            + "\n"
        )
        receipt.chmod(0o600)
        needs_build = any(
            p.startswith(("src/", "docker/"))
            or p
            in (
                "pyproject.toml",
                "uv.lock",
                ".dockerignore",
                "scripts/evolution_status.py",
                "scripts/prepare_speech.py",
                "scripts/prepare_knowledge.py",
            )
            for p in changed
        )
        changed_checkout = False
        touched = []
        for sig in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, signal_failure)
        try:
            changed_checkout = True
            git("checkout", BRANCH)
            git("pull", "--ff-only", "origin", BRANCH)
            require(git("rev-parse", "HEAD") == target, "Target commit changed during pull.")
            after_config = config()
            require(private_hashes() == hashes, "Private environment files changed unexpectedly.")
            # Never alter dependency topology, networks, volumes or other services.
            require(
                {k: v for k, v in before_config.items() if k != "services"}
                == {k: v for k, v in after_config.items() if k != "services"},
                "Compose project/network/volume changes require manual review.",
            )
            for name in DEPENDENCIES:
                require(
                    before_config["services"][name] == after_config["services"][name],
                    "Dependency service configuration changed; automatic deployment refused.",
                )
            touched = [
                s
                for s in SERVICES
                if needs_build or before_config["services"][s] != after_config["services"][s]
            ]
            if needs_build:
                # Only vasa has a build definition; voice uses that same image.
                print("Building the VASA app image (shared by API and worker).", flush=True)
                compose("build", "vasa", timeout=900)
            if touched:
                print("Updating only VASA app services: " + ", ".join(touched), flush=True)
                compose(
                    "up",
                    "-d",
                    "--no-deps",
                    "--wait",
                    "--wait-timeout",
                    "150",
                    *touched,
                    timeout=210,
                )
            require(private_hashes() == hashes, "Private environment files changed unexpectedly.")
            print("Validating VASA health and worker startup.", flush=True)
            health()
            receipt.write_text(
                json.dumps(
                    {
                        "previous_sha": previous,
                        "target_sha": target,
                        "status": "healthy",
                        "services": touched,
                    }
                )
                + "\n"
            )
            print("VASA_DEPLOYMENT_OK", flush=True)
        except BaseException:
            # Do not recursively interrupt rollback when SSH disconnects.
            for sig in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
                signal.signal(sig, signal.SIG_IGN)
            print("VASA deployment failed; inspecting only VASA app/worker.", flush=True)
            diagnostics()
            try:
                if changed_checkout:
                    require(
                        not git("status", "--porcelain", "--untracked-files=all"),
                        "Concurrent local edits detected; controlled reset refused.",
                    )
                    # Sole permitted destructive Git operation: known prior commit,
                    # under the deployment lock, after a clean-tree recheck.
                    git("reset", "--hard", previous)
                    require(private_hashes() == hashes, "Runtime configuration was not preserved.")
                    config()
                    if needs_build:
                        try:
                            compose("build", "vasa", timeout=900)
                        except Refusal:
                            run("docker", "image", "tag", backup_tag, "vasa-app:pinned")
                    if touched:
                        compose(
                            "up",
                            "-d",
                            "--no-deps",
                            "--wait",
                            "--wait-timeout",
                            "150",
                            *touched,
                            timeout=210,
                        )
                    health()
                    receipt.write_text(
                        json.dumps(
                            {
                                "previous_sha": previous,
                                "target_sha": target,
                                "status": "rolled_back",
                            }
                        )
                        + "\n"
                    )
                    print("VASA_ROLLBACK_OK; deployment remains failed.", flush=True)
            except BaseException:
                print("VASA_ROLLBACK_FAILED; operator intervention required.", flush=True)
                diagnostics()
            raise Refusal("Deployment failed; see sanitized VASA status above.") from None


def main():
    try:
        require(len(sys.argv) == 3 and sys.argv[1] in ("check", "deploy"), "Invalid invocation.")
        branch, previous = preflight()
        if sys.argv[1] == "check":
            print("Read-only check: no fetch, checkout, writes, builds or restarts.", flush=True)
            print("VASA_VPS_CONNECTIVITY_OK", flush=True)
        else:
            deploy(sys.argv[2], branch, previous)
    except (Refusal, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        # Only our fixed messages are safe; exception values from dependencies are not.
        print(
            str(exc)
            if isinstance(exc, Refusal)
            else "VASA preflight/deployment failed; raw exception withheld.",
            file=sys.stderr,
            flush=True,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
