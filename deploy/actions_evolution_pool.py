"""Manual, guarded Evolution-only rollout over the existing Actions bridge."""

import fcntl
import io
import json
import os
import re
import signal
import socket
import ssl
import time
import urllib.error
import urllib.request
from contextlib import redirect_stdout


class Deferred(Exception):
    pass


def emit_probe(ns, script, expected, *arguments):
    cid, _ = ns["container"]("vasa")
    result = ns["capture"](
        "docker", "exec", "-i", cid, "python", "-c", script, *arguments, timeout=100
    )
    lines = result.stdout.splitlines()
    for line in lines:
        if (
            re.fullmatch(r"EVOLUTION_CALL_GATE_(?:DB|REDIS)_ACTIVE=[0-9]{1,10}", line)
            or re.fullmatch(r"EVOLUTION_INSTANCE_(?:REGISTERED|UPSTREAM)_COUNT=[0-9]{1,5}", line)
            or re.fullmatch(r"EVOLUTION_INSTANCE_(?:CONNECTED|LOGGED_IN)=[01]", line)
            or line
            in {
                "EVOLUTION_INSTANCE_STAGE=database",
                "EVOLUTION_INSTANCE_STAGE=list",
                "EVOLUTION_INSTANCE_STAGE=status",
                "EVOLUTION_INSTANCE_STAGE=paired_device",
                "EVOLUTION_INSTANCE_BASELINE=online",
                "EVOLUTION_INSTANCE_BASELINE=offline",
            }
        ) or line in {
            "EVOLUTION_CALL_GATE_OK",
            "EVOLUTION_CALL_GATE_FAILED=active_calls",
            "EVOLUTION_CALL_GATE_FAILED=inspection_failed",
            "EVOLUTION_REGISTERED_INSTANCES_OK",
            "EVOLUTION_REGISTERED_INSTANCES_FAILED",
        }:
            print(line, flush=True)
    if result.returncode or expected not in lines:
        raise Deferred("call_or_instance_inspection")
    return lines


def udp_gate(ns):
    cid, _ = ns["container"]("evolution")
    count = 0
    for table in ("/proc/net/udp", "/proc/net/udp6"):
        result = ns["capture"]("docker", "exec", cid, "cat", table)
        if result.returncode or len(result.stdout) > 4 * 1024**2:
            raise Deferred("media_inspection")
        lines = result.stdout.splitlines()
        if not lines or "local_address" not in lines[0]:
            raise Deferred("media_inspection")
        for line in lines[1:]:
            parts = line.split()
            if len(parts) < 4:
                raise Deferred("media_inspection")
            address, separator, port = parts[1].partition(":")
            if not separator or re.fullmatch(r"[0-9A-Fa-f]{4}", port) is None:
                raise Deferred("media_inspection")
            if address.upper() == "0B00007F":  # Docker's embedded resolver only.
                continue
            if re.fullmatch(r"(?:[0-9A-Fa-f]{8}|[0-9A-Fa-f]{32})", address) is None:
                raise Deferred("media_inspection")
            count += 1
    print("EVOLUTION_MEDIA_SOCKETS=" + str(count), flush=True)
    if count:
        raise Deferred("media_sockets")


def no_calls(ns, gate):
    emit_probe(ns, gate, "EVOLUTION_CALL_GATE_OK")
    udp_gate(ns)


def compose_evolution(ns, image, *arguments):
    ns["require"](
        re.fullmatch(r"vasa-evolution:(?:pool|rollback)-[a-f0-9]{40}", image) is not None,
        "Invalid Evolution image reference.",
    )
    root = ns["ROOT"]
    return ns["run"](
        "docker",
        "compose",
        "--project-name",
        ns["PROJECT"],
        "--project-directory",
        str(root / "deploy"),
        "--env-file",
        str(root / ".local/vps.env"),
        "-f",
        str(root / "deploy/compose.yaml"),
        "-f",
        "-",
        "--profile",
        "voice",
        *arguments,
        input_text=json.dumps({"services": {"evolution": {"image": image}}}),
        timeout=210,
    )


def capacity(ns, module):
    output = io.StringIO()
    with redirect_stdout(output):
        module["diagnose_sockets"](ns)
    values = {}
    for line in output.getvalue().splitlines():
        if re.fullmatch(
            r"(?:DB_SOCKET_(?:VASA|VOICE|EVOLUTION|OTHER|TOTAL)|DB_CONFIG_MAX_CONNECTIONS)=[0-9]{1,8}",
            line,
        ):
            print(line, flush=True)
            key, value = line.split("=")
            values[key] = int(value)
    ns["require"]("DB_SOCKET_EVOLUTION" in values, "Database connection inspection unavailable.")
    return values


def verify_identity(ns, module, receipt):
    ns["require"](
        module["snapshot"](ns) == receipt["identity"],
        "Database identity/schema changed unexpectedly.",
    )
    print("EVOLUTION_PAIRING_AND_SCHEMA_PRESERVED", flush=True)


def staged_run(ns, stage, *arguments, **kwargs):
    """Classify a command failure without exposing command, output or exception text."""
    print("EVOLUTION_POOL_STAGE=" + stage, flush=True)
    if "request_stage" in ns:
        ns["request_stage"](stage)
    try:
        return ns["run"](*arguments, **kwargs)
    except BaseException as error:
        import subprocess

        category = "timeout" if isinstance(error, subprocess.TimeoutExpired) else "command_failed"
        print("EVOLUTION_POOL_FAILURE=" + stage + ":" + category, flush=True)
        raise


def public_health():
    """Check the fixed public origin, suppressing response bodies and redirect destinations."""

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    opener = urllib.request.build_opener(NoRedirect())
    print("EVOLUTION_POOL_STAGE=public_health", flush=True)
    for label, path, allowed in (
        ("login", "/login", {200}),
        ("readiness", "/health/ready", {200}),
        ("dashboard", "/dashboard", {302, 303, 307, 308, 401, 403}),
    ):
        try:
            with opener.open("https://vasa.litatech.xyz" + path, timeout=15) as response:
                status = response.status
        except urllib.error.HTTPError as error:
            status = error.code
            if status == 403:
                headers = error.headers or {}
                # Fixed structural indicators only; never print header values/body.
                denial = (
                    "cloudflare_challenge"
                    if headers.get("cf-mitigated", "").lower() == "challenge"
                    else "proxy_policy"
                    if headers.get("x-mitmproxy-blocked-reason", "")
                    in {"ROBOTS_DENIED", "DOMAIN_BLOCKED"}
                    else "cloudflare_response"
                    if headers.get("server", "").lower() == "cloudflare"
                    else "unclassified"
                )
                print("EVOLUTION_PUBLIC_DENIAL=" + denial, flush=True)
        except (urllib.error.URLError, OSError) as error:
            reason = error.reason if isinstance(error, urllib.error.URLError) else error
            category = (
                "certificate"
                if isinstance(reason, ssl.SSLCertVerificationError)
                else "timeout"
                if isinstance(reason, (TimeoutError, socket.timeout))
                else "network"
            )
            print("EVOLUTION_PUBLIC_FAILURE=" + category, flush=True)
            raise Deferred("public_health") from None
        print("EVOLUTION_PUBLIC_STATUS=" + label + ":" + str(status), flush=True)
        if status not in allowed:
            print("EVOLUTION_PUBLIC_FAILURE=invalid_status", flush=True)
            raise Deferred("public_health")
    print("EVOLUTION_PUBLIC_HEALTH_OK", flush=True)


def acquire_rollback(ns, before, source, rollback):
    """Retain old image or rebuild its pinned pre-fix public recipe; never commit runtime."""
    running = before["evolution"]["image"]
    inspected = ns["capture"]("docker", "image", "inspect", "--format", "{{.Id}}", running)
    if inspected.returncode == 0 and inspected.stdout.strip() == running:
        ns["run"]("docker", "image", "tag", running, rollback)
        expected = running
    else:
        print("EVOLUTION_ROLLBACK_IMAGE=previous_source_build", flush=True)
        old_source = source / ".local/evolution-rollback-source"
        staged_run(
            ns,
            "rollback_prepare",
            "python3",
            str(source / "scripts/prepare_evolution.py"),
            "--isolated",
            "--rollback-source",
            "--destination",
            str(old_source),
            timeout=300,
        )
        staged_run(
            ns,
            "rollback_build",
            "docker",
            "build",
            "--tag",
            rollback,
            "--file",
            str(source / "docker/evolution.Dockerfile"),
            "--build-arg",
            "VASA_REVISION=e21ce0dd7634f3047410c893b5e4d1c082034b84",
            str(old_source),
            timeout=1800,
        )
        expected = None
    image = ns["run"]("docker", "image", "inspect", "--format", "{{.Id}}", rollback)
    ns["require"](
        re.fullmatch(r"sha256:[a-f0-9]{64}", image) is not None
        and (expected is None or image == expected),
        "Rollback image unavailable.",
    )
    ns["assert_unchanged"](before)
    print("EVOLUTION_ROLLBACK_IMAGE_VERIFIED", flush=True)
    return image


def run(ns, target, deploy, gate, instances, backup_source, capacity_source):
    root = ns["ROOT"]
    ns["preflight"]()
    require, git = ns["require"], ns["git"]
    require(re.fullmatch(r"[a-f0-9]{40}", target) is not None, "Invalid Evolution release SHA.")
    lock_path = root / ".local/actions-deploy.lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        before = ns["snapshot_services"](ns["DEPENDENCIES"] + ns["SERVICES"])
        hashes = ns["private_hashes"]()
        canonical = git("rev-parse", "HEAD")
        status = git("status", "--porcelain=v1", "--untracked-files=all")
        cap = {"__name__": "evolution_capacity"}
        exec(compile(capacity_source, "capacity", "exec"), cap)
        print("EVOLUTION_CONNECTIONS_BEFORE", flush=True)
        before_connections = capacity(ns, cap)
        try:
            no_calls(ns, gate)
            initial_instances = emit_probe(ns, instances, "EVOLUTION_REGISTERED_INSTANCES_OK")
            require(
                sum(
                    line in initial_instances
                    for line in (
                        "EVOLUTION_INSTANCE_BASELINE=online",
                        "EVOLUTION_INSTANCE_BASELINE=offline",
                    )
                )
                == 1,
                "Instance connectivity baseline unavailable.",
            )
            instance_mode = (
                "preserve-offline"
                if "EVOLUTION_INSTANCE_BASELINE=offline" in initial_instances
                else "restore"
            )
        except Deferred as error:
            print("EVOLUTION_ROLLOUT_DEFERRED=" + str(error), flush=True)
            return 2
        if not deploy:
            print("EVOLUTION_POOL_PREFLIGHT_OK", flush=True)
            return 0
        git("fetch", "origin", ns["BRANCH"])
        require(git("rev-parse", "origin/" + ns["BRANCH"]) == target, "Evolution branch moved.")
        git("merge-base", "--is-ancestor", canonical, target)
        releases = root / ".local/evolution-releases"
        require(not releases.is_symlink(), "Unsafe Evolution release directory.")
        releases.mkdir(mode=0o700, exist_ok=True)
        source = releases / target
        if source.exists():
            require(not source.is_symlink(), "Unsafe Evolution release source.")
            require(git("-C", str(source), "rev-parse", "HEAD") == target, "Source differs.")
            require(not git("-C", str(source), "status", "--porcelain"), "Source is dirty.")
        else:
            git("worktree", "add", "--detach", str(source), target)
        # The application Alembic files cannot change in this dependency rollout.
        active = json.loads((root / ".local/actions-release.json").read_text())["active_sha"]
        require(
            not git("diff", "--name-only", active, target, "--", "migrations", "alembic.ini"),
            "Evolution rollout cannot include application schema changes.",
        )
        candidate = "vasa-evolution:pool-" + target
        rollback = "vasa-evolution:rollback-" + target
        print("EVOLUTION_POOL_STAGE=rollback_image", flush=True)
        acquire_rollback(ns, before, source, rollback)
        require(ns["private_hashes"]() == hashes, "Runtime files changed.")
        print("EVOLUTION_POOL_STAGE=prepare_source", flush=True)
        staged_run(
            ns,
            "prepare_source",
            "python3",
            str(source / "scripts/prepare_evolution.py"),
            "--isolated",
            "--destination",
            str(source / ".local/evolution-pool-source"),
            timeout=300,
        )
        print("EVOLUTION_POOL_STAGE=target_build", flush=True)
        staged_run(
            ns,
            "target_build",
            "docker",
            "build",
            "--tag",
            candidate,
            "--file",
            str(source / "docker/evolution.Dockerfile"),
            "--build-arg",
            "VASA_REVISION=" + target,
            str(source / ".local/evolution-pool-source"),
            timeout=1800,
        )
        candidate_id = ns["run"]("docker", "image", "inspect", "--format", "{{.Id}}", candidate)
        compose_evolution(ns, candidate, "config", "--quiet")
        back = {"__name__": "evolution_backups"}
        exec(compile(backup_source, "backups", "exec"), back)
        print("EVOLUTION_POOL_STAGE=backup", flush=True)
        if "request_stage" in ns:
            ns["request_stage"]("backup")
        receipt = back["backup"](ns)
        no_calls(ns, gate)
        ns["assert_unchanged"](before)
        require(ns["private_hashes"]() == hashes, "Runtime files changed.")
        voice, _ = ns["container"]("voice")
        paused = attempted = False
        if "before_evolution_mutation" in ns:
            ns["before_evolution_mutation"]()
        for sig in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, ns["signal_failure"])
        try:
            print("EVOLUTION_POOL_STAGE=quiesce", flush=True)
            ns["run"]("docker", "pause", voice)
            paused = True
            no_calls(ns, gate)
            attempted = True
            print("EVOLUTION_POOL_STAGE=replace", flush=True)
            compose_evolution(
                ns,
                candidate,
                "up",
                "-d",
                "--no-deps",
                "--no-build",
                "--wait",
                "--wait-timeout",
                "150",
                "evolution",
            )
            emit_probe(ns, instances, "EVOLUTION_REGISTERED_INSTANCES_OK", instance_mode)
            require(ns["container"]("evolution")[1]["image"] == candidate_id, "Wrong image.")
            verify_identity(ns, back, receipt)
            ns["run"]("docker", "unpause", voice)
            paused = False
            ns["health"]()
            ns["assert_unchanged"]({k: v for k, v in before.items() if k != "evolution"})
            require(ns["private_hashes"]() == hashes, "Runtime files changed.")
            require(git("rev-parse", "HEAD") == canonical, "Canonical checkout changed.")
            require(
                git("status", "--porcelain=v1", "--untracked-files=all") == status,
                "Operator files changed.",
            )
            for _ in range(3):
                # Read-only status probes exercise the existing device lookup without reconnecting.
                emit_probe(ns, instances, "EVOLUTION_REGISTERED_INSTANCES_OK")
                print("EVOLUTION_CONNECTIONS_AFTER", flush=True)
                after_connections = capacity(ns, cap)
                require(
                    after_connections["DB_SOCKET_EVOLUTION"] <= 50,
                    "Evolution connections exceed the two bounded process pools.",
                )
                if before_connections["DB_SOCKET_EVOLUTION"] > 50:
                    require(
                        after_connections["DB_SOCKET_EVOLUTION"]
                        < before_connections["DB_SOCKET_EVOLUTION"],
                        "Evolution connection consumption did not decrease.",
                    )
                time.sleep(5)
            public_health()
            ns["run"]("docker", "image", "tag", candidate, "vasa-evolution-calls:e21ce0dd")
            receipt.update(
                target_sha=target,
                image=candidate_id,
                status="healthy",
                connections_before=before_connections,
                connections_after=after_connections,
            )
            journal = root / ".local/actions-evolution-pool.json"
            descriptor = os.open(
                journal, os.O_CREAT | os.O_TRUNC | os.O_WRONLY | os.O_NOFOLLOW, 0o600
            )
            with os.fdopen(descriptor, "w") as output:
                json.dump(receipt, output)
            print("EVOLUTION_DEPLOYED_SHA=" + target, flush=True)
            print("VASA_EVOLUTION_POOL_DEPLOYMENT_OK", flush=True)
            return 0
        except BaseException:
            for sig in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
                signal.signal(sig, signal.SIG_IGN)
            if attempted:
                print("EVOLUTION_POOL_STAGE=rollback", flush=True)
                try:
                    compose_evolution(
                        ns,
                        rollback,
                        "up",
                        "-d",
                        "--no-deps",
                        "--no-build",
                        "--wait",
                        "--wait-timeout",
                        "150",
                        "evolution",
                    )
                    emit_probe(ns, instances, "EVOLUTION_REGISTERED_INSTANCES_OK", instance_mode)
                    verify_identity(ns, back, receipt)
                    ns["run"]("docker", "image", "tag", rollback, "vasa-evolution-calls:e21ce0dd")
                    if paused:
                        ns["run"]("docker", "unpause", voice)
                        paused = False
                    ns["health"]()
                    ns["assert_unchanged"]({k: v for k, v in before.items() if k != "evolution"})
                    require(ns["private_hashes"]() == hashes, "Runtime files changed.")
                    print("VASA_EVOLUTION_POOL_ROLLBACK_OK", flush=True)
                except BaseException:
                    print("VASA_EVOLUTION_POOL_ROLLBACK_FAILED", flush=True)
            else:
                print("EVOLUTION_ROLLOUT_DEFERRED=active_or_unknown_after_quiesce", flush=True)
            raise ns["Refusal"]("Evolution rollout failed; sanitized markers only.") from None
        finally:
            if paused:
                ns["run"]("docker", "unpause", voice)
