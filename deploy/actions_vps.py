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
    "git@github-vasa:ralphdeeney/VASA.git",
    "ssh://git@github.com/ralphdeeney/VASA.git",
}
READY_MARKER = "Voice worker ready for registered instances; caller audio is not recorded."
BAD_LOG = re.compile(r"Traceback \(most recent call last\)|\b(?:ERROR|CRITICAL|FATAL)\b")
VOICE_STAGES = frozenset(
    {
        "settings",
        "speech_verify",
        "database",
        "redis",
        "evolution_client",
        "resolve_instances",
        "instance_status",
        "persisted_config",
        "knowledge_init",
        "tools_config",
        "llm_provider",
        "stt_init",
        "tts_init",
        "runtime_init",
        "ready",
        "supervision",
    }
)
VOICE_ERRORS = frozenset(
    {
        "invalid_configuration",
        "invalid_assets",
        "missing_assets",
        "dependency_unavailable",
        "initialization_failed",
        "operation_failed",
        "internal_error",
    }
)
ACTIVE_STAGE = "VASA_STAGE=preflight"


class Refusal(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise Refusal(message)


def stage(mode, name):
    global ACTIVE_STAGE
    require(mode in ("BOOTSTRAP", "DEPLOY"), "Invalid deployment stage mode.")
    require(
        name
        in (
            "preflight",
            "git_fetch",
            "rollback_image",
            "checkout",
            "target_build",
            "vasa_update",
            "voice_create",
            "health",
            "rollback",
            "rollback_health",
        ),
        "Invalid deployment stage identifier.",
    )
    ACTIVE_STAGE = mode + "_STAGE=" + name
    print(ACTIVE_STAGE, flush=True)


def run(*args, timeout=60, input_text=None):
    """Never include command output/arguments in exceptions (may contain secrets)."""
    try:
        result = subprocess.run(
            args,
            **({"stdin": subprocess.DEVNULL} if input_text is None else {"input": input_text}),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Refusal(ACTIVE_STAGE + " failed or timed out; raw output withheld.") from exc
    require(result.returncode == 0, ACTIVE_STAGE + " failed; raw output withheld.")
    return result.stdout.strip()


def git(*args):
    return run("git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", *args)


def compose(*args, timeout=180, image_override=None):
    extra = ()
    override = None
    if image_override is not None:
        require(args == ("build", "vasa"), "Image override is restricted to rollback builds.")
        require(
            re.fullmatch(r"vasa-app:(?:bootstrap-)?rollback-[0-9a-f]{40}", image_override)
            is not None,
            "Invalid rollback image tag.",
        )
        extra = ("-f", "-")
        # Only override the output image tag, never context, Dockerfile, build
        # arguments, secrets, or runtime environment. Nothing is written to disk.
        override = json.dumps({"services": {"vasa": {"image": image_override}}})
    return run(
        "docker",
        "compose",
        "--project-name",
        PROJECT,
        "--env-file",
        ".local/vps.env",
        "-f",
        "deploy/compose.yaml",
        *extra,
        "--profile",
        "voice",
        *args,
        timeout=timeout,
        input_text=override,
    )


def acquire_rollback_image(running_image, previous, backup_tag):
    """Verify a rollback image before checkout or any app/container mutation."""
    require(
        re.fullmatch(r"[0-9a-f]{40}", previous) is not None
        and backup_tag
        in (
            "vasa-app:rollback-" + previous,
            "vasa-app:bootstrap-rollback-" + previous,
        ),
        "Invalid VASA rollback image target.",
    )
    require(git("rev-parse", "HEAD") == previous, "Previous source revision changed unexpectedly.")
    require(
        not git("status", "--porcelain", "--untracked-files=all"),
        "Rollback image acquisition requires a clean previous-source checkout.",
    )
    hashes = private_hashes()
    expected = None
    try:
        require(
            run("docker", "image", "inspect", "--format", "{{.Id}}", running_image)
            == running_image,
            "Running image is not locally inspectable.",
        )
        run("docker", "image", "tag", running_image, backup_tag)
        expected = running_image
    except Refusal:
        print(
            "Running image unavailable; building rollback from clean previous source.", flush=True
        )
        # Compose reads the existing build definition and dependency inputs. The
        # output goes straight to the rollback tag, leaving vasa-app:pinned alone.
        compose("build", "vasa", timeout=900, image_override=backup_tag)
    rollback_image = run("docker", "image", "inspect", "--format", "{{.Id}}", backup_tag)
    require(
        bool(rollback_image) and (expected is None or rollback_image == expected),
        "Rollback image verification failed.",
    )
    require(
        git("rev-parse", "HEAD") == previous
        and not git("status", "--porcelain", "--untracked-files=all"),
        "Previous-source checkout changed during rollback image acquisition.",
    )
    require(
        private_hashes() == hashes, "Private environment changed during rollback image acquisition."
    )
    return rollback_image


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


def voice_marker_lines(logs):
    markers = []
    for line in logs.split("\n"):
        if len(line) > 96:
            continue
        match = re.fullmatch(
            r"VOICE_(STARTUP|RUNTIME)_(STAGE|FAILED|ERROR)=([a-z_]+)", line, flags=re.ASCII
        )
        if match is None:
            continue
        phase, kind, value = match.groups()
        allowed = VOICE_ERRORS if kind == "ERROR" else VOICE_STAGES
        if value in allowed:
            markers.append(f"VOICE_{phase}_{kind}={value}")
    return markers[-64:]


def read_container_logs(cid, *, since=None):
    # Docker writes stderr logs to stderr even on success: capture both streams.
    # No raw log line reaches Actions.
    args = ["docker", "logs", "--tail", "200"]
    if since is not None:
        args.extend(["--since", since])
    args.append(cid)
    result = subprocess.run(
        args,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )
    require(result.returncode == 0, "Cannot inspect VASA startup logs.")
    return result.stdout + "\n" + result.stderr


def log_health(cid, started, worker=False):
    logs = read_container_logs(cid, since=started)
    markers = voice_marker_lines(logs) if worker else []
    require(
        not any("_FAILED=" in line or "_ERROR=" in line for line in markers),
        "Voice lifecycle failure markers found; raw logs withheld.",
    )
    failures = len(BAD_LOG.findall(logs))
    require(failures == 0, "VASA startup failure markers found; raw logs withheld.")
    return not worker or READY_MARKER in logs


def health(timeout=150, *, include_voice=True):
    apps = SERVICES if include_voice else ("vasa",)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ready = True
        for service in DEPENDENCIES + apps:
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
    baseline = {service: container(service) for service in apps}
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
    print("VASA API live/ready, container health and process stability: OK", flush=True)
    if include_voice:
        print("Voice worker readiness: OK", flush=True)


def snapshot_services(services):
    result = {}
    for service in services:
        cid, value = container(service)
        require(state_ok(value), "Expected a healthy existing VASA service: " + service)
        result[service] = {
            "id": cid,
            "image": value["image"],
            "restarts": value["restarts"],
            "started": value["state"]["StartedAt"],
        }
    return result


def assert_unchanged(snapshot):
    require(
        snapshot_services(tuple(snapshot)) == snapshot,
        "Existing VASA service identity/image/restarts changed unexpectedly.",
    )


def bootstrap_topology():
    expected = snapshot_services(DEPENDENCIES + ("vasa",))
    require(
        not compose("ps", "--all", "--quiet", "voice"),
        "Bootstrap requires exactly zero existing voice containers.",
    )
    project_ids = run(
        "docker",
        "ps",
        "--all",
        "--no-trunc",
        "--filter",
        "label=com.docker.compose.project=" + PROJECT,
        "--format",
        "{{.ID}}",
    ).splitlines()
    require(
        len(project_ids) == len(expected)
        and set(project_ids) == {item["id"] for item in expected.values()},
        "Unexpected VASA project topology; bootstrap refused.",
    )
    return expected


def require_deepgram_key(data):
    # Compose resolves the existing private env_file. Do not read a cloud key,
    # accept a command-line key, or render the environment in logs/receipts.
    key = data["services"]["voice"].get("environment", {}).get("DEEPGRAM_API_KEY")
    require(isinstance(key, str) and bool(key.strip()), "DEEPGRAM_VPS_KEY_REQUIRED")


def compatible_config(before, after):
    require(
        {k: v for k, v in before.items() if k != "services"}
        == {k: v for k, v in after.items() if k != "services"},
        "Compose project/network/volume changes require manual review.",
    )
    for service in DEPENDENCIES:
        require(
            before["services"][service] == after["services"][service],
            "Dependency service configuration changed; automatic deployment refused.",
        )


def up_services(*services):
    require(bool(services) and set(services) <= set(SERVICES), "Invalid app service selection.")
    compose("up", "-d", "--no-deps", "--wait", "--wait-timeout", "150", *services, timeout=210)


def remove_bootstrapped_voice():
    if not compose("ps", "--all", "--quiet", "voice"):
        return
    # container() requires exactly one container and validates project, service,
    # and working-directory labels before this single-ID removal. No volumes.
    cid, _ = container("voice")
    run("docker", "container", "rm", "--force", cid)
    require(
        not compose("ps", "--all", "--quiet", "voice"), "New voice container could not be removed."
    )


def write_bootstrap_receipt(path, previous, target, status):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(
            {"previous_sha": previous, "target_sha": target, "mode": "bootstrap", "status": status},
            stream,
        )
        stream.write("\n")


def bootstrap(target, branch, previous):
    stage("BOOTSTRAP", "preflight")
    require(branch == BRANCH, "Staging checkout must already be on build/vasa-foundation.")
    require(re.fullmatch(r"[0-9a-f]{40}", target) is not None, "Invalid target commit.")
    local = ROOT / ".local"
    require(
        local.is_dir() and not local.is_symlink() and local.stat().st_uid == os.getuid(),
        "Missing owned .local directory.",
    )
    fd = os.open(local / "actions-deploy.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise Refusal("Another staging deployment holds the project lock.") from exc
        require(
            not git("status", "--porcelain", "--untracked-files=all"),
            "Working tree has local modifications; nothing was overwritten.",
        )
        require(
            not git("ls-files", "--", *ENV_FILES),
            "Private runtime environment files must remain untracked.",
        )
        hashes = private_hashes()
        before_config = config()
        baseline = bootstrap_topology()
        require_deepgram_key(before_config)
        health(include_voice=False)
        assert_unchanged(baseline)
        print(
            "Bootstrap preflight: healthy four-service topology; private key configured.",
            flush=True,
        )
        print("PREVIOUS_SHA=" + previous + "\nTARGET_SHA=" + target, flush=True)
        stage("BOOTSTRAP", "git_fetch")
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
        old_image = baseline["vasa"]["image"]
        backup_tag = "vasa-app:bootstrap-rollback-" + previous
        stage("BOOTSTRAP", "rollback_image")
        rollback_image = acquire_rollback_image(old_image, previous, backup_tag)
        assert_unchanged(baseline)
        require(private_hashes() == hashes, "Private environment files changed unexpectedly.")
        receipt = local / "actions-bootstrap.json"
        write_bootstrap_receipt(receipt, previous, target, "in_progress")
        changed_checkout = app_attempted = voice_attempted = False
        for sig in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, signal_failure)
        try:
            stage("BOOTSTRAP", "checkout")
            changed_checkout = True
            git("checkout", BRANCH)
            git("pull", "--ff-only", "origin", BRANCH)
            require(git("rev-parse", "HEAD") == target, "Target commit changed during pull.")
            after_config = config()
            compatible_config(before_config, after_config)
            require_deepgram_key(after_config)
            require(private_hashes() == hashes, "Private environment files changed unexpectedly.")
            assert_unchanged(baseline)
            require(
                not compose("ps", "--all", "--quiet", "voice"),
                "Voice appeared concurrently; bootstrap refused.",
            )
            print("Building the shared VASA app image for bootstrap.", flush=True)
            stage("BOOTSTRAP", "target_build")
            compose("build", "vasa", timeout=900)
            new_image = run("docker", "image", "inspect", "--format", "{{.Id}}", "vasa-app:pinned")
            if new_image != old_image or (
                before_config["services"]["vasa"] != after_config["services"]["vasa"]
            ):
                app_attempted = True
                stage("BOOTSTRAP", "vasa_update")
                up_services("vasa")
            # Recheck immediately before creation; rollback is allowed to remove
            # voice only once this invocation has attempted its creation.
            require(
                not compose("ps", "--all", "--quiet", "voice"),
                "Voice appeared concurrently; bootstrap refused.",
            )
            voice_attempted = True
            stage("BOOTSTRAP", "voice_create")
            up_services("voice")
            require(
                container("voice")[1]["image"] == new_image,
                "Voice is not using the newly built shared app image.",
            )
            require(
                container("vasa")[1]["image"] == new_image,
                "API and voice do not share the built app image.",
            )
            stage("BOOTSTRAP", "health")
            health()
            assert_unchanged({s: baseline[s] for s in DEPENDENCIES})
            if not app_attempted:
                assert_unchanged({"vasa": baseline["vasa"]})
            require(private_hashes() == hashes, "Private environment files changed unexpectedly.")
            write_bootstrap_receipt(receipt, previous, target, "healthy")
            print("VASA_BOOTSTRAP_OK", flush=True)
        except BaseException:
            for sig in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
                signal.signal(sig, signal.SIG_IGN)
            print("VASA bootstrap failed; inspecting only VASA app/worker.", flush=True)
            diagnostics()
            try:
                stage("BOOTSTRAP", "rollback")
                if voice_attempted:
                    remove_bootstrapped_voice()
                if changed_checkout:
                    require(
                        not git("status", "--porcelain", "--untracked-files=all"),
                        "Concurrent local edits detected; controlled reset refused.",
                    )
                    git("reset", "--hard", previous)
                    require(private_hashes() == hashes, "Runtime configuration was not preserved.")
                    require(
                        config() == before_config, "Previous Compose configuration not restored."
                    )
                    # Restore the verified image: exact original when available,
                    # otherwise the clean PREVIOUS_SHA source build.
                    run("docker", "image", "tag", backup_tag, "vasa-app:pinned")
                    if app_attempted:
                        up_services("vasa")
                    stage("BOOTSTRAP", "rollback_health")
                    health(include_voice=False)
                    restored = bootstrap_topology()
                    require(
                        restored["vasa"]["image"]
                        == (rollback_image if app_attempted else old_image),
                        "Previous API image was not restored.",
                    )
                    assert_unchanged({s: baseline[s] for s in DEPENDENCIES})
                    if not app_attempted:
                        assert_unchanged({"vasa": baseline["vasa"]})
                    require(private_hashes() == hashes, "Runtime configuration was not preserved.")
                    write_bootstrap_receipt(receipt, previous, target, "rolled_back")
                    print("VASA_BOOTSTRAP_ROLLBACK_OK; bootstrap remains failed.", flush=True)
            except BaseException:
                print("VASA_BOOTSTRAP_ROLLBACK_FAILED; operator intervention required.", flush=True)
                diagnostics(report_voice_markers=False)
            raise Refusal("Bootstrap failed; see sanitized VASA status above.") from None


def private_hashes():
    result = {}
    for name in ENV_FILES:
        path = ROOT / name
        require(not path.is_symlink(), "Runtime environment symlinks are not supported.")
        result[name] = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
    return result


def diagnostics(*, report_voice_markers=True):
    for service in SERVICES:
        try:
            cid, value = container(service)
            state = value["state"]
            print(
                f"{service}: running={state['Status'] == 'running'}, "
                f"oom={bool(state.get('OOMKilled'))}, restarts={value['restarts']}",
                flush=True,
            )
            if service == "voice" and report_voice_markers:
                # Capture the target container BEFORE rollback/removal, across
                # restarts rather than only the most recent StartedAt window.
                for marker in voice_marker_lines(read_container_logs(cid)):
                    print(marker, flush=True)
            try:
                log_health(cid, state["StartedAt"], service == "voice")
                print(
                    service + ": current-attempt log scan complete (content withheld)", flush=True
                )
            except Refusal:
                print(
                    service + ": startup log failure markers detected (content withheld)",
                    flush=True,
                )
        except (Refusal, ValueError, KeyError, OSError, subprocess.TimeoutExpired):
            print(service + ": container diagnostic unavailable", flush=True)


def signal_failure(_signum, _frame):
    raise Refusal("Deployment interrupted; attempting controlled rollback.")


def deploy(target, branch, previous):
    stage("DEPLOY", "preflight")
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
        stage("DEPLOY", "git_fetch")
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
        stage("DEPLOY", "rollback_image")
        rollback_image = acquire_rollback_image(next(iter(old_images)), previous, backup_tag)
        require(private_hashes() == hashes, "Private environment files changed unexpectedly.")
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
        app_update_attempted = False
        touched = []
        for sig in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, signal_failure)
        try:
            stage("DEPLOY", "checkout")
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
                stage("DEPLOY", "target_build")
                compose("build", "vasa", timeout=900)
            if touched:
                print("Updating only VASA app services: " + ", ".join(touched), flush=True)
                stage("DEPLOY", "vasa_update")
                app_update_attempted = True
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
            stage("DEPLOY", "health")
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
                stage("DEPLOY", "rollback")
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
                    run("docker", "image", "tag", backup_tag, "vasa-app:pinned")
                    if app_update_attempted:
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
                    stage("DEPLOY", "rollback_health")
                    health()
                    require(
                        all(container(s)[1]["image"] == rollback_image for s in touched)
                        if app_update_attempted
                        else all(container(s)[1]["image"] in old_images for s in SERVICES),
                        "Verified rollback app image was not restored.",
                    )
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
                diagnostics(report_voice_markers=False)
            raise Refusal("Deployment failed; see sanitized VASA status above.") from None


def main():
    try:
        require(
            len(sys.argv) == 3 and sys.argv[1] in ("check", "bootstrap", "deploy"),
            "Invalid invocation.",
        )
        branch, previous = preflight()
        if sys.argv[1] == "check":
            print("Read-only check: no fetch, checkout, writes, builds or restarts.", flush=True)
            print("VASA_VPS_CONNECTIVITY_OK", flush=True)
        elif sys.argv[1] == "bootstrap":
            bootstrap(sys.argv[2], branch, previous)
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
